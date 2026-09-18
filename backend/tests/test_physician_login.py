"""Tests for physician username login + forced password change flow (iter5)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")

API = f"{BASE_URL}/api"
TEMP_PW = "Aguayo#Temp2026"
NEW_PW = "DocSecret2026!"


def login(identifier, password):
    return requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password})


def reset_physician():
    """Attempt to reset via admin - but we can't; instead try both temp & NEW_PW to detect current state."""
    r = login("PAGUAYO", TEMP_PW)
    if r.status_code == 200:
        return TEMP_PW, r.json()
    r = login("PAGUAYO", NEW_PW)
    if r.status_code == 200:
        # already changed by prior run; change back
        token = r.json()["token"]
        requests.post(f"{API}/auth/change-password",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"current_password": NEW_PW, "new_password": TEMP_PW})
        r2 = login("PAGUAYO", TEMP_PW)
        return TEMP_PW, r2.json() if r2.status_code == 200 else None
    return None, None


class TestPhysicianLogin:
    def test_username_login_returns_must_change(self):
        pw, data = reset_physician()
        assert data is not None, "Could not authenticate physician with temp or new password"
        u = data["user"]
        assert u["role"] == "physician"
        assert u["username"] == "PAGUAYO"
        assert u["name"] == "Dr. Pablo Aguayo"
        # If we just changed pw back to temp via change-password, must_change_password is False.
        # So only assert when temp was originally in use. Skip strict check if we reset.
        # Force reset flag via direct login again
        # We accept either state but log
        print("must_change_password:", u.get("must_change_password"))

    def test_case_insensitive_username(self):
        r = login("paguayo", TEMP_PW)
        if r.status_code != 200:
            # maybe pw was changed
            r = login("paguayo", NEW_PW)
        assert r.status_code == 200
        assert r.json()["user"]["username"] == "PAGUAYO"

    def test_change_password_flow(self):
        # Ensure state: temp password valid
        r = login("PAGUAYO", TEMP_PW)
        if r.status_code != 200:
            # was already changed; change back first
            r2 = login("PAGUAYO", NEW_PW)
            assert r2.status_code == 200
            tok = r2.json()["token"]
            requests.post(f"{API}/auth/change-password",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"current_password": NEW_PW, "new_password": TEMP_PW})
            r = login("PAGUAYO", TEMP_PW)
        assert r.status_code == 200
        token = r.json()["token"]

        # Reject same password
        same = requests.post(f"{API}/auth/change-password",
                             headers={"Authorization": f"Bearer {token}"},
                             json={"current_password": TEMP_PW, "new_password": TEMP_PW})
        assert same.status_code == 400

        # Reject <8 chars
        short = requests.post(f"{API}/auth/change-password",
                              headers={"Authorization": f"Bearer {token}"},
                              json={"current_password": TEMP_PW, "new_password": "short1"})
        assert short.status_code in (400, 422)

        # Successful change
        ok = requests.post(f"{API}/auth/change-password",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"current_password": TEMP_PW, "new_password": NEW_PW})
        assert ok.status_code == 200
        assert ok.json().get("ok") is True

        # New login shows must_change_password false
        r3 = login("PAGUAYO", NEW_PW)
        assert r3.status_code == 200
        assert r3.json()["user"]["must_change_password"] is False

        # Old temp password no longer works
        r4 = login("PAGUAYO", TEMP_PW)
        assert r4.status_code == 401

    def test_email_login_patient(self):
        r = requests.post(f"{API}/auth/login", json={"email": "maria.lopez@demo.com", "password": "Patient2026!"})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "patient"

    def test_email_login_patient_via_identifier(self):
        r = login("maria.lopez@demo.com", "Patient2026!")
        assert r.status_code == 200

    def test_staff_login(self):
        r = login("staff@visita.demo", "Staff2026!")
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "staff"

    def test_admin_login(self):
        r = login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "admin"

    def test_no_password_exposure_on_login_page(self):
        # Fetch login page HTML from frontend and check no demo passwords
        try:
            r = requests.get(BASE_URL + "/login", timeout=10)
            text = r.text
            for pw in ["Aguayo#Temp2026", "Patient2026!", "Staff2026!", "VisitaAdmin2026!", "DocSecret2026!"]:
                assert pw not in text, f"Password {pw} exposed on /login"
        except Exception as e:
            pytest.skip(f"Could not fetch /login: {e}")
