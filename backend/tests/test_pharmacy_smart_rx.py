"""PHARMACY -> PHYSICIAN smart Rx Request builder tests.

Reuses the shared parser + smart-combo architecture. Uses TWO temporary pharmacy
accounts (deleted in teardown) and never touches the real 1670dufferin account or
production patient data. Created prescription_requests + pharmacy_rx_memory are
cleaned up at the end. Patient records are only READ, never modified.
"""
import os
import sys
import json
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

_created_user_oids = []
_created_req_ids = []
_created_pharmacy_ids = []


def _login(identifier, password):
    return requests.post(f"{BASE}/api/auth/login", json={"identifier": identifier, "password": password}, timeout=30)


def _make_pharmacy(pharmacy_id, name, username, password="PharmRx123!"):
    doc = {
        "username": username, "name": name, "role": "pharmacy",
        "email": f"{username}@test.local", "pharmacy_id": pharmacy_id, "pharmacy_name": name,
        "active": True, "must_change_password": False,
        "password_hash": authlib.hash_password(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = db.users.insert_one(doc)
    _created_user_oids.append(res.inserted_id)
    _created_pharmacy_ids.append(pharmacy_id)
    r = _login(username, password)
    assert r.status_code == 200, f"temp pharmacy login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def pharmacies():
    sfx = uuid.uuid4().hex[:8]
    a = _make_pharmacy(f"pharmrx-A-{sfx}", f"Pharm Rx A {sfx}", f"pharmrxA{sfx}")
    b = _make_pharmacy(f"pharmrx-B-{sfx}", f"Pharm Rx B {sfx}", f"pharmrxB{sfx}")
    yield {"A": a, "A_id": f"pharmrx-A-{sfx}", "B": b, "B_id": f"pharmrx-B-{sfx}"}
    if _created_req_ids:
        db.prescription_requests.delete_many({"id": {"$in": _created_req_ids}})
    for pid in _created_pharmacy_ids:
        db.pharmacy_rx_memory.delete_many({"pharmacy_id": pid})
    for oid in _created_user_oids:
        db.users.delete_one({"_id": oid})


@pytest.fixture(scope="module")
def patient_with_ohip():
    d = db.patient_directory.find_one({"patient_status": {"$ne": "FORMER_CLOSED"},
                                       "health_card_number": {"$nin": [None, ""]}})
    if not d:
        pytest.skip("no ACTIVE directory patient with OHIP")
    return d


@pytest.fixture(scope="module")
def patient_no_ohip():
    d = db.patient_directory.find_one({"patient_status": {"$ne": "FORMER_CLOSED"},
                                       "$or": [{"health_card_number": None}, {"health_card_number": ""},
                                               {"health_card_number": {"$exists": False}}]})
    return d


@pytest.fixture(scope="module")
def clinic_token():
    for pw in PHYS_PWS:
        r = _login(PHYS_ID, pw)
        if r.status_code == 200 and r.json().get("token"):
            return r.json()["token"]
    r = _login(STAFF_ID, STAFF_PW)
    if r.status_code == 200:
        return r.json()["token"]
    pytest.skip("no clinic login available")


def test_patient_search_identity(pharmacies, patient_with_ohip):
    q = (patient_with_ohip.get("last_name") or "")[:4]
    r = requests.get(f"{BASE}/api/pharmacy/patients/search", params={"q": q}, headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_patient_detail_full_fields(pharmacies, patient_with_ohip):
    r = requests.get(f"{BASE}/api/pharmacy/patients/{patient_with_ohip['id']}", headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["health_card_number"]
    # version key present (either version or version_code)
    assert "health_card_version" in d and "health_card_expiry_date" in d
    assert "address_full" in d and "cell_phone" in d and "home_phone" in d


def test_no_ohip_not_fabricated(pharmacies, patient_no_ohip):
    if not patient_no_ohip:
        pytest.skip("no ACTIVE patient without OHIP")
    r = requests.get(f"{BASE}/api/pharmacy/patients/{patient_no_ohip['id']}", headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 200
    assert not r.json().get("health_card_number")


def test_parse_single(pharmacies):
    r = requests.post(f"{BASE}/api/pharmacy/rx/parse", json={"text": "Amlodipine besylate 5 mg tablet: 1 tablet HS"}, headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 200
    meds = r.json().get("medications") or []
    assert len(meds) == 1
    assert "amlodipine" in (meds[0].get("drug") or "").lower()


def test_parse_multi_one_card_each(pharmacies):
    text = ("Amlodipine besylate 5 mg tablet: 1 tablet HS\n"
            "Bisoprolol fumarate 5 mg tablet: 1 tablet HS\n"
            "Levothyroxine 50 µg tablet: 1 tablet OD\n"
            "Rosuvastatin calcium 5 mg tablet: 1 tablet OD\n"
            "Spironolactone 25 mg tablet: ½ tablet AM")
    r = requests.post(f"{BASE}/api/pharmacy/rx/parse", json={"text": text}, headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 200
    meds = r.json().get("medications") or []
    assert len(meds) == 5, f"expected 5 cards got {len(meds)}"
    drugs = " ".join((m.get("drug") or "").lower() for m in meds)
    for name in ["amlodipine", "bisoprolol", "levothyroxine", "rosuvastatin", "spironolactone"]:
        assert name in drugs


def test_send_multi_med_persists_structured_and_snapshot(pharmacies, patient_with_ohip):
    meds = [
        {"drug": "Amlodipine besylate", "strength": "5 mg", "form": "tablet", "sig": "1 tablet HS",
         "existing_rx_number": "RX-999", "days_supply": "90", "requested_duration": "3 months", "manufacturer": "Apotex"},
        {"drug": "Rosuvastatin calcium", "strength": "5 mg", "form": "tablet", "sig": "1 tablet OD"},
    ]
    fd = {"directory_id": (None, patient_with_ohip["id"]),
          "medications": (None, json.dumps(meds)),
          "pharmacy_note": (None, "Please renew"),
          "message_to_physician": (None, "Patient stable")}
    r = requests.post(f"{BASE}/api/pharmacy/rx", files=fd, headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 200, r.text
    doc = r.json()
    _created_req_ids.append(doc["id"])
    assert doc["source"] == "pharmacy" and doc["provenance"] == "PHARMACY_REQUEST"
    assert len(doc["medications_structured"]) == 2
    assert len(doc["medications"]) == 2  # display strings
    snap = doc.get("patient_snapshot") or {}
    assert snap.get("date_of_birth")  # frozen identity present
    # first structured med retained pharmacy-specific fields
    assert doc["medications_structured"][0]["existing_rx_number"] == "RX-999"


def test_suggest_after_send_and_isolation(pharmacies, patient_with_ohip):
    # Send a PHARMACY-UNIQUE drug so it is guaranteed to surface as source=pharmacy
    # (common drugs may be deduped behind the patient's own higher-ranked meds — by design).
    uniq = f"Zzpharmuniq {pharmacies['A_id'][-6:]}"
    fd = {"directory_id": (None, patient_with_ohip["id"]),
          "medications": (None, json.dumps([{"drug": uniq, "strength": "1 mg", "form": "tablet", "sig": "1 tablet OD"}]))}
    rc = requests.post(f"{BASE}/api/pharmacy/rx", files=fd, headers=_H(pharmacies["A"]), timeout=30)
    assert rc.status_code == 200, rc.text
    _created_req_ids.append(rc.json()["id"])
    # pharmacy A should now suggest Amlodipine + the unique drug from its own memory
    r = requests.get(f"{BASE}/api/pharmacy/rx/suggest", params={"patient_ref": patient_with_ohip["id"]}, headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 200
    drugs_a = [d["value"].lower() for d in r.json().get("drugs", [])]
    src_a = {d["value"].lower(): d["source"] for d in r.json().get("drugs", [])}
    assert any("amlodipine" in v for v in drugs_a)
    assert src_a.get(uniq.lower()) == "pharmacy"
    # field suggestions for the drug from pharmacy memory
    rf = requests.get(f"{BASE}/api/pharmacy/rx/suggest", params={"drug": "Amlodipine besylate"}, headers=_H(pharmacies["A"]), timeout=30)
    assert rf.status_code == 200
    manus = [x["value"] for x in (rf.json().get("fields", {}).get("manufacturers") or [])]
    assert "Apotex" in manus
    # pharmacy B must NOT see A's remembered manufacturer
    rb = requests.get(f"{BASE}/api/pharmacy/rx/suggest", params={"drug": "Amlodipine besylate"}, headers=_H(pharmacies["B"]), timeout=30)
    assert rb.status_code == 200
    manus_b = [x["value"] for x in (rb.json().get("fields", {}).get("manufacturers") or [])]
    assert "Apotex" not in manus_b


def test_prior_requests_scoped(pharmacies, patient_with_ohip):
    ra = requests.get(f"{BASE}/api/pharmacy/patients/{patient_with_ohip['id']}/prior-requests", headers=_H(pharmacies["A"]), timeout=30)
    assert ra.status_code == 200 and len(ra.json()) >= 1
    rb = requests.get(f"{BASE}/api/pharmacy/patients/{patient_with_ohip['id']}/prior-requests", headers=_H(pharmacies["B"]), timeout=30)
    assert rb.status_code == 200 and len(rb.json()) == 0  # B sees none of A's


def test_physician_memory_not_written_by_pharmacy(pharmacies):
    # provenance separation: pharmacy send must not create physician_rx_memory
    cnt = db.physician_rx_memory.count_documents({"drug_key": "amlodipine besylate", "physician_id": {"$in": _created_pharmacy_ids}})
    assert cnt == 0


def test_clinic_sees_structured_request(pharmacies, clinic_token, patient_with_ohip):
    r = requests.get(f"{BASE}/api/internal/prescriptions", params={"status": "waiting_physician"}, headers=_H(clinic_token), timeout=30)
    if r.status_code != 200:
        r = requests.get(f"{BASE}/api/internal/prescriptions", headers=_H(clinic_token), timeout=30)
    assert r.status_code == 200
    mine = [x for x in r.json() if x.get("id") in _created_req_ids]
    assert mine, "clinic queue did not include the pharmacy request"
    # pick the multi-medication request (other created requests may be 1-med/doc-only)
    item = next((x for x in mine if len(x.get("medications_structured") or []) == 2), None)
    assert item is not None, "multi-med pharmacy request not visible to clinic"
    assert len(item.get("medications_structured") or []) == 2
    assert (item.get("patient_snapshot") or {}).get("date_of_birth")


def test_document_only_request(pharmacies, patient_with_ohip):
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    fd = {"directory_id": (None, patient_with_ohip["id"]),
          "file": ("scan.pdf", pdf, "application/pdf")}
    r = requests.post(f"{BASE}/api/pharmacy/rx", files=fd, headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 200, r.text
    _created_req_ids.append(r.json()["id"])


def test_empty_request_rejected(pharmacies, patient_with_ohip):
    fd = {"directory_id": (None, patient_with_ohip["id"]), "medications": (None, "[]")}
    r = requests.post(f"{BASE}/api/pharmacy/rx", files=fd, headers=_H(pharmacies["A"]), timeout=30)
    assert r.status_code == 400
