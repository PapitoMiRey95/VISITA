"""Stage C — patient_provider_relationships testing.

Covers:
- Relationship creation on registration (applicant / active)
- Relationship on new-patient application (applicant via application_id)
- Applicant → active transition on physician accept
- Verify → active, reject → inactive
- Identity link preserves canonical PIN + re-anchors relationship (409 for duplicate link)
- Duplicate prevention (one relationship per (practice, canonical identity))
- New read endpoints: /internal/patients/{id}/relationship + /internal/canonical/{directory_id}/relationships
- Cross-practice isolation (Practice B leak check — no PHI leak, no row leak into dr-aguayo queues)
- No former/re-establish regression (FORMER match returns application_required)

Teardown removes all synthetic rows tagged _test_tag='TEST_STAGEC' and never touches real
dr-aguayo data, demo patients, or existing relationships.
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

DRAGUAYO_PRACTICE_ID = "86167166-27f3-4e46-89ee-f9000f700eff"
TAG = "TEST_STAGEC"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def mongo():
    c = MongoClient(MONGO_URL)
    try:
        yield c[DB_NAME]
    finally:
        c.close()


def _login(identifier, password):
    r = requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_token():
    return _login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")


@pytest.fixture(scope="session")
def staff_token():
    return _login("staff@visita.demo", os.environ["TEST_STAFF_PASSWORD"])


@pytest.fixture(scope="session")
def physician_token():
    return _login("PAGUAYO", os.environ["TEST_PHYSICIAN_PASSWORD"])


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ---------------------------------------------------------------------------
# Synthetic Practice B + synthetic directory record w/ relationships in both practices.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def practice_b(mongo):
    pb_id = str(uuid.uuid4())
    slug = f"stagec-pb-{uuid.uuid4().hex[:8]}"
    pb = {
        "id": pb_id, "slug": slug, "clinic_name": "StageC Practice B",
        "physician_name": "Dr. StageC B", "registration_code": f"PBC{uuid.uuid4().hex[:4].upper()}",
        "active": True, "_test_tag": TAG,
    }
    mongo.practices.insert_one(dict(pb))
    yield pb
    mongo.practices.delete_many({"_test_tag": TAG})


@pytest.fixture
def canonical_cross(mongo, practice_b):
    """A synthetic canonical directory record that has an ACTIVE relationship in BOTH
    dr-aguayo and Practice B — used to test cross-practice isolation."""
    dir_id = str(uuid.uuid4())
    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())
    pin = f"9{uuid.uuid4().int % 1000:03d}"
    mongo.patient_directory.insert_one({
        "id": dir_id, "visita_patient_id": pin,
        "first_name": "StageC", "last_name": "Cross", "date_of_birth": "1980-01-01",
        "patient_status": "ACTIVE", "norm_first": "stagec", "norm_last": "cross",
        "norm_dob": "19800101", "norm_hcn": "",
        "_test_tag": TAG,
    })
    mongo.patient_provider_relationships.insert_many([
        {"id": "rel_" + uuid.uuid4().hex, "practice_id": DRAGUAYO_PRACTICE_ID,
         "directory_id": dir_id, "patient_id": pid_a, "visita_patient_id": pin,
         "status": "active", "source": "test_seed", "history": [], "_test_tag": TAG},
        {"id": "rel_" + uuid.uuid4().hex, "practice_id": practice_b["id"],
         "directory_id": dir_id, "patient_id": pid_b, "visita_patient_id": pin,
         "status": "active", "source": "test_seed", "history": [], "_test_tag": TAG},
    ])
    # Minimal portal patient on dr-aguayo side so /internal/patients/{id}/relationship can be exercised.
    mongo.patients.insert_one({
        "id": pid_a, "first_name": "StageC", "last_name": "Cross",
        "date_of_birth": "1980-01-01", "email": f"stagec_cross_{uuid.uuid4().hex[:6]}@example.com",
        "visita_patient_id": pin, "matched_directory_id": dir_id,
        "practice_id": DRAGUAYO_PRACTICE_ID,
        "verification_status": "verified", "active_status": True,
        "_test_tag": TAG,
    })
    # Portal patient on Practice B side (used to test cross-practice GET 404).
    mongo.patients.insert_one({
        "id": pid_b, "first_name": "StageC", "last_name": "Cross",
        "date_of_birth": "1980-01-01", "email": f"stagec_crossb_{uuid.uuid4().hex[:6]}@example.com",
        "visita_patient_id": pin, "matched_directory_id": dir_id,
        "practice_id": practice_b["id"],
        "verification_status": "verified", "active_status": True,
        "_test_tag": TAG,
    })
    yield {"directory_id": dir_id, "pid_a": pid_a, "pid_b": pid_b, "pin": pin}


@pytest.fixture(scope="session", autouse=True)
def _global_teardown(mongo):
    yield
    # Wipe everything tagged TEST_STAGEC across any collection we might have touched.
    for coll in ("patient_provider_relationships", "patient_directory", "patients",
                 "patient_applications", "users", "practices", "visita_pins",
                 "account_activations"):
        mongo[coll].delete_many({"_test_tag": TAG})
    # Clean up any registration/application/user artefacts by TEST_STAGEC email prefix.
    mongo.users.delete_many({"email": {"$regex": "^stagec_"}})
    mongo.patients.delete_many({"email": {"$regex": "^stagec_"}})
    mongo.patient_applications.delete_many({"email": {"$regex": "^stagec_"}})
    mongo.patient_provider_relationships.delete_many({"_test_tag": TAG})


# Convenience: unique synthetic registration/application body.
def _reg_body(email_prefix="stagec_reg"):
    email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@example.com"
    return {
        "first_name": "StageC", "last_name": "Unmatched",
        "date_of_birth": "1990-05-10",
        "email": email, "password": "Patient2026!",
        "phone": "4165551234", "patient_type": "private",
        "province": "ON", "country": "Canada",
        "address": "1 Test St", "city": "Toronto", "postal_code": "M5A1A1",
    }


def _new_patient_app_body(email_prefix="stagec_app"):
    email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@example.com"
    return {
        "first_name": "StageC", "last_name": "Applicant",
        "date_of_birth": "1992-08-15",
        "email": email, "phone": "4165557777",
        "address": "99 App Rd", "city": "Toronto", "province": "ON",
        "postal_code": "M5A1A1", "country": "Canada",
        "has_ohip": True, "had_family_doctor": "no",
        "join_reason": "new", "patient_message": "stage c test",
    }


# ===========================================================================
# 1. Registration -> applicant relationship
# ===========================================================================
class TestRegistrationRelationship:
    def test_unmatched_registration_creates_applicant(self, mongo):
        body = _reg_body()
        r = requests.post(f"{API}/auth/register", json=body, timeout=20)
        assert r.status_code == 200, r.text
        user = r.json()["user"]
        pid = user["patient_id"]
        # tag for teardown
        mongo.patients.update_one({"id": pid}, {"$set": {"_test_tag": TAG}})
        mongo.users.update_one({"email": body["email"]}, {"$set": {"_test_tag": TAG}})
        rel = mongo.patient_provider_relationships.find_one({
            "practice_id": DRAGUAYO_PRACTICE_ID, "patient_id": pid})
        assert rel is not None, "No relationship row created on registration"
        assert rel["status"] == "applicant"
        assert rel["source"] == "registration"
        assert rel["directory_id"] is None
        # history has a creation entry
        assert len(rel.get("history", [])) >= 1
        assert rel["history"][0]["status"] == "applicant"

    def test_duplicate_email_registration_still_400(self, mongo):
        body = _reg_body()
        r1 = requests.post(f"{API}/auth/register", json=body, timeout=20)
        assert r1.status_code == 200
        pid = r1.json()["user"]["patient_id"]
        mongo.patients.update_one({"id": pid}, {"$set": {"_test_tag": TAG}})
        mongo.users.update_one({"email": body["email"]}, {"$set": {"_test_tag": TAG}})
        r2 = requests.post(f"{API}/auth/register", json=body, timeout=20)
        assert r2.status_code == 400

    def test_former_match_returns_application_required_no_account(self, mongo):
        # Seed a synthetic FORMER_CLOSED directory record (preview DB has none loaded)
        former_hcn = f"999{uuid.uuid4().int % 10000000:07d}"
        former_last = f"STAGEC_FORMER_{uuid.uuid4().hex[:6].upper()}"
        mongo.patient_directory.insert_one({
            "id": str(uuid.uuid4()),
            "first_name": "Ahmed Mohammed", "last_name": former_last,
            "date_of_birth": "1990-01-21", "health_card_number": former_hcn,
            "patient_status": "FORMER_CLOSED",
            "norm_first": "ahmed mohammed", "norm_last": former_last.lower(),
            "norm_dob": "19900121", "norm_hcn": former_hcn,
            "_test_tag": TAG,
        })
        body = _reg_body("stagec_former")
        body.update({
            "first_name": "Ahmed Mohammed", "last_name": former_last,
            "date_of_birth": "1990-01-21", "patient_type": "ohip",
            "health_card_number": former_hcn, "health_card_version": "AB",
            "health_card_issue_date": "2024-01-21",
            "health_card_expiry_date": "2030-01-21",
        })
        r = requests.post(f"{API}/auth/register", json=body, timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("application_required") is True
        assert "token" not in j
        # No account, no portal user, no relationship created
        assert mongo.users.find_one({"email": body["email"]}) is None
        assert mongo.patient_provider_relationships.find_one(
            {"source": "registration", "practice_id": DRAGUAYO_PRACTICE_ID,
             "patient_id": {"$exists": True},
             "history.note": {"$regex": "former_return"}}) is None


# ===========================================================================
# 2. New-patient application -> applicant via application_id
# ===========================================================================
class TestNewPatientApplicationRelationship:
    def test_new_patient_app_creates_applicant_by_application_id(self, mongo):
        body = _new_patient_app_body()
        r = requests.post(f"{API}/applications/new-patient", json=body, timeout=20)
        assert r.status_code == 200, r.text
        app = mongo.patient_applications.find_one({"email": body["email"]})
        assert app is not None
        mongo.patient_applications.update_one({"id": app["id"]}, {"$set": {"_test_tag": TAG}})
        rel = mongo.patient_provider_relationships.find_one({"application_id": app["id"]})
        assert rel is not None
        assert rel["status"] == "applicant"
        assert rel["source"] == "application"
        assert rel["directory_id"] is None
        assert rel["patient_id"] is None
        assert rel["practice_id"] == DRAGUAYO_PRACTICE_ID


# ===========================================================================
# 3. Physician accept new-patient application -> applicant->active (single relationship, single directory)
# ===========================================================================
class TestApplicantToActiveTransition:
    def test_accept_transitions_applicant_to_active(self, mongo, physician_token):
        body = _new_patient_app_body("stagec_accept")
        r = requests.post(f"{API}/applications/new-patient", json=body, timeout=20)
        assert r.status_code == 200
        app = mongo.patient_applications.find_one({"email": body["email"]})
        app_id = app["id"]
        mongo.patient_applications.update_one({"id": app_id}, {"$set": {"_test_tag": TAG}})

        # Confirm applicant row created before accept
        rel_before = mongo.patient_provider_relationships.find_one({"application_id": app_id})
        assert rel_before and rel_before["status"] == "applicant"
        rel_id = rel_before["id"]

        # Physician accepts
        r = requests.patch(f"{API}/internal/applications/{app_id}",
                           json={"action": "accept"}, headers=H(physician_token), timeout=30)
        assert r.status_code == 200, r.text

        app2 = mongo.patient_applications.find_one({"id": app_id})
        patient_id = app2.get("created_patient_id")
        assert patient_id, "accept did not create portal patient"
        mongo.patients.update_one({"id": patient_id}, {"$set": {"_test_tag": TAG}})
        if app2.get("account_created_user_id"):
            from bson import ObjectId
            try:
                mongo.users.update_one({"_id": ObjectId(app2["account_created_user_id"])},
                                       {"$set": {"_test_tag": TAG}})
            except Exception:
                pass

        p = mongo.patients.find_one({"id": patient_id})
        dir_id = p.get("matched_directory_id")
        assert dir_id, "accept did not anchor to a directory_id"
        mongo.patient_directory.update_one({"id": dir_id}, {"$set": {"_test_tag": TAG}})

        # Still ONE relationship, same id, now active, anchored to dir+patient+pin
        rel_after = mongo.patient_provider_relationships.find_one({"application_id": app_id})
        assert rel_after is not None
        assert rel_after["id"] == rel_id, "A second relationship row was created on accept"
        assert rel_after["status"] == "active"
        assert rel_after["directory_id"] == dir_id
        assert rel_after["patient_id"] == patient_id
        assert rel_after["visita_patient_id"] == p["visita_patient_id"]
        # History records the applicant->active transition
        statuses = [h.get("status") for h in rel_after.get("history", [])]
        assert "active" in statuses and "applicant" in statuses

        # And exactly ONE directory record was created
        dir_count = mongo.patient_directory.count_documents({"created_from_application_id": app_id})
        assert dir_count == 1, f"expected exactly 1 canonical directory record, got {dir_count}"


# ===========================================================================
# 4. Verify -> active, reject -> inactive
# ===========================================================================
class TestVerifyRejectRelationship:
    def _seed_pending_portal_patient(self, mongo):
        pid = str(uuid.uuid4())
        email = f"stagec_pend_{uuid.uuid4().hex[:6]}@example.com"
        mongo.patients.insert_one({
            "id": pid, "first_name": "StageC", "last_name": "Pend",
            "date_of_birth": "1991-02-02", "phone": "4165550000",
            "email": email, "patient_type": "private",
            "verification_status": "pending", "portal_status": "PENDING_VERIFICATION",
            "practice_id": DRAGUAYO_PRACTICE_ID,
            "active_status": True, "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "_test_tag": TAG,
        })
        # Seed an applicant relationship (as if from registration)
        mongo.patient_provider_relationships.insert_one({
            "id": "rel_" + uuid.uuid4().hex,
            "practice_id": DRAGUAYO_PRACTICE_ID, "patient_id": pid,
            "directory_id": None, "application_id": None,
            "status": "applicant", "source": "test_seed",
            "history": [{"status": "applicant", "at": "2026-01-01T00:00:00+00:00",
                         "by": "test", "source": "test_seed"}],
            "_test_tag": TAG,
        })
        return pid

    def test_verify_flips_to_active(self, mongo, staff_token):
        pid = self._seed_pending_portal_patient(mongo)
        r = requests.post(f"{API}/internal/verifications/{pid}",
                          json={"decision": "verified"}, headers=H(staff_token), timeout=20)
        assert r.status_code == 200, r.text
        rel = mongo.patient_provider_relationships.find_one(
            {"practice_id": DRAGUAYO_PRACTICE_ID, "patient_id": pid})
        assert rel["status"] == "active"
        assert any(h["status"] == "active" for h in rel["history"])

    def test_reject_flips_to_inactive(self, mongo, staff_token):
        pid = self._seed_pending_portal_patient(mongo)
        r = requests.post(f"{API}/internal/verifications/{pid}",
                          json={"decision": "rejected"}, headers=H(staff_token), timeout=20)
        assert r.status_code == 200, r.text
        rel = mongo.patient_provider_relationships.find_one(
            {"practice_id": DRAGUAYO_PRACTICE_ID, "patient_id": pid})
        assert rel["status"] == "inactive"


# ===========================================================================
# 5. Identity link preserves canonical identity + 409 for duplicate link
# ===========================================================================
class TestIdentityLinkPreservesCanonical:
    def test_link_preserves_pin_and_reanchors(self, mongo, staff_token):
        # Seed a canonical directory record (no linked patient)
        dir_id = str(uuid.uuid4())
        pin = f"8{uuid.uuid4().int % 1000:03d}"
        mongo.patient_directory.insert_one({
            "id": dir_id, "visita_patient_id": pin,
            "first_name": "Link", "last_name": "Candidate",
            "date_of_birth": "1985-03-03", "patient_status": "ACTIVE",
            "norm_first": "link", "norm_last": "candidate", "norm_dob": "19850303",
            "norm_hcn": "", "_test_tag": TAG,
        })
        # Seed a portal patient (pending) at dr-aguayo
        pid = str(uuid.uuid4())
        mongo.patients.insert_one({
            "id": pid, "first_name": "Link", "last_name": "Candidate",
            "date_of_birth": "1985-03-03", "phone": "4165550001",
            "email": f"stagec_link_{uuid.uuid4().hex[:6]}@example.com",
            "verification_status": "pending", "active_status": True,
            "practice_id": DRAGUAYO_PRACTICE_ID,
            "visita_patient_id": None,
            "_test_tag": TAG,
        })
        # Seed an applicant relationship
        mongo.patient_provider_relationships.insert_one({
            "id": "rel_" + uuid.uuid4().hex, "practice_id": DRAGUAYO_PRACTICE_ID,
            "patient_id": pid, "status": "applicant", "source": "test_seed",
            "history": [], "_test_tag": TAG,
        })
        dir_count_before = mongo.patient_directory.count_documents({})

        r = requests.post(f"{API}/internal/patients/{pid}/link-directory",
                          json={"directory_id": dir_id}, headers=H(staff_token), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["visita_patient_id"] == pin

        # No second canonical directory created
        assert mongo.patient_directory.count_documents({}) == dir_count_before

        # PIN preserved on portal patient
        p = mongo.patients.find_one({"id": pid})
        assert p["visita_patient_id"] == pin

        # Relationship re-anchored to dir_id — still ONE relationship
        rels = list(mongo.patient_provider_relationships.find(
            {"practice_id": DRAGUAYO_PRACTICE_ID, "patient_id": pid}))
        assert len(rels) == 1, f"duplicate relationship after link: {len(rels)}"
        assert rels[0]["directory_id"] == dir_id

        # Second attempt linking a different patient to same dir -> 409
        pid2 = str(uuid.uuid4())
        mongo.patients.insert_one({
            "id": pid2, "first_name": "Link", "last_name": "Other",
            "date_of_birth": "1985-03-03",
            "email": f"stagec_link2_{uuid.uuid4().hex[:6]}@example.com",
            "verification_status": "pending", "active_status": True,
            "practice_id": DRAGUAYO_PRACTICE_ID, "_test_tag": TAG,
        })
        # Confirm the row is readable from the API side before linking
        import time
        for _ in range(5):
            if mongo.patients.find_one({"id": pid2}) is not None:
                break
            time.sleep(0.2)
        r2 = requests.post(f"{API}/internal/patients/{pid2}/link-directory",
                           json={"directory_id": dir_id}, headers=H(staff_token), timeout=20)
        assert r2.status_code == 409, r2.text


# ===========================================================================
# 6. Duplicate prevention: re-running the same ops does not create 2nd rel
# ===========================================================================
class TestDuplicatePrevention:
    def test_verify_twice_does_not_duplicate(self, mongo, staff_token):
        pid = str(uuid.uuid4())
        mongo.patients.insert_one({
            "id": pid, "first_name": "DupV", "last_name": "Prev",
            "date_of_birth": "1991-02-02",
            "email": f"stagec_dupv_{uuid.uuid4().hex[:6]}@example.com",
            "verification_status": "pending", "active_status": True,
            "practice_id": DRAGUAYO_PRACTICE_ID, "_test_tag": TAG,
        })
        mongo.patient_provider_relationships.insert_one({
            "id": "rel_" + uuid.uuid4().hex, "practice_id": DRAGUAYO_PRACTICE_ID,
            "patient_id": pid, "status": "applicant", "source": "test_seed",
            "history": [], "_test_tag": TAG,
        })
        for _ in range(3):
            requests.post(f"{API}/internal/verifications/{pid}",
                          json={"decision": "verified"}, headers=H(staff_token), timeout=20)
        count = mongo.patient_provider_relationships.count_documents(
            {"practice_id": DRAGUAYO_PRACTICE_ID, "patient_id": pid})
        assert count == 1, f"duplicate relationships after re-verify: {count}"


# ===========================================================================
# 7. GET endpoints: /relationship + /canonical/{dir}/relationships + cross-practice isolation
# ===========================================================================
class TestRelationshipReadEndpoints:
    def test_patient_relationship_endpoint_own_practice(self, mongo, staff_token, canonical_cross):
        pid_a = canonical_cross["pid_a"]
        r = requests.get(f"{API}/internal/patients/{pid_a}/relationship",
                         headers=H(staff_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["relationship"] is not None
        assert data["relationship"]["status"] == "active"
        assert data["relationship"]["practice_id"] == DRAGUAYO_PRACTICE_ID
        assert "label" in data["relationship"]

    def test_patient_relationship_404_cross_practice(self, mongo, staff_token, canonical_cross):
        # A dr-aguayo staff must NOT see Practice B's portal patient.
        pid_b = canonical_cross["pid_b"]
        r = requests.get(f"{API}/internal/patients/{pid_b}/relationship",
                         headers=H(staff_token), timeout=20)
        assert r.status_code == 404, f"cross-practice leak: {r.status_code} {r.text}"

    def test_canonical_relationships_isolates_other_practices(self, staff_token, canonical_cross):
        dir_id = canonical_cross["directory_id"]
        r = requests.get(f"{API}/internal/canonical/{dir_id}/relationships",
                         headers=H(staff_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        # own = dr-aguayo (full)
        assert data["own"] is not None
        assert data["own"]["practice_id"] == DRAGUAYO_PRACTICE_ID
        # others = Practice B as status-only summary (no PHI)
        assert isinstance(data["others"], list) and len(data["others"]) >= 1
        for o in data["others"]:
            # Must NOT leak PHI; allowed keys are practice-name/status/label/updated/practice_id
            disallowed = {"first_name", "last_name", "email", "date_of_birth",
                          "phone", "health_card_number", "patient_id", "visita_patient_id"}
            assert not (set(o.keys()) & disallowed), f"PHI leaked in canonical.others: {o}"
            assert "practice_name" in o
            assert "status" in o


# ===========================================================================
# 8. Cross-practice: Practice B rows must NOT leak into dr-aguayo queues
# ===========================================================================
class TestQueueIsolation:
    def test_identity_links_queue_scoped(self, mongo, staff_token, practice_b):
        # Seed a Practice-B portal patient with directory_match candidates (identity-link queue candidate)
        pid_b = str(uuid.uuid4())
        mongo.patients.insert_one({
            "id": pid_b, "first_name": "Isolate", "last_name": "Leak",
            "date_of_birth": "1980-01-01",
            "email": f"stagec_isob_{uuid.uuid4().hex[:6]}@example.com",
            "practice_id": practice_b["id"], "active_status": True,
            "verification_status": "pending", "identity_linked": False,
            "directory_match": {"candidates": [{"id": "x", "strength": "weak"}],
                                "strength": "weak"},
            "_test_tag": TAG,
        })
        r = requests.get(f"{API}/internal/identity-links", headers=H(staff_token), timeout=20)
        assert r.status_code == 200
        ids = [row["id"] for row in r.json()]
        assert pid_b not in ids, "Practice B portal patient leaked into dr-aguayo /internal/identity-links"
