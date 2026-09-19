"""Iteration 13 regression: verify logins for patient, admin, physician
after low-risk security/code-quality cleanup. Also sanity-check /auth/me
and a couple of role-scoped endpoints.
"""
import os
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

CREDS = {
    "patient": ("maria.lopez@demo.com", "Patient2026!", "patient"),
    "admin": ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!", "admin"),
    "physician": ("PAGUAYO", "Newman2013_!", "physician"),
}


@pytest.fixture(scope="module")
def tokens():
    out = {}
    for role, (ident, pw, _) in CREDS.items():
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"identifier": ident, "password": pw}, timeout=20)
        assert r.status_code == 200, f"{role} login failed: {r.status_code} {r.text}"
        data = r.json()
        assert "token" in data and data.get("user")
        out[role] = data
    return out


@pytest.mark.parametrize("role", list(CREDS.keys()))
def test_login_role(tokens, role):
    data = tokens[role]
    assert data["user"]["role"] == CREDS[role][2], data["user"]


@pytest.mark.parametrize("role", list(CREDS.keys()))
def test_me_returns_user(tokens, role):
    tok = tokens[role]["token"]
    r = requests.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    user = body.get("user", body)
    assert user.get("role") == CREDS[role][2]


def test_invalid_login_401():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": "maria.lopez@demo.com", "password": "wrongpw!!"},
                      timeout=15)
    assert r.status_code == 401


def test_patient_cannot_access_internal(tokens):
    tok = tokens["patient"]["token"]
    r = requests.get(f"{BASE_URL}/api/internal/counters",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_admin_internal_counters(tokens):
    tok = tokens["admin"]["token"]
    r = requests.get(f"{BASE_URL}/api/internal/counters",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text


def test_patient_portal_overview(tokens):
    tok = tokens["patient"]["token"]
    r = requests.get(f"{BASE_URL}/api/portal/overview",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text


def test_availability_slots_public(tokens):
    tok = tokens["patient"]["token"]
    r = requests.get(f"{BASE_URL}/api/availability/slots",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    # Response could be a list or dict; just ensure something returned
    assert data is not None


def test_no_bearer_returns_401():
    r = requests.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code in (401, 403)
