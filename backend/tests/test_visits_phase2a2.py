"""Phase 2A2 backend tests: Vitals PATCH + Previous Encounters history has_vitals."""
import os
import pytest
import requests
from pymongo import MongoClient

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

PHYS_U, PHYS_P = "PAGUAYO", "Newman2013_!"
STAFF_U, STAFF_P = "staff@visita.demo", "Staff2026!"
ADMIN_U, ADMIN_P = "kevinrodriguez9528@gmail.com", "VisitaAdmin2026!"

MARIA_PATIENT_ID = "06f6ee08-58f7-4286-82f5-7c845de99ce1"
ROMERO_DIR_ID = "c5c30d56-acdd-416b-b61d-5cf8aab06a74"

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"


def _login(identifier, password):
    r = requests.post(f"{API}/auth/login", json={"email": identifier, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def phys_tok():
    return _login(PHYS_U, PHYS_P)


@pytest.fixture(scope="module")
def staff_tok():
    return _login(STAFF_U, STAFF_P)


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN_U, ADMIN_P)


@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="module")
def visit_id(phys_tok, mongo):
    # Clean up any prior maria IN_PROGRESS visits for this physician
    mongo.visits.delete_many({"patient_id": MARIA_PATIENT_ID, "status": "IN_PROGRESS"})
    r = requests.post(f"{API}/internal/visits", headers=_h(phys_tok),
                      json={"patient_id": MARIA_PATIENT_ID, "encounter_type": "IN_CLINIC"}, timeout=20)
    if r.status_code == 409:
        vid = r.json()["detail"]["visit_id"]
    else:
        assert r.status_code in (200, 201), r.text
        vid = r.json()["id"]
    yield vid
    # cleanup
    mongo.visits.delete_one({"id": vid})
    mongo.audit_logs.delete_many({"entity_id": vid})


class TestVitalsPatch:
    def test_patch_full_vitals(self, phys_tok, visit_id, mongo):
        body = {"systolic_bp": 128, "diastolic_bp": 82, "heart_rate": 72,
                "temperature_c": 36.8, "weight_kg": 80, "height_cm": 175}
        r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(phys_tok), json=body, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["noop"] is False
        assert len(data["changed"]) == 6
        v = data["vitals"]
        assert v["bmi"] == 26.1
        assert v["systolic_bp"] == 128 and v["diastolic_bp"] == 82
        # updated_by.name
        doc = mongo.visits.find_one({"id": visit_id})
        assert doc["vitals"]["updated_by"]["name"] == "Dr. Pablo Aguayo"

    def test_patch_noop(self, phys_tok, visit_id, mongo):
        before = mongo.audit_logs.count_documents({"entity_id": visit_id, "action": "visit_vitals_saved"})
        body = {"systolic_bp": 128, "diastolic_bp": 82, "heart_rate": 72,
                "temperature_c": 36.8, "weight_kg": 80, "height_cm": 175}
        r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(phys_tok), json=body, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["noop"] is True
        assert d["changed"] == []
        after = mongo.audit_logs.count_documents({"entity_id": visit_id, "action": "visit_vitals_saved"})
        assert before == after, "no-op must not write audit"

    def test_clear_height_bmi_null(self, phys_tok, visit_id):
        r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(phys_tok),
                           json={"height_cm": None}, timeout=20)
        assert r.status_code == 200
        v = r.json()["vitals"]
        assert v["height_cm"] is None
        assert v["bmi"] is None
        # restore height for subsequent cleanup / to leave realistic state
        r2 = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(phys_tok),
                            json={"height_cm": 175}, timeout=20)
        assert r2.status_code == 200
        assert r2.json()["vitals"]["bmi"] == 26.1

    def test_non_numeric_400(self, phys_tok, visit_id):
        r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(phys_tok),
                           json={"heart_rate": "abc"}, timeout=20)
        assert r.status_code == 400, r.text

    def test_implausible_400(self, phys_tok, visit_id):
        r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(phys_tok),
                           json={"systolic_bp": 900}, timeout=20)
        assert r.status_code == 400

    def test_unknown_field_400(self, phys_tok, visit_id):
        r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(phys_tok),
                           json={"subjective": "x"}, timeout=20)
        assert r.status_code == 400

    def test_get_visit_returns_vitals(self, phys_tok, visit_id):
        r = requests.get(f"{API}/internal/visits/{visit_id}", headers=_h(phys_tok), timeout=20)
        assert r.status_code == 200
        v = r.json()
        assert "vitals" in v
        assert v["vitals"]["bmi"] == 26.1

    def test_staff_403(self, staff_tok, visit_id):
        r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(staff_tok),
                           json={"heart_rate": 70}, timeout=20)
        assert r.status_code == 403, r.text

    def test_admin_403(self, admin_tok, visit_id):
        r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(admin_tok),
                           json={"heart_rate": 70}, timeout=20)
        assert r.status_code == 403, r.text

    def test_cross_practice_404(self, phys_tok, visit_id, mongo):
        orig = mongo.visits.find_one({"id": visit_id})["practice_id"]
        mongo.visits.update_one({"id": visit_id}, {"$set": {"practice_id": "other"}})
        try:
            r = requests.patch(f"{API}/internal/visits/{visit_id}/vitals", headers=_h(phys_tok),
                               json={"heart_rate": 70}, timeout=20)
            assert r.status_code == 404, r.text
        finally:
            mongo.visits.update_one({"id": visit_id}, {"$set": {"practice_id": orig}})


class TestVisitsHistory:
    def test_history_contains_sample_and_in_progress(self, phys_tok):
        r = requests.get(f"{API}/internal/patients/directory:{ROMERO_DIR_ID}/visits",
                         headers=_h(phys_tok), timeout=20)
        assert r.status_code == 200
        rows = r.json()["visits"]
        refs = {row["ref_number"]: row for row in rows}
        assert "VIS-000004" in refs
        assert "VIS-SAMPLE-HX" in refs
        assert refs["VIS-000004"]["status"] == "IN_PROGRESS"
        assert refs["VIS-SAMPLE-HX"]["status"] == "COMPLETED"
        # has_vitals flag present
        assert "has_vitals" in refs["VIS-000004"]
        assert "has_vitals" in refs["VIS-SAMPLE-HX"]
        assert refs["VIS-SAMPLE-HX"]["has_vitals"] is True
        # No soap text in rows
        for row in rows:
            assert "soap" not in row
