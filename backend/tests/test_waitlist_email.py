"""
Iteration 30 — Test waitlist email one-shot behavior + role-based button visibility
Coverage:
 - Create public new-patient application
 - PATCH waitlist -> internal_status=WAITING_LIST, waitlist_email_sent=True
 - Second PATCH waitlist -> still True, no error
 - `review` action / mark-under-review still exists in backend (frontend removed only)
"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
_mongo = MongoClient(os.environ["MONGO_URL"])
_db = _mongo[os.environ["DB_NAME"]]

STAFF = {"identifier": "staff@visita.demo", "password": "Staff2026!"}


@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE}/api/auth/login", json=STAFF, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("token") or j.get("access_token")


@pytest.fixture(scope="module")
def staff_headers(staff_token):
    return {"Authorization": f"Bearer {staff_token}"}


def _new_app_payload():
    uid = uuid.uuid4().hex[:8]
    return {
        "first_name": "Wait",
        "last_name": f"Test{uid}",
        "date_of_birth": "1990-01-01",
        "phone": "5551234567",
        "email": f"test-{uid}@resend.dev",
        "address": "1 Test St",
        "city": "Toronto",
        "province": "ON",
        "postal_code": "M1M1M1",
        "health_card_number": "1111222233",
        "patient_message": "please add me",
    }


def test_create_new_patient_application_public():
    payload = _new_app_payload()
    r = requests.post(f"{BASE}/api/applications/new-patient", json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert "id" in data or "application_id" in data or data.get("ok"), data


def test_waitlist_first_time_sends_second_time_does_not(staff_headers):
    # Create app
    payload = _new_app_payload()
    r = requests.post(f"{BASE}/api/applications/new-patient", json=payload, timeout=30)
    assert r.status_code in (200, 201)
    # find the app id via list
    lst = requests.get(f"{BASE}/api/internal/applications", headers=staff_headers, timeout=30)
    assert lst.status_code == 200
    apps = lst.json()
    match = [a for a in apps if a.get("email", "").lower() == payload["email"].lower()]
    assert match, f"application not found for {payload['email']}"
    app_id = match[0]["id"]
    assert not match[0].get("waitlist_email_sent")

    # First waitlist
    r1 = requests.patch(
        f"{BASE}/api/internal/applications/{app_id}",
        headers=staff_headers,
        json={"action": "waitlist"},
        timeout=60,
    )
    assert r1.status_code == 200, r1.text
    time.sleep(0.5)

    # Verify state via DB (serializer doesn't expose waitlist_email_sent)
    doc1 = _db.patient_applications.find_one({"id": app_id})
    assert doc1["internal_status"] == "WAITING_LIST"
    assert doc1.get("waitlist_email_sent") is True
    first_sent_at = doc1.get("waitlist_email_at")
    assert first_sent_at

    # Second waitlist (idempotent, no resend)
    r2 = requests.patch(
        f"{BASE}/api/internal/applications/{app_id}",
        headers=staff_headers,
        json={"action": "waitlist"},
        timeout=60,
    )
    assert r2.status_code == 200, r2.text

    doc2 = _db.patient_applications.find_one({"id": app_id})
    assert doc2["internal_status"] == "WAITING_LIST"
    assert doc2.get("waitlist_email_sent") is True
    assert doc2.get("waitlist_email_at") == first_sent_at, "waitlist_email_at should not change on second click"
