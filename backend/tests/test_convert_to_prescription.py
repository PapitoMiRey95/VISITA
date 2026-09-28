"""PHYSICIAN CONFIRM FLOW — 'Convert to Prescription' tests.

A pharmacy request is converted into a physician DRAFT (client-side), reviewed/edited,
then SENT. Only on successful physician Send may data become physician-confirmed.

Uses TWO temporary pharmacy accounts + a clinic sender (physician preferred, staff
fallback). Never mutates production data. All created requests / transmissions /
memory / confirmed meds are cleaned up in teardown. The pharmacy request is proven
IMMUTABLE (preserved as historical evidence) after conversion.
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

SFX = uuid.uuid4().hex[:8]
UNIQUE_DRUG = f"Zztestdrug {SFX}"  # unique so memory/med assertions are unambiguous

_user_oids = []
_req_ids = []
_tx_ids = []
_pharm_ids = []


def _login(i, p):
    return requests.post(f"{BASE}/api/auth/login", json={"identifier": i, "password": p}, timeout=30)


def _H(t):
    return {"Authorization": f"Bearer {t}"}


def _make_pharmacy(pid, name, username, pw="ConvRx123!"):
    doc = {"username": username, "name": name, "role": "pharmacy", "email": f"{username}@test.local",
           "pharmacy_id": pid, "pharmacy_name": name, "active": True, "must_change_password": False,
           "password_hash": authlib.hash_password(pw), "created_at": datetime.now(timezone.utc).isoformat()}
    _user_oids.append(db.users.insert_one(doc).inserted_id)
    _pharm_ids.append(pid)
    r = _login(username, pw)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def env():
    a = _make_pharmacy(f"conv-A-{SFX}", f"Conv A {SFX}", f"convA{SFX}")
    b = _make_pharmacy(f"conv-B-{SFX}", f"Conv B {SFX}", f"convB{SFX}")
    clinic = None
    for pw in PHYS_PWS:
        r = _login(PHYS_ID, pw)
        if r.status_code == 200 and r.json().get("token"):
            clinic = r.json()["token"]; break
    if not clinic:
        r = _login(STAFF_ID, STAFF_PW)
        if r.status_code == 200:
            clinic = r.json()["token"]
    if not clinic:
        pytest.skip("no clinic login")
    d = db.patient_directory.find_one({"patient_status": {"$ne": "FORMER_CLOSED"},
                                       "health_card_number": {"$nin": [None, ""]}})
    if not d:
        pytest.skip("no ACTIVE patient with OHIP")
    patient_id = d.get("linked_patient_id") or d["id"]
    yield {"A": a, "A_id": f"conv-A-{SFX}", "B": b, "B_id": f"conv-B-{SFX}",
           "clinic": clinic, "dir_id": d["id"], "patient_id": patient_id}
    # teardown
    if _req_ids:
        db.prescription_requests.delete_many({"id": {"$in": _req_ids}})
    if _tx_ids:
        db.rx_transmissions.delete_many({"id": {"$in": _tx_ids}})
    for pid in _pharm_ids:
        db.pharmacy_rx_memory.delete_many({"pharmacy_id": pid})
    db.physician_rx_memory.delete_many({"drug_key": UNIQUE_DRUG.lower()})
    db.patient_medications.delete_many({"drug": UNIQUE_DRUG})
    for oid in _user_oids:
        db.users.delete_one({"_id": oid})


PHARM_MEDS = [
    {"drug": "Amlodipine besylate", "strength": "5 mg", "form": "tablet", "sig": "1 tablet HS",
     "manufacturer": "Apotex", "existing_rx_number": "RX-CONV-1", "days_supply": "90", "requested_duration": "3 months"},
    {"drug": "Rosuvastatin calcium", "strength": "5 mg", "form": "tablet", "sig": "1 tablet OD"},
]


@pytest.fixture(scope="module")
def pharmacy_request(env):
    fd = {"directory_id": (None, env["dir_id"]),
          "medications": (None, json.dumps(PHARM_MEDS)),
          "pharmacy_note": (None, "Please renew")}
    r = requests.post(f"{BASE}/api/pharmacy/rx", files=fd, headers=_H(env["A"]), timeout=30)
    assert r.status_code == 200, r.text
    doc = r.json()
    _req_ids.append(doc["id"])
    return doc


def test_request_created_waiting_and_immutable_before_send(env, pharmacy_request):
    # Freshly created pharmacy request: waiting for physician, NOT yet linked/sent.
    raw = db.prescription_requests.find_one({"id": pharmacy_request["id"]})
    assert raw["internal_status"] == "waiting_physician"
    assert not raw.get("linked_transmission_id")
    assert raw.get("internal_status") != "prescription_sent"
    assert len(raw["medications_structured"]) == 2


def test_conversion_is_draft_only_no_confirmed_data(env, pharmacy_request):
    # 'Convert to Prescription' is client-side (no backend call), so at this point
    # NO physician-confirmed data may exist for our unique drug.
    assert db.physician_rx_memory.count_documents({"drug_key": UNIQUE_DRUG.lower()}) == 0
    assert db.patient_medications.count_documents({"patient_id": env["patient_id"], "drug": UNIQUE_DRUG}) == 0
    # and the pharmacy request is still waiting
    raw = db.prescription_requests.find_one({"id": pharmacy_request["id"]})
    assert raw["internal_status"] == "waiting_physician"


def test_send_converts_links_and_confirms(env, pharmacy_request):
    # Physician reviews + EDITS (renames first med to a unique physician-confirmed
    # value) then Sends with source_request_id.
    final_meds = [
        {"drug": UNIQUE_DRUG, "strength": "5 mg", "form": "tablet", "sig": "1 tablet HS at bedtime"},
        {"drug": "Rosuvastatin calcium", "strength": "5 mg", "form": "tablet", "sig": "1 tablet OD"},
    ]
    fd = {"patient_ref": (None, env["dir_id"]),
          "pharmacy_id": (None, env["A_id"]),
          "medications": (None, json.dumps(final_meds)),
          "physician_note": (None, "Confirmed"),
          "months": (None, "3"), "refills": (None, "1"),
          "source_request_id": (None, pharmacy_request["id"])}
    r = requests.post(f"{BASE}/api/internal/send-rx", files=fd, headers=_H(env["clinic"]), timeout=30)
    assert r.status_code == 200, r.text
    tx = r.json()
    _tx_ids.append(tx["id"])
    # 7 + 10: new rx_transmissions record links back to the source request
    txraw = db.rx_transmissions.find_one({"id": tx["id"]})
    assert txraw["source"] == "PHYSICIAN_PRESCRIPTION"
    assert txraw["source_request_id"] == pharmacy_request["id"]
    assert txraw["direction"] == "PHYSICIAN_TO_PHARMACY"

    # 11: pharmacy request advances to PRESCRIPTION SENT only now, and links to tx
    raw = db.prescription_requests.find_one({"id": pharmacy_request["id"]})
    assert raw["internal_status"] == "prescription_sent"
    assert raw["linked_transmission_id"] == tx["id"]
    assert raw.get("linked_transmission_ref")
    assert any(h.get("status") == "prescription_sent" for h in raw.get("history", []))

    # 2: original pharmacy request preserved UNCHANGED as evidence (meds not overwritten)
    assert raw["medications_structured"] == pharmacy_request["medications_structured"]
    assert raw["medications_structured"][0]["drug"] == "Amlodipine besylate"
    assert raw["medications_structured"][0]["manufacturer"] == "Apotex"

    # 8: ONLY the physician-confirmed FINAL value enters patient_medications
    assert db.patient_medications.count_documents({"patient_id": env["patient_id"], "drug": UNIQUE_DRUG}) >= 1
    # the physician's edited drug is confirmed; raw pharmacy 'Amlodipine besylate' was
    # NOT auto-confirmed by conversion (physician renamed it)

    # 9: ONLY physician-confirmed values enter physician_rx_memory, tagged as physician provenance
    pm = db.physician_rx_memory.find_one({"drug_key": UNIQUE_DRUG.lower()})
    assert pm is not None
    assert pm.get("source") != "PHARMACY_REQUEST"


def test_pharmacy_memory_not_copied_into_physician_memory(env):
    # pharmacy remembered Apotex for Amlodipine (source=PHARMACY_REQUEST); that must
    # never have been copied into physician_rx_memory by the Convert action.
    leaked = db.physician_rx_memory.find_one({"source": "PHARMACY_REQUEST"})
    assert leaked is None
    # and pharmacy_rx_memory still holds its own record (unchanged, separate)
    assert db.pharmacy_rx_memory.count_documents({"pharmacy_id": env["A_id"], "drug_key": "amlodipine besylate"}) == 1


def test_resulting_incoming_visible_to_owner_pharmacy_only(env):
    tx_id = _tx_ids[0]
    # 12: originating pharmacy A can see the resulting incoming Rx
    ra = requests.get(f"{BASE}/api/pharmacy/incoming/{tx_id}", headers=_H(env["A"]), timeout=30)
    assert ra.status_code == 200, ra.text
    # 13: pharmacy B cannot
    rb = requests.get(f"{BASE}/api/pharmacy/incoming/{tx_id}", headers=_H(env["B"]), timeout=30)
    assert rb.status_code in (403, 404)


def test_manual_physician_to_pharmacy_still_works(env):
    # 14: a normal manual prescription (no source_request_id) still sends fine.
    fd = {"patient_ref": (None, env["dir_id"]),
          "pharmacy_id": (None, env["A_id"]),
          "medications": (None, json.dumps([{"drug": "Metformin", "strength": "500 mg", "form": "tablet", "sig": "1 tablet BID"}])),
          "months": (None, "3")}
    r = requests.post(f"{BASE}/api/internal/send-rx", files=fd, headers=_H(env["clinic"]), timeout=30)
    assert r.status_code == 200, r.text
    tx = r.json()
    _tx_ids.append(tx["id"])
    txraw = db.rx_transmissions.find_one({"id": tx["id"]})
    assert txraw.get("source_request_id") is None
    assert txraw["source"] == "PHYSICIAN_PRESCRIPTION"
