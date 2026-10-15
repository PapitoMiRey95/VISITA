"""Phase 2A3.2 — GET /api/internal/patients/{patient_ref}/recent-vitals tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

PATIENT_REF = "directory:c5c30d56-acdd-416b-b61d-5cf8aab06a74"
EXCLUDE_VISIT = "84460a4c-032a-4e71-b9d3-183590d6ae12"


def _login(identifier, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": identifier, "password": password})
    assert r.status_code == 200, f"login failed {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def phys_token():
    return _login("PAGUAYO", os.environ["TEST_PHYSICIAN_PASSWORD"])


@pytest.fixture(scope="module")
def staff_token():
    return _login("staff@visita.demo", os.environ["TEST_STAFF_PASSWORD"])


@pytest.fixture(scope="module")
def admin_token():
    return _login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


def test_physician_default_limit3_with_exclude(phys_token):
    r = requests.get(
        f"{BASE_URL}/api/internal/patients/{PATIENT_REF}/recent-vitals",
        params={"limit": 3, "exclude": EXCLUDE_VISIT}, headers=_hdr(phys_token))
    assert r.status_code == 200, r.text
    data = r.json()
    refs = [v["ref_number"] for v in data["visits"]]
    assert refs == ["VIS-SAMPLE-HX", "VIS-SAMPLE-HX2", "VIS-SAMPLE-HX3"], refs
    for v in data["visits"]:
        assert "soap" not in v
        assert "_id" not in v
    # row 1 BMI 25.8
    assert data["visits"][0]["bmi"] == 25.8
    assert data["visits"][0]["systolic_bp"] == 121
    assert data["visits"][0]["diastolic_bp"] == 78
    # row 3 (HX3) temp null per spec ("—")
    assert data["visits"][2]["ref_number"] == "VIS-SAMPLE-HX3"


def test_physician_limit10_includes_hx4_but_not_novit(phys_token):
    r = requests.get(
        f"{BASE_URL}/api/internal/patients/{PATIENT_REF}/recent-vitals",
        params={"limit": 10, "exclude": EXCLUDE_VISIT}, headers=_hdr(phys_token))
    assert r.status_code == 200
    refs = [v["ref_number"] for v in r.json()["visits"]]
    assert "VIS-SAMPLE-NOVIT" not in refs
    assert "VIS-SAMPLE-HX4" in refs
    assert len(refs) == 4


def test_physician_limit0_treated_as_1(phys_token):
    r = requests.get(
        f"{BASE_URL}/api/internal/patients/{PATIENT_REF}/recent-vitals",
        params={"limit": 0, "exclude": EXCLUDE_VISIT}, headers=_hdr(phys_token))
    assert r.status_code == 200
    assert len(r.json()["visits"]) == 1


def test_staff_forbidden(staff_token):
    r = requests.get(
        f"{BASE_URL}/api/internal/patients/{PATIENT_REF}/recent-vitals",
        headers=_hdr(staff_token))
    assert r.status_code == 403, r.status_code


def test_admin_ok(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/internal/patients/{PATIENT_REF}/recent-vitals",
        headers=_hdr(admin_token))
    assert r.status_code == 200


def test_bogus_patient_ref_400(phys_token):
    r = requests.get(
        f"{BASE_URL}/api/internal/patients/bogus/recent-vitals",
        headers=_hdr(phys_token))
    assert r.status_code == 400, r.status_code


def test_vitals_patch_hr_999_rejected(phys_token):
    r = requests.patch(
        f"{BASE_URL}/api/internal/visits/{EXCLUDE_VISIT}/vitals",
        json={"heart_rate": 999}, headers=_hdr(phys_token))
    assert r.status_code == 400, r.status_code
