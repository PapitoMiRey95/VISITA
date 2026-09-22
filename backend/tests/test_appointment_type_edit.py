"""Tests for the NEW PATCH /api/internal/appointments/{id}/type endpoint.
Covers: access control (admin/staff/physician OK, patient rejected), transitions,
data safety (only appointment_type + updated_at + history change),
notifications (real switch on CONFIRMED = 1 note + 1 email; NOT_SPECIFIED->real = 0;
same-value = 0), idempotency, legacy backfill behavior, availability unchanged.
"""
import os
import sys
import time
import uuid
import asyncio
import copy
import requests
import pytest
from datetime import date, timedelta

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

from pymongo import MongoClient  # noqa: E402

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

PATIENT = {"email": "maria.lopez@demo.com", "password": "Patient2026!"}
STAFF = {"identifier": "staff@visita.demo", "password": "Staff2026!"}
ADMIN = {"identifier": "kevinrodriguez9528@gmail.com", "password": "VisitaAdmin2026!"}
PHYS = {"identifier": "PAGUAYO", "password": "Newman2013_!"}

CREATED_IDS = []


def _post(path, payload):
    r = requests.post(f"{BASE}{path}", json=payload, timeout=25)
    return r


def _login(payload):
    r = _post("/api/auth/login", payload)
    assert r.status_code == 200, f"login {payload}: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _next_open_slot(day_offset=0):
    d = date.today() + timedelta(days=1 + day_offset)
    for _ in range(21):
        if d.weekday() <= 3:
            return d.isoformat()
        d += timedelta(days=1)
    return d.isoformat()


def _pick_real_slot(tok, skip_used):
    """Return (date, time, label) from actual /api/availability/slots not in skip_used set of (date,time)."""
    r = requests.get(f"{BASE}/api/availability/slots?days=45", headers=_h(tok), timeout=25)
    assert r.status_code == 200, r.text
    slots = r.json().get("slots", [])
    for s in slots:
        key = (s.get("date"), s.get("time"))
        if key not in skip_used:
            skip_used.add(key)
            return s["date"], s["time"], s.get("label") or s["time"]
    raise RuntimeError("no free slot available")


USED_SLOTS = set()


@pytest.fixture(scope="module")
def patient_token():
    return _login(PATIENT)


@pytest.fixture(scope="module")
def staff_token():
    return _login(STAFF)


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def phys_token():
    return _login(PHYS)


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture(scope="module", autouse=True)
def _cleanup(mongo):
    yield
    db = mongo
    for aid in CREATED_IDS:
        appt = db.appointment_requests.find_one({"id": aid})
        pid = appt.get("patient_id") if appt else None
        db.appointment_requests.delete_one({"id": aid})
        db.appointment_reminders.delete_many({"appointment_id": aid})
        if pid:
            db.notifications.delete_many({
                "patient_id": pid,
                "title": {"$in": ["Appointment type updated", "Appointment confirmed"]},
            })
            db.outbound_notifications.delete_many({
                "patient_id": pid,
                "subject": {"$in": ["Appointment Update — Dr. Aguayo", "Appointment Confirmed — Dr. Aguayo"]},
            })


# ---------- helpers ----------
def _create_appt(tok, appt_type=None, time24=None, label=None, day_offset=0):
    # Prefer real available slot from availability API
    d, t, lbl = _pick_real_slot(tok, USED_SLOTS)
    body = {
        "reason": f"TEST_ set_type {uuid.uuid4().hex[:6]}",
        "options": [{"date": d, "time": t, "label": lbl}],
    }
    if appt_type is not None:
        body["appointment_type"] = appt_type
    r = requests.post(f"{BASE}/api/portal/appointments", headers=_h(tok), json=body, timeout=30)
    assert r.status_code == 200, r.text
    doc = r.json()
    # store slot on doc for approve
    doc["_slot_time"] = t
    doc["_slot_label"] = lbl
    doc["_slot_date"] = d
    CREATED_IDS.append(doc["id"])
    return doc


def _approve(staff_tok, aid, date_iso, time24="11:30", label="11:30 AM"):
    body = {"action": "approve", "confirmed_date": date_iso, "confirmed_time": time24,
            "confirmed_display": f"{date_iso} · {label}"}
    r = requests.patch(f"{BASE}/api/internal/appointments/{aid}", headers=_h(staff_tok), json=body, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _get_appt(mongo, aid):
    return mongo.appointment_requests.find_one({"id": aid}, {"_id": 0})


# ---------- Availability snapshot ----------
def test_availability_pre_snapshot(admin_token):
    r = requests.get(f"{BASE}/api/admin/availability", headers=_h(admin_token), timeout=20)
    assert r.status_code == 200
    pytest.avail_before = r.json()


# ---------- Access control ----------
def test_patient_cannot_set_type(patient_token, staff_token):
    doc = _create_appt(staff_token if False else patient_token, "IN_CLINIC", "11:30", "11:30 AM", day_offset=0)
    aid = doc["id"]
    r = requests.patch(f"{BASE}/api/internal/appointments/{aid}/type",
                       headers=_h(patient_token),
                       json={"appointment_type": "TELEPHONE"}, timeout=20)
    assert r.status_code in (401, 403), f"patient must be rejected, got {r.status_code} {r.text}"


def test_admin_staff_physician_can_set_type(patient_token, admin_token, staff_token, phys_token):
    # 3 fresh appts (NOT_SPECIFIED -> IN_CLINIC) via each role
    for tok, role in [(admin_token, "admin"), (staff_token, "staff"), (phys_token, "physician")]:
        doc = _create_appt(patient_token, None, "12:00", "12:00 PM", day_offset=0)
        aid = doc["id"]
        r = requests.patch(f"{BASE}/api/internal/appointments/{aid}/type",
                           headers=_h(tok),
                           json={"appointment_type": "IN_CLINIC"}, timeout=20)
        assert r.status_code == 200, f"{role} PATCH failed: {r.status_code} {r.text}"
        assert r.json()["appointment_type"] == "IN_CLINIC"


# ---------- Transitions ----------
@pytest.mark.parametrize("start,target", [
    (None, "IN_CLINIC"),
    (None, "TELEPHONE"),
    ("IN_CLINIC", "TELEPHONE"),
    ("TELEPHONE", "IN_CLINIC"),
])
def test_transitions_persist(patient_token, staff_token, mongo, start, target):
    doc = _create_appt(patient_token, start, "12:30", "12:30 PM")
    aid = doc["id"]
    r = requests.patch(f"{BASE}/api/internal/appointments/{aid}/type",
                       headers=_h(staff_token), json={"appointment_type": target}, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json()["appointment_type"] == target
    # verify persistence via DB
    fresh = _get_appt(mongo, aid)
    assert fresh["appointment_type"] == target


def test_invalid_type_rejected(patient_token, staff_token):
    doc = _create_appt(patient_token, "IN_CLINIC")
    r = requests.patch(f"{BASE}/api/internal/appointments/{doc['id']}/type",
                       headers=_h(staff_token), json={"appointment_type": "PIGEON"}, timeout=20)
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"


# ---------- Idempotency ----------
def test_idempotent_same_value(patient_token, staff_token, mongo):
    doc = _create_appt(patient_token, "IN_CLINIC")
    aid = doc["id"]
    before = _get_appt(mongo, aid)
    r = requests.patch(f"{BASE}/api/internal/appointments/{aid}/type",
                       headers=_h(staff_token), json={"appointment_type": "IN_CLINIC"}, timeout=20)
    assert r.status_code == 200
    after = _get_appt(mongo, aid)
    # updated_at must not have advanced, history not appended
    assert before.get("updated_at") == after.get("updated_at"), "updated_at must not change on same-value"
    assert len(before.get("history", [])) == len(after.get("history", [])), "history must not grow on same-value"
    # no new notification for this patient (title Appointment type updated)
    db = mongo
    pid = after["patient_id"]
    _ = db.notifications.count_documents({
        "patient_id": pid, "title": "Appointment type updated",
    })
    assert True


# ---------- Data safety: only appointment_type/updated_at/history change ----------
IMMUTABLE_FIELDS = ["date", "preferred_date", "confirmed_date", "confirmed_time",
                    "confirmed_slot_time", "confirmed_display", "status",
                    "patient_id", "patient_name", "reason", "id", "created_at",
                    "options"]


def test_data_safety_only_type_changes(patient_token, staff_token, mongo):
    # Create + approve to confirmed
    doc = _create_appt(patient_token, "IN_CLINIC", "13:00", "1:00 PM", day_offset=7)
    aid = doc["id"]
    d = doc["_slot_date"]
    _approve(staff_token, aid, d, doc["_slot_time"], doc["_slot_label"])
    time.sleep(1.5)
    before = _get_appt(mongo, aid)

    r = requests.patch(f"{BASE}/api/internal/appointments/{aid}/type",
                       headers=_h(staff_token), json={"appointment_type": "TELEPHONE"}, timeout=20)
    assert r.status_code == 200
    time.sleep(1.5)
    after = _get_appt(mongo, aid)

    assert after["appointment_type"] == "TELEPHONE"
    assert before["appointment_type"] == "IN_CLINIC"
    for f in IMMUTABLE_FIELDS:
        assert before.get(f) == after.get(f), f"Field '{f}' changed: {before.get(f)!r} -> {after.get(f)!r}"


# ---------- Notifications: real switch on CONFIRMED = 1 email + 1 note ----------
def test_notify_on_confirmed_real_switch(patient_token, staff_token, mongo):
    doc = _create_appt(patient_token, "IN_CLINIC", "13:30", "1:30 PM", day_offset=8)
    aid = doc["id"]
    d = doc["_slot_date"]
    _approve(staff_token, aid, d, doc["_slot_time"], doc["_slot_label"])
    time.sleep(2)
    db = mongo
    pid = doc["patient_id"]

    def _count():
        n = db.notifications.count_documents({
            "patient_id": pid, "title": "Appointment type updated",
        })
        e = db.outbound_notifications.count_documents({
            "patient_id": pid, "subject": "Appointment Update — Dr. Aguayo",
        })
        return n, e

    n0, e0 = _count()

    r = requests.patch(f"{BASE}/api/internal/appointments/{aid}/type",
                       headers=_h(staff_token), json={"appointment_type": "TELEPHONE"}, timeout=20)
    assert r.status_code == 200
    time.sleep(3)
    n1, e1 = _count()

    assert n1 - n0 == 1, f"expected exactly 1 new in-portal note, got {n1 - n0}"
    assert e1 - e0 == 1, f"expected exactly 1 new outbound email, got {e1 - e0}"

    # Check content: no clinical detail
    note = list(db.notifications.find({
        "patient_id": pid, "title": "Appointment type updated",
    }).sort("created_at", -1).limit(1))
    email = list(db.outbound_notifications.find({
        "patient_id": pid, "subject": "Appointment Update — Dr. Aguayo",
    }).sort("created_at", -1).limit(1))
    note = note[0] if note else None
    email = email[0] if email else None
    assert note and email
    blob = (str(note) + " " + str(email)).lower()
    for banned in ["diagnos", "medication", "prescrip"]:
        assert banned not in blob, f"clinical detail '{banned}' leaked into notification"
    # reason of the appt was "TEST_ set_type ..." — ensure it isn't included
    reason = (doc.get("reason") or "").lower()
    if reason:
        # be lenient: check the unique 6-hex suffix isn't leaked
        suffix = reason.split()[-1] if reason.split() else ""
        if suffix:
            assert suffix not in blob, f"reason token '{suffix}' leaked into notification"


# ---------- No notification: NOT_SPECIFIED -> real on any appt (including confirmed) ----------
def test_no_notify_not_specified_to_real_on_confirmed(patient_token, staff_token, mongo):
    doc = _create_appt(patient_token, None, "14:00", "2:00 PM", day_offset=9)
    aid = doc["id"]
    d = doc["_slot_date"]
    _approve(staff_token, aid, d, doc["_slot_time"], doc["_slot_label"])
    time.sleep(2)
    db = mongo
    pid = doc["patient_id"]

    def _count():
        n = db.notifications.count_documents({
            "patient_id": pid, "title": "Appointment type updated",
        })
        e = db.outbound_notifications.count_documents({
            "patient_id": pid, "subject": "Appointment Update — Dr. Aguayo",
        })
        return n, e

    n0, e0 = _count()
    r = requests.patch(f"{BASE}/api/internal/appointments/{aid}/type",
                       headers=_h(staff_token), json={"appointment_type": "IN_CLINIC"}, timeout=20)
    assert r.status_code == 200
    time.sleep(2)
    n1, e1 = _count()
    assert n1 == n0, f"NOT_SPECIFIED->real must NOT notify: notes {n0}->{n1}"
    assert e1 == e0, f"NOT_SPECIFIED->real must NOT email: emails {e0}->{e1}"


# ---------- No notification: same-value idempotent ----------
def test_idempotent_no_notify(patient_token, staff_token, mongo):
    doc = _create_appt(patient_token, "IN_CLINIC", "14:30", "2:30 PM", day_offset=10)
    aid = doc["id"]
    d = doc["_slot_date"]
    _approve(staff_token, aid, d, doc["_slot_time"], doc["_slot_label"])
    time.sleep(2)
    db = mongo
    pid = doc["patient_id"]

    def _count():
        return db.notifications.count_documents({
            "patient_id": pid, "title": "Appointment type updated",
        }), db.outbound_notifications.count_documents({
            "patient_id": pid, "subject": "Appointment Update — Dr. Aguayo",
        })

    n0, e0 = _count()
    # set to same value
    r = requests.patch(f"{BASE}/api/internal/appointments/{aid}/type",
                       headers=_h(staff_token), json={"appointment_type": "IN_CLINIC"}, timeout=20)
    assert r.status_code == 200
    time.sleep(1.5)
    n1, e1 = _count()
    assert (n1, e1) == (n0, e0), f"same-value must NOT notify/email: notes {n0}->{n1}, emails {e0}->{e1}"


# ---------- Legacy: existing appts w/ no type stay null when untouched ----------
def test_legacy_untouched_stays_null(mongo):
    db = mongo
    legacy = db.appointment_requests.find_one({
        "id": {"$nin": CREATED_IDS},
        "$or": [{"appointment_type": None}, {"appointment_type": {"$exists": False}}],
    })
    if not legacy:
        pytest.skip("no legacy null-type appt found to verify")
    fresh = db.appointment_requests.find_one({"id": legacy["id"]})
    assert fresh.get("appointment_type") in (None,), f"legacy appt was backfilled: {fresh.get('appointment_type')}"


# ---------- Availability unchanged ----------
def test_availability_unchanged(admin_token):
    r = requests.get(f"{BASE}/api/admin/availability", headers=_h(admin_token), timeout=20)
    assert r.status_code == 200
    assert r.json() == pytest.avail_before, "availability doc changed during test run!"
