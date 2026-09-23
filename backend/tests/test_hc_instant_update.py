"""Instant Health Card update flow tests (iteration_27)."""
import os
import datetime as dt
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback: read frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

EMAIL = "maria.lopez@demo.com"
PASSWORD = "Patient2026!"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def original_hc(h):
    """Snapshot current HC to restore later."""
    r = requests.get(f"{BASE_URL}/api/portal/overview", headers=h, timeout=15)
    assert r.status_code == 200
    ov = r.json().get("patient", {})
    return {
        "expiry": ov.get("health_card_expiry_date"),
        "issue": ov.get("health_card_issue_date"),
        "display": ov.get("health_card_display"),
    }


def _future(days=365):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def _past(days=30):
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def test_instant_update_valid(h):
    exp = _future(400)
    r = requests.post(f"{BASE_URL}/api/portal/profile/health-card", headers=h, json={
        "health_card_number": "1234567890",
        "health_card_version": "XD",
        "health_card_issue_date": "2022-01-01",
        "health_card_expiry_date": exp,
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("health_card_display") == "1234 567 890 XD"

    # GET overview -> reflects immediately, no pending
    r2 = requests.get(f"{BASE_URL}/api/portal/overview", headers=h, timeout=15)
    ov = r2.json()["patient"]
    assert ov["health_card_display"] == "1234 567 890 XD"
    assert ov["health_card_expiry_date"] == exp
    assert ov["health_card_update_pending"] is False
    assert not ov.get("pending_health_card")
    assert ov["health_card_status"] == "VALID"


def test_validation_bad_number(h):
    r = requests.post(f"{BASE_URL}/api/portal/profile/health-card", headers=h, json={
        "health_card_number": "12345",  # too short
        "health_card_version": "XD",
        "health_card_issue_date": "2022-01-01",
        "health_card_expiry_date": _future(200),
    }, timeout=15)
    assert r.status_code in (400, 422), r.text


def test_validation_bad_version(h):
    r = requests.post(f"{BASE_URL}/api/portal/profile/health-card", headers=h, json={
        "health_card_number": "1234567890",
        "health_card_version": "X1",  # not 2 letters
        "health_card_issue_date": "2022-01-01",
        "health_card_expiry_date": _future(200),
    }, timeout=15)
    assert r.status_code in (400, 422), r.text


def test_status_expiring_soon(h):
    exp = _future(30)
    r = requests.post(f"{BASE_URL}/api/portal/profile/health-card", headers=h, json={
        "health_card_number": "1234567890", "health_card_version": "XD",
        "health_card_issue_date": "2022-01-01", "health_card_expiry_date": exp,
    }, timeout=15)
    assert r.status_code == 200
    ov = requests.get(f"{BASE_URL}/api/portal/overview", headers=h, timeout=15).json()["patient"]
    assert ov["health_card_status"] == "EXPIRING_SOON"


def test_status_expired(h):
    exp = _past(10)
    r = requests.post(f"{BASE_URL}/api/portal/profile/health-card", headers=h, json={
        "health_card_number": "1234567890", "health_card_version": "XD",
        "health_card_issue_date": "2022-01-01", "health_card_expiry_date": exp,
    }, timeout=15)
    assert r.status_code == 200
    ov = requests.get(f"{BASE_URL}/api/portal/overview", headers=h, timeout=15).json()["patient"]
    assert ov["health_card_status"] == "EXPIRED"


def test_zzz_restore_original(h, original_hc):
    """Restore a valid future expiry so preview data stays clean."""
    # Use a safely future expiry; if original was future, keep it; else set +2y
    exp = original_hc["expiry"]
    try:
        d = dt.date.fromisoformat(exp)
        if d < dt.date.today() + dt.timedelta(days=90):
            exp = _future(730)
    except Exception:
        exp = _future(730)
    issue = original_hc["issue"] or "2022-01-01"
    r = requests.post(f"{BASE_URL}/api/portal/profile/health-card", headers=h, json={
        "health_card_number": "1234567890", "health_card_version": "XD",
        "health_card_issue_date": issue, "health_card_expiry_date": exp,
    }, timeout=15)
    assert r.status_code == 200
