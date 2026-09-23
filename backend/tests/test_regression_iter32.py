"""Regression tests for iter 32 changes:
- appt undo_status action (revert no_show/completed -> confirmed, 400 guard)
- physician allowed on PATCH /internal/patients/{id}
- appointment_type endpoint (IN_CLINIC/TELEPHONE) + list serialize includes appointment_type
- physician login (PAGUAYO / Newman2013_!)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")

STAFF = {"identifier": "staff@visita.demo", "password": "Staff2026!"}
PHYSICIAN = {"identifier": "PAGUAYO", "password": "Newman2013_!"}
PATIENT = {"identifier": "maria.lopez@demo.com", "password": "Patient2026!"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed for {creds['identifier']}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_token():
    return _login(STAFF)


@pytest.fixture(scope="module")
def physician_token():
    return _login(PHYSICIAN)


@pytest.fixture(scope="module")
def staff_h(staff_token):
    return {"Authorization": f"Bearer {staff_token}"}


@pytest.fixture(scope="module")
def phys_h(physician_token):
    return {"Authorization": f"Bearer {physician_token}"}


# ---------- Physician login ----------
def test_physician_login_ok():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=PHYSICIAN, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["role"] == "physician"


# ---------- Calendar serializer includes appointment_type ----------
def test_calendar_appointments_include_appointment_type(staff_h):
    from datetime import date, timedelta
    start = date.today().isoformat()
    r = requests.get(f"{BASE_URL}/api/internal/calendar?start={start}&days=30", headers=staff_h, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    days = data.get("days", [])
    any_appt = None
    for d in days:
        if d.get("appointments"):
            any_appt = d["appointments"][0]
            break
    if not any_appt:
        pytest.skip("No appointments in calendar range to verify shape")
    assert "appointment_type" in any_appt, f"missing appointment_type key: {any_appt}"


# ---------- Undo status flow: no_show -> undo -> confirmed ----------
def _get_or_create_confirmed_appt(staff_h):
    """Find a confirmed appointment or create one via portal/staff. We just look."""
    r = requests.get(f"{BASE_URL}/api/internal/appointments?status=confirmed", headers=staff_h, timeout=20)
    assert r.status_code == 200, r.text
    items = r.json()
    if items:
        return items[0]
    # Fallback: no confirmed appt available for testing
    return None


def test_undo_status_full_cycle(staff_h):
    appt = _get_or_create_confirmed_appt(staff_h)
    if not appt:
        pytest.skip("No confirmed appointment available to test undo cycle")
    aid = appt["id"]
    original_type = appt.get("appointment_type")

    # Force appointment_type to TELEPHONE first so no_show is legal (per business rule for IN_CLINIC hide, backend still allows)
    # Backend allows no_show regardless of type; UI hides for IN_CLINIC only. So we don't need to change here.

    # Mark no_show
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}",
                       headers=staff_h, json={"action": "no_show"}, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "no_show"

    # Undo status -> confirmed
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}",
                       headers=staff_h, json={"action": "undo_status"}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body.get("reverted_from") == "no_show"

    # Undo when already confirmed -> 400
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}",
                       headers=staff_h, json={"action": "undo_status"}, timeout=20)
    assert r.status_code == 400, r.text

    # Now test completed -> undo -> confirmed
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}",
                       headers=staff_h, json={"action": "complete"}, timeout=20)
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}",
                       headers=staff_h, json={"action": "undo_status"}, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "confirmed"
    assert body.get("reverted_from") == "completed"

    # Restore appointment_type if we changed it
    if original_type in ("IN_CLINIC", "TELEPHONE"):
        requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}/type",
                       headers=staff_h, json={"appointment_type": original_type}, timeout=20)


# ---------- Appointment type PATCH ----------
def test_appointment_type_toggle(staff_h):
    appt = _get_or_create_confirmed_appt(staff_h)
    if not appt:
        pytest.skip("No confirmed appointment")
    aid = appt["id"]
    original = appt.get("appointment_type")

    # Set to IN_CLINIC
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}/type",
                       headers=staff_h, json={"appointment_type": "IN_CLINIC"}, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json().get("appointment_type") == "IN_CLINIC"

    # Set back to TELEPHONE
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}/type",
                       headers=staff_h, json={"appointment_type": "TELEPHONE"}, timeout=20)
    assert r.status_code == 200
    assert r.json().get("appointment_type") == "TELEPHONE"

    # Invalid value
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}/type",
                       headers=staff_h, json={"appointment_type": "BOGUS"}, timeout=20)
    assert r.status_code == 400

    # Restore
    if original in ("IN_CLINIC", "TELEPHONE"):
        requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}/type",
                       headers=staff_h, json={"appointment_type": original}, timeout=20)


# ---------- Physician can PATCH /internal/patients/{id} ----------
def test_physician_can_edit_patient(phys_h, staff_h):
    # Find maria.lopez patient
    r = requests.get(f"{BASE_URL}/api/internal/patients?q=maria", headers=phys_h, timeout=20)
    assert r.status_code == 200, r.text
    items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    if not items:
        # try staff search
        r2 = requests.get(f"{BASE_URL}/api/internal/patients?q=maria", headers=staff_h, timeout=20)
        items = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
    assert items, "No patient found for maria"
    pid = items[0]["id"]
    current_pin = items[0].get("visita_patient_id")

    # Invalid PIN (3 digits) -> 400
    r = requests.patch(f"{BASE_URL}/api/internal/patients/{pid}",
                       headers=phys_h, json={"visita_patient_id": "123"}, timeout=20)
    assert r.status_code == 400, f"expected 400 for 3-digit PIN, got {r.status_code}: {r.text}"

    # Valid PIN via physician (choose an unlikely 4-digit; if collides, use current or skip)
    new_pin = "9137"
    if current_pin == new_pin:
        new_pin = "9138"
    r = requests.patch(f"{BASE_URL}/api/internal/patients/{pid}",
                       headers=phys_h, json={"visita_patient_id": new_pin}, timeout=20)
    if r.status_code == 409:
        # PIN in use, try another
        new_pin = "9251"
        r = requests.patch(f"{BASE_URL}/api/internal/patients/{pid}",
                           headers=phys_h, json={"visita_patient_id": new_pin}, timeout=20)
    assert r.status_code == 200, f"physician edit failed: {r.status_code} {r.text}"

    # Restore original pin if any
    if current_pin and current_pin != new_pin:
        requests.patch(f"{BASE_URL}/api/internal/patients/{pid}",
                       headers=staff_h, json={"visita_patient_id": current_pin}, timeout=20)


# ---------- Queue endpoints expose created_at (used for 'Received' column) ----------
@pytest.mark.parametrize("path", ["prescriptions", "imaging", "bloodwork", "messages"])
def test_queue_items_have_created_at(staff_h, path):
    r = requests.get(f"{BASE_URL}/api/internal/{path}", headers=staff_h, timeout=20)
    assert r.status_code == 200, r.text
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items", [])
    if not items:
        pytest.skip(f"No {path} items to check")
    assert "created_at" in items[0], f"{path} missing created_at"
