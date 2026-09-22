"""
VIen EMR — availability past-slot + status-preserves-occupancy tests.

Root-cause bug fix under test:
  * get_busy_slots() must now include statuses confirmed / rescheduled / completed / no_show.
  * availability._slots_for_day skips past dates and past times on today (America/Toronto).
  * Endpoint guards: create_appointment, select_slot, patient_reschedule, calendar_book,
    internal appt reschedule -- all reject past date/time.
  * The 'approve' internal action deliberately has NO past guard.

We ONLY create appointments with reason prefixed 'TEST_' + a hex suffix, and mandatory
cleanup wipes appointment_requests, appointment_reminders, notifications
(title 'Appointment confirmed'), and outbound_notifications
(subject 'Appointment Confirmed — Dr. Aguayo') for the touched patients.

Env: MONGO_URL, DB_NAME from /app/backend/.env, REACT_APP_BACKEND_URL from /app/frontend/.env.
"""
import os
import re
import uuid
import copy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
STAFF = ("staff@visita.demo", "Staff2026!")
PATIENT = ("maria.lopez@demo.com", "Patient2026!")

TAG = f"TEST_{uuid.uuid4().hex[:8]}"
CREATED_APPT_IDS: set[str] = set()
TOUCHED_PATIENT_IDS: set[str] = set()

TZ = ZoneInfo("America/Toronto")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mdb():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"identifier": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    tok = r.json()["token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def staff_h():
    return _login(*STAFF)


@pytest.fixture(scope="module")
def patient_h():
    return _login(*PATIENT)


@pytest.fixture(scope="module")
def directory_id(staff_h):
    r = requests.get(f"{API}/internal/directory", params={"q": "lopez"}, headers=staff_h, timeout=15)
    assert r.status_code == 200, r.text
    results = r.json().get("results") or r.json() if isinstance(r.json(), dict) else r.json()
    if isinstance(results, dict):
        results = results.get("results") or []
    assert results, "No directory match for 'lopez'"
    return results[0]["id"]


def _today_iso():
    return datetime.now(TZ).date().isoformat()


def _now_hm():
    n = datetime.now(TZ)
    return n.hour * 60 + n.minute


def _find_future_open_slot(staff_h, min_days_ahead=1):
    """Fetch calendar_range and find an open slot >= tomorrow that's not in busy."""
    start = (datetime.now(TZ).date() + timedelta(days=min_days_ahead)).isoformat()
    r = requests.get(f"{API}/internal/calendar", params={"start": start, "days": 14}, headers=staff_h, timeout=15)
    assert r.status_code == 200, r.text
    days = r.json().get("days") or r.json()
    for day in days:
        if day.get("closed"):
            continue
        for s in day.get("open_slots", []):
            return day["date"], s["time"], s.get("label") or s["time"]
    pytest.skip("No future open slot found in next 14 days")


def _get_calendar_day(staff_h, ds):
    r = requests.get(f"{API}/internal/calendar", params={"start": ds, "days": 1}, headers=staff_h, timeout=15)
    assert r.status_code == 200, r.text
    days = r.json().get("days") or r.json()
    return days[0]


# ---------------------------------------------------------------------------
# Cleanup teardown
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _cleanup(mdb):
    yield
    if CREATED_APPT_IDS:
        mdb.appointment_requests.delete_many({"id": {"$in": list(CREATED_APPT_IDS)}})
        mdb.appointment_reminders.delete_many({"appointment_id": {"$in": list(CREATED_APPT_IDS)}})
    if TOUCHED_PATIENT_IDS:
        mdb.notifications.delete_many({
            "user_id": {"$in": list(TOUCHED_PATIENT_IDS)},
            "title": {"$in": ["Appointment confirmed"]},
        })
        mdb.outbound_notifications.delete_many({
            "to_user_id": {"$in": list(TOUCHED_PATIENT_IDS)},
            "subject": {"$in": ["Appointment Confirmed — Dr. Aguayo"]},
        })


# ---------------------------------------------------------------------------
# 1. get_busy_slots correctness — books a future slot, completes, verifies stays occupied
# ---------------------------------------------------------------------------
class TestCompleteKeepsSlotOccupied:

    def test_book_future_slot_then_complete_stays_occupied(self, staff_h, directory_id, mdb):
        ds, time24, label = _find_future_open_slot(staff_h)
        # Pre-check: slot is currently in open_slots
        day = _get_calendar_day(staff_h, ds)
        open_times_before = {s["time"] for s in day["open_slots"]}
        assert time24 in open_times_before, f"Precondition failed: {time24} not initially open on {ds}"

        # Book
        body = {"directory_id": directory_id, "date": ds, "time": time24, "label": label,
                "reason": f"{TAG} complete-keeps-slot"}
        r = requests.post(f"{API}/internal/calendar/book", json=body, headers=staff_h, timeout=15)
        assert r.status_code == 200, r.text
        appt = r.json()
        CREATED_APPT_IDS.add(appt["id"])
        if appt.get("patient_id"):
            TOUCHED_PATIENT_IDS.add(appt["patient_id"])

        # After booking: slot removed from open_slots
        day2 = _get_calendar_day(staff_h, ds)
        open_times_after_book = {s["time"] for s in day2["open_slots"]}
        assert time24 not in open_times_after_book, "Booked slot should be occupied"

        # Complete
        r2 = requests.patch(f"{API}/internal/appointments/{appt['id']}",
                            json={"action": "complete"}, headers=staff_h, timeout=15)
        assert r2.status_code == 200, r2.text

        # After complete: slot MUST still be occupied
        day3 = _get_calendar_day(staff_h, ds)
        open_times_after_complete = {s["time"] for s in day3["open_slots"]}
        assert time24 not in open_times_after_complete, \
            f"REGRESSION: completed appt reopened slot {time24} on {ds}"

        # Appointment itself unchanged (status completed, same confirmed date/time)
        doc = mdb.appointment_requests.find_one({"id": appt["id"]})
        assert doc["status"] == "completed"
        assert doc["confirmed_date"] == ds
        assert doc["confirmed_slot_time"] == time24

    def test_no_show_keeps_slot_occupied(self, staff_h, directory_id, mdb):
        ds, time24, label = _find_future_open_slot(staff_h)
        body = {"directory_id": directory_id, "date": ds, "time": time24, "label": label,
                "reason": f"{TAG} noshow-keeps-slot"}
        r = requests.post(f"{API}/internal/calendar/book", json=body, headers=staff_h, timeout=15)
        assert r.status_code == 200, r.text
        appt = r.json()
        CREATED_APPT_IDS.add(appt["id"])
        if appt.get("patient_id"):
            TOUCHED_PATIENT_IDS.add(appt["patient_id"])

        r2 = requests.patch(f"{API}/internal/appointments/{appt['id']}",
                            json={"action": "no_show"}, headers=staff_h, timeout=15)
        assert r2.status_code == 200, r2.text

        day = _get_calendar_day(staff_h, ds)
        open_times = {s["time"] for s in day["open_slots"]}
        assert time24 not in open_times, "no_show slot must remain occupied"

        doc = mdb.appointment_requests.find_one({"id": appt["id"]})
        assert doc["status"] == "no_show"
        assert doc["confirmed_date"] == ds
        assert doc["confirmed_slot_time"] == time24


# ---------------------------------------------------------------------------
# 2. Past times never available
# ---------------------------------------------------------------------------
class TestPastTimesExcluded:

    def test_today_open_slots_exclude_past_times(self, staff_h):
        today = _today_iso()
        day = _get_calendar_day(staff_h, today)
        now_min = _now_hm()
        for s in day.get("open_slots", []):
            h, m = s["time"].split(":")
            assert int(h) * 60 + int(m) >= now_min, \
                f"Past time {s['time']} appeared in today's open_slots"

    def test_past_date_open_slots_empty(self, staff_h):
        past = (datetime.now(TZ).date() - timedelta(days=2)).isoformat()
        day = _get_calendar_day(staff_h, past)
        assert day["open_slots"] == [], f"Past date {past} should have no open slots"

    def test_patient_availability_excludes_past_and_busy(self, patient_h, mdb):
        r = requests.get(f"{API}/availability/slots", headers=patient_h, timeout=15)
        assert r.status_code == 200, r.text
        slots = r.json().get("slots", [])
        today = _today_iso()
        now_min = _now_hm()
        # None earlier than now
        for s in slots:
            if s["date"] < today:
                pytest.fail(f"Patient availability contains past date {s['date']}")
            if s["date"] == today:
                h, m = s["time"].split(":")
                assert int(h) * 60 + int(m) >= now_min

        # None colliding with confirmed/completed/no_show
        busy = set()
        for a in mdb.appointment_requests.find(
            {"status": {"$in": ["confirmed", "rescheduled", "completed", "no_show"]},
             "confirmed_date": {"$ne": None}}):
            t = a.get("confirmed_slot_time") or ""
            if a.get("confirmed_date") and t:
                busy.add(f"{a['confirmed_date']} {t}")
        for s in slots:
            key = f"{s['date']} {s['time']}"
            assert key not in busy, f"Patient sees busy slot {key}"


# ---------------------------------------------------------------------------
# 3. Endpoint guards reject past slots
# ---------------------------------------------------------------------------
class TestEndpointPastGuards:

    def test_calendar_book_past_date_400(self, staff_h, directory_id):
        past = (datetime.now(TZ).date() - timedelta(days=1)).isoformat()
        body = {"directory_id": directory_id, "date": past, "time": "12:30", "label": "12:30 PM",
                "reason": f"{TAG} past-book"}
        r = requests.post(f"{API}/internal/calendar/book", json=body, headers=staff_h, timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        assert "past" in r.text.lower()

    def test_calendar_book_past_time_today_400(self, staff_h, directory_id):
        # Try 11:30 today (working day starts 11:30). If current Toronto time > 11:30 the slot is past.
        today = _today_iso()
        if _now_hm() < 11 * 60 + 30:
            pytest.skip("Toronto now is before working hours start, cannot test past-time-today")
        body = {"directory_id": directory_id, "date": today, "time": "11:30", "label": "11:30 AM",
                "reason": f"{TAG} past-time-today"}
        r = requests.post(f"{API}/internal/calendar/book", json=body, headers=staff_h, timeout=15)
        assert r.status_code == 400, r.text
        assert "past" in r.text.lower()

    def test_internal_reschedule_into_past_400(self, staff_h, directory_id):
        # Create a future appt first
        ds, time24, label = _find_future_open_slot(staff_h)
        body = {"directory_id": directory_id, "date": ds, "time": time24, "label": label,
                "reason": f"{TAG} reschedule-past-seed"}
        r = requests.post(f"{API}/internal/calendar/book", json=body, headers=staff_h, timeout=15)
        assert r.status_code == 200, r.text
        appt = r.json()
        CREATED_APPT_IDS.add(appt["id"])
        if appt.get("patient_id"):
            TOUCHED_PATIENT_IDS.add(appt["patient_id"])

        # Pick a past date that is a working day (Mon-Thu) so we hit the past guard,
        # not the "outside availability" guard.
        past_d = datetime.now(TZ).date() - timedelta(days=1)
        while past_d.weekday() > 3:  # 0=Mon..3=Thu
            past_d -= timedelta(days=1)
        past = past_d.isoformat()
        rr = requests.patch(f"{API}/internal/appointments/{appt['id']}",
                            json={"action": "reschedule", "confirmed_date": past,
                                  "confirmed_time": "12:30"}, headers=staff_h, timeout=15)
        assert rr.status_code == 400, rr.text
        assert "past" in rr.text.lower(), f"expected past message, got: {rr.text}"

    def test_patient_create_appointment_past_option_400(self, patient_h):
        past = (datetime.now(TZ).date() - timedelta(days=1)).isoformat()
        body = {"reason": f"{TAG} patient-past",
                "options": [{"date": past, "time": "12:30", "label": "12:30 PM"}]}
        r = requests.post(f"{API}/portal/appointments", json=body, headers=patient_h, timeout=15)
        assert r.status_code == 400, r.text
        assert "past" in r.text.lower()

    def test_patient_reschedule_into_past_400(self, patient_h, staff_h, mdb):
        """
        Maria (patient) creates a request via portal → staff approves to a future slot
        > 24h out → patient attempts to reschedule into a past date → must 400.
        """
        # Pick a future slot > 24h out on a working day
        chosen = None
        for delta in range(2, 15):
            ds_try = (datetime.now(TZ).date() + timedelta(days=delta)).isoformat()
            day = _get_calendar_day(staff_h, ds_try)
            if day.get("closed") or not day.get("open_slots"):
                continue
            slot = day["open_slots"][0]
            chosen = (ds_try, slot["time"], slot.get("label") or slot["time"])
            break
        if not chosen:
            pytest.skip("No suitable future slot > 24h out")
        ds, time24, label = chosen

        # Create request as patient
        create_body = {"reason": f"{TAG} patient-portal-req",
                       "options": [{"date": ds, "time": time24, "label": label}]}
        rc = requests.post(f"{API}/portal/appointments", json=create_body, headers=patient_h, timeout=15)
        assert rc.status_code == 200, rc.text
        appt = rc.json()
        CREATED_APPT_IDS.add(appt["id"])
        TOUCHED_PATIENT_IDS.add(appt["patient_id"])

        # Approve as staff to that time
        ra = requests.patch(f"{API}/internal/appointments/{appt['id']}",
                            json={"action": "approve", "confirmed_date": ds,
                                  "confirmed_time": time24}, headers=staff_h, timeout=15)
        assert ra.status_code == 200, ra.text

        # Try to reschedule into past working-day date
        past_d = datetime.now(TZ).date() - timedelta(days=1)
        while past_d.weekday() > 3:
            past_d -= timedelta(days=1)
        past = past_d.isoformat()
        rr = requests.post(f"{API}/portal/appointments/{appt['id']}/reschedule",
                           json={"date": past, "time": "12:30", "label": "12:30 PM"},
                           headers=patient_h, timeout=15)
        assert rr.status_code == 400, rr.text
        assert "past" in rr.text.lower(), f"expected past message, got: {rr.text}"


# ---------------------------------------------------------------------------
# 4. Future open slot bookable + disappears
# ---------------------------------------------------------------------------
class TestFutureBookingHappyPath:
    def test_future_slot_books_and_disappears(self, staff_h, directory_id):
        ds, time24, label = _find_future_open_slot(staff_h)
        body = {"directory_id": directory_id, "date": ds, "time": time24, "label": label,
                "reason": f"{TAG} happy-book"}
        r = requests.post(f"{API}/internal/calendar/book", json=body, headers=staff_h, timeout=15)
        assert r.status_code == 200, r.text
        appt = r.json()
        CREATED_APPT_IDS.add(appt["id"])
        if appt.get("patient_id"):
            TOUCHED_PATIENT_IDS.add(appt["patient_id"])

        day = _get_calendar_day(staff_h, ds)
        assert time24 not in {s["time"] for s in day["open_slots"]}


# ---------------------------------------------------------------------------
# 5. Availability document unchanged (snapshot)
# ---------------------------------------------------------------------------
class TestAvailabilitySnapshot:
    _snapshot: dict = {}

    def test_snapshot_before(self, admin_h):
        r = requests.get(f"{API}/admin/availability", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        TestAvailabilitySnapshot._snapshot = r.json()

    def test_snapshot_after(self, admin_h):
        r = requests.get(f"{API}/admin/availability", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json() == TestAvailabilitySnapshot._snapshot, "Availability doc changed during run"

    def test_break_still_excluded(self, staff_h):
        """Recurring break 15:00-15:30 must NEVER appear in open_slots for any working day."""
        start = (datetime.now(TZ).date() + timedelta(days=1)).isoformat()
        r = requests.get(f"{API}/internal/calendar", params={"start": start, "days": 14},
                         headers=staff_h, timeout=15)
        days = r.json().get("days") or r.json()
        for d in days:
            times = {s["time"] for s in d.get("open_slots", [])}
            assert "15:00" not in times, f"Break 15:00 leaked on {d['date']}"
