"""Quick regression for appointment slot-locking rework (PREVIEW)."""
import os
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
JOHN = ("john.smith@demo.com", "Patient2026!")
MARIA = ("maria.lopez@demo.com", "Patient2026!")

# Clinic Mon-Thu. Use future dates.
TEST_DATE = "2026-10-29"  # Thursday
ALT_DATE = "2026-10-28"   # Wednesday


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _slots_for(tok, date):
    r = requests.get(f"{API}/availability/slots", headers=_h(tok), timeout=30)
    assert r.status_code == 200, r.text
    slots = r.json().get("slots", [])
    return [s for s in slots if s.get("date") == date]


def _cancel_requests(tok):
    r = requests.get(f"{API}/portal/appointments", headers=_h(tok), timeout=30)
    if r.status_code != 200:
        return
    items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    for it in items:
        if it.get("status") == "requested":
            requests.post(f"{API}/portal/appointments/{it['id']}/cancel", headers=_h(tok), timeout=30)


@pytest.fixture(scope="module")
def admin_tok(): return _login(*ADMIN)


@pytest.fixture(scope="module")
def john_tok():
    tok = _login(*JOHN)
    _cancel_requests(tok)
    yield tok
    _cancel_requests(tok)


@pytest.fixture(scope="module")
def maria_tok():
    tok = _login(*MARIA)
    _cancel_requests(tok)
    yield tok
    _cancel_requests(tok)


def test_availability_slots_endpoint(john_tok):
    r = requests.get(f"{API}/availability/slots", headers=_h(john_tok), timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json().get("slots"), list)


def test_patient_create_holds_slot_and_second_gets_409(john_tok, maria_tok):
    john_slots = _slots_for(john_tok, ALT_DATE)
    assert john_slots, f"No slots on {ALT_DATE}"
    chosen = john_slots[-1]  # pick late slot
    hhmm = chosen["time"]

    payload = {
        "options": [{"date": ALT_DATE, "time": hhmm, "label": chosen.get("label"),
                     "display": chosen.get("display")}],
        "appointment_type": "IN_CLINIC",
        "reason": "TEST slot lock",
        "acknowledge_existing": True,
    }
    r1 = requests.post(f"{API}/portal/appointments", json=payload, headers=_h(john_tok), timeout=30)
    assert r1.status_code in (200, 201), f"John create failed: {r1.status_code} {r1.text}"
    appt = r1.json()
    assert appt["status"] == "requested"
    assert appt.get("slot_state") == "HELD"
    appt_id = appt["id"]

    # Verify slot not visible for maria
    maria_slots = _slots_for(maria_tok, ALT_DATE)
    times = [s["time"] for s in maria_slots]
    assert hhmm not in times, f"Slot {hhmm} still visible to maria after john held"

    # Maria tries same slot -> expect 409 "no longer available"
    payload2 = dict(payload, reason="TEST duplicate")
    r3 = requests.post(f"{API}/portal/appointments", json=payload2, headers=_h(maria_tok), timeout=30)
    assert r3.status_code == 409, f"Expected 409, got {r3.status_code} {r3.text}"
    body = r3.json()
    msg = str(body.get("detail") or body)
    assert "no longer available" in msg.lower() or "unavailable" in msg.lower(), msg

    # John cancels
    rc = requests.post(f"{API}/portal/appointments/{appt_id}/cancel", headers=_h(john_tok), timeout=30)
    assert rc.status_code in (200, 204), rc.text

    # Slot returns to availability
    john_slots2 = _slots_for(john_tok, ALT_DATE)
    assert hhmm in [s["time"] for s in john_slots2], "Slot not released after cancel"


def test_existing_upcoming_flag(john_tok):
    _cancel_requests(john_tok)
    slots = _slots_for(john_tok, TEST_DATE)
    assert len(slots) >= 2
    s1, s2 = slots[0], slots[1]

    p1 = {"options": [{"date": TEST_DATE, "time": s1["time"], "label": s1.get("label")}],
          "appointment_type": "IN_CLINIC", "reason": "TEST base", "acknowledge_existing": True}
    r1 = requests.post(f"{API}/portal/appointments", json=p1, headers=_h(john_tok), timeout=30)
    assert r1.status_code in (200, 201), r1.text

    p2 = {"options": [{"date": TEST_DATE, "time": s2["time"], "label": s2.get("label")}],
          "appointment_type": "IN_CLINIC", "reason": "TEST second"}
    r2 = requests.post(f"{API}/portal/appointments", json=p2, headers=_h(john_tok), timeout=30)
    assert r2.status_code == 409, f"Expected 409, got {r2.status_code} {r2.text}"
    body = r2.json()
    detail = body.get("detail") or {}
    code = detail.get("code") if isinstance(detail, dict) else None
    assert code == "EXISTING_UPCOMING", f"Expected code EXISTING_UPCOMING: {body}"


def test_internal_calendar(admin_tok):
    r = requests.get(f"{API}/internal/calendar",
                     params={"start": "2026-10-26", "end": "2026-11-01"},
                     headers=_h(admin_tok), timeout=30)
    assert r.status_code == 200, r.text


def test_legacy_offer_action_rejected(admin_tok, john_tok):
    # Create a request first so we have a real id to target
    _cancel_requests(john_tok)
    slots = _slots_for(john_tok, TEST_DATE)
    assert slots
    s = slots[-1]
    payload = {"options": [{"date": TEST_DATE, "time": s["time"], "label": s.get("label")}],
               "appointment_type": "IN_CLINIC", "reason": "TEST offer legacy",
               "acknowledge_existing": True}
    r1 = requests.post(f"{API}/portal/appointments", json=payload, headers=_h(john_tok), timeout=30)
    assert r1.status_code in (200, 201), r1.text
    appt_id = r1.json()["id"]
    try:
        r = requests.patch(f"{API}/internal/appointments/{appt_id}",
                           json={"action": "offer", "options": []},
                           headers=_h(admin_tok), timeout=30)
        assert r.status_code == 400, f"Expected 400 for legacy offer, got {r.status_code}: {r.text}"
        assert "no longer supported" in r.text.lower() or "change time" in r.text.lower()
    finally:
        requests.post(f"{API}/portal/appointments/{appt_id}/cancel", headers=_h(john_tok), timeout=30)
