"""
Tests for the patient-verification-approved email + in-portal notification flow.

Scope (iteration_19):
- Staff/Admin can approve a PENDING patient via POST /api/internal/verifications/{id}
- Approval creates exactly 1 outbound_notifications row (channel=email,
  subject 'Your VIen EMR account has been verified') for the patient.
- Approval creates exactly 1 in-portal notification (title 'Account verified').
- Re-approving an already-verified patient does NOT create a second email/note (dedup).
- Physician role is rejected (403) and does NOT cause any email/note.
- Email HTML contains no clinical information.

Uses robert.chen@demo.com so that sofia.martinez remains available for the UI test.
Restores robert.chen to PENDING and deletes created email/notification rows at the end.
"""
import os
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

# Load backend env for MongoDB access
load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

ADMIN_EMAIL = "kevinrodriguez9528@gmail.com"
ADMIN_PASSWORD = "VisitaAdmin2026!"
STAFF_EMAIL = "staff@visita.demo"
STAFF_PASSWORD = "Staff2026!"
PHYSICIAN_USER = "PAGUAYO"
PHYSICIAN_PASSWORD = "Newman2013_!"

# The two pending demo patients
ROBERT_ID = "492fde1d-b7ae-4016-bc67-bcb79d69e73c"  # robert.chen@demo.com — used for backend test
SOFIA_ID = "21244c47-d3de-4579-89fe-7a7aaf6fc3c5"   # sofia.martinez@demo.com — reserved for UI test

VERIFY_EMAIL_SUBJECT = "Your VIen EMR account has been verified"
VERIFY_NOTE_TITLE = "Account verified"


def _login(identifier, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"identifier": identifier, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def mongo():
    assert MONGO_URL and DB_NAME, "Missing MONGO_URL / DB_NAME in backend/.env"
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def staff_token():
    return _login(STAFF_EMAIL, STAFF_PASSWORD)


@pytest.fixture(scope="module")
def physician_token():
    return _login(PHYSICIAN_USER, PHYSICIAN_PASSWORD)


@pytest.fixture(scope="module", autouse=True)
def ensure_pending_and_cleanup(mongo):
    """Ensure robert.chen is pending before tests, and restore + clean rows after."""
    # Snapshot original patient doc
    orig = mongo.patients.find_one({"id": ROBERT_ID}, {"_id": 0})
    assert orig is not None, "robert.chen demo patient not found in DB"

    # Reset to pending state before test
    mongo.patients.update_one({"id": ROBERT_ID}, {
        "$set": {"verification_status": "pending", "portal_status": "PENDING_VERIFICATION"},
        "$unset": {"verified_by": "", "verified_at": ""},
    })
    # Clean any pre-existing verification email/note (leftover from failed prior run)
    mongo.outbound_notifications.delete_many({"patient_id": ROBERT_ID, "subject": VERIFY_EMAIL_SUBJECT})
    mongo.notifications.delete_many({"patient_id": ROBERT_ID, "title": VERIFY_NOTE_TITLE})

    yield

    # Post-test cleanup: restore pending + drop the created email + in-portal note
    mongo.patients.update_one({"id": ROBERT_ID}, {
        "$set": {
            "verification_status": orig.get("verification_status", "pending"),
            "portal_status": orig.get("portal_status", "PENDING_VERIFICATION"),
        },
        "$unset": {"verified_by": "", "verified_at": ""},
    })
    mongo.outbound_notifications.delete_many({"patient_id": ROBERT_ID, "subject": VERIFY_EMAIL_SUBJECT})
    mongo.notifications.delete_many({"patient_id": ROBERT_ID, "title": VERIFY_NOTE_TITLE})


# ---------- Role gating: physician cannot verify ----------
def test_physician_cannot_verify(physician_token, mongo):
    r = requests.post(
        f"{BASE_URL}/api/internal/verifications/{ROBERT_ID}",
        headers={"Authorization": f"Bearer {physician_token}"},
        json={"decision": "verified"}, timeout=15,
    )
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
    # No email / no note should have been created
    assert mongo.outbound_notifications.count_documents({"patient_id": ROBERT_ID, "subject": VERIFY_EMAIL_SUBJECT}) == 0
    assert mongo.notifications.count_documents({"patient_id": ROBERT_ID, "title": VERIFY_NOTE_TITLE}) == 0
    # Patient still pending
    p = mongo.patients.find_one({"id": ROBERT_ID}, {"_id": 0})
    assert p.get("verification_status") == "pending"


# ---------- Staff can verify: exactly 1 email + 1 note ----------
def test_staff_approve_creates_one_email_and_one_note(staff_token, mongo):
    r = requests.post(
        f"{BASE_URL}/api/internal/verifications/{ROBERT_ID}",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"decision": "verified"}, timeout=15,
    )
    assert r.status_code == 200, f"approve failed: {r.status_code} {r.text}"
    assert r.json().get("ok") is True

    # Patient state updated
    p = mongo.patients.find_one({"id": ROBERT_ID}, {"_id": 0})
    assert p["verification_status"] == "verified"
    assert p.get("portal_status") == "VERIFIED"
    assert p.get("verified_by")
    assert p.get("verified_at")

    # Exactly ONE verification email row (channel=email)
    emails = list(mongo.outbound_notifications.find(
        {"patient_id": ROBERT_ID, "subject": VERIFY_EMAIL_SUBJECT}, {"_id": 0}
    ))
    assert len(emails) == 1, f"expected 1 verification email row, got {len(emails)}"
    assert emails[0]["channel"] == "email"
    # @demo.com will 'failed' on real send but row must exist
    assert emails[0]["status"] in ("sent", "failed", "prepared")

    # Exactly ONE in-portal note
    notes = list(mongo.notifications.find(
        {"patient_id": ROBERT_ID, "title": VERIFY_NOTE_TITLE}, {"_id": 0}
    ))
    assert len(notes) == 1, f"expected 1 in-portal note, got {len(notes)}"


# ---------- Re-approve is a no-op (dedup on was_verified) ----------
def test_reapprove_does_not_duplicate(staff_token, mongo):
    r = requests.post(
        f"{BASE_URL}/api/internal/verifications/{ROBERT_ID}",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"decision": "verified"}, timeout=15,
    )
    assert r.status_code == 200
    email_count = mongo.outbound_notifications.count_documents(
        {"patient_id": ROBERT_ID, "subject": VERIFY_EMAIL_SUBJECT}
    )
    note_count = mongo.notifications.count_documents(
        {"patient_id": ROBERT_ID, "title": VERIFY_NOTE_TITLE}
    )
    assert email_count == 1, f"dedup broken: {email_count} verification emails after re-approve"
    assert note_count == 1, f"dedup broken: {note_count} verification notes after re-approve"


# ---------- Email template contains no clinical info ----------
def test_email_template_has_no_clinical_info():
    from email_service import account_verified_html  # imported after conftest sys.path

    html = account_verified_html("Robert", "https://example.com").lower()
    forbidden = ["diagnosis", "medication", "prescription", "reason for visit",
                 "clinical", "test result", "lab result", "note:"]
    for term in forbidden:
        assert term not in html, f"clinical term leaked into verification email: {term!r}"
    # Sanity: template mentions patient portal
    assert "patient portal" in html
