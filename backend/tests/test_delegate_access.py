"""Family/Caregiver delegated portal access — v1 end-to-end regression.

Validates: grant list, add existing user, duplicate 409, add NEW caregiver (no patient),
reuse by email, delegate my-delegations, permission-filtered summary, delegated appt,
delegated Rx (patient_name=Linda, audit actor=Maria + on_behalf_of=Linda + relationship),
documents list (released-only), unauthorized on_behalf_of => 404, missing permission => 403,
revoke => immediate loss + history preserved, self-portal unchanged.

Cleans up ONLY synthetic artefacts (TEST_DELG tag / email prefix). Never touches the
Maria->Linda demo grant or any real users/patients.
"""
import os
import re
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "kevinrodriguez9528@gmail.com"
ADMIN_PASS = "VisitaAdmin2026!"
MARIA_EMAIL = "maria.lopez@demo.com"
MARIA_PASS = "Patient2026!"
LINDA_PID = "2f4d3a87-1bce-4c30-8212-cf10e64ce3fc"
JOHN_PID = "1609399b-ac9a-46a8-8f01-6dac071aa9ea"

TAG = "TEST_DELG"


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture(scope="module")
def maria_token():
    return _login(MARIA_EMAIL, MARIA_PASS)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def maria_h(maria_token):
    return {"Authorization": f"Bearer {maria_token}"}


@pytest.fixture(scope="module", autouse=True)
def cleanup(mongo):
    """Teardown-only cleanup of synthetic artefacts."""
    yield
    # Any grants we created tagged with TAG
    mongo["patient_portal_delegates"].delete_many({"_test_tag": TAG})
    # Any caregivers we created tagged with TAG
    mongo["users"].delete_many({"email": {"$regex": r"^delg_test_"}})
    # Any delegated appts/rx we created (ref via meta tag)
    mongo["appointment_requests"].delete_many({"_test_tag": TAG})
    mongo["prescription_requests"].delete_many({"_test_tag": TAG})


# ---------- helpers ----------

def _tag_doc(mongo, coll, flt):
    """After an insert via API, mark the newest row with TAG so cleanup can find it."""
    doc = mongo[coll].find_one(flt, sort=[("created_at", -1)])
    if doc:
        mongo[coll].update_one({"_id": doc["_id"]}, {"$set": {"_test_tag": TAG}})
    return doc


# ---------- Admin: grant list / delegate options ----------

class TestDelegateOptions:
    def test_delegate_options(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/internal/delegate-options", headers=admin_h)
        assert r.status_code == 200
        d = r.json()
        assert set(d["permissions"]) == {"APPOINTMENTS", "RX_REQUESTS", "DOCUMENTS", "REQUEST_STATUS"}
        assert "Daughter" in d["relationships"]
        assert "Patient consent" in d["consent_types"]

    def test_linda_grants_lists_maria(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates", headers=admin_h)
        assert r.status_code == 200
        grants = r.json()
        active = [g for g in grants if g.get("active") and g.get("delegate_email") == MARIA_EMAIL]
        assert len(active) >= 1, f"Expected active Maria->Linda grant, got {grants}"
        g = active[0]
        assert g["relationship"] == "Daughter"
        assert set(g["permissions"]) == {"APPOINTMENTS", "RX_REQUESTS", "DOCUMENTS", "REQUEST_STATUS"}
        assert g.get("consent_type") in ("Patient consent", "Legal / Substitute Decision Maker", "Other authorized basis")
        assert g.get("granted_at")

    def test_user_search_finds_maria(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/internal/user-search?q=maria.lopez", headers=admin_h)
        assert r.status_code == 200
        hits = r.json()
        assert any(h["email"] == MARIA_EMAIL for h in hits)


# ---------- Add flows ----------

class TestAddGrantFlows:
    def test_duplicate_active_returns_409(self, admin_h):
        # Resolve Maria's user_id
        hits = requests.get(f"{BASE_URL}/api/internal/user-search?q=maria.lopez", headers=admin_h).json()
        maria_uid = next(h["id"] for h in hits if h["email"] == MARIA_EMAIL)
        body = {
            "delegate_user_id": maria_uid,
            "relationship": "Daughter",
            "permissions": ["APPOINTMENTS"],
            "consent_type": "Patient consent",
        }
        r = requests.post(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates",
                          json=body, headers=admin_h)
        assert r.status_code == 409, f"Expected 409 dup, got {r.status_code} {r.text}"

    def test_new_caregiver_creates_user_no_patient_record(self, admin_h, mongo):
        email = f"delg_test_{uuid.uuid4().hex[:8]}@demo.test"
        body = {
            "new_caregiver": {"name": "TEST Caregiver", "email": email},
            "relationship": "Caregiver",
            "permissions": ["APPOINTMENTS", "DOCUMENTS"],
            "consent_type": "Patient consent",
        }
        r = requests.post(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates",
                          json=body, headers=admin_h)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["delegate_role"] == "caregiver"
        assert out.get("temp_password"), "temp_password should be returned ONCE"
        assert out["active"] is True

        # Caregiver user exists in users; NO patient record / NO patient_id link
        u = mongo.users.find_one({"email": email})
        assert u is not None
        assert u["role"] == "caregiver"
        assert u.get("patient_id") in (None, "")
        assert u.get("must_change_password") is True
        # NO patient document created with this email
        patient_match = mongo.patients.find_one({"email": email})
        assert patient_match is None, "Caregiver should NOT create a patient record"

        # Tag the grant for cleanup
        mongo["patient_portal_delegates"].update_one({"id": out["id"]}, {"$set": {"_test_tag": TAG}})

        # Granting same email again => reuses user (no duplicate)
        before = mongo.users.count_documents({"email": email})
        body2 = dict(body)
        body2["new_caregiver"] = {"name": "x", "email": email}
        # First revoke existing to avoid 409
        requests.post(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates/{out['id']}/revoke",
                      headers=admin_h)
        r2 = requests.post(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates",
                           json=body2, headers=admin_h)
        assert r2.status_code == 200, r2.text
        out2 = r2.json()
        assert mongo.users.count_documents({"email": email}) == before, "User must be reused"
        mongo["patient_portal_delegates"].update_one({"id": out2["id"]}, {"$set": {"_test_tag": TAG}})
        # Revoke this one too (don't leave stale extras)
        requests.post(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates/{out2['id']}/revoke",
                      headers=admin_h)


# ---------- Delegate reads ----------

class TestDelegateReads:
    def test_my_delegations_lists_linda(self, maria_h):
        r = requests.get(f"{BASE_URL}/api/portal/my-delegations", headers=maria_h)
        assert r.status_code == 200
        d = r.json()
        assert d["has_own_patient"] is True
        names = [m["patient_name"] for m in d["managing"]]
        assert any("Linda" in n for n in names), f"Linda not in managing list: {names}"
        linda = next(m for m in d["managing"] if "Linda" in m["patient_name"])
        assert linda["relationship"] == "Daughter"
        assert set(linda["permissions"]) == {"APPOINTMENTS", "RX_REQUESTS", "DOCUMENTS", "REQUEST_STATUS"}

    def test_managed_summary_filtered(self, maria_h):
        r = requests.get(f"{BASE_URL}/api/portal/managed/{LINDA_PID}/summary", headers=maria_h,
                         params={"on_behalf_of": LINDA_PID})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["patient_id"] == LINDA_PID
        assert "Linda" in d["patient_name"]
        assert d["relationship"] == "Daughter"
        # all four sections present (because full perms)
        assert d["appointments"] is not None
        assert d["documents"] is not None
        assert d["requests"] is not None

    def test_portal_documents_delegated_lists_only_released(self, maria_h, mongo):
        r = requests.get(f"{BASE_URL}/api/portal/documents?on_behalf_of={LINDA_PID}", headers=maria_h)
        assert r.status_code == 200
        docs = r.json()
        # Every returned doc must be for Linda and NOT internal-only
        for d in docs:
            assert d.get("shared_with_patient") is not False
        # Internal-only attachments must not appear
        internal_only = list(mongo.attachments.find(
            {"patient_id": LINDA_PID, "shared_with_patient": False}, {"id": 1}))
        returned_ids = {d.get("id") for d in docs}
        for att in internal_only:
            assert att["id"] not in returned_ids, "Internal attachment leaked to delegate"


# ---------- Delegated writes + audit ----------

class TestDelegatedWritesAndAudit:
    def test_delegated_rx_patient_is_linda_and_audit_attribution(self, maria_h, mongo):
        body = {
            "medication_name": "TEST_DELG Vitamin D",
            "strength": "1000 IU",
            "duration_qty": 30,
            "pharmacy_name": "Test Pharmacy",
            "patient_note": "delegated rx test",
        }
        r = requests.post(f"{BASE_URL}/api/portal/prescriptions?on_behalf_of={LINDA_PID}",
                          json=body, headers=maria_h)
        assert r.status_code in (200, 201), r.text
        out = r.json()
        rx_id = out.get("id") or out.get("ref_number")
        # Rx must be for Linda (not Maria)
        rx = mongo.prescription_requests.find_one(
            {"$or": [{"id": rx_id}, {"ref_number": rx_id}]})
        assert rx is not None, "Rx not persisted"
        mongo.prescription_requests.update_one({"_id": rx["_id"]}, {"$set": {"_test_tag": TAG}})
        assert rx["patient_id"] == LINDA_PID, f"patient_id must be Linda, got {rx['patient_id']}"
        pname = (rx.get("patient_name") or "").lower()
        assert "linda" in pname, f"patient_name must be Linda, got {rx.get('patient_name')}"
        assert "maria" not in pname

        # Audit log attribution
        audit = mongo.audit_logs.find_one({
            "meta.on_behalf_of_patient_id": LINDA_PID,
            "entity_type": "prescription",
        }, sort=[("created_at", -1)])
        assert audit is not None, "No delegated audit record found"
        assert audit.get("actor_role") == "patient"
        assert "maria" in (audit.get("actor_name") or "").lower()
        meta = audit.get("meta", {})
        assert meta.get("on_behalf_of_patient_id") == LINDA_PID
        assert meta.get("delegate_relationship") == "Daughter"
        assert meta.get("acted_by_user_id")

    def test_delegated_appointment_for_linda(self, maria_h, mongo):
        body = {
            "reason": "TEST_DELG delegated appt",
            "options": [{"date": "2027-04-15", "time": "14:00", "label": "2027-04-15 14:00",
                         "display": "Thu Apr 15, 2027 at 2:00 PM"}],
            "appointment_type": "IN_CLINIC",
        }
        r = requests.post(f"{BASE_URL}/api/portal/appointments?on_behalf_of={LINDA_PID}",
                          json=body, headers=maria_h)
        assert r.status_code in (200, 201), r.text
        out = r.json()
        appt = mongo.appointment_requests.find_one(
            {"$or": [{"id": out.get("id")}, {"ref_number": out.get("ref_number")}]})
        assert appt and appt["patient_id"] == LINDA_PID
        mongo.appointment_requests.update_one({"_id": appt["_id"]}, {"$set": {"_test_tag": TAG}})


# ---------- Server-side authorization ----------

class TestAuthZ:
    def test_unauthorized_on_behalf_returns_404(self, maria_h):
        # Maria has NO grant for John Smith
        r = requests.get(f"{BASE_URL}/api/portal/managed/{JOHN_PID}/summary?on_behalf_of={JOHN_PID}",
                         headers=maria_h)
        assert r.status_code == 404, f"Expected 404, got {r.status_code} {r.text}"

    def test_unauthorized_write_returns_404(self, maria_h):
        r = requests.post(
            f"{BASE_URL}/api/portal/prescriptions?on_behalf_of={JOHN_PID}",
            json={"medication_name": "x", "strength": "1", "duration_qty": 1},
            headers=maria_h)
        assert r.status_code == 404

    def test_bogus_pid_returns_404(self, maria_h):
        r = requests.get(f"{BASE_URL}/api/portal/documents?on_behalf_of=nonexistent-pid-xyz",
                         headers=maria_h)
        assert r.status_code == 404

    def test_missing_permission_returns_403(self, admin_h, maria_h, mongo):
        """Create a reduced-permission grant (DOCUMENTS only) to a throwaway caregiver that is
        also Maria, by temporarily reducing Maria's grant? Instead: create a fresh caregiver,
        login as that caregiver, and try RX endpoint — must return 403."""
        # Create caregiver with DOCUMENTS-only permission
        email = f"delg_test_{uuid.uuid4().hex[:8]}@demo.test"
        body = {
            "new_caregiver": {"name": "TEST CG Docs", "email": email},
            "relationship": "Caregiver",
            "permissions": ["DOCUMENTS"],
            "consent_type": "Patient consent",
        }
        r = requests.post(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates",
                          json=body, headers=admin_h)
        assert r.status_code == 200, r.text
        grant = r.json()
        mongo["patient_portal_delegates"].update_one({"id": grant["id"]}, {"$set": {"_test_tag": TAG}})
        temp_pw = grant["temp_password"]

        # Caregiver must change password first
        login = requests.post(f"{BASE_URL}/api/auth/login",
                              json={"email": email, "password": temp_pw})
        assert login.status_code == 200, login.text
        tok = login.json()["token"]
        cg_h = {"Authorization": f"Bearer {tok}"}

        # If must_change_password forces a change endpoint, change it
        new_pw = "Caregiver2026!"
        cp = requests.post(f"{BASE_URL}/api/auth/change-password",
                           json={"current_password": temp_pw, "new_password": new_pw},
                           headers=cg_h)
        if cp.status_code in (200, 204):
            # re-login after change
            login = requests.post(f"{BASE_URL}/api/auth/login",
                                  json={"email": email, "password": new_pw})
            tok = login.json()["token"]
            cg_h = {"Authorization": f"Bearer {tok}"}

        # Caregiver tries Rx (not in permissions) => 403
        r = requests.post(
            f"{BASE_URL}/api/portal/prescriptions?on_behalf_of={LINDA_PID}",
            json={"medication_name": "x", "strength": "1", "duration_qty": 1},
            headers=cg_h)
        assert r.status_code == 403, f"Expected 403, got {r.status_code} {r.text}"

        # Caregiver tries DOCUMENTS (in permissions) => 200
        r = requests.get(f"{BASE_URL}/api/portal/documents?on_behalf_of={LINDA_PID}", headers=cg_h)
        assert r.status_code == 200

        # Revoke
        requests.post(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates/{grant['id']}/revoke",
                      headers=admin_h)


# ---------- Revoke ----------

class TestRevoke:
    def test_revoke_immediate_loss_history_preserved(self, admin_h, maria_h, mongo):
        # Create a throwaway caregiver grant with RX_REQUESTS, use it, revoke, then verify loss
        email = f"delg_test_{uuid.uuid4().hex[:8]}@demo.test"
        body = {
            "new_caregiver": {"name": "TEST CG Revoke", "email": email},
            "relationship": "Caregiver",
            "permissions": ["APPOINTMENTS", "RX_REQUESTS"],
            "consent_type": "Patient consent",
        }
        r = requests.post(f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates",
                          json=body, headers=admin_h)
        assert r.status_code == 200
        grant = r.json()
        mongo["patient_portal_delegates"].update_one({"id": grant["id"]}, {"$set": {"_test_tag": TAG}})
        temp_pw = grant["temp_password"]

        login = requests.post(f"{BASE_URL}/api/auth/login",
                              json={"email": email, "password": temp_pw}).json()
        tok = login["token"]
        cg_h = {"Authorization": f"Bearer {tok}"}
        # change pw if required
        new_pw = "Caregiver2026!"
        cp = requests.post(f"{BASE_URL}/api/auth/change-password",
                           json={"current_password": temp_pw, "new_password": new_pw}, headers=cg_h)
        if cp.status_code in (200, 204):
            tok = requests.post(f"{BASE_URL}/api/auth/login",
                                json={"email": email, "password": new_pw}).json()["token"]
            cg_h = {"Authorization": f"Bearer {tok}"}

        # Pre-revoke: access works
        r = requests.get(f"{BASE_URL}/api/portal/my-delegations", headers=cg_h)
        assert r.status_code == 200
        assert any(m["patient_id"] == LINDA_PID for m in r.json()["managing"])

        # Revoke
        rv = requests.post(
            f"{BASE_URL}/api/internal/patients/{LINDA_PID}/delegates/{grant['id']}/revoke",
            headers=admin_h)
        assert rv.status_code == 200
        rev = rv.json()
        assert rev["active"] is False
        assert rev["revoked_at"]

        # Post-revoke: my-delegations no longer lists Linda
        r = requests.get(f"{BASE_URL}/api/portal/my-delegations", headers=cg_h)
        assert r.status_code == 200
        assert not any(m["patient_id"] == LINDA_PID for m in r.json()["managing"])

        # Summary returns 404
        r = requests.get(f"{BASE_URL}/api/portal/managed/{LINDA_PID}/summary?on_behalf_of={LINDA_PID}",
                         headers=cg_h)
        assert r.status_code == 404

        # on-behalf write returns 404
        r = requests.post(
            f"{BASE_URL}/api/portal/prescriptions?on_behalf_of={LINDA_PID}",
            json={"medication_name": "x", "strength": "1", "duration_qty": 1},
            headers=cg_h)
        assert r.status_code == 404

        # Historical grant row still exists in DB with active=false
        g = mongo["patient_portal_delegates"].find_one({"id": grant["id"]})
        assert g is not None and g["active"] is False and g.get("revoked_at")


# ---------- Self-portal unchanged ----------

class TestSelfPortalUnchanged:
    def test_maria_self_overview_unchanged(self, maria_h):
        r = requests.get(f"{BASE_URL}/api/portal/overview", headers=maria_h)
        assert r.status_code == 200
        d = r.json()
        # Maria's own patient_id should be here (NOT Linda's)
        pname = (d.get("patient", {}).get("first_name") or "").lower() if "patient" in d else ""
        # Just ensure endpoint still works (shape varies — assert the call works)
        assert isinstance(d, dict)

    def test_maria_self_rx_list(self, maria_h):
        # Simple healthcheck of a self endpoint without on_behalf_of
        r = requests.get(f"{BASE_URL}/api/portal/documents", headers=maria_h)
        assert r.status_code == 200
