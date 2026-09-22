"""Backend tests for the Rx Void / Archive soft-delete feature."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"identifier": "kevinrodriguez9528@gmail.com", "password": "VisitaAdmin2026!"}
STAFF = {"identifier": "staff@visita.demo", "password": "Staff2026!"}
PHYS = {"identifier": "PAGUAYO", "password": "Newman2013_!"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['identifier']}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login(ADMIN),
        "staff": _login(STAFF),
        "phys": _login(PHYS),
    }


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _find_or_create_active_rx(tokens):
    """Return an active (non-voided) Rx request id, creating one if needed."""
    r = requests.get(f"{API}/internal/prescriptions", headers=_hdr(tokens["staff"]), timeout=15)
    assert r.status_code == 200, r.text
    items = r.json()
    active = [x for x in items if x.get("internal_status") != "voided"]
    if active:
        return active[0]
    # else create a patient Rx request - need a patient user. Try to find one.
    # Fallback: try seeded patient
    for creds in [
        {"identifier": "patient@visita.demo", "password": "Patient2026!"},
        {"identifier": "demo.patient@visita.demo", "password": "Patient2026!"},
    ]:
        try:
            pt = requests.post(f"{API}/auth/login", json=creds, timeout=10)
            if pt.status_code == 200:
                ptok = pt.json()["token"]
                body = {
                    "medication_name": "TEST_VOID_MED",
                    "strength": "10mg",
                    "quantity": "30",
                    "pharmacy_name": "TEST Pharmacy",
                }
                cr = requests.post(f"{API}/portal/prescriptions", headers=_hdr(ptok), json=body, timeout=15)
                if cr.status_code in (200, 201):
                    # refetch
                    r2 = requests.get(f"{API}/internal/prescriptions", headers=_hdr(tokens["staff"]), timeout=15)
                    return r2.json()[0]
        except Exception:
            pass
    pytest.skip("No active Rx request available and could not create one")


def test_physician_void_forbidden(tokens):
    item = _find_or_create_active_rx(tokens)
    rid = item["id"]
    r = requests.patch(
        f"{API}/internal/prescriptions/{rid}",
        headers=_hdr(tokens["phys"]),
        json={"action": "void", "void_reason": "Test - should fail"},
        timeout=15,
    )
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


def test_staff_void_and_soft_delete_behavior(tokens):
    item = _find_or_create_active_rx(tokens)
    rid = item["id"]
    original_med = item.get("medication_name")
    original_ref = item.get("ref_number")
    original_patient = item.get("patient_name")
    original_patient_id = item.get("patient_id")

    # Count patient notifications before
    notif_before = None
    if original_patient_id:
        # Notifications endpoint requires patient token; use admin-visible if available; skip if not.
        pass

    # Void as staff
    r = requests.patch(
        f"{API}/internal/prescriptions/{rid}",
        headers=_hdr(tokens["staff"]),
        json={"action": "void", "void_reason": "Duplicate request"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["internal_status"] == "voided"
    assert updated.get("void_reason") == "Duplicate request"
    assert updated.get("voided_by")
    assert updated.get("voided_at")
    # Original data intact
    assert updated.get("medication_name") == original_med
    assert updated.get("ref_number") == original_ref
    assert updated.get("patient_name") == original_patient

    # Active queue should NOT include it
    r2 = requests.get(f"{API}/internal/prescriptions", headers=_hdr(tokens["staff"]), timeout=15)
    assert r2.status_code == 200
    active_ids = [x["id"] for x in r2.json()]
    assert rid not in active_ids, "Voided record should not appear in active queue"

    # Voided filter should include it
    r3 = requests.get(f"{API}/internal/prescriptions?status=voided", headers=_hdr(tokens["staff"]), timeout=15)
    assert r3.status_code == 200
    voided_items = r3.json()
    match = [x for x in voided_items if x["id"] == rid]
    assert match, "Voided record must appear under status=voided filter"
    m = match[0]
    assert m["internal_status"] == "voided"
    assert m.get("void_reason") == "Duplicate request"
    assert m.get("medication_name") == original_med  # not erased


def test_admin_can_void(tokens):
    item = _find_or_create_active_rx(tokens)
    rid = item["id"]
    r = requests.patch(
        f"{API}/internal/prescriptions/{rid}",
        headers=_hdr(tokens["admin"]),
        json={"action": "void", "void_reason": "Admin test void"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["internal_status"] == "voided"


def test_voided_record_still_exists_no_hard_delete(tokens):
    # Fetch all voided; ensure GET by status returns records (document still exists)
    r = requests.get(f"{API}/internal/prescriptions?status=voided", headers=_hdr(tokens["admin"]), timeout=15)
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    for it in items:
        assert it["internal_status"] == "voided"
        # medication data preserved
        assert it.get("medication_name") is not None
