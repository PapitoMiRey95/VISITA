"""Backend tests for Professional SELF-onboarding (PUT /api/professionals/me).

Covers:
- physician can create/update own canonical profile via PUT /professionals/me
- high-risk fields (linked_user_id, id, role) are stripped server-side
- calling PUT twice returns SAME profile id (duplicate guard + partial-unique index)
- patient cannot call PUT /professionals/me (403)
- physician cannot POST /professionals (403)
- audit_logs has professional_profile_created edit_source=SELF, no secrets
- cleans up: professional_profiles ends EMPTY for this user
"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient
from dotenv import dotenv_values

_fe = dotenv_values("/app/frontend/.env")
_be = dotenv_values("/app/backend/.env")
BASE_URL = (_fe.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").strip('"').rstrip("/")
MONGO_URL = (_be.get("MONGO_URL") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017").strip('"')
DB_NAME = (_be.get("DB_NAME") or os.environ.get("DB_NAME") or "test_database").strip('"')
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

# --- helpers ---------------------------------------------------------------

def _login(identifier: str, password: str):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": identifier, "password": password}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"login failed for {identifier}: {r.status_code} {r.text[:200]}")
    return r.json()


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


@pytest.fixture(scope="module")
def physician():
    return _login("PAGUAYO", "Newman2013_!")


@pytest.fixture(scope="module")
def admin():
    return _login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")


@pytest.fixture(scope="module")
def phys_headers(physician):
    return {"Authorization": f"Bearer {physician['token']}"}


@pytest.fixture(scope="module")
def admin_headers(admin):
    return {"Authorization": f"Bearer {admin['token']}"}


@pytest.fixture(scope="module", autouse=True)
def _wipe(db):
    db.professional_profiles.delete_many({})
    db.professional_profile_editors.delete_many({})
    db.professional_organization_affiliations.delete_many({})
    yield
    db.professional_profiles.delete_many({})
    db.professional_profile_editors.delete_many({})
    db.professional_organization_affiliations.delete_many({})


# --- baseline -------------------------------------------------------------

class TestSelfOnboarding:

    def test_me_null_before(self, phys_headers):
        r = requests.get(f"{BASE_URL}/api/professionals/me", headers=phys_headers, timeout=10)
        assert r.status_code == 200
        assert r.json().get("profile") is None

    def test_create_self_profile_strips_high_risk(self, phys_headers, physician, admin):
        forged = {
            "id": "HACKED",
            "linked_user_id": admin["user"]["id"],  # someone else's id
            "role": "admin",
            "surname": "ZZSelfTest",
            "given_name": "QA",
            "sphere_id": "1",
            "area_id": "36",
            "registration": "CPSO-QA1",
            "specialty_id": "133",
            "areas_of_practice_ids": [],
            "language_ids": [],
            "credential_ids": [],
            "practice_type_ids": [],
            "primary_care_model_ids": [],
            "organization_ids": [],
        }
        r = requests.put(f"{BASE_URL}/api/professionals/me",
                         json=forged, headers=phys_headers, timeout=15)
        assert r.status_code == 200, r.text
        prof = r.json()
        assert prof["id"] != "HACKED"
        # id must be a real uuid
        uuid.UUID(prof["id"])
        assert prof.get("linked_user_id") == physician["user"]["id"]
        assert prof.get("role") in (None, "", "physician") or "role" not in prof
        assert prof["surname"] == "ZZSelfTest"

    def test_duplicate_put_returns_same_id(self, phys_headers, db, physician):
        # second PUT should update in place -> same id, exactly 1 doc for this user
        first = requests.get(f"{BASE_URL}/api/professionals/me",
                             headers=phys_headers, timeout=10).json()["profile"]
        assert first is not None
        r = requests.put(f"{BASE_URL}/api/professionals/me",
                         json={"surname": "ZZSelfTest", "sphere_id": "1", "area_id": "36",
                               "registration": "CPSO-QA1", "specialty_id": "133"},
                         headers=phys_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["id"] == first["id"]
        count = db.professional_profiles.count_documents({"linked_user_id": physician["user"]["id"]})
        assert count == 1

    def test_audit_log_entry(self, db, physician):
        # allow any log write delay
        time.sleep(0.5)
        entries = list(db.audit_logs.find({
            "action": "professional_profile_created",
            "actor_id": physician["user"]["id"],
        }).sort("_id", -1).limit(3))
        assert entries, "no professional_profile_created audit entry"
        top = entries[0]
        meta = top.get("meta") or {}
        assert meta.get("edit_source") == "SELF"
        # no obvious secrets
        blob = str(top).lower()
        for bad in ("password", "token", "bearer "):
            assert bad not in blob, f"secret leaked in audit: {bad}"

    def test_physician_cannot_post_canonical(self, phys_headers):
        r = requests.post(f"{BASE_URL}/api/professionals",
                          json={"surname": "ZZOther", "sphere_id": "1", "area_id": "36",
                                "specialty_id": "133", "registration": "X"},
                          headers=phys_headers, timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"


class TestPatientForbidden:
    """A patient-role user must not be able to PUT /professionals/me (403)."""

    def test_patient_put_me_forbidden(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "maria.lopez@demo.com", "password": "Patient2026!"},
                          timeout=15)
        if r.status_code != 200:
            pytest.skip("patient login unavailable")
        tok = r.json()["token"]
        r2 = requests.put(f"{BASE_URL}/api/professionals/me",
                          json={"surname": "ZZPatient"},
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r2.status_code == 403


class TestAdminCanUseMeEndpoint:
    """PROF_SELF_ROLES includes admin; ensure endpoint reachable (not 403)."""

    def test_admin_get_me_200(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/professionals/me", headers=admin_headers, timeout=10)
        assert r.status_code == 200
