"""Professionals PREVIEW Phase-3 tests: Ownership + Authorized Editors + Affiliations + Audit.

Covers backend authorization matrix (admin/self/authorized/staff/pharmacy/patient),
RBAC on management endpoints, audit meta (edit_source + fields_changed + diff),
high-risk field stripping, link-user safety, permission fields on GET, affiliations
existence-does-not-grant-edit.

Cleans up: all professional_profiles, professional_profile_editors,
professional_organization_affiliations docs created by this run — via Mongo. Never
modifies users/patients/organizations/taxonomy/providers.
"""
import os
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")

MONGO_URL, DB_NAME = None, None
with open("/app/backend/.env") as f:
    for ln in f:
        if ln.startswith("MONGO_URL"):
            MONGO_URL = ln.split("=", 1)[1].strip().strip('"')
        if ln.startswith("DB_NAME"):
            DB_NAME = ln.split("=", 1)[1].strip().strip('"')

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
PHYSICIAN = ("PAGUAYO", "Newman2013_!")
STAFF = ("staff@visita.demo", "Staff2026!")
PHARM = ("1670dufferin", "PharmNew2026!")


def _login(identifier, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": identifier, "password": password}, timeout=20)
    return r


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def sessions():
    out = {}
    for key, (ident, pw) in [("admin", ADMIN), ("physician", PHYSICIAN), ("staff", STAFF), ("pharmacy", PHARM)]:
        r = _login(ident, pw)
        if r.status_code != 200:
            pytest.skip(f"{key} login failed: {r.status_code} {r.text[:200]}")
        j = r.json()
        out[key] = {"token": j["token"], "user": j["user"]}
    return out


@pytest.fixture(scope="module")
def created_ids():
    """Registry so teardown can wipe every doc this test created."""
    return {"profiles": [], "editors": [], "affiliations": []}


@pytest.fixture(scope="module")
def profiles(sessions, created_ids):
    """Create 2 empty professional profiles as admin (unlinked)."""
    admin_h = _h(sessions["admin"]["token"])
    ids = []
    for label in ("TEST_AuthzA", "TEST_AuthzB"):
        r = requests.post(f"{BASE_URL}/api/professionals",
                          json={"surname": label, "first_name": "QA",
                                "sphere_id": "1", "area_id": "36", "specialty_id": "133"},
                          headers=admin_h)
        assert r.status_code in (200, 201), f"create {label}: {r.status_code} {r.text}"
        pid = r.json()["id"]
        ids.append(pid)
        created_ids["profiles"].append(pid)
    return {"A": ids[0], "B": ids[1]}


# ---------- Ownership + editor authorization matrix ----------
class TestAuthzMatrix:
    def test_admin_can_patch(self, sessions, profiles):
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['A']}",
                           json={"surname": "TEST_AuthzA", "professorship": "Prof X"},
                           headers=_h(sessions["admin"]["token"]))
        assert r.status_code == 200
        assert r.json().get("professorship") == "Prof X"

    def test_physician_unlinked_cannot_patch(self, sessions, profiles):
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['A']}",
                           json={"surname": "TEST_AuthzA"},
                           headers=_h(sessions["physician"]["token"]))
        assert r.status_code == 403

    def test_staff_pre_grant_cannot_patch(self, sessions, profiles):
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['A']}",
                           json={"surname": "TEST_AuthzA"},
                           headers=_h(sessions["staff"]["token"]))
        assert r.status_code == 403

    def test_pharmacy_cannot_patch(self, sessions, profiles):
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['A']}",
                           json={"surname": "TEST_AuthzA"},
                           headers=_h(sessions["pharmacy"]["token"]))
        assert r.status_code == 403

    def test_admin_link_physician_and_self_patch_works(self, sessions, profiles):
        admin_h = _h(sessions["admin"]["token"])
        phys_id = sessions["physician"]["user"]["id"]
        r = requests.put(f"{BASE_URL}/api/professionals/{profiles['A']}/link-user",
                         json={"user_id": phys_id}, headers=admin_h)
        assert r.status_code == 200, r.text
        assert r.json()["linked_user_id"] == phys_id

        # Physician can PATCH profile A (SELF)
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['A']}",
                           json={"surname": "TEST_AuthzA", "second_name": "SelfEdit"},
                           headers=_h(sessions["physician"]["token"]))
        assert r.status_code == 200
        assert r.json().get("second_name") == "SelfEdit"

    def test_physician_cannot_patch_other_profile(self, sessions, profiles):
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['B']}",
                           json={"surname": "TEST_AuthzB"},
                           headers=_h(sessions["physician"]["token"]))
        assert r.status_code == 403

    def test_grant_editor_to_staff_and_patch_works(self, sessions, profiles, created_ids):
        admin_h = _h(sessions["admin"]["token"])
        staff_id = sessions["staff"]["user"]["id"]
        r = requests.post(f"{BASE_URL}/api/professionals/{profiles['A']}/editors",
                         json={"user_id": staff_id}, headers=admin_h)
        assert r.status_code == 200, r.text
        auth_id = r.json()["id"]
        assert r.json()["permission_level"] == "EDIT_PROFILE"
        assert r.json()["active"] is True
        created_ids["editors"].append((profiles["A"], auth_id, staff_id))

        # Now staff can patch A
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['A']}",
                           json={"surname": "TEST_AuthzA", "professorship": "StaffEdit"},
                           headers=_h(sessions["staff"]["token"]))
        assert r.status_code == 200
        assert r.json().get("professorship") == "StaffEdit"

    def test_authorized_staff_cannot_patch_other(self, sessions, profiles):
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['B']}",
                           json={"surname": "TEST_AuthzB"},
                           headers=_h(sessions["staff"]["token"]))
        assert r.status_code == 403

    def test_revoke_editor_immediately_removes_access(self, sessions, profiles, created_ids):
        admin_h = _h(sessions["admin"]["token"])
        prof_id, auth_id, staff_id = created_ids["editors"][-1]
        r = requests.delete(f"{BASE_URL}/api/professionals/{prof_id}/editors/{auth_id}",
                            headers=admin_h)
        assert r.status_code == 200

        r = requests.patch(f"{BASE_URL}/api/professionals/{prof_id}",
                           json={"surname": "TEST_AuthzA"},
                           headers=_h(sessions["staff"]["token"]))
        assert r.status_code == 403


# ---------- RBAC on management endpoints ----------
class TestManagementRBAC:
    @pytest.mark.parametrize("role", ["physician", "staff", "pharmacy"])
    def test_non_admin_cannot_grant_editor(self, sessions, profiles, role):
        r = requests.post(f"{BASE_URL}/api/professionals/{profiles['A']}/editors",
                          json={"user_id": sessions["staff"]["user"]["id"]},
                          headers=_h(sessions[role]["token"]))
        assert r.status_code == 403

    @pytest.mark.parametrize("role", ["physician", "staff", "pharmacy"])
    def test_non_admin_cannot_list_editors(self, sessions, profiles, role):
        r = requests.get(f"{BASE_URL}/api/professionals/{profiles['A']}/editors",
                         headers=_h(sessions[role]["token"]))
        assert r.status_code == 403

    @pytest.mark.parametrize("role", ["physician", "staff", "pharmacy"])
    def test_non_admin_cannot_link_user(self, sessions, profiles, role):
        r = requests.put(f"{BASE_URL}/api/professionals/{profiles['B']}/link-user",
                         json={"user_id": sessions["physician"]["user"]["id"]},
                         headers=_h(sessions[role]["token"]))
        assert r.status_code == 403

    @pytest.mark.parametrize("role", ["physician", "staff", "pharmacy"])
    def test_non_admin_cannot_add_affiliation(self, sessions, profiles, role):
        r = requests.post(f"{BASE_URL}/api/professionals/{profiles['A']}/affiliations",
                          json={"organization_id": "any"},
                          headers=_h(sessions[role]["token"]))
        assert r.status_code == 403

    @pytest.mark.parametrize("role", ["physician", "staff", "pharmacy"])
    def test_non_admin_cannot_user_search(self, sessions, role):
        r = requests.get(f"{BASE_URL}/api/professionals/authz/user-search?q=staff",
                         headers=_h(sessions[role]["token"]))
        assert r.status_code == 403

    def test_admin_user_search_returns_ids(self, sessions):
        r = requests.get(f"{BASE_URL}/api/professionals/authz/user-search?q=staff",
                         headers=_h(sessions["admin"]["token"]))
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # Route not captured as prof_id
        assert not (isinstance(rows, dict) and rows.get("detail") == "Professional not found.")


# ---------- link-user safety ----------
class TestLinkUserSafety:
    def test_already_linked_returns_409(self, sessions, profiles):
        # Physician is linked to A already; try to link same physician to B
        r = requests.put(f"{BASE_URL}/api/professionals/{profiles['B']}/link-user",
                         json={"user_id": sessions["physician"]["user"]["id"]},
                         headers=_h(sessions["admin"]["token"]))
        assert r.status_code == 409

    def test_link_patient_returns_400(self, sessions, profiles):
        # Find any patient user id via mongo (read-only)
        async def _get_patient():
            c = AsyncIOMotorClient(MONGO_URL)
            u = await c[DB_NAME].users.find_one({"role": "patient"})
            c.close()
            return str(u["_id"]) if u else None
        pid = asyncio.run(_get_patient())
        if not pid:
            pytest.skip("no patient user")
        r = requests.put(f"{BASE_URL}/api/professionals/{profiles['B']}/link-user",
                         json={"user_id": pid}, headers=_h(sessions["admin"]["token"]))
        assert r.status_code == 400

    def test_null_unlinks(self, sessions, profiles):
        # First unlink physician from A, verify SELF is now revoked
        r = requests.put(f"{BASE_URL}/api/professionals/{profiles['A']}/link-user",
                         json={"user_id": None}, headers=_h(sessions["admin"]["token"]))
        assert r.status_code == 200
        assert r.json().get("linked_user_id") in (None, "")
        # Physician can no longer edit
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['A']}",
                           json={"surname": "TEST_AuthzA"},
                           headers=_h(sessions["physician"]["token"]))
        assert r.status_code == 403
        # Relink for later tests (audit needs SELF edit)
        r = requests.put(f"{BASE_URL}/api/professionals/{profiles['A']}/link-user",
                         json={"user_id": sessions["physician"]["user"]["id"]},
                         headers=_h(sessions["admin"]["token"]))
        assert r.status_code == 200


# ---------- High-risk field safety ----------
class TestHighRiskFields:
    def test_patch_ignores_linked_user_id_and_id(self, sessions, profiles):
        # As SELF (physician on A), try to hijack
        pid = profiles["A"]
        before = requests.get(f"{BASE_URL}/api/professionals/{pid}",
                              headers=_h(sessions["admin"]["token"])).json()
        assert before["linked_user_id"] == sessions["physician"]["user"]["id"]

        r = requests.patch(f"{BASE_URL}/api/professionals/{pid}",
                           json={"surname": "TEST_AuthzA",
                                 "linked_user_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                                 "id": "hijack",
                                 "source_professional_id": "src",
                                 "created_by": "attacker",
                                 "role": "admin"},
                           headers=_h(sessions["physician"]["token"]))
        assert r.status_code == 200
        after = requests.get(f"{BASE_URL}/api/professionals/{pid}",
                             headers=_h(sessions["admin"]["token"])).json()
        assert after["linked_user_id"] == sessions["physician"]["user"]["id"]
        assert after["id"] == pid
        assert after.get("created_by") == before.get("created_by")


# ---------- Audit log verification ----------
class TestAudit:
    def test_audit_sources_present(self, sessions, profiles, created_ids):
        """After SELF, ADMIN edits already produced above, add one AUTHORIZED editor edit."""
        admin_h = _h(sessions["admin"]["token"])
        # Re-grant staff as editor on A
        staff_id = sessions["staff"]["user"]["id"]
        r = requests.post(f"{BASE_URL}/api/professionals/{profiles['A']}/editors",
                          json={"user_id": staff_id}, headers=admin_h)
        assert r.status_code == 200
        auth_id = r.json()["id"]
        created_ids["editors"].append((profiles["A"], auth_id, staff_id))

        # Staff PATCH -> AUTHORIZED_ORGANIZATION_EDITOR audit
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['A']}",
                           json={"surname": "TEST_AuthzA", "professorship": "AuthzEdit"},
                           headers=_h(sessions["staff"]["token"]))
        assert r.status_code == 200

        # Read audit_logs for prof A
        async def _fetch():
            c = AsyncIOMotorClient(MONGO_URL)
            rows = await c[DB_NAME].audit_logs.find(
                {"entity_id": profiles["A"], "action": "professional_update"}).to_list(200)
            c.close()
            return rows
        rows = asyncio.run(_fetch())
        sources = {r.get("meta", {}).get("edit_source") for r in rows}
        assert "ADMIN" in sources, f"missing ADMIN in {sources}"
        assert "SELF" in sources, f"missing SELF in {sources}"
        assert "AUTHORIZED_ORGANIZATION_EDITOR" in sources, f"missing AUTHORIZED in {sources}"

        # Verify fields_changed + diff structure and no secrets
        for r in rows:
            meta = r.get("meta") or {}
            assert "fields_changed" in meta
            assert isinstance(meta["fields_changed"], list)
            assert "diff" in meta
            # No password/secret keys
            blob = str(meta).lower()
            assert "password" not in blob and "password_hash" not in blob
            assert "secret" not in blob


# ---------- GET single/list permission fields ----------
class TestPermissionFields:
    def test_get_single_admin_fields(self, sessions, profiles):
        r = requests.get(f"{BASE_URL}/api/professionals/{profiles['A']}",
                         headers=_h(sessions["admin"]["token"]))
        assert r.status_code == 200
        d = r.json()
        assert d["can_edit"] is True
        assert d["edit_source"] == "ADMIN"
        assert d["can_manage_editors"] is True
        # A is linked to physician => Self-managed
        assert d["management_label"] == "Self-managed"

    def test_get_single_physician_self(self, sessions, profiles):
        r = requests.get(f"{BASE_URL}/api/professionals/{profiles['A']}",
                         headers=_h(sessions["physician"]["token"]))
        assert r.status_code == 200
        d = r.json()
        assert d["can_edit"] is True
        assert d["edit_source"] == "SELF"
        assert d["can_manage_editors"] is False

    def test_get_single_authorized_editor(self, sessions, profiles):
        # Staff currently has active grant on A (from Audit test)
        r = requests.get(f"{BASE_URL}/api/professionals/{profiles['A']}",
                         headers=_h(sessions["staff"]["token"]))
        assert r.status_code == 200
        d = r.json()
        assert d["can_edit"] is True
        assert d["edit_source"] == "AUTHORIZED_ORGANIZATION_EDITOR"
        assert d["can_manage_editors"] is False

    def test_get_single_no_access(self, sessions, profiles):
        r = requests.get(f"{BASE_URL}/api/professionals/{profiles['B']}",
                         headers=_h(sessions["pharmacy"]["token"]))
        assert r.status_code == 200
        d = r.json()
        assert d["can_edit"] is False
        assert d["edit_source"] is None
        # B not linked, no editors -> Admin-managed
        assert d["management_label"] == "Admin-managed"

    def test_management_label_organization_managed(self, sessions, created_ids):
        """Create fresh profile C with editor only (not linked) -> Organization-managed."""
        admin_h = _h(sessions["admin"]["token"])
        r = requests.post(f"{BASE_URL}/api/professionals",
                          json={"surname": "TEST_AuthzC", "sphere_id": "1",
                                "area_id": "36", "specialty_id": "133"},
                          headers=admin_h)
        pid = r.json()["id"]
        created_ids["profiles"].append(pid)

        staff_id = sessions["staff"]["user"]["id"]
        r = requests.post(f"{BASE_URL}/api/professionals/{pid}/editors",
                          json={"user_id": staff_id}, headers=admin_h)
        auth_id = r.json()["id"]
        created_ids["editors"].append((pid, auth_id, staff_id))

        r = requests.get(f"{BASE_URL}/api/professionals/{pid}", headers=admin_h)
        assert r.json()["management_label"] == "Organization-managed"

    def test_get_list_can_edit_per_row(self, sessions, profiles):
        # As staff: A + C have edit (from prior tests), B does not
        r = requests.get(f"{BASE_URL}/api/professionals?q=TEST_Authz",
                         headers=_h(sessions["staff"]["token"]))
        assert r.status_code == 200
        rows = {row["id"]: row for row in r.json()}
        assert rows[profiles["A"]]["can_edit"] is True
        assert rows[profiles["B"]]["can_edit"] is False


# ---------- Affiliations ----------
class TestAffiliations:
    def test_affiliation_lifecycle_and_no_edit_grant(self, sessions, profiles, created_ids):
        admin_h = _h(sessions["admin"]["token"])
        # Get an existing organization id
        async def _one_org():
            c = AsyncIOMotorClient(MONGO_URL)
            o = await c[DB_NAME].organizations.find_one({}, {"id": 1})
            c.close()
            return o and o.get("id")
        org_id = asyncio.run(_one_org())
        if not org_id:
            pytest.skip("no organization in db")

        # Bad org -> 400
        r = requests.post(f"{BASE_URL}/api/professionals/{profiles['B']}/affiliations",
                          json={"organization_id": "does-not-exist"}, headers=admin_h)
        assert r.status_code == 400

        # Good create
        r = requests.post(f"{BASE_URL}/api/professionals/{profiles['B']}/affiliations",
                          json={"organization_id": org_id}, headers=admin_h)
        assert r.status_code == 200
        aff = r.json()
        created_ids["affiliations"].append((profiles["B"], aff["id"]))

        # List includes organization_name
        r = requests.get(f"{BASE_URL}/api/professionals/{profiles['B']}/affiliations",
                         headers=admin_h)
        assert r.status_code == 200
        assert any(a["id"] == aff["id"] and "organization_name" in a for a in r.json())

        # Affiliation does NOT grant edit -- staff still cannot patch B
        r = requests.patch(f"{BASE_URL}/api/professionals/{profiles['B']}",
                           json={"surname": "TEST_AuthzB"},
                           headers=_h(sessions["staff"]["token"]))
        assert r.status_code == 403

        # DELETE deactivates
        r = requests.delete(f"{BASE_URL}/api/professionals/{profiles['B']}/affiliations/{aff['id']}",
                            headers=admin_h)
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/professionals/{profiles['B']}/affiliations",
                         headers=admin_h)
        assert not any(a["id"] == aff["id"] for a in r.json())


# ---------- Cleanup: remove ALL created docs so collections end empty ----------
class TestZZZCleanup:
    def test_zzz_wipe_created(self, created_ids):
        async def _wipe():
            c = AsyncIOMotorClient(MONGO_URL)
            db_ = c[DB_NAME]
            deleted = {"profiles": 0, "editors": 0, "affiliations": 0}
            for pid in created_ids["profiles"]:
                r = await db_.professional_profiles.delete_many({"id": pid})
                deleted["profiles"] += r.deleted_count
                r = await db_.professional_profile_editors.delete_many({"professional_id": pid})
                deleted["editors"] += r.deleted_count
                r = await db_.professional_organization_affiliations.delete_many({"professional_id": pid})
                deleted["affiliations"] += r.deleted_count
            # Safety: ensure collections are empty of any TEST_ leftovers
            r = await db_.professional_profiles.delete_many({"surname": {"$regex": "^TEST_Authz"}})
            deleted["profiles"] += r.deleted_count
            # Final counts
            counts = {
                "profiles": await db_.professional_profiles.count_documents({}),
                "editors": await db_.professional_profile_editors.count_documents({}),
                "affiliations": await db_.professional_organization_affiliations.count_documents({}),
            }
            c.close()
            return deleted, counts

        deleted, counts = asyncio.run(_wipe())
        print(f"Cleanup deleted: {deleted}; remaining counts: {counts}")
        assert counts["profiles"] == 0, f"professional_profiles not empty: {counts['profiles']}"
        assert counts["editors"] == 0, f"editors not empty: {counts['editors']}"
        assert counts["affiliations"] == 0, f"affiliations not empty: {counts['affiliations']}"
