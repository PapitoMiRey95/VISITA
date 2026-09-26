"""Backend DOB age validation tests for iter44.

Covers 3 endpoints that call validate_dob_age():
- POST /api/auth/register
- POST /api/applications/new-patient
- POST /api/applications/return-request

Edge cases: exactly 17 accepted, one day under 17 rejected 400, exactly 99
accepted, 100+ rejected 400, invalid date (2023-02-29) rejected 400, garbage
rejected 400.
"""
import os
import uuid
from datetime import date, timedelta
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def unique_email(tag=""):
    return f"TEST_agecheck_{tag}_{uuid.uuid4().hex[:10]}@example.com"


def np_payload(dob):
    return {
        "first_name": "TestAge", "last_name": "Check",
        "date_of_birth": dob,
        "phone": "(416) 555-0000",
        "email": unique_email("np"),
        "city": "Toronto", "province": "ON", "country": None,
        "patient_message": "iter44 agecheck",
    }


def rr_payload(dob):
    return {
        "first_name": "TestAge", "last_name": "Check",
        "date_of_birth": dob,
        "health_card_number": None,
        "phone": "(416) 555-0000",
        "email": unique_email("rr"),
        "address": None, "city": None, "province": None, "postal_code": None,
        "patient_message": "iter44 agecheck",
    }


def reg_payload(dob):
    return {
        "patient_type": "none",
        "first_name": "TestAge", "last_name": "Check",
        "date_of_birth": dob,
        "phone": "(416) 555-0000",
        "email": unique_email("reg"),
        "password": "Passw0rd!",
    }


# ---------------- helpers ----------------
def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


TODAY = date.today()


def dob_age_exact(age_years: int, off_days: int = 0) -> str:
    """DOB such that today the age is exactly `age_years` (or off by off_days)."""
    try:
        d = TODAY.replace(year=TODAY.year - age_years)
    except ValueError:
        # today == Feb 29
        d = TODAY.replace(year=TODAY.year - age_years, day=28)
    return iso(d + timedelta(days=off_days))


# ---------------- Tests ----------------
class TestNewPatientAge:
    def test_age_17_exact_accepted(self):
        dob = dob_age_exact(17)  # birthday today, age 17
        r = requests.post(f"{API}/applications/new-patient", json=np_payload(dob), timeout=15)
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"

    def test_age_one_day_under_17_rejected(self):
        # DOB = today - 17y + 1 day => age is 16 (still 16, turns 17 tomorrow)
        dob = dob_age_exact(17, off_days=1)
        r = requests.post(f"{API}/applications/new-patient", json=np_payload(dob), timeout=15)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text}"
        assert "17" in r.text and "99" in r.text

    def test_age_99_exact_accepted(self):
        dob = dob_age_exact(99)
        r = requests.post(f"{API}/applications/new-patient", json=np_payload(dob), timeout=15)
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"

    def test_age_100_rejected(self):
        dob = dob_age_exact(100)
        r = requests.post(f"{API}/applications/new-patient", json=np_payload(dob), timeout=15)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text}"

    def test_invalid_calendar_date_rejected(self):
        r = requests.post(f"{API}/applications/new-patient", json=np_payload("2023-02-29"), timeout=15)
        assert r.status_code == 400

    def test_garbage_dob_rejected(self):
        r = requests.post(f"{API}/applications/new-patient", json=np_payload("not-a-date"), timeout=15)
        assert r.status_code in (400, 422)

    def test_future_dob_rejected(self):
        fut = iso(TODAY + timedelta(days=30))
        r = requests.post(f"{API}/applications/new-patient", json=np_payload(fut), timeout=15)
        assert r.status_code == 400


class TestReturnRequestAge:
    def test_age_17_exact_accepted(self):
        r = requests.post(f"{API}/applications/return-request", json=rr_payload(dob_age_exact(17)), timeout=15)
        assert r.status_code == 200, r.text

    def test_age_one_day_under_17_rejected(self):
        r = requests.post(f"{API}/applications/return-request",
                          json=rr_payload(dob_age_exact(17, off_days=1)), timeout=15)
        assert r.status_code == 400, r.text

    def test_age_99_accepted(self):
        r = requests.post(f"{API}/applications/return-request", json=rr_payload(dob_age_exact(99)), timeout=15)
        assert r.status_code == 200, r.text

    def test_age_100_rejected(self):
        r = requests.post(f"{API}/applications/return-request", json=rr_payload(dob_age_exact(100)), timeout=15)
        assert r.status_code == 400, r.text

    def test_invalid_leap_date_rejected(self):
        r = requests.post(f"{API}/applications/return-request", json=rr_payload("2023-02-29"), timeout=15)
        assert r.status_code == 400, r.text

    def test_garbage_dob_rejected(self):
        r = requests.post(f"{API}/applications/return-request", json=rr_payload("abcxyz"), timeout=15)
        assert r.status_code in (400, 422)


class TestRegisterAge:
    def test_age_17_exact_accepted(self):
        r = requests.post(f"{API}/auth/register", json=reg_payload(dob_age_exact(17)), timeout=15)
        # register may return 200 with token or 400/409 for duplicate; the DOB gate is our target
        assert r.status_code != 400 or "age" not in r.text.lower(), r.text

    def test_age_one_day_under_17_rejected(self):
        r = requests.post(f"{API}/auth/register", json=reg_payload(dob_age_exact(17, off_days=1)), timeout=15)
        assert r.status_code == 400 and "17" in r.text, r.text

    def test_age_99_accepted(self):
        r = requests.post(f"{API}/auth/register", json=reg_payload(dob_age_exact(99)), timeout=15)
        assert r.status_code != 400 or "age" not in r.text.lower(), r.text

    def test_age_100_rejected(self):
        r = requests.post(f"{API}/auth/register", json=reg_payload(dob_age_exact(100)), timeout=15)
        assert r.status_code == 400, r.text

    def test_invalid_leap_date_rejected(self):
        r = requests.post(f"{API}/auth/register", json=reg_payload("2023-02-29"), timeout=15)
        assert r.status_code == 400, r.text

    def test_garbage_dob_rejected(self):
        r = requests.post(f"{API}/auth/register", json=reg_payload("garbage"), timeout=15)
        assert r.status_code in (400, 422)
