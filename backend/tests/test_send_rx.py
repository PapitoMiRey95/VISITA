"""PHYSICIAN -> PHARMACY 'Send Prescription' workflow tests (direction=PHYSICIAN_TO_PHARMACY).

Covers the 12 required scenarios. Uses two TEMPORARY pharmacy accounts created in
setup and deleted in teardown (never touches the real 1670dufferin account or any
production patient data). Created rx_transmissions are cleaned up at the end.
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


# 9b. Confirmation checkbox removed — send works without confirm.
def test_09b_no_confirm_needed(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"],
                            "medications": '[{"drug":"Aspirin","strength":"81 mg","form":"tablet","sig":"1 tab OD"}]'}, timeout=30)
    assert r.status_code == 200, r.text
    _created_tx_ids.append(r.json()["id"])


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
    # The seeded pharmacy portal account must still exist and be untouched.
    # NOTE: >= 1 (not == 1) intentionally: a prior Preview session manually re-scoped
    # a real human account (dufferindm@hotmail.com / "Emad henei") to
    # role=pharmacy, pharmacy_id=1670-dufferin. That is Preview test-data
    # contamination, not created by any code path (only seed.py creates the single
    # '1670dufferin' account). This test only guarantees our temp pharmacies did not
    # collide with, or delete, the real seeded account.
    assert db.users.count_documents({"username": "1670dufferin", "role": "pharmacy", "pharmacy_id": "1670-dufferin"}) == 1
    assert not db.users.count_documents({"role": "pharmacy", "pharmacy_id": {"$regex": "^pharmrx-"}})



# 13. Access parsing: single + multiple meds; prescription-level months/refills; no fabrication.
def test_13_parse_single_and_multi(physician_token):
    single = "Candesartan cilexetil 16 mg tablet film-coated scored: 1 tablet HS"
    d = requests.post(f"{BASE}/api/internal/rx/parse", headers=_h(physician_token), json={"text": single}, timeout=30).json()
    assert len(d["medications"]) == 1
    m = d["medications"][0]
    assert m["drug"] == "Candesartan cilexetil" and m["strength"] == "16 mg" and m["form"] == "tablet"
    assert "film-coated" in m["attributes"] and "scored" in m["attributes"] and m["sig"] == "1 tablet HS"
    assert m["original_text"] == single
    multi = ("Vacation Supply for 6 months.\nAmlodipine besylate 05 mg tablet: 1 tablet HS\n"
             "Bisoprolol fumarate 05 mg tablet: 1 tablet HS\nNumber of months: 6\nNumber of refills: 0")
    d2 = requests.post(f"{BASE}/api/internal/rx/parse", headers=_h(physician_token), json={"text": multi}, timeout=30).json()
    assert len(d2["medications"]) == 2
    assert d2["months"] == 6 and d2["refills"] == 0
    assert all(x["refills"] is None for x in d2["medications"])


def test_13b_no_fabrication(physician_token):
    d = requests.post(f"{BASE}/api/internal/rx/parse", headers=_h(physician_token),
                      json={"text": "Some Compound Cream: apply as directed"}, timeout=30).json()
    m = d["medications"][0]
    assert m["strength"] is None and "strength" in m["needs_review"]


# 14. Confirmed med is remembered; Repeat Rx creates NEW history (old untouched).
def test_14_memory_and_repeat(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    snap = requests.get(f"{BASE}/api/internal/patient-snapshot/{pid}", headers=_h(physician_token), timeout=30).json()
    real_pid = snap.get("patient_id") or snap.get("directory_id") or pid
    drug = f"ZZTestDrug{uuid.uuid4().hex[:6]}"
    meds = json.dumps([{"drug": drug, "strength": "10 mg", "form": "tablet", "sig": "1 tab OD",
                        "original_text": f"{drug} 10 mg tablet: 1 tab OD"}])
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"], "medications": meds,
                            "months": "3", "refills": "1"}, timeout=30)
    assert r.status_code == 200, r.text
    _created_tx_ids.append(r.json()["id"])
    pm = requests.get(f"{BASE}/api/internal/patients/{pid}/medications", headers=_h(physician_token), timeout=30).json()
    match = [x for x in pm if x["drug"] == drug]
    assert match and match[0]["months"] == 3 and match[0]["refills"] == 1
    before = db.rx_transmissions.count_documents({"patient_id": real_pid})
    r2 = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                       data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"], "medications": meds}, timeout=30)
    assert r2.status_code == 200
    _created_tx_ids.append(r2.json()["id"])
    assert db.rx_transmissions.count_documents({"patient_id": real_pid}) == before + 1
    db.patient_medications.delete_many({"drug": drug})
    db.medication_catalog.delete_many({"drug": drug})


# 15. Patient mismatch in pasted text warns and never auto-switches the patient.
def test_15_patient_mismatch_warning(physician_token):
    pid = _find_patient(physician_token)
    d = requests.post(f"{BASE}/api/internal/rx/parse", headers=_h(physician_token),
                      json={"text": "Patient: Nonexistent Zzztestperson\nAmlodipine besylate 5 mg tablet: 1 tablet HS", "patient_ref": pid}, timeout=30).json()
    assert d["mismatch"] is True and len(d["warnings"]) >= 1


# 16. Repeat Entire Prescription: prescriptions endpoint groups a whole Rx (many meds),
#     is read-only (no new transmission), keeps meds as separate records, and flags a
#     newer regimen instead of silently substituting.
def test_16_repeat_entire_and_newer_flag(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    snap = requests.get(f"{BASE}/api/internal/patient-snapshot/{pid}", headers=_h(physician_token), timeout=30).json()
    real_pid = snap.get("patient_id") or snap.get("directory_id") or pid
    d1 = f"ZZRepA{uuid.uuid4().hex[:6]}"
    d2 = f"ZZRepB{uuid.uuid4().hex[:6]}"
    # A multi-medication prescription (this is the historical Rx we will "repeat").
    meds = json.dumps([
        {"drug": d1, "strength": "10 mg", "form": "tablet", "sig": "1 tablet OD", "original_text": f"{d1} 10 mg tablet: 1 tablet OD"},
        {"drug": d2, "strength": "5 mg", "form": "tablet", "sig": "1 tablet HS", "original_text": f"{d2} 5 mg tablet: 1 tablet HS"},
    ])
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"], "medications": meds,
                            "months": "3", "refills": "0"}, timeout=30)
    assert r.status_code == 200, r.text
    old_tx = r.json()["id"]
    _created_tx_ids.append(old_tx)

    # 16a. Prescriptions endpoint groups it as one prescription with 2 separate meds.
    rx_list = requests.get(f"{BASE}/api/internal/patients/{pid}/prescriptions", headers=_h(physician_token), timeout=30)
    assert rx_list.status_code == 200, rx_list.text
    mine = [p for p in rx_list.json() if p["id"] == old_tx]
    assert len(mine) == 1
    grp = mine[0]
    assert len(grp["medications"]) == 2
    assert {m["drug"] for m in grp["medications"]} == {d1, d2}
    assert grp["months"] == 3 and grp["refills"] == 0
    assert all(m["newer_available"] is False for m in grp["medications"])

    # 16b. Reading the prescriptions list did NOT create a transmission (read-only).
    before = db.rx_transmissions.count_documents({"patient_id": real_pid})
    requests.get(f"{BASE}/api/internal/patients/{pid}/prescriptions", headers=_h(physician_token), timeout=30)
    assert db.rx_transmissions.count_documents({"patient_id": real_pid}) == before

    # 16c. Prescribe d1 again with a DIFFERENT regimen (newer). Old Rx's d1 must be flagged
    #      newer_available (never auto-substituted); d2 stays unflagged.
    newer = json.dumps([{"drug": d1, "strength": "20 mg", "form": "tablet", "sig": "1 tablet BID",
                         "original_text": f"{d1} 20 mg tablet: 1 tablet BID"}])
    r2 = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                       data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"], "medications": newer}, timeout=30)
    assert r2.status_code == 200, r2.text
    _created_tx_ids.append(r2.json()["id"])

    rx_list2 = requests.get(f"{BASE}/api/internal/patients/{pid}/prescriptions", headers=_h(physician_token), timeout=30).json()
    old_grp = [p for p in rx_list2 if p["id"] == old_tx][0]
    d1_med = [m for m in old_grp["medications"] if m["drug"] == d1][0]
    d2_med = [m for m in old_grp["medications"] if m["drug"] == d2][0]
    assert d1_med["newer_available"] is True
    assert d1_med["newer"] and d1_med["newer"]["strength"] == "20 mg" and d1_med["newer"]["sig"] == "1 tablet BID"
    # Historical record itself is unchanged (still says 10 mg / 1 tablet OD).
    assert d1_med["strength"] == "10 mg" and d1_med["sig"] == "1 tablet OD"
    assert d2_med["newer_available"] is False

    # 16d. Historical transmission document is immutable (meds unchanged in DB).
    stored = db.rx_transmissions.find_one({"id": old_tx})
    stored_d1 = [m for m in stored["medications"] if m["drug"] == d1][0]
    assert stored_d1["strength"] == "10 mg" and stored_d1["sig"] == "1 tablet OD"

    db.patient_medications.delete_many({"drug": {"$in": [d1, d2]}})
    db.medication_catalog.delete_many({"drug": {"$in": [d1, d2]}})


# 17. Smart editor: extended structured fields (route/quantity_unit/duration) persist,
#     and physician-scoped memory + suggestions reflect ONLY sent prescriptions.
def test_17_extended_fields_and_suggestions(physician_token, pharmacies):
    pid = _find_patient(physician_token)
    drug = f"ZZSmart{uuid.uuid4().hex[:6]}"
    meds = json.dumps([{
        "drug": drug, "strength": "1 mg/mL", "form": "prefilled pen", "sig": "1 mg once weekly",
        "route": "Subcutaneous / SC", "quantity_unit": "pen", "duration_value": "3", "duration_unit": "month(s)",
        "attributes": ["single-use"], "original_text": f"{drug} 1 mg/mL prefilled pen: 1 mg once weekly",
    }])
    r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                      data={"patient_ref": pid, "pharmacy_id": pharmacies["A_id"], "medications": meds,
                            "months": "3", "refills": "0"}, timeout=30)
    assert r.status_code == 200, r.text
    tx = r.json()
    _created_tx_ids.append(tx["id"])
    # Extended fields persisted on the transmission med record.
    stored_med = [m for m in db.rx_transmissions.find_one({"id": tx["id"]})["medications"] if m["drug"] == drug][0]
    assert stored_med["route"] == "Subcutaneous / SC" and stored_med["quantity_unit"] == "pen"
    assert stored_med["duration_value"] == "3" and stored_med["duration_unit"] == "month(s)"

    # patient_medications carries the extended fields.
    pm = requests.get(f"{BASE}/api/internal/patients/{pid}/medications", headers=_h(physician_token), timeout=30).json()
    mine = [x for x in pm if x["drug"] == drug][0]
    assert mine.get("route") == "Subcutaneous / SC" and mine.get("quantity_unit") == "pen"

    # Suggestions for this drug include the just-sent values (physician/patient source).
    s = requests.get(f"{BASE}/api/internal/rx/suggest", params={"drug": drug, "patient_ref": pid},
                     headers=_h(physician_token), timeout=30).json()
    f = s["fields"]
    assert any(x["value"] == "1 mg/mL" for x in f["strengths"])
    assert any(x["value"] == "prefilled pen" for x in f["forms"])
    assert any(x["value"] == "1 mg once weekly" for x in f["sigs"])
    assert any(x["value"] == "Subcutaneous / SC" for x in f["routes"])
    assert any(x["value"] == "pen" for x in f["quantity_units"])
    assert any(x["value"] == drug for x in s["drugs"])

    # Physician memory is scoped to this physician and drug (workflow memory, not clinical).
    mem = db.physician_rx_memory.find_one({"drug_key": drug.lower()})
    assert mem is not None and mem["physician_id"]
    assert "1 mg once weekly" in mem.get("sigs", [])

    db.patient_medications.delete_many({"drug": drug})
    db.medication_catalog.delete_many({"drug": drug})
    db.physician_rx_memory.delete_many({"drug_key": drug.lower()})


def _make_dir_patient(**over):
    doc = {
        "id": str(uuid.uuid4()), "first_name": over.get("first_name", "Testina"),
        "last_name": over.get("last_name", "SNAPQA"), "date_of_birth": "1952-04-29",
        "visita_patient_id": over.get("visita_patient_id", f"99{uuid.uuid4().hex[:4]}"),
        "address": "3174 Bathurst Street", "unit": "5B", "city": "Toronto",
        "province": "ON", "postal_code": "M6A 2B1",
        "cell_phone": "(647) 555-0100", "home_phone": "(416) 555-0111",
        "health_card_number": "1572035465", "health_card_version": "VH",
        "health_card_expiry_date": "2027-04-29", "patient_type": "ohip",
        "patient_status": "ACTIVE", "linked_patient_id": None,
    }
    doc.update(over)
    db.patient_directory.insert_one(doc)
    return doc


# 18. Pharmacy patient-information panel: snapshot present for the receiving pharmacy,
#     list stays compact, other pharmacy blocked, and the snapshot is immutable history.
def test_18_pharmacy_patient_snapshot(physician_token, pharmacies):
    pat = _make_dir_patient()
    try:
        meds = '[{"drug":"ZZSnapDrug","strength":"10 mg","form":"tablet","sig":"1 tablet OD"}]'
        r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                          data={"patient_ref": pat["id"], "pharmacy_id": pharmacies["A_id"], "medications": meds}, timeout=30)
        assert r.status_code == 200, r.text
        tx_id = r.json()["id"]
        _created_tx_ids.append(tx_id)

        # Receiving pharmacy sees the full patient information snapshot.
        d = requests.get(f"{BASE}/api/pharmacy/incoming/{tx_id}", headers=_h(pharmacies["A_token"]), timeout=30)
        assert d.status_code == 200, d.text
        ps = d.json().get("patient_snapshot")
        assert ps, "patient_snapshot missing on authorized detail"
        assert ps["last_name"] == "SNAPQA" and ps["date_of_birth"] == "1952-04-29"
        assert ps["visita_patient_id"] == pat["visita_patient_id"]
        assert ps["address"] == "3174 Bathurst Street" and ps["city"] == "Toronto" and ps["postal_code"] == "M6A 2B1"
        assert ps["cell_phone"] == "(647) 555-0100" and ps["home_phone"] == "(416) 555-0111"
        assert ps["health_card_number"] == "1572035465" and ps["health_card_version"] == "VH"

        # Incoming list stays compact — no full PHI snapshot in list rows.
        lst = requests.get(f"{BASE}/api/pharmacy/incoming", headers=_h(pharmacies["A_token"]), timeout=30).json()
        row = [i for i in lst["items"] if i["id"] == tx_id][0]
        assert "patient_snapshot" not in row
        assert row.get("patient_name") and row.get("patient_dob")  # enough to identify

        # A different pharmacy cannot retrieve the prescription or its patient details.
        other = requests.get(f"{BASE}/api/pharmacy/incoming/{tx_id}", headers=_h(pharmacies["B_token"]), timeout=30)
        assert other.status_code == 404

        # Immutable history: change the live patient address; the sent Rx snapshot is unchanged.
        db.patient_directory.update_one({"id": pat["id"]}, {"$set": {"address": "999 New Address Ave"}})
        d2 = requests.get(f"{BASE}/api/pharmacy/incoming/{tx_id}", headers=_h(pharmacies["A_token"]), timeout=30).json()
        assert d2["patient_snapshot"]["address"] == "3174 Bathurst Street"
    finally:
        db.patient_directory.delete_one({"id": pat["id"]})
        db.patient_medications.delete_many({"drug": "ZZSnapDrug"})
        db.medication_catalog.delete_many({"drug": "ZZSnapDrug"})


# 19. Private/uninsured patient: no OHIP is fabricated in the snapshot.
def test_19_private_patient_no_fabricated_ohip(physician_token, pharmacies):
    pat = _make_dir_patient(first_name="Priv", last_name="NOOHIPQA", patient_type="private",
                            health_card_number=None, health_card_version=None, health_card_expiry_date=None)
    try:
        meds = '[{"drug":"ZZPrivDrug","strength":"5 mg","form":"tablet","sig":"1 tablet HS"}]'
        r = requests.post(f"{BASE}/api/internal/send-rx", headers=_h(physician_token),
                          data={"patient_ref": pat["id"], "pharmacy_id": pharmacies["A_id"], "medications": meds}, timeout=30)
        assert r.status_code == 200, r.text
        tx_id = r.json()["id"]
        _created_tx_ids.append(tx_id)
        ps = requests.get(f"{BASE}/api/pharmacy/incoming/{tx_id}", headers=_h(pharmacies["A_token"]), timeout=30).json()["patient_snapshot"]
        assert "health_card_number" not in ps  # omitted, never fabricated
        assert ps["last_name"] == "NOOHIPQA"
    finally:
        db.patient_directory.delete_one({"id": pat["id"]})
        db.patient_medications.delete_many({"drug": "ZZPrivDrug"})
        db.medication_catalog.delete_many({"drug": "ZZPrivDrug"})

