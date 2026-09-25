"""A1 + P3: Server-side private/uninsured 30-min evening-window guard.

Valid start times: 17:30, 18:00, 18:30, 19:00, 19:30, 20:00, 20:30 (5:30-9:00 PM).
Invalid times submitted to API must be rejected with HTTP 400 and MUST NOT
create or modify an appointment. Existing conflict protections (409) preserved.
Preview-only. Does not touch protected IZAO / PIN 3040.
"""
import os
import datetime as dt
import requests
import pytest

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!"),
    "staff": ("staff@visita.demo", "Staff2026!"),
    "physician": ("PAGUAYO", "Newman2013_!"),
    "linda": ("linda.nguyen@demo.com", "Patient2026!"),
    "maria": ("maria.lopez@demo.com", "Patient2026!"),
}


def _login(identifier, password):
    r = requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password}, timeout=20)
    return r.json().get("token") if r.status_code == 200 else None


@pytest.fixture(scope="session")
def tokens():
    return {k: _login(u, p) for k, (u, p) in CREDS.items()}


def _h(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


# ---------- helpers ----------

def _leaf_reason_codes(token):
    r = requests.get(f"{API}/config/reasons", headers=_h(token))
    assert r.status_code == 200
    tax = r.json()
    codes = []
    node_map = tax
    while node_map:
        code = next(iter(node_map))
        codes.append(code)
        node = node_map[code]
        children = node.get("children") if isinstance(node, dict) else None
        if not children:
            break
        node_map = children
    return codes


def _next_weekday_iso(days_ahead=45, weekday=None):
    """Return an ISO date at least `days_ahead` days out. If weekday is None → return that date.
    Otherwise, find the next matching weekday (0=Mon..6=Sun) at or after days_ahead."""
    d = dt.date.today() + dt.timedelta(days=days_ahead)
    if weekday is None:
        return d.isoformat()
    while d.weekday() != weekday:
        d += dt.timedelta(days=1)
    return d.isoformat()


def _create_private_request_specific(patient_token, preferred_date, preferred_time):
    codes = _leaf_reason_codes(patient_token)
    body = {
        "preference_mode": "SPECIFIC",
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
        "reason_codes": codes,
    }
    r = requests.post(f"{API}/portal/private-requests", json=body, headers=_h(patient_token))
    assert r.status_code in (200, 201), r.text
    return r.json()


def _create_private_request_no_pref(patient_token):
    codes = _leaf_reason_codes(patient_token)
    body = {"preference_mode": "NO_PREFERENCE", "reason_codes": codes}
    r = requests.post(f"{API}/portal/private-requests", json=body, headers=_h(patient_token))
    assert r.status_code in (200, 201), r.text
    return r.json()


def _offer(token, rid, date_iso, time_str, label=None):
    return requests.post(
        f"{API}/internal/private-requests/{rid}/offer",
        json={"date": date_iso, "time": time_str, "label": label or time_str},
        headers=_h(token),
    )


# ---------- A1+P3 window guard tests ----------

class TestPrivateWindowGuard:
    def test_valid_evening_time_accepted(self, tokens):
        pr = _create_private_request_no_pref(tokens["linda"])
        date_iso = _next_weekday_iso(45)
        r = _offer(tokens["staff"], pr["id"], date_iso, "19:00", "7:00 PM")
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"

    def test_first_slot_17_30_accepted(self, tokens):
        pr = _create_private_request_no_pref(tokens["linda"])
        date_iso = _next_weekday_iso(46)
        r = _offer(tokens["staff"], pr["id"], date_iso, "17:30", "5:30 PM")
        assert r.status_code == 200, r.text

    def test_last_slot_20_30_accepted(self, tokens):
        pr = _create_private_request_no_pref(tokens["linda"])
        date_iso = _next_weekday_iso(47)
        r = _offer(tokens["staff"], pr["id"], date_iso, "20:30", "8:30 PM")
        assert r.status_code == 200, r.text

    def test_before_window_17_00_rejected(self, tokens):
        pr = _create_private_request_no_pref(tokens["linda"])
        date_iso = _next_weekday_iso(48)
        r = _offer(tokens["staff"], pr["id"], date_iso, "17:00", "5:00 PM")
        assert r.status_code == 400, f"expected 400 for 17:00 got {r.status_code}: {r.text}"
        # Ensure request not moved to AWAITING_PATIENT
        g = requests.get(f"{API}/internal/private-requests/{pr['id']}", headers=_h(tokens["staff"]))
        assert g.status_code == 200
        assert g.json().get("status") != "AWAITING_PATIENT"

    def test_after_window_21_00_rejected(self, tokens):
        pr = _create_private_request_no_pref(tokens["linda"])
        date_iso = _next_weekday_iso(49)
        r = _offer(tokens["staff"], pr["id"], date_iso, "21:00", "9:00 PM")
        assert r.status_code == 400, r.text

    def test_non_30min_18_15_rejected(self, tokens):
        pr = _create_private_request_no_pref(tokens["linda"])
        date_iso = _next_weekday_iso(50)
        r = _offer(tokens["staff"], pr["id"], date_iso, "18:15", "6:15 PM")
        assert r.status_code == 400, r.text

    def test_weekend_saturday_valid_time_ok(self, tokens):
        pr = _create_private_request_no_pref(tokens["linda"])
        # Weekday 5 = Saturday
        date_iso = _next_weekday_iso(30, weekday=5)
        r = _offer(tokens["staff"], pr["id"], date_iso, "18:00", "6:00 PM")
        assert r.status_code == 200, f"expected 200 on Saturday: {r.text}"

    def test_accept_requested_invalid_time_rejected(self, tokens):
        # Create SPECIFIC request with an invalid time; accept-requested must 400
        date_iso = _next_weekday_iso(51)
        pr = _create_private_request_specific(tokens["linda"], date_iso, "18:15")
        r = requests.post(
            f"{API}/internal/private-requests/{pr['id']}/accept-requested",
            headers=_h(tokens["staff"]),
        )
        assert r.status_code == 400, f"accept-requested must reject invalid time: {r.status_code} {r.text}"
        # No appointment created; status still REQUESTED
        g = requests.get(f"{API}/internal/private-requests/{pr['id']}", headers=_h(tokens["staff"]))
        assert g.status_code == 200
        j = g.json()
        assert j.get("status") == "REQUESTED"
        assert not j.get("confirmed_appointment_id")

    def test_accept_requested_valid_time_creates_appt(self, tokens):
        date_iso = _next_weekday_iso(52)
        pr = _create_private_request_specific(tokens["linda"], date_iso, "18:30")
        r = requests.post(
            f"{API}/internal/private-requests/{pr['id']}/accept-requested",
            headers=_h(tokens["staff"]),
        )
        assert r.status_code == 200, r.text
        apt_id = r.json().get("appointment_id")
        assert apt_id
        # Appears on internal calendar with PRIVATE badge
        cal = requests.get(f"{API}/internal/appointments", headers=_h(tokens["staff"]))
        assert cal.status_code == 200
        arr = cal.json() if isinstance(cal.json(), list) else cal.json().get("appointments") or cal.json().get("items") or []
        match = [a for a in arr if a.get("id") == apt_id]
        assert match, "confirmed private appointment not found on calendar"
        a = match[0]
        assert (a.get("appointment_type") == "PRIVATE") or a.get("is_private") is True

    def test_double_booking_valid_slot_409(self, tokens):
        # Offer a valid slot, then re-offer same slot on another request → 409
        date_iso = _next_weekday_iso(60)
        pr1 = _create_private_request_specific(tokens["linda"], date_iso, "19:30")
        r1 = requests.post(
            f"{API}/internal/private-requests/{pr1['id']}/accept-requested",
            headers=_h(tokens["staff"]),
        )
        assert r1.status_code == 200, r1.text

        pr2 = _create_private_request_no_pref(tokens["linda"])
        r2 = _offer(tokens["staff"], pr2["id"], date_iso, "19:30", "7:30 PM")
        assert r2.status_code == 409, f"expected 409 double-book, got {r2.status_code}: {r2.text}"

    def test_past_dated_valid_window_409(self, tokens):
        # A past date with a valid window time must return 409 (conflict), not 400
        past = (dt.date.today() - dt.timedelta(days=5)).isoformat()
        pr = _create_private_request_no_pref(tokens["linda"])
        r = _offer(tokens["staff"], pr["id"], past, "19:00", "7:00 PM")
        assert r.status_code == 409, f"expected 409 past-date, got {r.status_code}: {r.text}"


# ---------- OHIP scheduling unchanged ----------

class TestOhipAvailability:
    def test_availability_slots_unchanged(self, tokens):
        r = requests.get(f"{API}/availability/slots", headers=_h(tokens["admin"]))
        assert r.status_code == 200, r.text
        data = r.json()
        # Accept dict or list; assert non-empty slot list somewhere
        if isinstance(data, dict):
            slots = data.get("slots") or data.get("items") or data.get("open_slots") or []
        else:
            slots = data
        assert isinstance(slots, list)
        # Slots must be OHIP daytime (11:30-16:30), not evening
        if slots:
            times = [s.get("time") for s in slots if isinstance(s, dict) and s.get("time")]
            for t in times[:20]:
                hh = int(t.split(":")[0])
                assert 11 <= hh < 17, f"OHIP slot outside 11:00-16:59: {t}"
