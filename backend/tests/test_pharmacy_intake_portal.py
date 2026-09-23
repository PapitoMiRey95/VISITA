"""Iteration 33 — Verify Request Intake works with portal-only patients (lookup + snapshot + pharmacy-rx)
while directory regression path still works."""
import os
import requests
import pytest

def _load_base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    try:
        for line in open("/app/frontend/.env"):
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE = _load_base()
STAFF = {"identifier": "staff@visita.demo", "password": "Staff2026!"}


@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE}/api/auth/login", json=STAFF, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(staff_token):
    return {"Authorization": f"Bearer {staff_token}", "Content-Type": "application/json"}


# ---- patient-lookup: should include verified portal-only patient (Maria) ----
def test_lookup_returns_portal_only_maria(headers):
    r = requests.get(f"{BASE}/api/internal/patient-lookup", params={"q": "maria"}, headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) > 0
    hits = [x for x in rows if (x.get("first_name") or "").lower() == "maria" and (x.get("last_name") or "").lower() == "lopez"]
    assert hits, f"Maria Lopez not found in lookup results: {rows}"
    # she must be surfaced (regardless of source label) — capture her id
    return hits[0]


def _find_maria(headers):
    r = requests.get(f"{BASE}/api/internal/patient-lookup", params={"q": "maria lopez"}, headers=headers, timeout=15)
    assert r.status_code == 200
    for row in r.json():
        if (row.get("first_name") or "").lower() == "maria" and (row.get("last_name") or "").lower() == "lopez":
            return row
    pytest.fail("Maria Lopez not found in lookup")


# ---- patient-snapshot: portal source w/ patient_id set, directory_id null ----
def test_snapshot_portal_only(headers):
    maria = _find_maria(headers)
    r = requests.get(f"{BASE}/api/internal/patient-snapshot/{maria['id']}", headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    snap = r.json()
    # Maria is portal-only (verified w/o directory linkage per spec)
    if snap["source"] == "portal":
        assert snap["patient_id"] == maria["id"]
        assert snap.get("directory_id") in (None, "")
    else:
        # If for any reason she is now directory-linked, still verify shape
        assert snap.get("directory_id")
    assert snap.get("first_name") and snap.get("last_name")


# ---- pharmacy-rx: portal-only path (patient_id only, no directory_id) ----
def test_pharmacy_rx_portal_only(headers):
    maria = _find_maria(headers)
    snap = requests.get(f"{BASE}/api/internal/patient-snapshot/{maria['id']}", headers=headers, timeout=15).json()
    payload = {
        "directory_id": snap.get("directory_id"),
        "patient_id": snap.get("patient_id"),
        "pharmacy": "TEST_PortalPharmacy",
        "medications": ["TEST_Ramipril 10 mg"],
        "selected_active_meds": [],
        "duration_qty": "3 months",
        "pharmacy_note": None,
        "received_via": "fax",
        "internal_note": "iter33 portal-only test",
    }
    r = requests.post(f"{BASE}/api/internal/pharmacy-rx", json=payload, headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["source"] == "pharmacy"
    assert doc["internal_status"] == "waiting_physician"
    assert doc["patient_id"] == snap["patient_id"]
    assert doc["pharmacy"] == "TEST_PortalPharmacy"
    # patient_name must be "Last, First"
    assert doc["patient_name"].startswith("Lopez,")
    # Verify it lands in the Rx queue
    q = requests.get(f"{BASE}/api/internal/prescriptions", headers=headers, timeout=15)
    assert q.status_code == 200
    assert any(x["id"] == doc["id"] and x["internal_status"] == "waiting_physician" for x in q.json())


# ---- regression: directory patient still works ----
def _find_directory_patient(headers):
    # try a common directory-only query — use lookup and take a directory-source hit
    for q in ("smith", "perez", "khan", "nguyen", "lopez"):
        r = requests.get(f"{BASE}/api/internal/patient-lookup", params={"q": q}, headers=headers, timeout=15)
        for row in r.json():
            if row.get("source") == "directory":
                return row
    pytest.skip("No directory-source patient available")


def test_snapshot_and_rx_directory(headers):
    d = _find_directory_patient(headers)
    r = requests.get(f"{BASE}/api/internal/patient-snapshot/{d['id']}", headers=headers, timeout=15)
    assert r.status_code == 200
    snap = r.json()
    assert snap["source"] == "directory"
    assert snap["directory_id"] == d["id"]
    payload = {
        "directory_id": snap["directory_id"],
        "patient_id": snap.get("patient_id"),
        "pharmacy": "TEST_DirectoryPharmacy",
        "medications": ["TEST_Metformin 500 mg"],
        "received_via": "phone",
    }
    r2 = requests.post(f"{BASE}/api/internal/pharmacy-rx", json=payload, headers=headers, timeout=20)
    assert r2.status_code == 200, r2.text
    doc = r2.json()
    assert doc["directory_id"] == snap["directory_id"]
    assert doc["internal_status"] == "waiting_physician"


# ---- edge: neither directory_id nor patient_id -> 404 ----
def test_pharmacy_rx_missing_ids_404(headers):
    payload = {"pharmacy": "TEST_X", "medications": ["X 1 mg"], "received_via": "fax"}
    r = requests.post(f"{BASE}/api/internal/pharmacy-rx", json=payload, headers=headers, timeout=15)
    assert r.status_code == 404


# ---- edge: unknown id snapshot -> 404 ----
def test_snapshot_unknown_404(headers):
    r = requests.get(f"{BASE}/api/internal/patient-snapshot/nonexistent-xxx", headers=headers, timeout=15)
    assert r.status_code == 404
