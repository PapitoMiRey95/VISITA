"""
Bloodwork + Book-Appointment iteration tests.
Covers:
 - POST /api/portal/bloodwork (Reason required, ref BLD-*, internal_status 'new')
 - GET/PATCH /api/internal/bloodwork (staff + physician list-scope, actions)
 - GET /api/internal/counters (bloodwork for staff & physician)
 - POST /api/internal/book-appointment (source: bloodwork/imaging/prescription/message)
 - Double-book 409, out-of-window 400
 - PATCH /api/internal/appointments/{id}: reschedule + cancel + double-book 409
 - GET /api/portal/overview: bloodwork array + Bloodwork in combined 'requests'
"""
import os
import uuid
import pytest
import requests
from datetime import datetime, timedelta

def _read_frontend_env():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _read_frontend_env()).rstrip("/")
API = f"{BASE_URL}/api"

STAFF = {"login": "staff@visita.demo", "password": "Staff2026!"}
PATIENT = {"login": "maria.lopez@demo.com", "password": "Patient2026!"}
PHYS = {"login": "PAGUAYO", "password": "Aguayo#Temp2026"}
PHYS_NEW = "AguayoTest#2026Blood"


def _login(email_or_user, password):
    r = requests.post(f"{API}/auth/login", json={"email": email_or_user, "password": password}, timeout=15)
    return r


@pytest.fixture(scope="module")
def patient_token():
    r = _login(PATIENT["login"], PATIENT["password"])
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_token():
    r = _login(STAFF["login"], STAFF["password"])
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def physician_token():
    # Handle forced password change
    r = _login(PHYS["login"], PHYS["password"])
    if r.status_code == 200 and r.json().get("must_change_password"):
        tok = r.json()["token"]
        cp = requests.post(
            f"{API}/auth/change-password",
            headers={"Authorization": f"Bearer {tok}"},
            json={"current_password": PHYS["password"], "new_password": PHYS_NEW},
            timeout=15,
        )
        assert cp.status_code == 200, cp.text
        # Login again to be sure
        r2 = _login(PHYS["login"], PHYS_NEW)
        assert r2.status_code == 200, r2.text
        return r2.json()["token"]
    if r.status_code != 200:
        # Try new password (previous test run may have already changed it)
        r2 = _login(PHYS["login"], PHYS_NEW)
        if r2.status_code == 200:
            return r2.json()["token"]
        pytest.skip(f"Physician login failed: {r.text}")
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ------------------------------------------------------------------ Bloodwork
class TestBloodworkCreate:
    def test_reason_required(self, patient_token):
        r = requests.post(f"{API}/portal/bloodwork", headers=_h(patient_token), json={}, timeout=15)
        assert r.status_code == 422, r.text

    def test_create_ok(self, patient_token):
        r = requests.post(f"{API}/portal/bloodwork", headers=_h(patient_token),
                          json={"reason": "TEST Annual checkup CBC", "patient_note": "TEST fasting since morning"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ref_number"].startswith("BLD-")
        assert d["internal_status"] == "new"
        assert d["reason"] == "TEST Annual checkup CBC"
        assert "_id" not in d
        pytest.bld_id = d["id"]
        pytest.bld_ref = d["ref_number"]


# ---------------------------------------------------------- Portal overview
class TestPortalOverviewBloodwork:
    def test_overview_contains_bloodwork(self, patient_token):
        r = requests.get(f"{API}/portal/overview", headers=_h(patient_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "bloodwork" in d and isinstance(d["bloodwork"], list)
        assert any(b["id"] == pytest.bld_id for b in d["bloodwork"])
        # Combined requests
        merged = [x for x in d["requests"] if x["type"] == "Bloodwork"]
        assert any(x["id"] == pytest.bld_id for x in merged)
        # Patient-facing status maps to human string
        our = next(x for x in merged if x["id"] == pytest.bld_id)
        assert our["status"] in ("Received", "Under Review", "Completed", "Appointment Booked",
                                 "Appointment Required", "More Information Requested", "Declined")


# --------------------------------------------------- Internal listing + counters
class TestBloodworkInternal:
    def test_staff_lists(self, staff_token):
        r = requests.get(f"{API}/internal/bloodwork", headers=_h(staff_token), timeout=15)
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()]
        assert pytest.bld_id in ids

    def test_staff_counter_includes_bloodwork(self, staff_token):
        r = requests.get(f"{API}/internal/counters", headers=_h(staff_token), timeout=15)
        assert r.status_code == 200
        c = r.json()["counters"]
        assert "bloodwork" in c
        assert c["bloodwork"] >= 1

    def test_send_to_physician_then_physician_sees_it(self, staff_token, physician_token):
        r = requests.patch(f"{API}/internal/bloodwork/{pytest.bld_id}", headers=_h(staff_token),
                           json={"action": "send_to_physician"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["internal_status"] == "waiting_physician"
        # physician list is scoped
        r2 = requests.get(f"{API}/internal/bloodwork", headers=_h(physician_token), timeout=15)
        assert r2.status_code == 200
        assert all(x["internal_status"] == "waiting_physician" for x in r2.json())
        assert any(x["id"] == pytest.bld_id for x in r2.json())
        # physician counter
        rc = requests.get(f"{API}/internal/counters", headers=_h(physician_token), timeout=15)
        assert rc.status_code == 200
        assert rc.json()["counters"]["bloodwork"] >= 1

    def test_more_info_and_decline_on_second_request(self, patient_token, physician_token):
        # Create two more bloodwork requests to exercise more_info + decline
        for action, expected in (("more_info", "more_info_required"), ("decline", "declined")):
            c = requests.post(f"{API}/portal/bloodwork", headers=_h(patient_token),
                              json={"reason": f"TEST {action}"}, timeout=15)
            assert c.status_code == 200
            bid = c.json()["id"]
            r = requests.patch(f"{API}/internal/bloodwork/{bid}", headers=_h(physician_token),
                               json={"action": action, "staff_note": f"TEST {action}"}, timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["internal_status"] == expected


# ------------------------------------------------------------------- Booking
def _pick_free_slot(staff_token):
    """Fetch slots and find one not already used by any confirmed appointment."""
    # Look 7-21 days ahead
    appts = requests.get(f"{API}/internal/appointments", headers=_h(staff_token), timeout=15).json()
    taken = {(a.get("confirmed_date"), a.get("confirmed_slot_time") or a.get("confirmed_time"))
             for a in appts if a.get("status") == "confirmed"}
    for delta in range(7, 90):
        d = (datetime.utcnow() + timedelta(days=delta)).date()
        if d.weekday() > 3:  # Mon-Thu only
            continue
        date_str = d.isoformat()
        r = requests.get(f"{API}/availability/slots?date={date_str}", headers=_h(staff_token), timeout=15)
        if r.status_code != 200:
            continue
        for s in r.json().get("slots", []):
            key = (date_str, s.get("time"))
            if key in taken:
                continue
            return date_str, s
    pytest.skip("No free slot found")


class TestBooking:
    def test_book_from_bloodwork(self, staff_token):
        date_str, slot = _pick_free_slot(staff_token)
        body = {
            "source_type": "bloodwork", "source_id": pytest.bld_id,
            "date": date_str, "time": slot["time"],
            "label": slot.get("label"), "display": slot.get("display"),
            "reason": "TEST Bloodwork follow-up",
        }
        r = requests.post(f"{API}/internal/book-appointment", headers=_h(staff_token), json=body, timeout=15)
        assert r.status_code == 200, r.text
        appt = r.json()
        assert appt["ref_number"].startswith("APT-")
        assert appt["status"] == "confirmed"
        assert appt["confirmed_date"] == date_str
        assert appt["booked_from"]["source_type"] == "bloodwork"
        assert appt["booked_from"]["source_id"] == pytest.bld_id
        assert appt["approved_by"]
        pytest.appt_id = appt["id"]
        pytest.appt_date = date_str
        pytest.appt_time = slot["time"]
        pytest.appt_label = slot.get("label")
        pytest.appt_display = slot.get("display")

        # Source request updated
        bld = requests.get(f"{API}/internal/bloodwork", headers=_h(staff_token), timeout=15).json()
        src = next(x for x in bld if x["id"] == pytest.bld_id)
        assert src["internal_status"] == "appointment_booked"
        assert src.get("appointment_booked") is True
        assert src.get("linked_appointment_id") == appt["id"]

    def test_double_book_same_slot(self, staff_token, patient_token):
        # Create another bloodwork and try to book the same slot
        c = requests.post(f"{API}/portal/bloodwork", headers=_h(patient_token),
                          json={"reason": "TEST dup"}, timeout=15).json()
        body = {
            "source_type": "bloodwork", "source_id": c["id"],
            "date": pytest.appt_date, "time": pytest.appt_time,
            "label": pytest.appt_label, "display": pytest.appt_display,
        }
        r = requests.post(f"{API}/internal/book-appointment", headers=_h(staff_token), json=body, timeout=15)
        assert r.status_code == 409, r.text
        assert "no longer available" in r.text.lower()

    def test_out_of_window_400(self, staff_token, patient_token):
        c = requests.post(f"{API}/portal/bloodwork", headers=_h(patient_token),
                          json={"reason": "TEST oow"}, timeout=15).json()
        # Saturday 9am -> outside Mon-Thu 11:30-16:30
        for delta in range(1, 30):
            d = (datetime.utcnow() + timedelta(days=delta)).date()
            if d.weekday() == 5:  # Saturday
                break
        body = {
            "source_type": "bloodwork", "source_id": c["id"],
            "date": d.isoformat(), "time": "09:00",
        }
        r = requests.post(f"{API}/internal/book-appointment", headers=_h(staff_token), json=body, timeout=15)
        assert r.status_code == 400, r.text


class TestReschedCancel:
    def test_reschedule(self, staff_token):
        new_date, new_slot = _pick_free_slot(staff_token)
        r = requests.patch(f"{API}/internal/appointments/{pytest.appt_id}", headers=_h(staff_token),
                           json={"action": "reschedule", "confirmed_date": new_date,
                                 "confirmed_time": new_slot.get("label") or new_slot["time"],
                                 "confirmed_display": new_slot.get("display")}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "confirmed"
        assert d["confirmed_date"] == new_date
        pytest.appt_date = new_date
        pytest.appt_time = new_slot["time"]

    def test_reschedule_conflict_409(self, staff_token, patient_token):
        # Create another appointment on a different free slot to reschedule INTO
        c = requests.post(f"{API}/portal/bloodwork", headers=_h(patient_token),
                          json={"reason": "TEST resched conflict"}, timeout=15).json()
        d2, s2 = _pick_free_slot(staff_token)
        # Book a second appointment
        rb = requests.post(f"{API}/internal/book-appointment", headers=_h(staff_token), json={
            "source_type": "bloodwork", "source_id": c["id"],
            "date": d2, "time": s2["time"], "label": s2.get("label"), "display": s2.get("display"),
        }, timeout=15)
        assert rb.status_code == 200, rb.text
        second_id = rb.json()["id"]
        # Try to reschedule the first appointment INTO the second's slot
        r = requests.patch(f"{API}/internal/appointments/{pytest.appt_id}", headers=_h(staff_token),
                           json={"action": "reschedule", "confirmed_date": d2,
                                 "confirmed_time": s2.get("label") or s2["time"]}, timeout=15)
        assert r.status_code == 409, r.text
        pytest.second_appt_id = second_id

    def test_cancel(self, staff_token):
        r = requests.patch(f"{API}/internal/appointments/{pytest.appt_id}", headers=_h(staff_token),
                           json={"action": "cancel", "staff_note": "TEST cancel"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "cancelled"
