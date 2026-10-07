"""Tests for /api/auth/register field validation (OHIP vs private)."""
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or "https://visita-admin.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _ts():
    return int(time.time() * 1000)


def _cleanup(mongo, email):
    try:
        mongo.users.delete_many({"email": email})
        mongo.patients.delete_many({"email": email})
    except Exception:
        pass


def _base_ohip(email):
    return {
        "patient_type": "ohip",
        "first_name": "QA",
        "last_name": "Register",
        "date_of_birth": "1985-03-10",
        "sex": "Male",
        "phone": "4165551212",
        "email": email,
        "password": "Password1!",
        "health_card_number": "9988776655",
        "health_card_version": "AB",
        "health_card_issue_date": "2024-03-10",
        "health_card_expiry_date": "2029-03-10",
        "province": "ON",
        "address": "1 Main St",
        "city": "Toronto",
        "postal_code": "M1M1M1",
    }


OHIP_REQUIRED_FIELDS = [
    "health_card_version",
    "health_card_expiry_date",
    "health_card_issue_date",
    "date_of_birth",
    "sex",
    "address",
    "city",
    "province",
    "postal_code",
    "phone",
]


@pytest.mark.parametrize("field", OHIP_REQUIRED_FIELDS)
def test_ohip_missing_field_returns_400(field, mongo):
    email = f"qa.reg.{_ts()}.{field}@example.com"
    payload = _base_ohip(email)
    # DOB is required by Pydantic (str) — send empty string instead of None
    payload[field] = ""
    r = requests.post(f"{API}/auth/register", json=payload)
    # Pydantic may reject some fields with 422; our server returns 400 w/ MISSING_FIELDS
    assert r.status_code == 400, f"{field}: expected 400 got {r.status_code} body={r.text}"
    detail = r.json().get("detail", {})
    assert isinstance(detail, dict), f"detail not dict: {detail}"
    assert detail.get("code") == "MISSING_FIELDS", f"{field}: {detail}"
    assert field in detail.get("fields", []), f"{field} not in {detail.get('fields')}"

    # Second attempt with same email → still MISSING_FIELDS (no user was created)
    r2 = requests.post(f"{API}/auth/register", json=payload)
    assert r2.status_code == 400
    d2 = r2.json().get("detail", {})
    assert d2.get("code") == "MISSING_FIELDS"
    _cleanup(mongo, email.lower())


def test_ohip_optional_fields_omitted_succeeds_and_cleanup(mongo):
    email = f"qa.reg.{_ts()}.ok@example.com"
    payload = _base_ohip(email)
    # Omit optional: middle_name, second_last_name, unit (already not present)
    r = requests.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    body = r.json()
    # account should be created OR application_required path — either acceptable
    # as long as no error. We clean up either way.
    _cleanup(mongo, email.lower())
    assert body is not None


def test_private_branch_no_hc_required(mongo):
    email = f"qa.reg.{_ts()}.priv@example.com"
    payload = {
        "patient_type": "private",
        "first_name": "QA",
        "last_name": "Private",
        "date_of_birth": "1985-03-10",
        "sex": "Female",
        "phone": "4165551212",
        "email": email,
        "password": "Password1!",
        "province": "ON",
        "address": "2 Main St",
        "city": "Toronto",
        "postal_code": "M1M1M1",
    }
    r = requests.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    _cleanup(mongo, email.lower())


def test_applications_new_patient_no_hc_required():
    """POST /api/applications/new-patient still works with own schema (no HC)."""
    email = f"qa.reg.{_ts()}.app@example.com"
    payload = {
        "first_name": "QA",
        "last_name": "AppFlow",
        "date_of_birth": "1985-03-10",
        "phone": "4165551212",
        "email": email,
        "address": "3 Main St",
        "city": "Toronto",
        "province": "ON",
        "postal_code": "M1M1M1",
        "country": "Canada",
        "has_ohip": False,
        "had_family_doctor": False,
    }
    r = requests.post(f"{API}/applications/new-patient", json=payload)
    # Accept 200/201; definitely not 400 missing-HC
    assert r.status_code in (200, 201), f"got {r.status_code}: {r.text}"
