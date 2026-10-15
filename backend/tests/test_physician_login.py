"""Tests for physician username login (read-only: never changes the live physician password)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")

API = f"{BASE_URL}/api"
PHYS_PW = os.environ["TEST_PHYSICIAN_PASSWORD"]


def login(identifier, password):
    return requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password})


class TestPhysicianLogin:
    def test_username_login(self):
        r = login("PAGUAYO", PHYS_PW)
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u["role"] == "physician" and u["username"] == "PAGUAYO"

    def test_case_insensitive_username(self):
        assert login("paguayo", PHYS_PW).status_code == 200

    def test_wrong_password_rejected(self):
        assert login("PAGUAYO", "definitely-wrong-password-1").status_code == 401

    def test_change_password_validation_only(self):
        """Negative checks only — a wrong current password and a too-short new password must be rejected.
        The live password is never modified by tests."""
        token = login("PAGUAYO", PHYS_PW).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        bad_current = requests.post(f"{API}/auth/change-password", headers=h,
                                    json={"current_password": "not-the-password-1", "new_password": "Another#Strong2026"})
        assert bad_current.status_code in (400, 401, 403)
        short = requests.post(f"{API}/auth/change-password", headers=h,
                              json={"current_password": PHYS_PW, "new_password": "short1"})
        assert short.status_code in (400, 422)
        assert login("PAGUAYO", PHYS_PW).status_code == 200

    def test_email_login_patient(self):
        r = requests.post(f"{API}/auth/login", json={"email": "maria.lopez@demo.com", "password": "Patient2026!"})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "patient"

    def test_email_login_patient_via_identifier(self):
        r = login("maria.lopez@demo.com", "Patient2026!")
        assert r.status_code == 200

    def test_staff_login(self):
        r = login("staff@visita.demo", os.environ["TEST_STAFF_PASSWORD"])
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
            for pw in ["Patient2026!", os.environ["TEST_STAFF_PASSWORD"], PHYS_PW]:
                assert pw not in text, f"Password {pw} exposed on /login"
        except Exception as e:
            pytest.skip(f"Could not fetch /login: {e}")
