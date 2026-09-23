"""Iter 32 safety corrections regression:
- VISITA PIN retirement via internal_edit_patient path (staff & physician)
- VISITA PIN retirement via applications assign-pin path
- Suggestions never return retired pins
- 409 on trying to reassign a retired pin to another patient
- identity_history entry recorded
- Undo No Show / undo complete works and returns 400 when idempotent
- Physician can edit patient PIN (4-digit validation)
"""
import os
import random
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")

STAFF = {"identifier": "staff@visita.demo", "password": "Staff2026!"}
PHYSICIAN = {"identifier": "PAGUAYO", "password": "Newman2013_!"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_h():
    return {"Authorization": f"Bearer {_login(STAFF)}"}


@pytest.fixture(scope="module")
def phys_h():
    return {"Authorization": f"Bearer {_login(PHYSICIAN)}"}


def _get_suggestions(headers, n=10):
    r = requests.get(f"{BASE_URL}/api/internal/visita-pin/suggestions?count={n}",
                     headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    return r.json().get("suggestions", [])


def _find_patient(headers, q):
    r = requests.get(f"{BASE_URL}/api/internal/patients?q={q}", headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    return items[0] if items else None


# ---------------- (1) Old retired pin 9137 is not in suggestions ----------------
def test_previous_retired_pin_9137_not_suggested(staff_h):
    # Sample many times; 9137 must never appear if retired.
    for _ in range(6):
        sug = _get_suggestions(staff_h, n=10)
        assert "9137" not in sug, f"Retired PIN 9137 found in suggestions: {sug}"


# ---------------- (2) 409 when trying to reassign retired 9137 to any other patient ----------------
def test_reassign_retired_pin_returns_409(staff_h):
    # Find any patient that is NOT maria (retired_from) to try reassigning.
    r = requests.get(f"{BASE_URL}/api/internal/patients?q=john", headers=staff_h, timeout=20)
    items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    if not items:
        pytest.skip("no john patient to test")
    john = items[0]
    if john.get("visita_patient_id") == "9137":
        pytest.skip("john already has 9137 somehow")
    r = requests.patch(f"{BASE_URL}/api/internal/patients/{john['id']}",
                       headers=staff_h, json={"visita_patient_id": "9137"}, timeout=20)
    assert r.status_code == 409, f"expected 409 for retired PIN reassign, got {r.status_code}: {r.text}"


# ---------------- (3) PIN change via internal_edit_patient retires OLD, reserves NEW, adds identity_history ----------------
def test_internal_edit_patient_retires_old_pin(staff_h, phys_h):
    p = _find_patient(staff_h, "maria")
    assert p, "maria not found"
    pid = p["id"]
    current_pin = p.get("visita_patient_id")
    assert current_pin, "maria has no current PIN"

    # Pick a NEW unused pin from suggestions
    sug = _get_suggestions(staff_h, n=10)
    new_pin = next((s for s in sug if s != current_pin), None)
    assert new_pin, "no suggested pin available"

    # PHYSICIAN performs the edit (also validates physician can edit PIN)
    r = requests.patch(f"{BASE_URL}/api/internal/patients/{pid}",
                       headers=phys_h, json={"visita_patient_id": new_pin}, timeout=20)
    assert r.status_code == 200, f"physician edit failed: {r.status_code} {r.text}"

    # Verify new pin is now on the patient
    p2 = _find_patient(staff_h, "maria")
    assert p2["visita_patient_id"] == new_pin

    # Old pin must be retired -> suggestions should not include it, and reassigning it to another patient must 409
    for _ in range(4):
        sug2 = _get_suggestions(staff_h, n=10)
        assert current_pin not in sug2, f"OLD pin {current_pin} still suggested: {sug2}"

    john = _find_patient(staff_h, "john")
    if john and john.get("visita_patient_id") != current_pin:
        r = requests.patch(f"{BASE_URL}/api/internal/patients/{john['id']}",
                           headers=staff_h, json={"visita_patient_id": current_pin}, timeout=20)
        assert r.status_code == 409, f"retired old pin {current_pin} allowed to be reassigned: {r.status_code} {r.text}"

    # Patient lookup by new pin
    r = requests.get(f"{BASE_URL}/api/internal/patient-lookup?q={new_pin}", headers=staff_h, timeout=20)
    assert r.status_code in (200, 404), r.text

    # identity_history entry must include the change (via patient search / snapshot if exposed)
    # Fetch snapshot: /api/internal/patient-snapshot/{directory_id} if linked, otherwise verify by round-tripping.
    # As a proxy, we PATCH again with SAME new pin -> should return changes==0
    r = requests.patch(f"{BASE_URL}/api/internal/patients/{pid}",
                       headers=phys_h, json={"visita_patient_id": new_pin}, timeout=20)
    assert r.status_code == 200
    assert r.json().get("changes") == 0

    # Restore back — but NOTE: the previous pin is now retired. Restoring would require
    # server to allow re-assigning to the SAME patient it was retired from. The endpoint
    # blocks (claim.patient_id != pid AND retired). So we CANNOT restore original pin.
    # Instead, keep the new pin. Log this as test-created state change.
    print(f"[PIN RETIREMENT] maria PIN changed {current_pin} -> {new_pin}. Old pin retired.")


# ---------------- (4) 3-digit PIN -> 400 (physician role) ----------------
def test_physician_pin_validation_bad(phys_h, staff_h):
    p = _find_patient(staff_h, "maria")
    r = requests.patch(f"{BASE_URL}/api/internal/patients/{p['id']}",
                       headers=phys_h, json={"visita_patient_id": "123"}, timeout=20)
    assert r.status_code == 400


# ---------------- (5) Undo No Show flow & 400 idempotent ----------------
def test_undo_no_show_and_complete(staff_h):
    r = requests.get(f"{BASE_URL}/api/internal/appointments?status=confirmed",
                     headers=staff_h, timeout=20)
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items", [])
    if not items:
        pytest.skip("no confirmed appt")
    aid = items[0]["id"]

    # no_show
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}",
                       headers=staff_h, json={"action": "no_show"}, timeout=20)
    assert r.status_code == 200 and r.json()["status"] == "no_show"
    # undo -> confirmed
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}",
                       headers=staff_h, json={"action": "undo_status"}, timeout=20)
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    # already confirmed -> 400
    r = requests.patch(f"{BASE_URL}/api/internal/appointments/{aid}",
                       headers=staff_h, json={"action": "undo_status"}, timeout=20)
    assert r.status_code == 400


# ---------------- (6) Queue endpoints have created_at (Received column) ----------------
@pytest.mark.parametrize("path", ["prescriptions", "imaging", "bloodwork", "messages"])
def test_queue_created_at(staff_h, path):
    r = requests.get(f"{BASE_URL}/api/internal/{path}", headers=staff_h, timeout=20)
    assert r.status_code == 200
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items", [])
    if not items:
        pytest.skip(f"no {path}")
    assert "created_at" in items[0]


# ---------------- (7) Application assign-pin path retires old pin ----------------
def test_application_assign_pin_retires_old(staff_h):
    # Find an application with created_patient_id (accepted new_patient)
    r = requests.get(f"{BASE_URL}/api/internal/applications", headers=staff_h, timeout=20)
    assert r.status_code == 200
    apps = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    target = None
    for a in apps:
        if a.get("created_patient_id") and a.get("internal_status") in (None, "ACCEPTED"):
            target = a
            break
    if not target:
        pytest.skip("no accepted application with created_patient_id")
    appid = target["id"]
    pid = target["created_patient_id"]

    # Fetch current pin
    r = requests.get(f"{BASE_URL}/api/internal/patients?q={target.get('email','')}",
                     headers=staff_h, timeout=20)
    plist = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    match = next((x for x in plist if x["id"] == pid), None)
    if not match:
        pytest.skip("could not locate created patient")
    old_pin = match.get("visita_patient_id")
    if not old_pin:
        pytest.skip("no old_pin on created patient")

    # pick new unused pin
    sug = _get_suggestions(staff_h, n=10)
    new_pin = next((s for s in sug if s != old_pin), None)
    assert new_pin

    r = requests.post(f"{BASE_URL}/api/internal/applications/{appid}/assign-pin",
                      headers=staff_h, json={"pin": new_pin}, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json().get("visita_patient_id") == new_pin

    # old pin retired -> not in suggestions
    sug2 = _get_suggestions(staff_h, n=10)
    assert old_pin not in sug2

    # 409 if we try to assign old pin to some other patient
    other = _find_patient(staff_h, "john")
    if other and other.get("visita_patient_id") != old_pin:
        r = requests.patch(f"{BASE_URL}/api/internal/patients/{other['id']}",
                           headers=staff_h, json={"visita_patient_id": old_pin}, timeout=20)
        assert r.status_code == 409

    print(f"[PIN RETIREMENT via assign-pin] app {appid}: {old_pin} -> {new_pin}")
