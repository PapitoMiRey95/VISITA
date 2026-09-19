"""Tests for VIen native Calendar + appointment reminders + Google-removal (iteration 11)."""
import os
import time
import requests
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
STAFF = ("staff@visita.demo", "Staff2026!")
PHYS = ("PAGUAYO", "Newman2013_!")
PHYS_FALLBACK = ("PAGUAYO", "Aguayo#Perm2026!")
MARIA = ("maria.lopez@demo.com", "Patient2026!")
CRON_SECRET = None  # loaded lazily from backend/.env


def _load_cron_secret():
    global CRON_SECRET
    if CRON_SECRET is None:
        try:
            with open("/app/backend/.env") as f:
                for line in f:
                    if line.startswith("WEBHOOK_CRON_SECRET"):
                        CRON_SECRET = line.split("=", 1)[1].strip().strip('"')
                        break
        except Exception:
            CRON_SECRET = ""
    return CRON_SECRET or ""


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    return r


def staff_h():
    r = _login(*STAFF)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def phys_h():
    r = _login(*PHYS)
    if r.status_code != 200:
        r = _login(*PHYS_FALLBACK)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def maria_h():
    r = _login(*MARIA)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def next_weekday(target_weekdays=(0, 1, 2, 3)):
    """Return an iso date >= 7 days from today whose weekday is Mon-Thu."""
    d = date.today() + timedelta(days=7)
    while d.weekday() not in target_weekdays:
        d += timedelta(days=1)
    return d.isoformat()


# ------------------ availability ------------------

class TestAvailability:
    def test_availability_slots_returned(self):
        h = maria_h()
        r = requests.get(f"{API}/availability/slots?days=28", headers=h, timeout=30)
        assert r.status_code == 200
        js = r.json()
        assert "slots" in js and len(js["slots"]) > 0
        s0 = js["slots"][0]
        for k in ("date", "time", "label", "display"):
            assert k in s0

    def test_slot_subtracted_after_book(self):
        d = next_weekday()
        # get slots from calendar view (staff)
        h = staff_h()
        r = requests.get(f"{API}/internal/calendar", headers=h, params={"start": d, "days": 1}, timeout=30)
        assert r.status_code == 200
        day = r.json()["days"][0]
        assert not day["closed"], f"expected open day, got closed: {day}"
        open_slots = day["open_slots"]
        assert open_slots
        slot = open_slots[0]

        # pick directory patient
        dr = requests.get(f"{API}/internal/directory", headers=h, params={"q": "ROMERO"}, timeout=30)
        assert dr.status_code == 200 and dr.json(), dr.text
        directory_id = dr.json()[0]["id"]

        # book
        body = {"directory_id": directory_id, "date": slot["date"], "time": slot["time"], "label": slot["label"], "reason": "TEST_slot_take"}
        rb = requests.post(f"{API}/internal/calendar/book", headers=h, json=body, timeout=30)
        assert rb.status_code == 200, rb.text
        appt = rb.json()
        assert appt["status"] == "confirmed"
        assert appt["booked_from"]["source_type"] == "calendar"
        appt_id = appt["id"]

        try:
            # slot should not appear anymore
            r2 = requests.get(f"{API}/internal/calendar", headers=h, params={"start": d, "days": 1}, timeout=30)
            times_open = {s["time"] for s in r2.json()["days"][0]["open_slots"]}
            assert slot["time"] not in times_open

            # appt should appear under that day
            appt_times = {a["time"] for a in r2.json()["days"][0]["appointments"]}
            assert slot["time"] in appt_times

            # double-book -> 409
            rd = requests.post(f"{API}/internal/calendar/book", headers=h, json=body, timeout=30)
            assert rd.status_code == 409, rd.text

            # outside hours -> 400 (05:00 outside 11:30-16:30)
            bad = {**body, "time": "05:00", "label": "5:00 AM"}
            r_bad = requests.post(f"{API}/internal/calendar/book", headers=h, json=bad, timeout=30)
            assert r_bad.status_code == 400, r_bad.text

            # reminders scheduled? verify via mongo-free path: call cron with wrong secret should be 401
            r401 = requests.post(f"{API}/cron/appointment-reminders", timeout=30)
            assert r401.status_code == 401
            r401b = requests.post(f"{API}/cron/appointment-reminders", headers={"Authorization": "Bearer wrong"}, timeout=30)
            assert r401b.status_code == 401
            r200 = requests.post(f"{API}/cron/appointment-reminders", headers={"Authorization": f"Bearer {_load_cron_secret()}"}, timeout=30)
            assert r200.status_code == 200, r200.text
        finally:
            # cleanup: cancel and reminder-cancel should occur automatically
            requests.patch(f"{API}/internal/appointments/{appt_id}", headers=h, json={"action": "cancel", "staff_note": "TEST cleanup"}, timeout=30)


class TestBlockTime:
    def test_block_removes_slots(self):
        d = next_weekday()
        h = staff_h()
        r = requests.get(f"{API}/internal/calendar", headers=h, params={"start": d, "days": 1}, timeout=30)
        day = r.json()["days"][0]
        assert day["open_slots"]
        # find contiguous block covering the first open slot
        s = day["open_slots"][0]
        block_start = s["time"]
        # end = time + 30m
        h_i, m_i = map(int, block_start.split(":"))
        end_m = h_i * 60 + m_i + 30
        block_end = f"{end_m // 60:02d}:{end_m % 60:02d}"

        rb = requests.post(f"{API}/internal/calendar/block", headers=h,
                           json={"date": d, "start": block_start, "end": block_end, "reason": "TEST_block"}, timeout=30)
        assert rb.status_code == 200, rb.text
        try:
            r2 = requests.get(f"{API}/internal/calendar", headers=h, params={"start": d, "days": 1}, timeout=30)
            times_open = {s2["time"] for s2 in r2.json()["days"][0]["open_slots"]}
            assert block_start not in times_open
        finally:
            # cleanup: remove that block entry via admin PUT availability
            admin_r = _login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
            ah = {"Authorization": f"Bearer {admin_r.json()['token']}"}
            av = requests.get(f"{API}/admin/availability", headers=ah).json()
            av["blocked_periods"] = [b for b in av.get("blocked_periods", [])
                                     if not (b.get("date") == d and b.get("start") == block_start and (b.get("reason") == "TEST_block"))]
            requests.put(f"{API}/admin/availability", headers=ah, json=av, timeout=30)


# ------------------ Approve/reschedule/complete/no_show flows ------------------

class TestApproveAndLifecycle:
    def _create_patient_request(self, h_patient, d, time24):
        body = {
            "reason": "TEST_approve_flow",
            "options": [{"date": d, "time": time24, "label": time24, "display": f"{d} {time24}"}],
        }
        r = requests.post(f"{API}/portal/appointments", headers=h_patient, json=body, timeout=30)
        assert r.status_code == 200, r.text
        return r.json()

    def test_approve_confirms_and_double_book_409(self):
        h_pat = maria_h()
        h_staff = staff_h()
        d = next_weekday()
        cal = requests.get(f"{API}/internal/calendar", headers=h_staff, params={"start": d, "days": 1}).json()["days"][0]
        s = cal["open_slots"][0]
        req = self._create_patient_request(h_pat, s["date"], s["time"])
        req_id = req["id"]
        appt_id_cal = None
        try:
            # approve
            ap = requests.patch(f"{API}/internal/appointments/{req_id}", headers=h_staff,
                                json={"action": "approve", "confirmed_date": s["date"], "confirmed_time": s["time"]}, timeout=30)
            assert ap.status_code == 200, ap.text
            assert ap.json()["status"] == "confirmed"

            # Slot busy: another calendar booking for same slot must return 409
            dr = requests.get(f"{API}/internal/directory", headers=h_staff, params={"q": "ROMERO"}).json()
            body = {"directory_id": dr[0]["id"], "date": s["date"], "time": s["time"], "label": s["label"], "reason": "TEST_dup"}
            rd = requests.post(f"{API}/internal/calendar/book", headers=h_staff, json=body, timeout=30)
            assert rd.status_code == 409, rd.text

            # Complete
            rc = requests.patch(f"{API}/internal/appointments/{req_id}", headers=h_staff, json={"action": "complete"}, timeout=30)
            assert rc.status_code == 200 and rc.json()["status"] == "completed"

            # Reschedule not-applicable now; test no_show on a fresh confirmed appt (calendar-book)
            d2_iso = (date.fromisoformat(d) + timedelta(days=7)).isoformat()
            cal2 = requests.get(f"{API}/internal/calendar", headers=h_staff, params={"start": d2_iso, "days": 1}).json()["days"][0]
            if not cal2["closed"] and cal2["open_slots"]:
                s2 = cal2["open_slots"][0]
                body2 = {"directory_id": dr[0]["id"], "date": s2["date"], "time": s2["time"], "label": s2["label"], "reason": "TEST_noshow"}
                rb = requests.post(f"{API}/internal/calendar/book", headers=h_staff, json=body2, timeout=30)
                assert rb.status_code == 200, rb.text
                appt_id_cal = rb.json()["id"]
                # reschedule
                s3 = None
                for sc in cal2["open_slots"][1:]:
                    s3 = sc
                    break
                if s3:
                    rr = requests.patch(f"{API}/internal/appointments/{appt_id_cal}", headers=h_staff,
                                        json={"action": "reschedule", "confirmed_date": s3["date"], "confirmed_time": s3["time"]}, timeout=30)
                    assert rr.status_code == 200 and rr.json()["status"] == "confirmed"
                # no_show
                rns = requests.patch(f"{API}/internal/appointments/{appt_id_cal}", headers=h_staff, json={"action": "no_show"}, timeout=30)
                assert rns.status_code == 200 and rns.json()["status"] == "no_show"
        finally:
            requests.patch(f"{API}/internal/appointments/{req_id}", headers=h_staff, json={"action": "cancel", "staff_note": "TEST"}, timeout=30)
            if appt_id_cal:
                # already no_show - fine
                pass


# ------------------ Cron auth ------------------

class TestCronReminders:
    def test_cron_auth_matrix(self):
        r = requests.post(f"{API}/cron/appointment-reminders", timeout=30)
        assert r.status_code == 401
        r = requests.post(f"{API}/cron/appointment-reminders", headers={"Authorization": "Bearer nope"}, timeout=30)
        assert r.status_code == 401
        r = requests.post(f"{API}/cron/appointment-reminders", headers={"Authorization": f"Bearer {_load_cron_secret()}"}, timeout=30)
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ------------------ Google removal sanity ------------------

class TestNoGoogle:
    def test_notifications_py_no_google(self):
        with open("/app/backend/notifications.py") as f:
            txt = f.read().lower()
        # Only allow "google" inside the docstring assertion of "no google dependency".
        # Assert no active integrations remain.
        for term in ("apps script", "sync_calendar", "gscript", "googleapiclient", "oauth2client"):
            assert term not in txt, f"unexpected reference to {term} in notifications.py"
