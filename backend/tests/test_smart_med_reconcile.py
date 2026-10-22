# Smart Medication reconciliation (organize/reconcile/visibility), Rx completion outcomes, admin Portal Preview
import os
import uuid
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
PID = "06f6ee08-58f7-4286-82f5-7c845de99ce1"
MDB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ATORVA = "af0e53b7-dc14-4456-8172-55d7c1cedd0b"


def _login(body):
    r = requests.post(f"{API}/auth/login", json=body, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {body}: {r.status_code} {r.text[:200]}")
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def phys():
    return _login({"identifier": "PAGUAYO", "password": "Aguayo-Preview-2026#Tmp"})


@pytest.fixture(scope="module")
def admin():
    return _login({"email": "kevinrodriguez9528@gmail.com", "password": "VisitaAdmin2026!"})


@pytest.fixture(scope="module")
def staff():
    return _login({"email": "staff@visita.demo", "password": "Staff2026!"})


@pytest.fixture(scope="module")
def patient():
    return _login({"email": "maria.lopez@demo.com", "password": "Patient2026!"})


TEXT = "Metformin 500 mg BID\nRamipril 10 mg BID\nAmlodipine 5 mg OD\nAtorvastatin 40 mg HS\nVitamin D 1000 IU daily"


def _by_drug(items):
    return {i["parsed"]["drug"].split()[0].lower(): i for i in items}


# ---- organize ----
class TestOrganize:
    def test_classifications(self, phys):
        MDB.patient_medications.update_one({"id": ATORVA}, {"$unset": {"review_flag": ""}})
        r = requests.post(f"{API}/internal/patients/{PID}/medications/organize", json={"text": TEXT}, headers=phys, timeout=30)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 5
        m = _by_drug(items)
        assert m["metformin"]["classification"] == "ALREADY_ON_LIST"
        assert m["ramipril"]["classification"] == "SIG_DIFFERENCE"
        assert m["amlodipine"]["classification"] == "ADD_MISSING"
        assert m["atorvastatin"]["classification"] == "POSSIBLE_DOSE_CHANGE"
        assert m["vitamin"]["classification"] == "POSSIBLE_RESTART"
        for k, it in m.items():
            assert isinstance(it["summary"], str) and it["summary"]
            if k != "amlodipine":
                assert it["match"] and it["match"].get("id"), k
        assert m["atorvastatin"]["match"]["id"] == ATORVA

    def test_staff_forbidden(self, staff):
        r = requests.post(f"{API}/internal/patients/{PID}/medications/organize", json={"text": TEXT}, headers=staff, timeout=30)
        assert r.status_code == 403
        r = requests.post(f"{API}/internal/patients/{PID}/medications/reconcile", json={"decisions": []}, headers=staff, timeout=30)
        assert r.status_code == 403


# ---- reconcile + visibility ----
class TestReconcile:
    def test_reconcile_flow(self, phys, patient):
        org = requests.post(f"{API}/internal/patients/{PID}/medications/organize", json={"text": "Metformin 500 mg BID\nAmlodipine 5 mg OD\nAtorvastatin 40 mg HS"}, headers=phys, timeout=30).json()["items"]
        tx_before = MDB.rx_transmissions.count_documents({})
        decisions = []
        for it in org:
            d = it["parsed"]["drug"].lower()
            dec = "add" if d.startswith("amlodipine") else "flag" if d.startswith("atorvastatin") else "skip"
            decisions.append({"med": it["parsed"], "classification": it["classification"], "decision": dec,
                              "match_id": (it.get("match") or {}).get("id"), "portal_visible": True})
        r = requests.post(f"{API}/internal/patients/{PID}/medications/reconcile", json={"decisions": decisions}, headers=phys, timeout=30)
        assert r.status_code == 200, r.text
        res = r.json()
        assert len(res["applied"]) == 1 and len(res["flagged"]) == 1
        aml = [m for m in MDB.patient_medications.find({"patient_id": PID, "drug": {"$regex": "^Amlodipine"}, "active": True})]
        assert len(aml) == 1
        a = aml[0]
        assert a["source"] == "MEDICATION_RECONCILIATION" and a["history"][0]["action"] == "added"
        assert MDB.patient_medications.find_one({"id": ATORVA}).get("review_flag")
        assert MDB.rx_transmissions.count_documents({}) == tx_before
        assert MDB.audit_logs.find_one({"action": "medication_reconciliation_applied", "entity_id": PID}) or \
            MDB.audit_logs.find_one({"action": "medication_reconciliation_applied"})
        # medical record shows it
        mr = requests.get(f"{API}/internal/patients/{PID}/medical-record", headers=phys, timeout=30)
        assert mr.status_code == 200 and "Amlodipine" in mr.text
        # duplicate
        r2 = requests.post(f"{API}/internal/patients/{PID}/medications/reconcile", json={"decisions": [d for d in decisions if d["decision"] == "add"]}, headers=phys, timeout=30)
        assert r2.status_code == 200 and len(r2.json()["applied"]) == 0 and any("duplicate" in s for s in r2.json()["skipped"])
        assert MDB.patient_medications.count_documents({"patient_id": PID, "drug": {"$regex": "^Amlodipine"}, "active": True}) == 1
        # portal visibility
        mid = a["id"]
        names = lambda: [m.get("drug") for m in requests.get(f"{API}/portal/medications", headers=patient, timeout=30).json()["medications"]]
        assert any("Amlodipine" in (n or "") for n in names())
        v = requests.patch(f"{API}/internal/patients/{PID}/medications/{mid}/portal-visibility", json={"portal_visible": False}, headers=phys, timeout=30)
        assert v.status_code == 200 and v.json()["portal_visible"] is False
        assert not any("Amlodipine" in (n or "") for n in names())
        v = requests.patch(f"{API}/internal/patients/{PID}/medications/{mid}/portal-visibility", json={"portal_visible": True}, headers=phys, timeout=30)
        assert v.status_code == 200
        assert any("Amlodipine" in (n or "") for n in names())
        # cleanup
        c = requests.patch(f"{API}/internal/patients/{PID}/medications/{mid}", json={"action_type": "discontinue"}, headers=phys, timeout=30)
        assert c.status_code == 200, c.text
        MDB.patient_medications.update_one({"id": ATORVA}, {"$unset": {"review_flag": ""}})

    def test_flag_foreign_match_id_not_scoped(self, phys):
        """match_id is not scoped to the patient: flagging another patient's med succeeds (IDOR check)."""
        other = MDB.patient_medications.find_one({"patient_id": {"$ne": PID}, "active": True})
        if not other:
            pytest.skip("no foreign med")
        r = requests.post(f"{API}/internal/patients/{PID}/medications/reconcile", json={"decisions": [
            {"med": {"drug": "TEST_X"}, "classification": "POSSIBLE_DOSE_CHANGE", "decision": "flag", "match_id": other["id"]}]}, headers=phys, timeout=30)
        flagged = MDB.patient_medications.find_one({"id": other["id"]}).get("review_flag")
        MDB.patient_medications.update_one({"id": other["id"]}, {"$unset": {"review_flag": ""}} if not other.get("review_flag") else {"$set": {"review_flag": other["review_flag"]}})
        assert not (flagged and (flagged.get("pasted") or {}).get("drug") == "TEST_X"), "cross-patient med modified via match_id"


# ---- Rx completion outcomes ----
def _clone_request(name):
    src = MDB.prescription_requests.find_one({"id": "54ec99a6-42a1-445b-b646-cf8247f70b74"}, {"_id": 0})
    nid = str(uuid.uuid4())
    src.update(id=nid, ref_number=f"TEST_RX_{nid[:6]}", medication_name=name, internal_status="waiting_physician", history=[], completed_at=None, strength=None)
    MDB.prescription_requests.insert_one(src)
    return nid


class TestRxComplete:
    def test_verified_external(self, admin, patient):
        rid = _clone_request("TEST_Ramipril 10 mg")
        p = requests.get(f"{API}/internal/prescriptions/{rid}/completion-preview", headers=admin, timeout=30)
        assert p.status_code == 200, p.text
        pv = p.json()
        assert pv["vien_transmission"] is None and "PRESCRIPTION_VERIFIED_EXTERNAL" in pv["outcomes"]
        assert pv["reconciliation"]["items"]
        bad = requests.post(f"{API}/internal/prescriptions/{rid}/complete", json={"outcome": "PRESCRIPTION_SENT_VIEN"}, headers=admin, timeout=30)
        assert bad.status_code == 400
        nc = requests.post(f"{API}/internal/prescriptions/{rid}/complete", json={"outcome": "PRESCRIPTION_VERIFIED_EXTERNAL"}, headers=admin, timeout=30)
        assert nc.status_code == 400
        r = requests.post(f"{API}/internal/prescriptions/{rid}/complete", json={"outcome": "PRESCRIPTION_VERIFIED_EXTERNAL", "confirm_external": True, "decisions": []}, headers=admin, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["internal_status"] == "completed_external_verified" and d["completion_outcome"] == "PRESCRIPTION_VERIFIED_EXTERNAL"
        assert d["verified_by"]["name"] and d["reconciliation"] is not None
        ov = requests.get(f"{API}/portal/overview", headers=patient, timeout=30).json()
        reqs = [x for x in ov.get("requests", []) if x.get("id") == rid or x.get("ref_number") == d["ref_number"]]
        assert reqs and reqs[0]["status"] == "Processed by clinic — external prescription verified", reqs

    def test_no_prescription(self, admin):
        rid = _clone_request("TEST_Metformin 500 mg")
        r = requests.post(f"{API}/internal/prescriptions/{rid}/complete", json={"outcome": "NO_PRESCRIPTION_ISSUED", "note": "TEST"}, headers=admin, timeout=30)
        assert r.status_code == 200 and r.json()["internal_status"] == "completed_no_prescription"

    def test_unknown_outcome(self, admin):
        rid = _clone_request("TEST_Metformin 500 mg")
        r = requests.post(f"{API}/internal/prescriptions/{rid}/complete", json={"outcome": "BOGUS"}, headers=admin, timeout=30)
        assert r.status_code == 400


# ---- Portal preview ----
class TestPortalPreview:
    def test_preview_matches_portal(self, admin, patient):
        r = requests.get(f"{API}/internal/patients/{PID}/portal-preview", headers=admin, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["linked"] is True
        pm = requests.get(f"{API}/portal/medications", headers=patient, timeout=30).json()
        assert sorted(m["id"] for m in d["medications"]["medications"]) == sorted(m["id"] for m in pm["medications"])
        assert MDB.audit_logs.find_one({"action": "portal_preview_viewed"})

    def test_patient_forbidden(self, patient):
        r = requests.get(f"{API}/internal/patients/{PID}/portal-preview", headers=patient, timeout=30)
        assert r.status_code == 403

    def test_unlinked(self, admin):
        d = MDB.patient_directory.find_one({"$or": [{"linked_patient_id": None}, {"linked_patient_id": {"$exists": False}}], "practice_id": {"$exists": True}}, {"_id": 0, "id": 1})
        if not d:
            pytest.skip("no unlinked directory record")
        r = requests.get(f"{API}/internal/patients/{d['id']}/portal-preview", headers=admin, timeout=30)
        assert r.status_code == 200 and r.json()["linked"] is False
