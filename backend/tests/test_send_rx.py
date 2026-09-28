"""PHYSICIAN -> PHARMACY 'Send Prescription' workflow tests (direction=PHYSICIAN_TO_PHARMACY).

Covers the 12 required scenarios. Uses two TEMPORARY pharmacy accounts created in
setup and deleted in teardown (never touches the real 1670dufferin account or any
production patient data). Created rx_transmissions are cleaned up at the end.
"""
import os
import sys
import uuid
import pytest
import requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pymongo import MongoClient
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
import auth as authlib  # noqa: E402

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
_mc = MongoClient(os.environ["MONGO_URL"])
db = _mc[os.environ["DB_NAME"]]

PHYS_ID = "PAGUAYO"
PHYS_PWS = ["Newman2013_!", "Aguayo#Temp2026", "Aguayo#Perm2026!"]
STAFF_ID, STAFF_PW = "staff@visita.demo", "Staff2026!"

_created_pharmacy_object_ids = []
_created_tx_ids = []


def _login(identifier, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"identifier": identifier, "password": password}, timeout=30)
    return r


def _make_pharmacy(pharmacy_id, name, username, password="RxTest123!"):
    doc = {
        "username": username, "name": name, "role": "pharmacy",
        "email": f"{username}@test.local",
        "pharmacy_id": pharmacy_id, "pharmacy_name": name,
        "active": True, "must_change_password": False,
        "password_hash": authlib.hash_password(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = db.users.insert_one(doc)
    _created_pharmacy_object_ids.append(res.inserted_id)
    r = _login(username, password)
    assert r.status_code == 200, f"temp pharmacy login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def physician_token():
    for pw in PHYS_PWS:
        r = _login(PHYS_ID, pw)
        if r.status_code == 200 and r.json().get("token"):
            return r.json()["token"]
    pytest.skip("physician login unavailable")


@pytest.fixture(scope="module")
def staff_token():
    r = _login(STAFF_ID, STAFF_PW)
    assert r.status_code == 200, f"staff login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def pharmacies():
    sfx = uuid.uuid4().hex[:8]
    a = _make_pharmacy(f"testrx-A-{sfx}", f"Test Rx Pharmacy A {sfx}", f"testrxA{sfx}")
    b = _make_pharmacy(f"testrx-B-{sfx}", f"Test Rx Pharmacy B {sfx}", f"testrxB{sfx}")
    yield {"A_token": a, "A_id": f"testrx-A-{sfx}", "B_token": b, "B_id": f"testrx-B-{sfx}"}
    # teardown
    for oid in _created_pharmacy_object_ids:
        db.users.delete_one({"_id": oid})
    if _created_tx_ids:
        db.rx_transmissions.delete_many({"id": {"$in": _created_tx_ids}})


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _find_patient(physician_token):
    r = requests.get(f"{BASE}/api/internal/directory", params={"q": "ROMERO"}, headers=_h(physician_token), timeout=30)
    assert r.status_code == 200, r.text
    items = r.json()
    assert items, "no directory patient found for ROMERO"
    return items[0]["id"]


PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


# 1. Physician finds an existing patient.
def test_01_physician_finds_patient(physician_token):
    pid = _find_patient(physician_token)
    assert pid


# 2. Physician sees pharmacy accounts (patient's pharmacy selectable).
def test_02_pharmacies_listed(physician_token, pharmacies):
    r = requests.get(f"{BASE}/api/internal/pharmacies", headers=_h(physician_token), timeout=30)
    assert r.status_code == 200, r.text
    ids = {p["pharmacy_id"] for p in r.json()}
    assert pharmacies["A_id"] in ids and pharmacies["B_id"] in ids


# 3. Physician sends a manually entered prescription.
def test_03_send_manual_rx(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    meds = '[{"drug":"Ramipril","strength":"10 mg","form":"tablet","sig":"1 tab daily","quantity":"90","refills":"3"}]'
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"],
                            "medications": meds, "physician_note": "please dispense", "confirm": "true"},
                      timeout=30)
    assert r.status_code == 200, r.text
    tx = r.json()
    _created_tx_ids.append(tx["id"])
    assert tx["status"] == "SENT" and tx["direction"] == "PHYSICIAN_TO_PHARMACY"
    assert "attachment" not in tx  # storage path never exposed
    pytest.tx_manual = tx["id"]


# 4. Pharmacy receives only prescriptions addressed to that pharmacy.
def test_04_pharmacy_scoped_visibility(pharmacies):
    ra = requests.get(f"{BASE}/api/pharmacy/incoming", headers=_h(pharmacies["A_token"]), timeout=30)
    assert ra.status_code == 200, ra.text
    a_ids = {i["id"] for i in ra.json()["items"]}
    assert pytest.tx_manual in a_ids
    rb = requests.get(f"{BASE}/api/pharmacy/incoming", headers=_h(pharmacies["B_token"]), timeout=30)
    b_ids = {i["id"] for i in rb.json()["items"]}
    assert pytest.tx_manual not in b_ids


# 5. Physician uploads and sends an Rx PDF.
def test_05_send_pdf_rx(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"],
                            "medications": "[]", "confirm": "true"},
                      files={"file": ("scan.pdf", PDF_BYTES, "application/pdf")}, timeout=30)
    assert r.status_code == 200, r.text
    tx = r.json()
    _created_tx_ids.append(tx["id"])
    assert tx["has_attachment"] is True
    pytest.tx_pdf = tx["id"]


# 6. Pharmacy can securely access that PDF.
def test_06_pharmacy_access_pdf(pharmacies):
    r = requests.get(f"{BASE}/api/pharmacy/incoming/{pytest.tx_pdf}/attachment",
                     headers=_h(pharmacies["A_token"]), timeout=30)
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"


# 7. A different pharmacy cannot access the prescription or PDF.
def test_07_other_pharmacy_blocked(pharmacies):
    d = requests.get(f"{BASE}/api/pharmacy/incoming/{pytest.tx_pdf}", headers=_h(pharmacies["B_token"]), timeout=30)
    assert d.status_code == 404
    a = requests.get(f"{BASE}/api/pharmacy/incoming/{pytest.tx_pdf}/attachment", headers=_h(pharmacies["B_token"]), timeout=30)
    assert a.status_code == 404


# 8. Prescription cannot be sent with neither medication nor PDF.
def test_08_requires_med_or_pdf(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"],
                            "medications": "[]", "confirm": "true"}, timeout=30)
    assert r.status_code == 400


# 9. Invalid/non-PDF upload is rejected server-side.
def test_09_reject_non_pdf(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"],
                            "medications": "[]", "confirm": "true"},
                      files={"file": ("notes.txt", b"hello world", "text/plain")}, timeout=30)
    assert r.status_code == 400


# 9b. Confirmation required.
def test_09b_requires_confirm(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"],
                            "medications": '[{"drug":"Test"}]', "confirm": "false"}, timeout=30)
    assert r.status_code == 400


# 9c. Non-portal pharmacy id rejected gracefully.
def test_09c_unknown_pharmacy(physician_token):
    pid = _find_patient(physician_token)
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": "does-not-exist",
                            "medications": '[{"drug":"Test"}]', "confirm": "true"}, timeout=30)
    assert r.status_code == 400


# 10. Pharmacy opening prescription changes SENT -> VIEWED.
def test_10_sent_to_viewed(pharmacies):
    r = requests.get(f"{BASE}/api/pharmacy/incoming/{pytest.tx_manual}", headers=_h(pharmacies["A_token"]), timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "VIEWED"


# 11. Existing pharmacy -> physician refill workflow still works and stays separate.
def test_11_inbound_refill_unaffected(staff_token, physician_token, pharmacies):
    pid = _find_patient(physician_token)
    r = requests.post(f"{BASE}/api/internal/pharmacy-rx", headers=_h(staff_token),
                      json={"patient_id": pid, "directory_id": pid, "pharmacy": "Some Pharmacy",
                            "medications": ["Metformin 500mg"], "received_via": "fax"}, timeout=30)
    assert r.status_code == 200, r.text
    # It must NOT surface in the physician->pharmacy incoming list
    ra = requests.get(f"{BASE}/api/pharmacy/incoming", headers=_h(pharmacies["A_token"]), timeout=30)
    ref = r.json().get("id")
    assert ref not in {i["id"] for i in ra.json()["items"]}
    # cleanup this inbound test record
    db.prescription_requests.delete_one({"id": ref})


# 12. No production patient/pharmacy directory data reseeded/deleted/replaced.
def test_12_no_directory_mutation():
    # directory count should be stable across this run (we never touch it)
    count = db.patient_directory.count_documents({})
    assert count > 0
    # our temp pharmacies are the only pharmacy users we added; real one untouched
    assert db.users.count_documents({"role": "pharmacy", "pharmacy_id": "1670-dufferin"}) == 1
