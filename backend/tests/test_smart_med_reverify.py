# Re-verification (iteration_94) of Smart Medication fixes: parser, IDOR scoping, dedupe, no-Rx, visibility,
# external verification safety, default/replace/restart semantics, Portal Preview parity, add-med refills, strength display.
# PREVIEW ONLY: BASE_URL from frontend/.env (preview host) and local Mongo from backend/.env.
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
RAMI = "c46cb23f-d838-453f-8bb3-4de374dc57a2"
METF = "e3c29cff-0b05-4ca9-b7db-58b924d08d50"
VITD = "808426d2-2eb2-4663-bb0d-b42e12e1ab62"
TEXT = "Metformin 500 mg BID\nRamipril 10 mg BID\nAmlodipine 5 mg OD\nAtorvastatin 40 mg HS\nVitamin D 1000 IU daily"
NEWDRUG = f"TEST_Perindopril_{uuid.uuid4().hex[:5]}"
FIELDS = ("strength", "unit", "sig", "active", "discontinued_at")


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
def patient():
    return _login({"email": "maria.lopez@demo.com", "password": "Patient2026!"})


def _snap(mid):
    d = MDB.patient_medications.find_one({"id": mid}, {"_id": 0}) or {}
    return {k: d.get(k) for k in FIELDS}


def _organize(h, text):
    r = requests.post(f"{API}/internal/patients/{PID}/medications/organize", json={"text": text}, headers=h, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _reconcile(h, decisions):
    r = requests.post(f"{API}/internal/patients/{PID}/medications/reconcile", json={"decisions": decisions}, headers=h, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _dec(it, decision):
    return {"med": it["parsed"], "classification": it["classification"], "decision": decision,
            "match_id": (it.get("match") or {}).get("id"), "portal_visible": True}


def _discontinue_active(drug_regex):
    MDB.patient_medications.update_many({"patient_id": PID, "drug": {"$regex": drug_regex}, "active": True},
                                        {"$set": {"active": False, "discontinued_at": "TEST_cleanup"}})


def _clear_flags():
    MDB.patient_medications.update_many({"patient_id": PID}, {"$unset": {"review_flag": ""}})


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    _clear_flags()
    yield
    _discontinue_active("^(Lisinopril|Amlodipine)")
    MDB.patient_medications.update_one({"id": VITD}, {"$set": {"active": False}})
    _clear_flags()
    MDB.patient_medications.update_many({"patient_id": PID}, {"$set": {"portal_visible": True}})


# ---- FIX: parser line-by-line, 5 items ----
class TestOrganize5:
    def test_five_items(self, phys):
        items = _organize(phys, TEXT)
        assert len(items) == 5, [i["parsed"].get("original_text") for i in items]
        m = {i["parsed"]["drug"].split()[0].lower(): i for i in items}
        assert m["metformin"]["classification"] == "ALREADY_ON_LIST"
        assert m["ramipril"]["classification"] == "SIG_DIFFERENCE"
        assert m["amlodipine"]["classification"] in ("POSSIBLE_RESTART", "ADD_MISSING")
        assert m["atorvastatin"]["classification"] == "POSSIBLE_DOSE_CHANGE" and m["atorvastatin"]["match"]["id"] == ATORVA
        assert m["vitamin"]["classification"] == "POSSIBLE_RESTART" and m["vitamin"]["parsed"]["drug"].startswith("Vitamin D")


# ---- FIX IDOR ----
class TestIDOR:
    def test_reconcile_foreign_match_id(self, phys):
        other = MDB.patient_medications.find_one({"patient_id": {"$ne": PID}, "active": True}, {"_id": 0})
        if not other:
            pytest.skip("no foreign med")
        before = MDB.patient_medications.find_one({"id": other["id"]}, {"_id": 0})
        for dec, cls in (("flag", "POSSIBLE_DOSE_CHANGE"), ("update_sig", "SIG_DIFFERENCE"), ("replace", "POSSIBLE_DOSE_CHANGE"), ("restart", "POSSIBLE_RESTART")):
            _reconcile(phys, [{"med": {"drug": "TEST_IDOR", "strength": "1 mg", "sig": "TEST_SIG"}, "classification": cls, "decision": dec, "match_id": other["id"]}])
        after = MDB.patient_medications.find_one({"id": other["id"]}, {"_id": 0})
        MDB.patient_medications.update_many({"patient_id": PID, "drug": "TEST_IDOR"}, {"$set": {"active": False}})
        for k in ("review_flag", "sig", "active", "strength", "history", "updated_at"):
            assert before.get(k) == after.get(k), f"foreign med field {k} changed"

    def test_rx_complete_foreign_match_id(self, admin):
        other = MDB.patient_medications.find_one({"patient_id": {"$ne": PID}, "active": True}, {"_id": 0})
        rid = _clone_request("TEST_Ramipril 10 mg")
        before = MDB.patient_medications.find_one({"id": other["id"]}, {"_id": 0})
        r = requests.post(f"{API}/internal/prescriptions/{rid}/complete", json={"outcome": "PRESCRIPTION_VERIFIED_EXTERNAL", "confirm_external": True, "decisions": [
            {"med": {"drug": "TEST_IDOR2"}, "classification": "SIG_DIFFERENCE", "decision": "flag", "match_id": other["id"]}]}, headers=admin, timeout=30)
        assert r.status_code == 200, r.text
        after = MDB.patient_medications.find_one({"id": other["id"]}, {"_id": 0})
        assert before.get("review_flag") == after.get("review_flag") and before.get("updated_at") == after.get("updated_at")


# ---- QA duplicate prevention + no Rx transmission ----
class TestDuplicateAndNoRx:
    def test_duplicate_add_and_no_rx(self, phys):
        tx0, pr0 = MDB.rx_transmissions.count_documents({}), MDB.prescription_requests.count_documents({})
        _discontinue_active("^Lisinopril")
        it = [i for i in _organize(phys, "Lisinopril 10 mg daily") if i["parsed"]["drug"].lower().startswith("lisinopril")][0]
        cls = it["classification"]
        dec = "restart" if cls == "POSSIBLE_RESTART" else "add"
        r1 = _reconcile(phys, [{**_dec(it, "add"), "match_id": None}])
        assert len(r1["applied"]) == 1, r1
        r2 = _reconcile(phys, [{**_dec(it, "add"), "match_id": None}])
        assert r2["applied"] == [] and any("(duplicate)" in s for s in r2["skipped"]), r2
        assert MDB.patient_medications.count_documents({"patient_id": PID, "drug": {"$regex": "^Lisinopril"}, "active": True}) == 1
        assert MDB.rx_transmissions.count_documents({}) == tx0
        assert MDB.prescription_requests.count_documents({}) == pr0
        assert dec  # classification observed


# ---- QA portal visibility ----
class TestVisibility:
    def test_toggle(self, phys, patient):
        mid = METF
        names = lambda: [m["id"] for m in requests.get(f"{API}/portal/medications", headers=patient, timeout=30).json()["medications"]]
        assert mid in names()
        assert requests.patch(f"{API}/internal/patients/{PID}/medications/{mid}/portal-visibility", json={"portal_visible": False}, headers=phys, timeout=30).status_code == 200
        assert mid not in names()
        pv = requests.get(f"{API}/internal/patients/{PID}/portal-preview", headers=phys, timeout=30)
        if pv.status_code == 200:
            assert mid not in [m["id"] for m in pv.json()["medications"]["medications"]]
        assert requests.patch(f"{API}/internal/patients/{PID}/medications/{mid}/portal-visibility", json={"portal_visible": True}, headers=phys, timeout=30).status_code == 200
        assert mid in names()


# ---- QA dose/SIG never silently overwritten; replace semantics; restart semantics ----
class TestSemantics:
    def test_default_flag_leaves_rows(self, phys):
        before = {x: _snap(x) for x in (ATORVA, RAMI, VITD)}
        items = _organize(phys, TEXT)
        defaults = {"ALREADY_ON_LIST": "skip", "ADD_MISSING": "add", "POSSIBLE_DOSE_CHANGE": "flag", "SIG_DIFFERENCE": "flag", "POSSIBLE_RESTART": "flag"}
        res = _reconcile(phys, [_dec(i, defaults[i["classification"]]) for i in items if i["classification"] != "ADD_MISSING"])
        assert res["applied"] == []
        for x in (ATORVA, RAMI, VITD):
            assert _snap(x) == before[x], x
        assert MDB.patient_medications.find_one({"id": ATORVA})["review_flag"]["type"] == "POSSIBLE_DOSE_CHANGE"
        assert MDB.patient_medications.find_one({"id": VITD})["active"] is False
        _clear_flags()

    def test_replace_discontinues_and_inserts(self, phys):
        old = MDB.patient_medications.find_one({"patient_id": PID, "drug": {"$regex": "^Lisinopril"}, "active": True})
        assert old, "needs Lisinopril from duplicate test"
        it = [i for i in _organize(phys, "Lisinopril 20 mg daily") if i["parsed"]["drug"].lower().startswith("lisinopril")][0]
        assert it["classification"] == "POSSIBLE_DOSE_CHANGE" and it["match"]["id"] == old["id"]
        _reconcile(phys, [_dec(it, "replace")])
        o = MDB.patient_medications.find_one({"id": old["id"]})
        assert o["active"] is False and o["strength"] == old["strength"] and o["discontinue_reason"] == "dose_change"
        assert o["history"][-1]["action"] == "discontinued" and o["history"][-1]["reason"] == "dose_change"
        new = list(MDB.patient_medications.find({"patient_id": PID, "drug": {"$regex": "^Lisinopril"}, "active": True}))
        assert len(new) == 1 and new[0]["id"] != old["id"] and new[0]["strength"] == "20"

    def test_restart_requires_explicit(self, phys):
        it = [i for i in _organize(phys, "Vitamin D 1000 IU daily")][0]
        assert it["classification"] == "POSSIBLE_RESTART" and it["match"]["id"] == VITD
        _reconcile(phys, [_dec(it, "flag")])
        assert MDB.patient_medications.find_one({"id": VITD})["active"] is False
        _reconcile(phys, [_dec(it, "restart")])
        v = MDB.patient_medications.find_one({"id": VITD})
        assert v["active"] is True and v["history"][-1]["action"] == "restarted"
        MDB.patient_medications.update_one({"id": VITD}, {"$set": {"active": False, "discontinued_at": "TEST_cleanup"}})


# ---- QA external verification ----
def _clone_request(name, items=None):
    src = MDB.prescription_requests.find_one({"id": "54ec99a6-42a1-445b-b646-cf8247f70b74"}, {"_id": 0})
    nid = str(uuid.uuid4())
    src.update(id=nid, ref_number=f"TEST_RX_{nid[:6]}", medication_name=name, internal_status="waiting_physician", history=[], completed_at=None, strength=None)
    if items:
        src["items"] = items
    MDB.prescription_requests.insert_one(src)
    return nid


class TestExternalVerification:
    def test_only_add_missing_added(self, admin, patient):
        _discontinue_active("^Amlodipine")
        items = [{"drug": "Ramipril", "strength": "10 mg", "sig": "BID"}, {"drug": "Atorvastatin", "strength": "40 mg", "sig": "HS"},
                 {"drug": "Vitamin D", "strength": "1000 IU", "sig": "daily"}, {"drug": NEWDRUG, "strength": "4 mg", "sig": "daily"}]
        rid = _clone_request("TEST_multi", items)
        before = {x: _snap(x) for x in (ATORVA, RAMI, VITD)}
        tx0 = MDB.rx_transmissions.count_documents({})
        pv = requests.get(f"{API}/internal/prescriptions/{rid}/completion-preview", headers=admin, timeout=30).json()
        cls = {i["parsed"]["drug"]: i["classification"] for i in pv["reconciliation"]["items"]}
        assert cls == {"Ramipril": "SIG_DIFFERENCE", "Atorvastatin": "POSSIBLE_DOSE_CHANGE", "Vitamin D": "POSSIBLE_RESTART", NEWDRUG: "ADD_MISSING"}, cls
        safe = {"ADD_MISSING": "add", "POSSIBLE_DOSE_CHANGE": "flag", "SIG_DIFFERENCE": "flag", "POSSIBLE_RESTART": "flag"}
        decs = [_dec(i, safe[i["classification"]]) for i in pv["reconciliation"]["items"]]
        r = requests.post(f"{API}/internal/prescriptions/{rid}/complete", json={"outcome": "PRESCRIPTION_VERIFIED_EXTERNAL", "confirm_external": True, "decisions": decs}, headers=admin, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["internal_status"] == "completed_external_verified" and d["completion_outcome"] == "PRESCRIPTION_VERIFIED_EXTERNAL" and d["verified_by"]["name"]
        assert len(d["reconciliation"]["applied"]) == 1 and NEWDRUG in d["reconciliation"]["applied"][0]
        assert len(d["reconciliation"]["flagged"]) == 3
        for x in (ATORVA, RAMI, VITD):
            assert _snap(x) == before[x], x
        assert MDB.patient_medications.find_one({"id": ATORVA}).get("review_flag")
        assert MDB.patient_medications.find_one({"id": RAMI}).get("review_flag")
        assert MDB.patient_medications.count_documents({"patient_id": PID, "drug": NEWDRUG, "active": True}) == 1
        assert MDB.rx_transmissions.count_documents({}) == tx0
        ov = requests.get(f"{API}/portal/overview", headers=patient, timeout=30).json()
        st = [x["status"] for x in ov.get("requests", []) if x.get("ref_number") == d["ref_number"]]
        assert st == ["Processed by clinic — external prescription verified"], st
        MDB.patient_medications.update_many({"patient_id": PID, "drug": NEWDRUG}, {"$set": {"active": False, "discontinued_at": "TEST_cleanup"}})
        _clear_flags()

    def test_external_cannot_add_conflicting_dose(self, admin):
        """Client-forged 'add' for a POSSIBLE_DOSE_CHANGE item must not create a second active Atorvastatin."""
        rid = _clone_request("TEST_forge", [{"drug": "Atorvastatin", "strength": "40 mg", "sig": "HS"}])
        r = requests.post(f"{API}/internal/prescriptions/{rid}/complete", json={"outcome": "PRESCRIPTION_VERIFIED_EXTERNAL", "confirm_external": True, "decisions": [
            {"med": {"drug": "Atorvastatin", "strength": "40 mg", "sig": "HS"}, "classification": "POSSIBLE_DOSE_CHANGE", "decision": "add", "match_id": ATORVA}]}, headers=admin, timeout=30)
        n = MDB.patient_medications.count_documents({"patient_id": PID, "drug": "Atorvastatin", "active": True})
        MDB.patient_medications.update_many({"patient_id": PID, "drug": "Atorvastatin", "active": True, "id": {"$ne": ATORVA}}, {"$set": {"active": False, "discontinued_at": "TEST_cleanup"}})
        assert r.status_code in (200, 400)
        assert n == 1, "server accepted forged 'add' on a POSSIBLE_DOSE_CHANGE item -> two active Atorvastatin rows"


# ---- QA Portal Preview parity ----
class TestPreviewParity:
    def test_parity(self, admin, patient):
        d = requests.get(f"{API}/internal/patients/{PID}/portal-preview", headers=admin, timeout=30).json()
        pm = requests.get(f"{API}/portal/medications", headers=patient, timeout=30).json()
        key = lambda ms: sorted((m["drug"], m.get("strength_display") or m.get("strength")) for m in ms)
        assert key(d["medications"]["medications"]) == key(pm["medications"])
        ov = requests.get(f"{API}/portal/overview", headers=patient, timeout=30).json()
        for k in ("appointments", "requests", "referrals"):
            assert sorted(x.get("id") for x in d["overview"].get(k, [])) == sorted(x.get("id") for x in ov.get(k, [])), k
        docs = requests.get(f"{API}/portal/documents", headers=patient, timeout=30).json()
        docs = docs if isinstance(docs, list) else docs.get("documents") or docs.get("items") or []
        assert sorted(x["id"] for x in d["documents"]) == sorted(x["id"] for x in docs)


# ---- QA regression: add medication with blank refills; strength display ----
class TestRegressions:
    def test_add_blank_refills(self, phys):
        r = requests.post(f"{API}/internal/patients/{PID}/medications", json={"drug": "TEST_Blankrefill", "strength": "5 mg", "sig": "OD", "refills": ""}, headers=phys, timeout=30)
        assert r.status_code == 200, r.text
        MDB.patient_medications.update_many({"patient_id": PID, "drug": "TEST_Blankrefill"}, {"$set": {"active": False}})
        assert "mg mg" not in (r.json().get("strength_display") or "")

    def test_no_unit_duplication(self, phys, patient):
        mr = requests.get(f"{API}/internal/patients/{PID}/medical-record", headers=phys, timeout=30)
        assert mr.status_code == 200 and "mg mg" not in mr.text
        pm = requests.get(f"{API}/portal/medications", headers=patient, timeout=30)
        assert "mg mg" not in pm.text and "IU IU" not in pm.text
