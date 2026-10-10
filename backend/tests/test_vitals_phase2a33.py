"""Phase 2A3.3 Smart Vitals: head_circumference_cm field + bmi/weight_lb in response."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
VISIT_ID = "6db10ab1-7fb0-467c-8b66-3b149c8082cc"


@pytest.fixture(scope="module")
def phys_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": "PAGUAYO", "password": "Newman2013_!"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def h(phys_token):
    return {"Authorization": f"Bearer {phys_token}"}


def test_get_visit_vitals_shape(h):
    r = requests.get(f"{BASE_URL}/api/internal/visits/{VISIT_ID}", headers=h)
    assert r.status_code == 200, r.text
    v = r.json().get("vitals", {})
    for k in ("systolic_bp", "diastolic_bp", "heart_rate", "temperature_c", "weight_kg",
              "height_cm", "head_circumference_cm", "bmi", "weight_lb"):
        assert k in v, f"missing {k}"


def test_head_circ_out_of_range(h):
    r = requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                       headers=h, json={"head_circumference_cm": 100})
    assert r.status_code == 400
    assert "head_circumference_cm" in r.text or "range" in r.text.lower()


def test_head_circ_in_range_and_persistence(h):
    r = requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                       headers=h, json={"head_circumference_cm": 46})
    assert r.status_code == 200, r.text
    assert r.json()["vitals"]["head_circumference_cm"] == 46
    g = requests.get(f"{BASE_URL}/api/internal/visits/{VISIT_ID}", headers=h).json()
    assert g["vitals"]["head_circumference_cm"] == 46
    # cleanup
    requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                   headers=h, json={"head_circumference_cm": None})


def test_bmi_and_weight_lb_computed(h):
    # Set height 170, weight 90
    r = requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                       headers=h, json={"height_cm": 170, "weight_kg": 90, "systolic_bp": 128,
                                        "diastolic_bp": 82, "heart_rate": 72})
    assert r.status_code == 200, r.text
    v = r.json()["vitals"]
    assert v["bmi"] == 31.1
    assert v["weight_lb"] == 198.4
    assert v["height_cm"] == 170


def test_clear_height_bmi_null_weight_lb_preserved(h):
    r = requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                       headers=h, json={"height_cm": None})
    assert r.status_code == 200
    v = r.json()["vitals"]
    assert v["bmi"] is None
    assert v["weight_lb"] == 198.4
    # restore
    requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                   headers=h, json={"height_cm": 170})


def test_head_circ_lower_boundary(h):
    # 20 is lower bound (inclusive)
    r = requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                       headers=h, json={"head_circumference_cm": 20})
    assert r.status_code == 200
    r = requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                       headers=h, json={"head_circumference_cm": 70})
    assert r.status_code == 200
    r = requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                       headers=h, json={"head_circumference_cm": 19.9})
    assert r.status_code == 400
    r = requests.patch(f"{BASE_URL}/api/internal/visits/{VISIT_ID}/vitals",
                       headers=h, json={"head_circumference_cm": None})
    assert r.status_code == 200
