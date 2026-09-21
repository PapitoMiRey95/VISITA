"""Iteration 15 — verify Twilio/SMS removal from VIen EMR notifications.

Covers appointment lifecycle: confirm / reschedule / cancel via admin PATCH
and the cron reminders endpoint. Asserts:
  * in-portal notifications inserted with correct titles
  * outbound_notifications rows created ONLY with channel="email"
  * appointment_reminders scheduled ONLY with reminder_type="email"
  * legacy reminder_type="sms" rows are marked "cancelled" and never "sent"
  * cron endpoint responds 200 with valid Bearer secret, 401 without
  * no bulk appointment mutation (only the test appointment_request is touched)
"""
import os
import re
import time
import uuid
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

def _load_env(path):
    try:
        with open(path) as f:
            return dict(re.findall(r'^([A-Z_]+)\s*=\s*"?([^"\n]+)"?', f.read(), re.M))
    except FileNotFoundError:
        return {}


_fe = _load_env("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not found"
API = f"{BASE_URL}/api"

# Read cron secret + Mongo config from backend/.env
_env = _load_env("/app/backend/.env")
CRON_SECRET = _env.get("WEBHOOK_CRON_SECRET")
MONGO_URL = _env.get("MONGO_URL", "mongodb://localhost:27017").strip('"')
DB_NAME = _env.get("DB_NAME", "test_database").strip('"')

ADMIN_EMAIL = "kevinrodriguez9528@gmail.com"
ADMIN_PW = "VisitaAdmin2026!"
PATIENT_ID = "maria.lopez@demo.com"
PATIENT_PW = "Patient2026!"


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _login(identifier, password):
    r = requests.post(f"{API}/auth/login",
                      json={"identifier": identifier, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {identifier} -> {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def patient_token():
    return _login(PATIENT_ID, PATIENT_PW)


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PW)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def free_slots(patient_token):
    """Fetch the availability slots visible to the patient (60d window)."""
    r = requests.get(f"{API}/availability/slots?days=60", headers=_hdr(patient_token), timeout=20)
    assert r.status_code == 200, r.text
    slots = r.json().get("slots", [])
    # API returns only available slots (busy ones are filtered server-side)
    return slots


@pytest.fixture(scope="module")
def baseline(db):
    """Capture counts before test to prove no bulk change happens."""
    return {
        "outbound_total": db.outbound_notifications.count_documents({}),
        "outbound_sms": db.outbound_notifications.count_documents({"channel": "sms"}),
        "reminders_total": db.appointment_reminders.count_documents({}),
        "reminders_sms": db.appointment_reminders.count_documents({"reminder_type": "sms"}),
        "appts_total": db.appointment_requests.count_documents({}),
        "appts_confirmed": db.appointment_requests.count_documents({"status": "confirmed"}),
        "notifications_total": db.notifications.count_documents({}),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture(scope="module")
def appt(patient_token, admin_token, free_slots, baseline):
    """Create a fresh appointment request as patient, confirm as admin.
    Returns dict with initial_slot, second_slot, appt_id, patient_id."""
    assert len(free_slots) >= 2, "Not enough free slots available for reschedule test"
    s1, s2 = free_slots[0], free_slots[1]

    payload = {
        "reason": "Follow-Up",
        "patient_note": "TEST_iter15 automated notification test",
        "options": [{"date": s1["date"], "time": s1["time"], "label": s1.get("label")}],
    }
    r = requests.post(f"{API}/portal/appointments", headers=_hdr(patient_token),
                      json=payload, timeout=15)
    assert r.status_code == 200, r.text
    created = r.json()
    appt_id = created["id"]

    # Admin approves at slot s1
    r = requests.patch(f"{API}/internal/appointments/{appt_id}",
                       headers=_hdr(admin_token),
                       json={"action": "approve",
                             "confirmed_date": s1["date"], "confirmed_time": s1["time"],
                             "confirmed_display": s1.get("display")}, timeout=15)
    assert r.status_code == 200, f"approve failed: {r.status_code} {r.text}"
    yield {"id": appt_id, "patient_id": created["patient_id"], "s1": s1, "s2": s2}

    # Teardown: leave data as-is but mark cancelled to free slot
    requests.patch(f"{API}/internal/appointments/{appt_id}",
                   headers=_hdr(admin_token),
                   json={"action": "cancel", "staff_note": "TEST_iter15 cleanup"}, timeout=15)


# ---------------- Tests ----------------

class TestConfirm:
    def test_in_portal_notification_confirmed(self, db, appt):
        n = db.notifications.find_one({"patient_id": appt["patient_id"],
                                       "title": "Appointment confirmed"},
                                      sort=[("created_at", -1)])
        assert n is not None, "Missing 'Appointment confirmed' in-portal notification"
        assert n.get("read") is False

    def test_outbound_email_record_confirmed(self, db, appt, baseline):
        latest = list(db.outbound_notifications.find(
            {"patient_id": appt["patient_id"],
             "created_at": {"$gt": baseline["started_at"]}}).sort("created_at", -1))
        assert len(latest) >= 1, "No outbound_notifications created for patient"
        # All new outbounds for this patient MUST be email
        channels = {d.get("channel") for d in latest}
        assert channels == {"email"}, f"Non-email channel present: {channels}"
        assert "Appointment Confirmed" in latest[0].get("subject", "")

    def test_reminder_scheduled_email_only(self, db, appt):
        reminders = list(db.appointment_reminders.find({"appointment_id": appt["id"]}))
        assert len(reminders) >= 1, "No reminder scheduled after confirmation"
        types = {r.get("reminder_type") for r in reminders}
        assert types == {"email"}, f"Unexpected reminder types: {types}"


class TestReschedule:
    def test_reschedule_creates_email_and_in_portal(self, db, admin_token, appt, baseline):
        s2 = appt["s2"]
        r = requests.patch(f"{API}/internal/appointments/{appt['id']}",
                           headers=_hdr(admin_token),
                           json={"action": "reschedule",
                                 "confirmed_date": s2["date"], "confirmed_time": s2["time"],
                                 "confirmed_display": s2.get("display")}, timeout=15)
        assert r.status_code == 200, r.text
        time.sleep(0.5)
        n = db.notifications.find_one({"patient_id": appt["patient_id"],
                                       "title": "Appointment rescheduled"},
                                      sort=[("created_at", -1)])
        assert n is not None, "Missing 'Appointment rescheduled' in-portal notification"
        # Outbound email record present, no sms since baseline
        new_sms = db.outbound_notifications.count_documents(
            {"channel": "sms", "created_at": {"$gt": baseline["started_at"]}})
        assert new_sms == 0, f"SMS outbound record created after reschedule: {new_sms}"
        email_after = db.outbound_notifications.count_documents(
            {"channel": "email", "patient_id": appt["patient_id"],
             "subject": {"$regex": "Rescheduled"},
             "created_at": {"$gt": baseline["started_at"]}})
        assert email_after >= 1, "No 'Rescheduled' email outbound record"

    def test_reschedule_no_sms_reminder(self, db, appt):
        sms = db.appointment_reminders.count_documents(
            {"appointment_id": appt["id"], "reminder_type": "sms"})
        assert sms == 0, "SMS reminder row exists for test appointment"


class TestCancel:
    def test_cancel_creates_email_and_in_portal(self, db, admin_token, appt, baseline):
        r = requests.patch(f"{API}/internal/appointments/{appt['id']}",
                           headers=_hdr(admin_token),
                           json={"action": "cancel", "staff_note": "TEST_iter15 cancel"},
                           timeout=15)
        assert r.status_code == 200, r.text
        time.sleep(0.5)
        n = db.notifications.find_one({"patient_id": appt["patient_id"],
                                       "title": "Appointment cancelled"},
                                      sort=[("created_at", -1)])
        assert n is not None, "Missing 'Appointment cancelled' in-portal notification"

        new_sms = db.outbound_notifications.count_documents(
            {"channel": "sms", "created_at": {"$gt": baseline["started_at"]}})
        assert new_sms == 0, f"SMS outbound created after cancel: {new_sms}"

        cancel_email = db.outbound_notifications.count_documents(
            {"channel": "email", "patient_id": appt["patient_id"],
             "subject": {"$regex": "Cancelled"},
             "created_at": {"$gt": baseline["started_at"]}})
        assert cancel_email >= 1, "No 'Cancelled' email outbound record"

    def test_cancel_marks_reminders_cancelled(self, db, appt):
        pending = db.appointment_reminders.count_documents(
            {"appointment_id": appt["id"], "delivery_status": "pending"})
        assert pending == 0, "Reminders still pending after cancel"


class TestCronEndpoint:
    def test_cron_unauthorized(self):
        r = requests.post(f"{API}/cron/appointment-reminders", timeout=10)
        assert r.status_code == 401

    def test_cron_wrong_secret(self):
        r = requests.post(f"{API}/cron/appointment-reminders",
                          headers={"Authorization": "Bearer wrongsecret"}, timeout=10)
        assert r.status_code == 401

    def test_cron_ok(self, db, appt, baseline):
        # Insert a legacy sms reminder row that is due now — must be cancelled, not sent
        legacy_id = str(uuid.uuid4())
        db.appointment_reminders.insert_one({
            "id": legacy_id, "appointment_id": appt["id"], "patient_id": appt["patient_id"],
            "reminder_type": "sms",
            "scheduled_time": "2020-01-01T00:00:00+00:00",
            "sent_time": None, "delivery_status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Reopen appointment temporarily so send_due_reminders processes it
        db.appointment_requests.update_one({"id": appt["id"]},
                                           {"$set": {"status": "confirmed"}})

        r = requests.post(f"{API}/cron/appointment-reminders",
                          headers={"Authorization": f"Bearer {CRON_SECRET}"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # Give background task time
        time.sleep(2.5)

        legacy = db.appointment_reminders.find_one({"id": legacy_id})
        assert legacy["delivery_status"] == "cancelled", \
            f"Legacy SMS reminder was not cancelled: {legacy}"
        assert legacy.get("sent_time") is None, "Legacy SMS reminder was 'sent'"

        # No new outbound SMS ever
        new_sms = db.outbound_notifications.count_documents(
            {"channel": "sms", "created_at": {"$gt": baseline["started_at"]}})
        assert new_sms == 0, f"Cron created SMS outbound rows: {new_sms}"

        # Cleanup: restore cancel
        db.appointment_requests.update_one({"id": appt["id"]},
                                           {"$set": {"status": "cancelled"}})


class TestNoBulkChange:
    def test_only_test_appointment_added(self, db, baseline, appt):
        after = db.appointment_requests.count_documents({})
        # Should differ by exactly 1 (the new test request)
        assert after == baseline["appts_total"] + 1, (
            f"Bulk change detected: appts_total {baseline['appts_total']} -> {after}")

    def test_zero_sms_outbound_since_start(self, db, baseline):
        after_sms = db.outbound_notifications.count_documents({"channel": "sms"})
        assert after_sms == baseline["outbound_sms"], (
            "New SMS outbound records were created during test: "
            f"{baseline['outbound_sms']} -> {after_sms}")

    def test_zero_new_sms_reminders(self, db, baseline):
        after = db.appointment_reminders.count_documents({"reminder_type": "sms"})
        # We inserted 1 legacy SMS row ourselves in TestCronEndpoint.test_cron_ok
        assert after - baseline["reminders_sms"] <= 1, (
            f"Unexpected SMS reminders: {baseline['reminders_sms']} -> {after}")
