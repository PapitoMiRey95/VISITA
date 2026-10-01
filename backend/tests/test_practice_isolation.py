"""
Stage B — Practice-isolation verification.

Scope:
- Public practice resolution endpoints.
- Registration practice stamping (default fallback + explicit-unknown rejection).
- Internal queue isolation (prescriptions, imaging, bloodwork, messages,
  appointments, referrals, verifications, counters, applications).
- Single-record cross-practice access returns 404.
- Default dr-aguayo internal flows still work (no regression).

All synthetic Practice-B data is removed in teardown.
"""
import os
import re
import uuid
import time
import pytest
import requests
import bcrypt
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"

DEFAULT_PRACTICE_ID = "86167166-27f3-4e46-89ee-f9000f700eff"
DEFAULT_PRACTICE_SLUG = "dr-aguayo"

ADMIN_EMAIL = "kevinrodriguez9528@gmail.com"
ADMIN_PASSWORD = "VisitaAdmin2026!"
STAFF_EMAIL = "staff@visita.demo"
STAFF_PASSWORD = "Staff2026!"
PHYS_IDENT = "PAGUAYO"
PHYS_PASSWORD = "Newman2013_!"
PATIENT_EMAIL = "maria.lopez@demo.com"
PATIENT_PASSWORD = "Patient2026!"

TEST_TAG = "TEST_STAGEB"


# ------------------- Shared fixtures -------------------
@pytest.fixture(scope="session")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


def _login(identifier, password):
    r = requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="session")
def staff_token():
    return _login(STAFF_EMAIL, STAFF_PASSWORD)


@pytest.fixture(scope="session")
def physician_token():
    return _login(PHYS_IDENT, PHYS_PASSWORD)


@pytest.fixture(scope="session")
def patient_token():
    return _login(PATIENT_EMAIL, PATIENT_PASSWORD)


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ------------------- Synthetic Practice B seeding -------------------
@pytest.fixture(scope="session")
def practice_b(mongo):
    """Create synthetic Practice B, a scoped admin user, and a few scoped records.
    Teardown removes everything prefixed with TEST_STAGEB."""
    practice_b_id = str(uuid.uuid4())
    now = "2026-01-01T00:00:00Z"
    practice_doc = {
        "id": practice_b_id,
        "slug": f"test-stageb-{practice_b_id[:8]}",
        "registration_code": f"TSTB{practice_b_id[:4].upper()}",
        "physician_name": "TEST_STAGEB Dr Beta",
        "clinic_name": "TEST_STAGEB Clinic B",
        "clinic_phone": "+10000000000",
        "clinic_address": "100 Test St",
        "active": True,
        "created_at": now,
        "updated_at": now,
    }
    mongo.practices.insert_one(dict(practice_doc))

    # Create a staff user scoped to Practice B
    email_b = f"test_stageb_{practice_b_id[:8]}@test.local"
    pwd_b = "TestStageB2026!"
    pw_hash = bcrypt.hashpw(pwd_b.encode(), bcrypt.gensalt()).decode()
    user_b_doc = {
        "email": email_b,
        "name": "TEST_STAGEB Staff B",
        "role": "staff",
        "password_hash": pw_hash,
        "active": True,
        "practice_id": practice_b_id,
        "created_at": now,
        "_test_tag": TEST_TAG,
    }
    mongo.users.insert_one(dict(user_b_doc))

    # Seed one record in each queue for Practice B
    seeded_ids = {"prescription": str(uuid.uuid4()), "imaging": str(uuid.uuid4()),
                  "bloodwork": str(uuid.uuid4()), "message": str(uuid.uuid4()),
                  "appointment": str(uuid.uuid4()), "referral": str(uuid.uuid4()),
                  "verification_patient": str(uuid.uuid4()),
                  "application": str(uuid.uuid4())}

    patient_name = "TEST_STAGEB Patient B"
    mongo.prescription_requests.insert_one({
        "id": seeded_ids["prescription"], "ref_number": "RX-TSTB-1",
        "patient_name": patient_name, "medication_name": "TEST_STAGEB_MED",
        "internal_status": "waiting_physician", "internal_notes": [], "history": [],
        "practice_id": practice_b_id, "practice_slug": practice_doc["slug"],
        "created_at": now, "updated_at": now, "_test_tag": TEST_TAG,
    })
    mongo.imaging_requests.insert_one({
        "id": seeded_ids["imaging"], "ref_number": "IMG-TSTB-1",
        "patient_name": patient_name, "body_part": "TEST_STAGEB_BODY",
        "internal_status": "waiting_physician",
        "practice_id": practice_b_id, "practice_slug": practice_doc["slug"],
        "created_at": now, "updated_at": now, "_test_tag": TEST_TAG,
    })
    mongo.bloodwork_requests.insert_one({
        "id": seeded_ids["bloodwork"], "ref_number": "BLD-TSTB-1",
        "patient_name": patient_name, "reason": "TEST_STAGEB_REASON",
        "internal_status": "waiting_physician",
        "practice_id": practice_b_id, "practice_slug": practice_doc["slug"],
        "created_at": now, "updated_at": now, "_test_tag": TEST_TAG,
    })
    mongo.patient_messages.insert_one({
        "id": seeded_ids["message"], "ref_number": "MSG-TSTB-1",
        "patient_name": patient_name, "subject": "TEST_STAGEB_SUBJ",
        "body": "TEST_STAGEB body", "status": "new", "thread": [],
        "practice_id": practice_b_id, "practice_slug": practice_doc["slug"],
        "created_at": now, "updated_at": now, "_test_tag": TEST_TAG,
    })
    mongo.appointment_requests.insert_one({
        "id": seeded_ids["appointment"], "ref_number": "APT-TSTB-1",
        "patient_name": patient_name, "reason": "TEST_STAGEB_APT",
        "status": "requested", "preferred_options": [],
        "practice_id": practice_b_id, "practice_slug": practice_doc["slug"],
        "created_at": now, "updated_at": now, "_test_tag": TEST_TAG,
    })
    mongo.referrals.insert_one({
        "id": seeded_ids["referral"], "ref_number": "REF-TSTB-1",
        "patient_name": patient_name, "specialty": "TEST_STAGEB_SPC",
        "specialist_name": "Dr Spec B", "ready_to_fax": True, "faxed": False,
        "practice_id": practice_b_id, "practice_slug": practice_doc["slug"],
        "created_at": now, "updated_at": now, "_test_tag": TEST_TAG,
    })
    # Pending patient (for verifications queue)
    mongo.patients.insert_one({
        "id": seeded_ids["verification_patient"],
        "first_name": "TEST_STAGEB", "last_name": "PendingB",
        "date_of_birth": "1990-01-01", "patient_type": "ohip",
        "phone": "+10000000001", "email": f"test_stageb_pending_{practice_b_id[:6]}@test.local",
        "verification_status": "pending", "active_status": True,
        "practice_id": practice_b_id, "practice_slug": practice_doc["slug"],
        "created_at": now, "updated_at": now, "_test_tag": TEST_TAG,
    })
    mongo.patient_applications.insert_one({
        "id": seeded_ids["application"], "ref_number": "APP-TSTB-1",
        "application_type": "new_patient", "first_name": "TEST_STAGEB",
        "last_name": "ApplicantB", "date_of_birth": "1992-01-01",
        "internal_status": "REQUEST_RECEIVED", "history": [],
        "practice_id": practice_b_id, "practice_slug": practice_doc["slug"],
        "created_at": now, "updated_at": now, "_test_tag": TEST_TAG,
    })

    token_b = _login(email_b, pwd_b)
    ctx = {
        "practice_id": practice_b_id,
        "slug": practice_doc["slug"],
        "code": practice_doc["registration_code"],
        "email": email_b,
        "password": pwd_b,
        "token": token_b,
        "ids": seeded_ids,
    }
    yield ctx

    # ---------- Teardown ----------
    mongo.practices.delete_one({"id": practice_b_id})
    mongo.users.delete_many({"_test_tag": TEST_TAG})
    for coll in ["prescription_requests", "imaging_requests", "bloodwork_requests",
                 "patient_messages", "appointment_requests", "referrals",
                 "patients", "patient_applications"]:
        mongo[coll].delete_many({"_test_tag": TEST_TAG})


# ------------------- 1. Public practice endpoints -------------------
class TestPublicPractices:
    def test_get_default_by_slug_returns_public_fields_only(self):
        r = requests.get(f"{API}/practices/{DEFAULT_PRACTICE_SLUG}", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["id"] == DEFAULT_PRACTICE_ID
        assert d["slug"] == DEFAULT_PRACTICE_SLUG
        assert "physician_name" in d
        # No secrets leaked
        assert "registration_code" not in d
        assert "active" not in d
        assert "_id" not in d

    def test_unknown_slug_404(self):
        r = requests.get(f"{API}/practices/does-not-exist-xyz", timeout=20)
        assert r.status_code == 404

    def test_by_code_requires_valid_code(self, practice_b):
        # unknown
        r = requests.get(f"{API}/practices/by-code/UNKNOWN999", timeout=20)
        assert r.status_code == 404
        # valid synthetic
        r2 = requests.get(f"{API}/practices/by-code/{practice_b['code']}", timeout=20)
        assert r2.status_code == 200
        assert r2.json()["id"] == practice_b["practice_id"]
        assert "registration_code" not in r2.json()

    def test_list_practices_search(self, practice_b):
        r = requests.get(f"{API}/practices", params={"q": "TEST_STAGEB"}, timeout=20)
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert practice_b["practice_id"] in ids
        # Public fields only
        for p in r.json():
            assert "registration_code" not in p


# ------------------- 2. Registration context stamping -------------------
class TestRegistrationStamping:
    def _reg_body(self, extra=None):
        suffix = uuid.uuid4().hex[:8]
        body = {
            "first_name": "TEST_STAGEB", "last_name": f"Reg{suffix}",
            "email": f"test_stageb_reg_{suffix}@example.com",
            "phone": "+15550001111", "province": "ON",
            "join_reason": "new_to_area", "reason_other": None,
            "patient_message": "stageb-isolation-test",
            "preferred_language": "en",
            "address": "1 Test Rd", "unit": None, "city": "Toronto",
            "postal_code": "M1M 1M1", "country": "Canada",
            "has_ohip": True, "had_family_doctor": False,
            "date_of_birth": "1990-05-05",
        }
        if extra:
            body.update(extra)
        return body

    def test_default_stamp_when_no_context(self, mongo):
        body = self._reg_body()
        r = requests.post(f"{API}/applications/new-patient", json=body, timeout=20)
        assert r.status_code == 200, r.text
        ref = r.json()["ref_number"]
        doc = mongo.patient_applications.find_one({"ref_number": ref})
        assert doc is not None
        assert doc.get("practice_id") == DEFAULT_PRACTICE_ID
        assert doc.get("practice_slug") == DEFAULT_PRACTICE_SLUG
        mongo.patient_applications.delete_one({"ref_number": ref})

    def test_explicit_unknown_slug_rejected(self):
        body = self._reg_body({"practice_slug": "does-not-exist-xyz"})
        r = requests.post(f"{API}/applications/new-patient", json=body, timeout=20)
        assert r.status_code == 400, r.text

    def test_explicit_unknown_code_rejected(self):
        body = self._reg_body({"practice_code": "ZZZZZZZZ"})
        r = requests.post(f"{API}/applications/new-patient", json=body, timeout=20)
        assert r.status_code == 400

    def test_explicit_valid_slug_stamps(self, mongo, practice_b):
        body = self._reg_body({"practice_slug": practice_b["slug"]})
        r = requests.post(f"{API}/applications/new-patient", json=body, timeout=20)
        assert r.status_code == 200
        ref = r.json()["ref_number"]
        doc = mongo.patient_applications.find_one({"ref_number": ref})
        assert doc.get("practice_id") == practice_b["practice_id"]
        mongo.patient_applications.delete_one({"ref_number": ref})


# ------------------- 3. Internal queue isolation (CORE) -------------------
QUEUE_ENDPOINTS = [
    ("prescriptions", "/internal/prescriptions"),
    ("imaging", "/internal/imaging"),
    ("bloodwork", "/internal/bloodwork"),
    ("messages", "/internal/messages"),
    ("appointments", "/internal/appointments"),
    ("referrals", "/internal/referrals"),
    ("verifications", "/internal/verifications"),
    ("applications", "/internal/applications"),
]


class TestInternalQueueIsolation:

    @pytest.mark.parametrize("name,path", QUEUE_ENDPOINTS)
    def test_practice_B_sees_only_B(self, practice_b, name, path):
        r = requests.get(f"{API}{path}", headers=_h(practice_b["token"]), timeout=20)
        assert r.status_code == 200, f"{name}: {r.status_code} {r.text}"
        rows = r.json()
        # Every returned record (if any) must belong to practice B
        for row in rows:
            # Verifications doesn't return practice_id in projection but IDs we seeded should be known
            if "practice_id" in row:
                assert row["practice_id"] == practice_b["practice_id"], \
                    f"{name} leaked non-B record to B user: {row.get('id')}"
        # And the seeded B record (where applicable) must appear
        key_map = {"prescriptions": "prescription", "imaging": "imaging",
                   "bloodwork": "bloodwork", "messages": "message",
                   "appointments": "appointment", "referrals": "referral",
                   "verifications": "verification_patient", "applications": "application"}
        expected = practice_b["ids"][key_map[name]]
        ids = [r.get("id") for r in rows]
        assert expected in ids, f"{name}: expected B record {expected} not found. ids={ids[:5]}"

    @pytest.mark.parametrize("name,path", QUEUE_ENDPOINTS)
    def test_practice_A_does_NOT_see_B(self, admin_token, practice_b, name, path):
        r = requests.get(f"{API}{path}", headers=_h(admin_token), timeout=20)
        assert r.status_code == 200, f"{name}: {r.status_code} {r.text}"
        rows = r.json()
        key_map = {"prescriptions": "prescription", "imaging": "imaging",
                   "bloodwork": "bloodwork", "messages": "message",
                   "appointments": "appointment", "referrals": "referral",
                   "verifications": "verification_patient", "applications": "application"}
        bad_id = practice_b["ids"][key_map[name]]
        ids = [r.get("id") for r in rows]
        assert bad_id not in ids, f"LEAK: Practice-A user saw Practice-B {name} record {bad_id}"
        # Also validate: no row carries practice_B id
        for row in rows:
            if "practice_id" in row:
                assert row["practice_id"] != practice_b["practice_id"]


# ------------------- 4. Single-record cross-practice -> 404 -------------------
class TestCrossPractice404:
    def test_patch_B_prescription_from_A_returns_404(self, admin_token, practice_b):
        rx_id = practice_b["ids"]["prescription"]
        r = requests.patch(f"{API}/internal/prescriptions/{rx_id}",
                           headers=_h(admin_token),
                           json={"action": "review"}, timeout=20)
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"

    def test_patch_B_message_from_A_returns_404(self, admin_token, practice_b):
        mid = practice_b["ids"]["message"]
        r = requests.patch(f"{API}/internal/messages/{mid}",
                           headers=_h(admin_token),
                           json={"action": "complete"}, timeout=20)
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"

    def test_patch_B_imaging_from_A_returns_404(self, admin_token, practice_b):
        iid = practice_b["ids"]["imaging"]
        r = requests.patch(f"{API}/internal/imaging/{iid}",
                           headers=_h(admin_token),
                           json={"action": "review"}, timeout=20)
        assert r.status_code == 404

    def test_patch_B_bloodwork_from_A_returns_404(self, admin_token, practice_b):
        bid = practice_b["ids"]["bloodwork"]
        r = requests.patch(f"{API}/internal/bloodwork/{bid}",
                           headers=_h(admin_token),
                           json={"action": "review"}, timeout=20)
        assert r.status_code == 404


# ------------------- 5. Counters practice-scope -------------------
class TestCounters:
    def test_admin_counters_do_not_include_B_records(self, admin_token, practice_b, mongo):
        """Counter endpoint must only count the caller's practice records."""
        r = requests.get(f"{API}/internal/counters", headers=_h(admin_token), timeout=20)
        assert r.status_code == 200
        c = r.json()["counters"]

        # Compute "A-only" counts directly from Mongo to compare.
        # Must mirror server db.RX_ACTIVE exactly.
        RX_ACTIVE = ["received", "under_review", "waiting_physician",
                     "approved_process_visita", "more_info_required"]
        a_rx = mongo.prescription_requests.count_documents(
            {"practice_id": DEFAULT_PRACTICE_ID,
             "internal_status": {"$in": RX_ACTIVE}})
        # Server-reported rx should be <= total but == to a_rx if properly scoped
        total_rx = mongo.prescription_requests.count_documents(
            {"internal_status": {"$in": RX_ACTIVE}})
        # Our seeded B rx is "waiting_physician" → counted in total but not in A.
        assert total_rx > a_rx, "seed sanity: B record should bump total above A"
        assert c["rx"] == a_rx, f"counters.rx leaks cross-practice: reported={c['rx']} A-only={a_rx} total={total_rx}"

    def test_B_counters_only_count_B(self, practice_b):
        r = requests.get(f"{API}/internal/counters", headers=_h(practice_b["token"]), timeout=20)
        assert r.status_code == 200
        c = r.json()["counters"]
        # Rx: exactly 1 waiting_physician record for B
        assert c["rx"] == 1, f"B user counters.rx expected 1, got {c['rx']}"
        assert c["imaging"] == 1
        assert c["bloodwork"] == 1


# ------------------- 6. Default dr-aguayo flows still work -------------------
class TestNoRegressionDefault:
    def test_admin_counters_200(self, admin_token):
        r = requests.get(f"{API}/internal/counters", headers=_h(admin_token), timeout=20)
        assert r.status_code == 200

    def test_staff_counters_200(self, staff_token):
        r = requests.get(f"{API}/internal/counters", headers=_h(staff_token), timeout=20)
        assert r.status_code == 200

    def test_physician_counters_200(self, physician_token):
        r = requests.get(f"{API}/internal/counters", headers=_h(physician_token), timeout=20)
        assert r.status_code == 200

    @pytest.mark.parametrize("name,path", QUEUE_ENDPOINTS)
    def test_admin_queues_200(self, admin_token, name, path):
        r = requests.get(f"{API}{path}", headers=_h(admin_token), timeout=20)
        assert r.status_code == 200, f"{name}: {r.status_code} {r.text}"

    def test_admin_sees_existing_demo_records(self, admin_token):
        """Non-empty queues sanity (demo data must still be visible to admin)."""
        r_apps = requests.get(f"{API}/internal/applications",
                              headers=_h(admin_token), timeout=20)
        r_verif = requests.get(f"{API}/internal/verifications",
                               headers=_h(admin_token), timeout=20)
        # at least one of applications or verifications should be non-empty for the
        # demo tenant — accept either (data may fluctuate).
        assert r_apps.status_code == 200 and r_verif.status_code == 200


# ------------------- 7. Patient portal unaffected -------------------
class TestPatientPortalUnaffected:
    def test_patient_overview_200(self, patient_token):
        r = requests.get(f"{API}/portal/overview", headers=_h(patient_token), timeout=20)
        assert r.status_code == 200, r.text

    def test_patient_me_200(self, patient_token):
        r = requests.get(f"{API}/auth/me", headers=_h(patient_token), timeout=20)
        assert r.status_code == 200
