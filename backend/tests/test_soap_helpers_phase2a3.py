"""Phase 2A3 — SOAP helpers backend tests (search, get, helper-used audit, role gating)."""
import os
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://visita-admin.preview.emergentagent.com"
MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

VISIT_ID = "84460a4c-032a-4e71-b9d3-183590d6ae12"
MARIA_PATIENT = "patient:06f6ee08-58f7-4286-82f5-7c845de99ce1"
ROMERO_DIR = "directory:c5c30d56-acdd-416b-b61d-5cf8aab06a74"


def _login(identifier, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"identifier": identifier, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def phys_h():
    return {"Authorization": f"Bearer {_login('PAGUAYO', 'Newman2013_!')}"}


@pytest.fixture(scope="module")
def staff_h():
    return {"Authorization": f"Bearer {_login('staff@visita.demo', 'Staff2026!')}"}


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('kevinrodriguez9528@gmail.com', 'VisitaAdmin2026!')}"}


@pytest.fixture(scope="module")
def helper_ids():
    rows = list(MONGO.soap_helpers.find({"synthetic_sample": True}, {"_id": 0, "key": 1, "id": 1}))
    return {r["key"]: r["id"] for r in rows}


# ---------------- physician search ----------------
class TestPhysicianSearch:
    def test_no_params(self, phys_h):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers", headers=phys_h, timeout=20)
        assert r.status_code == 200
        data = r.json()
        keys = {h["key"] for h in data["helpers"]}
        assert "SYNTH_FOLLOWUP" in keys and "SYNTH_URI" in keys and "SYNTH_REVIEW" in keys
        assert "SYNTH_INACTIVE" not in keys
        assert "SYNTH_OTHER_PRACTICE" not in keys
        assert "SYNTH_FEMALE_ONLY" not in keys  # no patient -> unknown sex -> ANY only
        assert data["patient_sex"] is None

    def test_search_uri(self, phys_h):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers?search=uri", headers=phys_h, timeout=20)
        assert r.status_code == 200
        keys = {h["key"] for h in r.json()["helpers"]}
        assert keys == {"SYNTH_URI"}

    def test_search_by_key_review(self, phys_h):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers?search=SYNTH_REVIEW", headers=phys_h, timeout=20)
        assert r.status_code == 200
        helpers = r.json()["helpers"]
        assert len(helpers) == 1 and helpers[0]["key"] == "SYNTH_REVIEW"
        assert helpers[0]["has_objective"] is False
        assert helpers[0]["has_subjective"] is True
        assert helpers[0]["has_plan"] is True

    def test_patient_ref_romero_unknown_sex(self, phys_h):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers?patient_ref={ROMERO_DIR}", headers=phys_h, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["patient_sex"] is None
        keys = {h["key"] for h in data["helpers"]}
        assert "SYNTH_FEMALE_ONLY" not in keys

    def test_patient_ref_maria_female(self, phys_h):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers?patient_ref={MARIA_PATIENT}", headers=phys_h, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["patient_sex"] == "FEMALE"
        keys = {h["key"] for h in data["helpers"]}
        assert "SYNTH_FEMALE_ONLY" in keys


# ---------------- physician get-by-id ----------------
class TestPhysicianGet:
    def test_get_active_ok(self, phys_h, helper_ids):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers/{helper_ids['SYNTH_URI']}", headers=phys_h, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["key"] == "SYNTH_URI"
        assert d["subjective_text"] and d["objective_text"] and d["plan_text"]

    def test_get_inactive_404(self, phys_h, helper_ids):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers/{helper_ids['SYNTH_INACTIVE']}", headers=phys_h, timeout=20)
        assert r.status_code == 404

    def test_get_other_practice_404(self, phys_h, helper_ids):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers/{helper_ids['SYNTH_OTHER_PRACTICE']}", headers=phys_h, timeout=20)
        assert r.status_code == 404


# ---------------- role gating: staff + admin -> 403 ----------------
class TestRoleGating:
    def test_staff_search_403(self, staff_h):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers", headers=staff_h, timeout=20)
        assert r.status_code == 403

    def test_staff_get_403(self, staff_h, helper_ids):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers/{helper_ids['SYNTH_URI']}", headers=staff_h, timeout=20)
        assert r.status_code == 403

    def test_staff_helper_used_403(self, staff_h, helper_ids):
        r = requests.post(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/helper-used", headers=staff_h,
                          json={"helper_id": helper_ids["SYNTH_URI"], "sections_inserted": ["objective"]}, timeout=20)
        assert r.status_code == 403

    def test_admin_search_403(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers", headers=admin_h, timeout=20)
        assert r.status_code == 403

    def test_admin_get_403(self, admin_h, helper_ids):
        r = requests.get(f"{BASE_URL}/api/internal/soap-helpers/{helper_ids['SYNTH_URI']}", headers=admin_h, timeout=20)
        assert r.status_code == 403

    def test_admin_helper_used_403(self, admin_h, helper_ids):
        r = requests.post(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/helper-used", headers=admin_h,
                          json={"helper_id": helper_ids["SYNTH_URI"], "sections_inserted": ["objective"]}, timeout=20)
        assert r.status_code == 403


# ---------------- helper-used audit ----------------
class TestHelperUsedAudit:
    def test_post_filters_invalid_section_and_audits(self, phys_h, helper_ids):
        before = MONGO.audit_logs.count_documents({"action": "soap_helper_used"})
        r = requests.post(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/helper-used", headers=phys_h,
                          json={"helper_id": helper_ids["SYNTH_URI"], "sections_inserted": ["objective", "bogus"]}, timeout=20)
        assert r.status_code == 200, r.text
        after = MONGO.audit_logs.count_documents({"action": "soap_helper_used"})
        assert after == before + 1
        row = MONGO.audit_logs.find({"action": "soap_helper_used"}).sort("_id", -1).limit(1)[0]
        meta = row.get("meta", {})
        assert meta.get("sections_inserted") == ["objective"]
        # no helper text in meta
        joined = str(meta).lower()
        assert "nasal congestion" not in joined
        assert "throat" not in joined
