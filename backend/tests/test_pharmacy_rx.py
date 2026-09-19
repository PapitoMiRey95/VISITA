"""Pharmacy-initiated Prescription Request workflow tests.

Covers:
- GET  /api/internal/directory?q=       (staff search)
- GET  /api/internal/patient-snapshot/{directory_id}
- POST /api/internal/pharmacy-rx        (create pharmacy request)
- GET  /api/internal/prescriptions      (physician queue filter)
- PATCH /api/internal/prescriptions/{id} (approve / modify / more_info / decline / complete)
- GET  /api/internal/counters           (RX counter includes approved-but-not-completed)
- POST /api/internal/book-appointment   (from a pharmacy Rx)
"""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

STAFF_ID = "staff@visita.demo"
STAFF_PW = "Staff2026!"
PHYS_ID = "PAGUAYO"
PHYS_PW = "Aguayo#Temp2026"
PHYS_PW_PERM = "Aguayo#Perm2026!"


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": STAFF_ID, "password": STAFF_PW}, timeout=30)
    assert r.status_code == 200, f"staff login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def physician_token():
    """Login as physician; try temp then permanent password."""
    for pw in (PHYS_PW, PHYS_PW_PERM):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"identifier": PHYS_ID, "password": pw}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            tok = data["token"]
            if data.get("user", {}).get("must_change_password"):
                cp = requests.post(f"{BASE_URL}/api/auth/change-password",
                                   headers={"Authorization": f"Bearer {tok}"},
                                   json={"current_password": pw, "new_password": PHYS_PW_PERM}, timeout=30)
                if cp.status_code == 200:
                    r2 = requests.post(f"{BASE_URL}/api/auth/login",
                                       json={"identifier": PHYS_ID, "password": PHYS_PW_PERM}, timeout=30)
                    if r2.status_code == 200:
                        return r2.json()["token"]
            return tok
    pytest.skip("physician login failed")


def _h(t): return {"Authorization": f"Bearer {t}"}


# ---------------- directory search ----------------
def test_directory_search_by_name(staff_token):
    r = requests.get(f"{BASE_URL}/api/internal/directory",
                     params={"q": "ROMERO"}, headers=_h(staff_token), timeout=30)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list) and len(items) > 0, "expected at least one directory match for ROMERO"
    got = items[0]
    assert "id" in got
    assert "first_name" in got and "last_name" in got


def test_directory_search_empty_q(staff_token):
    r = requests.get(f"{BASE_URL}/api/internal/directory",
                     headers=_h(staff_token), timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------- snapshot ----------------
@pytest.fixture(scope="module")
def romero_directory_id(staff_token):
    r = requests.get(f"{BASE_URL}/api/internal/directory",
                     params={"q": "ROMERO"}, headers=_h(staff_token), timeout=30)
    assert r.status_code == 200
    items = r.json()
    assert items, "no ROMERO directory candidate available for tests"
    return items[0]["id"]


def test_patient_snapshot(staff_token, romero_directory_id):
    r = requests.get(f"{BASE_URL}/api/internal/patient-snapshot/{romero_directory_id}",
                     headers=_h(staff_token), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    for f in ("first_name", "last_name", "visita_patient_id", "date_of_birth",
              "age", "phone", "patient_status", "medications",
              "last_visit_date", "last_visit_plan", "current_pharmacy"):
        assert f in d, f"missing field {f} in snapshot"
    assert d["medications"] == [], "medications should be empty (model-ready)"
    if d["date_of_birth"]:
        assert isinstance(d["age"], int), "age should be computed integer"


def test_patient_snapshot_404(staff_token):
    r = requests.get(f"{BASE_URL}/api/internal/patient-snapshot/NOT-A-REAL-ID",
                     headers=_h(staff_token), timeout=30)
    assert r.status_code == 404


# ---------------- create pharmacy Rx ----------------
@pytest.fixture(scope="module")
def created_pharmacy_rx(staff_token, romero_directory_id):
    body = {
        "directory_id": romero_directory_id,
        "pharmacy": "TEST Pharmacy Downtown",
        "medications": ["Atorvastatin 20mg", "Metformin 500mg"],
        "received_via": "fax",
        "duration_qty": "90-day supply",
        "pharmacy_note": "TEST pharmacy_note",
        "internal_note": "TEST internal_note",
        "selected_active_meds": [],
    }
    r = requests.post(f"{BASE_URL}/api/internal/pharmacy-rx",
                      json=body, headers=_h(staff_token), timeout=30)
    assert r.status_code == 200, f"create pharmacy rx failed: {r.status_code} {r.text}"
    doc = r.json()
    return doc


def test_pharmacy_rx_fields(created_pharmacy_rx):
    d = created_pharmacy_rx
    assert d["source"] == "pharmacy"
    assert d["internal_status"] == "waiting_physician"
    assert d["ref_number"].startswith("RX-")
    assert d["pharmacy"] == "TEST Pharmacy Downtown"
    assert d["medication_name"] == "Atorvastatin 20mg; Metformin 500mg"
    assert d["medications"] == ["Atorvastatin 20mg", "Metformin 500mg"]
    assert d.get("patient_name"), "patient_name should be populated from directory"
    assert "_id" not in d


def test_pharmacy_rx_empty_meds_400(staff_token, romero_directory_id):
    r = requests.post(f"{BASE_URL}/api/internal/pharmacy-rx",
                      json={"directory_id": romero_directory_id, "pharmacy": "X",
                            "medications": ["  ", ""], "received_via": "fax"},
                      headers=_h(staff_token), timeout=30)
    assert r.status_code == 400


def test_pharmacy_rx_bad_directory_404(staff_token):
    r = requests.post(f"{BASE_URL}/api/internal/pharmacy-rx",
                      json={"directory_id": "does-not-exist", "pharmacy": "X",
                            "medications": ["Med A"], "received_via": "phone"},
                      headers=_h(staff_token), timeout=30)
    assert r.status_code == 404


# ---------------- physician queue filter ----------------
def test_physician_sees_pharmacy_rx_in_queue(physician_token, created_pharmacy_rx):
    r = requests.get(f"{BASE_URL}/api/internal/prescriptions",
                     headers=_h(physician_token), timeout=30)
    assert r.status_code == 200
    items = r.json()
    ids = [x["id"] for x in items]
    assert created_pharmacy_rx["id"] in ids, "pharmacy rx not in physician queue"
    match = next(x for x in items if x["id"] == created_pharmacy_rx["id"])
    assert match["source"] == "pharmacy"
    assert match["pharmacy"] == "TEST Pharmacy Downtown"
    assert match["internal_status"] == "waiting_physician"


# ---------------- counters ----------------
def test_counter_rx_includes_waiting(staff_token, created_pharmacy_rx):
    r = requests.get(f"{BASE_URL}/api/internal/counters",
                     headers=_h(staff_token), timeout=30)
    assert r.status_code == 200
    c = r.json()["counters"]
    assert c["rx"] >= 1


# ---------------- physician actions ----------------
def _mk_rx(staff_token, directory_id, meds=None):
    body = {
        "directory_id": directory_id,
        "pharmacy": "TEST Pharmacy Actions",
        "medications": meds or ["TEST-Med A"],
        "received_via": "phone",
    }
    r = requests.post(f"{BASE_URL}/api/internal/pharmacy-rx",
                      json=body, headers=_h(staff_token), timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_action_approve(physician_token, staff_token, romero_directory_id):
    rx = _mk_rx(staff_token, romero_directory_id)
    r = requests.patch(f"{BASE_URL}/api/internal/prescriptions/{rx['id']}",
                       json={"action": "approve"}, headers=_h(physician_token), timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["internal_status"] == "approved_process_visita"

    # Approved-not-completed still counted in staff rx counter
    c = requests.get(f"{BASE_URL}/api/internal/counters",
                     headers=_h(staff_token), timeout=30).json()["counters"]
    assert c["rx"] >= 1

    # Staff completes
    r2 = requests.patch(f"{BASE_URL}/api/internal/prescriptions/{rx['id']}",
                        json={"action": "complete"}, headers=_h(staff_token), timeout=30)
    assert r2.status_code == 200
    assert r2.json()["internal_status"] == "completed"


def test_action_modify(physician_token, staff_token, romero_directory_id):
    rx = _mk_rx(staff_token, romero_directory_id)
    r = requests.patch(f"{BASE_URL}/api/internal/prescriptions/{rx['id']}",
                       json={"action": "modify", "staff_note": "adjust dose"},
                       headers=_h(physician_token), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["internal_status"] == "approved_process_visita"
    assert d.get("modified") is True


def test_action_more_info(physician_token, staff_token, romero_directory_id):
    rx = _mk_rx(staff_token, romero_directory_id)
    r = requests.patch(f"{BASE_URL}/api/internal/prescriptions/{rx['id']}",
                       json={"action": "more_info", "staff_note": "need last labs"},
                       headers=_h(physician_token), timeout=30)
    assert r.status_code == 200
    assert r.json()["internal_status"] == "more_info_required"


def test_action_decline(physician_token, staff_token, romero_directory_id):
    rx = _mk_rx(staff_token, romero_directory_id)
    r = requests.patch(f"{BASE_URL}/api/internal/prescriptions/{rx['id']}",
                       json={"action": "decline", "staff_note": "not appropriate"},
                       headers=_h(physician_token), timeout=30)
    assert r.status_code == 200
    assert r.json()["internal_status"] == "declined"


# ---------------- book appointment from pharmacy rx ----------------
def test_book_appointment_from_pharmacy_rx(staff_token, romero_directory_id):
    rx = _mk_rx(staff_token, romero_directory_id)

    # Fetch a valid slot from availability
    slots_r = requests.get(f"{BASE_URL}/api/availability/slots",
                           headers=_h(staff_token), params={"days": 21}, timeout=30)
    assert slots_r.status_code == 200
    slots = slots_r.json().get("slots") or []
    # slots is grouped by date; pick first date/time
    if not slots:
        pytest.skip("no availability slots returned")
    # Try slots in order until one is free (avoid 409 from prior tests)
    r = None
    for slot in slots[:20]:
        body = {"source_type": "prescription", "source_id": rx["id"],
                "date": slot["date"], "time": slot["time"], "label": slot.get("label"),
                "display": slot.get("display")}
        r = requests.post(f"{BASE_URL}/api/internal/book-appointment",
                          json=body, headers=_h(staff_token), timeout=30)
        if r.status_code == 200:
            break
        if r.status_code not in (409, 400):
            break
    assert r is not None and r.status_code == 200, f"could not book: {r.status_code} {r.text}"
    appt = r.json()
    assert appt["status"] == "confirmed"
    assert appt.get("booked_from", {}).get("source_id") == rx["id"]

    # Source rx should now be appointment_booked
    fetched = requests.get(f"{BASE_URL}/api/internal/prescriptions",
                           headers=_h(staff_token), params={"q": rx["ref_number"]}, timeout=30)
    got = [x for x in fetched.json() if x["id"] == rx["id"]]
    assert got and got[0]["internal_status"] == "appointment_booked"


# ---------------- cleanup ----------------
def test_cleanup_test_pharmacy_data(staff_token):
    """Best-effort report — actual DB cleanup is done externally by the test harness."""
    # simply report items; harness (main agent) handles delete
    r = requests.get(f"{BASE_URL}/api/internal/prescriptions",
                     headers=_h(staff_token), timeout=30)
    if r.status_code == 200:
        pharm = [x for x in r.json() if x.get("source") == "pharmacy"]
        print(f"[cleanup-note] pharmacy rx count in DB: {len(pharm)}")
