"""Backend contract tests for combined-name registration.

The Register.jsx frontend now combines First+Second name -> `first_name` and
First+Second last name -> `last_name` on the client. The backend data model
is unchanged. These tests directly hit the public endpoints with the values
the frontend would produce, then verify persistence via admin-authenticated
internal endpoints.
"""
import os
import time
import uuid
import pytest
import requests

def _load_frontend_url():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


BASE_URL = _load_frontend_url().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing"

ADMIN_EMAIL = "kevinrodriguez9528@gmail.com"
ADMIN_PASSWORD = "VisitaAdmin2026!"


# ------------------------------------------------------------------ helpers
def _uniq(email_prefix: str) -> str:
    return f"TEST_{email_prefix}_{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        # some codebases use "email" key
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _register(payload):
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    return r


def _find_pending_by_email(admin_headers, email):
    r = requests.get(f"{BASE_URL}/api/internal/verifications", headers=admin_headers)
    assert r.status_code == 200, r.text
    for p in r.json():
        if (p.get("email") or "").lower() == email.lower():
            return p
    return None


# ------------------------------------------------------------------ register
class TestRegisterCombinedNames:
    def test_all_four_name_fields_combined(self, admin_headers):
        email = _uniq("juan")
        payload = {
            # Frontend has already combined; backend just receives the combined strings.
            "first_name": "Juan Carlos",
            "last_name": "Pérez López",
            "date_of_birth": "1985-04-12",
            "phone": "(416) 555-0101",
            "email": email,
            "password": "Testpass123!",
            "patient_type": "private",
            "province": "ON",
        }
        r = _register(payload)
        assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
        data = r.json()
        assert "token" in data
        assert data["user"]["email"] == email.lower()

        # Verify persistence via internal verifications queue
        rec = _find_pending_by_email(admin_headers, email)
        assert rec is not None, "created patient not found in verifications queue"
        assert rec["first_name"] == "Juan Carlos", rec
        assert rec["last_name"] == "Pérez López", rec

    def test_blank_optional_fields_no_extra_spaces(self, admin_headers):
        email = _uniq("maria")
        payload = {
            "first_name": "Maria",
            "last_name": "Gomez",
            "date_of_birth": "1990-01-01",
            "phone": "(416) 555-0102",
            "email": email,
            "password": "Testpass123!",
            "patient_type": "private",
            "province": "ON",
        }
        r = _register(payload)
        assert r.status_code == 200, r.text
        rec = _find_pending_by_email(admin_headers, email)
        assert rec is not None
        # No leading/trailing/double spaces:
        assert rec["first_name"] == "Maria"
        assert rec["last_name"] == "Gomez"
        assert "  " not in rec["first_name"]
        assert "  " not in rec["last_name"]

    def test_accents_hyphens_apostrophes_preserved(self, admin_headers):
        email = _uniq("oconnor")
        payload = {
            "first_name": "José María-José",
            "last_name": "O'Connor",
            "date_of_birth": "1988-08-08",
            "phone": "(416) 555-0103",
            "email": email,
            "password": "Testpass123!",
            "patient_type": "private",
            "province": "ON",
        }
        r = _register(payload)
        assert r.status_code == 200, r.text
        rec = _find_pending_by_email(admin_headers, email)
        assert rec is not None
        assert rec["first_name"] == "José María-José"
        assert rec["last_name"] == "O'Connor"


# ------------------------------------------------------------------ return-request
class TestReturnRequestCombinedNames:
    def test_return_request_accepts_combined_names(self):
        # Simulates the Re-establish Care flow. Uses random data so directory
        # match will simply be UNKNOWN, but the endpoint must still accept &
        # persist the combined names in the ref-numbered application.
        email = _uniq("return")
        payload = {
            "first_name": "Ana Sofía",
            "last_name": "García Ruiz",
            "date_of_birth": "1970-06-15",
            "health_card_number": None,
            "phone": "(416) 555-0104",
            "email": email,
            "address": None, "city": None, "province": None,
            "postal_code": None, "patient_message": "please re-establish",
        }
        r = requests.post(f"{BASE_URL}/api/applications/return-request", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("ref_number", "").startswith("APP")


# ------------------------------------------------------------------ new-patient
class TestNewPatientCombinedNames:
    def test_new_patient_request_accepts_combined_names(self):
        email = _uniq("new")
        payload = {
            "first_name": "Peter James",
            "last_name": "Smith Jones",
            "date_of_birth": "1995-11-30",
            "phone": "(416) 555-0105",
            "email": email,
            "city": "Toronto", "province": "ON", "country": "Canada",
            "patient_message": "New patient — please review",
        }
        r = requests.post(f"{BASE_URL}/api/applications/new-patient", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("ref_number", "").startswith("APP")


# ------------------------------------------------------------------ search regression
class TestInternalSearchByPartialCompoundName:
    """Directory search should still find patients by a single part of a
    compound name (e.g. searching 'ROMERO' matches 'ROMERO CUAHUEY')."""

    def test_search_partial_last_name(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/internal/directory",
                         params={"q": "ROMERO"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        docs = r.json()
        assert isinstance(docs, list)
        # At least one directory entry with 'ROMERO' in last_name
        matched = [d for d in docs if "ROMERO" in (d.get("last_name") or "").upper()]
        assert matched, f"expected ROMERO match, got {docs[:3]}"
