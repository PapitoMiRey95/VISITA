# Patient Portal Rx Refill redesign — regression (B1-B11, R1-R2). Cleans up every QA record it creates.
import os
import uuid
import json
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _env("/app/frontend/.env", "REACT_APP_BACKEND_URL")).rstrip("/")
MONGO = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
CRON_SECRET = _env("/app/backend/.env", "WEBHOOK_CRON_SECRET")
MARIA_PID = "06f6ee08-58f7-4286-82f5-7c845de99ce1"
ROMERO_PID = "977ca75a-70bd-48ae-89eb-51e92bff46df"
ROMERO_DIR = "c5c30d56-acdd-416b-b61d-5cf8aab06a74"
CREATED = {"prescription_requests": [], "patient_medications": []}
LOG = "/app/test_reports/rx_refill_qa_created_ids.json"


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


@pytest.fixture(scope="module")
def pt():
    return _login("maria.lopez@demo.com", "Patient2026!")


@pytest.fixture(scope="module")
def admin():
    return _login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    notif_before = {d["id"] for d in MONGO.notifications.find({"title": "Refill reminder"}, {"id": 1})}
    rr_before = {d["key"] for d in MONGO.refill_reminders.find({}, {"key": 1})}
    yield
    MONGO.prescription_requests.delete_many({"id": {"$in": CREATED["prescription_requests"]}})
    MONGO.patient_medications.delete_many({"id": {"$in": CREATED["patient_medications"]}})
    new_n = [d["id"] for d in MONGO.notifications.find({"title": "Refill reminder"}, {"id": 1}) if d["id"] not in notif_before]
    MONGO.notifications.delete_many({"id": {"$in": new_n}})
    new_rr = [d["key"] for d in MONGO.refill_reminders.find({}, {"key": 1}) if d["key"] not in rr_before]
    MONGO.refill_reminders.delete_many({"key": {"$in": new_rr}})
    json.dump({**CREATED, "notifications_deleted": new_n, "refill_reminders_deleted": new_rr}, open(LOG, "w"), indent=1)


def _ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _temp_med(**kw):
    mid = "QA-" + str(uuid.uuid4())
    doc = {"id": mid, "patient_id": MARIA_PID, "drug": kw.pop("drug", "QA Drug " + mid[-6:]), "strength": "5 mg", "form": "tablet",
           "sig": "QA " + mid[-6:], "active": True, "source": "qa_temp", "regimen_key": "qa|" + mid, "history": [],
           "created_at": _ago(0), "updated_at": _ago(0), **kw}
    MONGO.patient_medications.insert_one(dict(doc))
    CREATED["patient_medications"].append(mid)
    return mid


def _meds_snapshot():
    return sorted((d["id"], d.get("active", True)) for d in MONGO.patient_medications.find({"patient_id": MARIA_PID}, {"id": 1, "active": 1}))


def _post_req(pt, payload):
    r = pt.post(f"{BASE_URL}/api/portal/rx-requests", json=payload, timeout=30)
    if r.status_code == 200:
        CREATED["prescription_requests"].append(r.json()["id"])
    return r


def _find(meds, name):
    return next(m for m in meds if (m["drug"] or "").lower().startswith(name.lower()))


# B1 portal medications shape + seeded due fields
def test_b1_portal_medications(pt):
    r = pt.get(f"{BASE_URL}/api/portal/medications")
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d["medications"], list) and isinstance(d["previously_prescribed"], list)
    assert d["clinic_phone"] == "(416) 652-7667"
    assert set(d["request_modes"]) == {"selected", "all_regular", "blister_pack", "medication_change"}
    for m in d["medications"]:
        for k in ("regular", "coverage_days", "due_on", "days_left", "likely_due"):
            assert k in m
    for n in ("Atorvastatin", "Ramipril", "Metformin"):
        m = _find(d["medications"], n)
        assert m["likely_due"] is False, m
    print({m["drug"]: (m["coverage_days"], m["due_on"], m["days_left"]) for m in d["medications"]})


# B2 selected mode: list x2 + catalog + manual -> ONE request
def test_b2_selected_mixed(pt, admin):
    meds = pt.get(f"{BASE_URL}/api/portal/medications").json()["medications"]
    a, b = _find(meds, "Atorvastatin"), _find(meds, "Ramipril")
    before = _meds_snapshot()
    r = _post_req(pt, {"request_mode": "selected", "items": [
        {"kind": "list", "patient_medication_id": a["id"]}, {"kind": "list", "patient_medication_id": b["id"]},
        {"kind": "catalog", "drug": "Acetaminophen", "label": "Acetaminophen"}, {"kind": "manual", "text": "Blue pill"}]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["source"] == "patient_refill" and d["internal_status"] == "waiting_physician"
    assert [c["entry_source"] for c in d["medications_structured"]] == ["LIST", "LIST", "CATALOG", "MANUAL"]
    assert d["review_required"] is True and d["medication_entry_source"] == "MANUAL"
    assert d["medication_name"].count("; ") == 3 and "Blue pill" in d["medication_name"]
    rows = admin.get(f"{BASE_URL}/api/internal/prescriptions").json()
    rows = rows if isinstance(rows, list) else rows.get("items", rows.get("requests", []))
    assert any(x["id"] == d["id"] for x in rows), "request not visible in admin queue"
    assert _meds_snapshot() == before  # B7 tail: request alone never writes patient_medications


# B3/B4 blister + all_regular keep individual cards
@pytest.mark.parametrize("mode,label", [("blister_pack", "Blister / Compliance Pack"), ("all_regular", "All regular medications")])
def test_b3_b4_modes(pt, mode, label):
    meds = [m for m in pt.get(f"{BASE_URL}/api/portal/medications").json()["medications"] if m["regular"]]
    r = _post_req(pt, {"request_mode": mode, "items": [{"kind": "list", "patient_medication_id": m["id"]} for m in meds]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["request_mode"] == mode and d["request_mode_label"] == label
    assert len(d["medications_structured"]) == len(meds)
    assert not any("blister" in (c["drug"] or "").lower() for c in d["medications_structured"])
    assert d["medication_name"] == "; ".join(" ".join(x for x in (m["drug"], m["strength"]) if x) for m in meds)


# B5 medication_change
def test_b5_medication_change(pt):
    before = _meds_snapshot()
    r = _post_req(pt, {"request_mode": "medication_change", "items": [], "patient_note": "QA change my dose"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["review_required"] is True and d["requested_months"] is None and d["supply_type"] is None
    assert d["request_mode_label"] == "Medication change request"
    r2 = _post_req(pt, {"request_mode": "medication_change", "items": []})
    assert r2.status_code == 400
    assert _meds_snapshot() == before


# B6 validation
def test_b6_validation(pt):
    assert _post_req(pt, {"request_mode": "selected", "items": []}).status_code == 400
    assert _post_req(pt, {"items": [{"kind": "list", "patient_medication_id": "nope"}]}).status_code == 404
    assert _post_req(pt, {"items": [{"kind": "weird", "drug": "x"}]}).status_code == 400


# B7 due intelligence
def test_b7_due_intelligence(pt):
    ia = _temp_med(months=1, refills=0, last_prescribed_at=_ago(25))
    ib = _temp_med(last_prescribed_at=_ago(25))
    ic = _temp_med(duration_value=7, duration_unit="days", last_prescribed_at=_ago(2))
    idd = _temp_med(months=1, refills=0, last_prescribed_at=_ago(25), active=False)
    ie = _temp_med(months=3, refills=0, last_prescribed_at=_ago(10))
    d = pt.get(f"{BASE_URL}/api/portal/medications").json()
    by = {m["id"]: m for m in d["medications"]}
    prev = {m["id"]: m for m in d["previously_prescribed"]}
    assert by[ia]["likely_due"] is True and by[ia]["regular"] is True
    assert by[ib]["due_on"] is None and by[ib]["likely_due"] is False and by[ib]["regular"] is True
    assert by[ic]["coverage_days"] == 7 and by[ic]["due_on"] is None and by[ic]["regular"] is False and by[ic]["likely_due"] is False
    assert idd in prev and prev[idd]["likely_due"] is False
    assert by[ie]["likely_due"] is False
    MONGO.patient_medications.delete_many({"id": {"$in": [ia, ib, ic, idd, ie]}})
    before = _meds_snapshot()
    meds = pt.get(f"{BASE_URL}/api/portal/medications").json()["medications"]
    assert _post_req(pt, {"items": [{"kind": "list", "patient_medication_id": meds[0]["id"]}]}).status_code == 200
    assert _meds_snapshot() == before


# B8 refill reminders
def test_b8_cron_auth():
    assert requests.post(f"{BASE_URL}/api/cron/refill-reminders").status_code == 401
    assert requests.post(f"{BASE_URL}/api/cron/refill-reminders", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = requests.post(f"{BASE_URL}/api/cron/refill-reminders", headers={"Authorization": f"Bearer {CRON_SECRET}"})
    assert r.status_code == 200 and r.json() == {"ok": True, "queued": True}


def test_b8_reminder_run_idempotent(admin):
    import time; time.sleep(3)  # let the queued cron task finish
    base = admin.post(f"{BASE_URL}/api/internal/system/refill-reminders/run")
    assert base.status_code == 200 and {"patients_notified", "medications"} <= set(base.json())
    mid = _temp_med(drug="QA Reminder Drug", months=1, refills=0, last_prescribed_at=_ago(25))
    r1 = admin.post(f"{BASE_URL}/api/internal/system/refill-reminders/run").json()
    assert r1["patients_notified"] == 1 and r1["medications"] == 1, r1
    n = MONGO.notifications.find_one({"patient_id": MARIA_PID, "title": "Refill reminder", "body": {"$regex": "QA Reminder Drug"}})
    assert n is not None
    r2 = admin.post(f"{BASE_URL}/api/internal/system/refill-reminders/run").json()
    assert r2["patients_notified"] == 0, r2
    MONGO.patient_medications.delete_one({"id": mid})


# B9 directory-id linking
def test_b9_directory_linking(admin):
    a = admin.get(f"{BASE_URL}/api/internal/patients/directory:{ROMERO_DIR}/medical-record")
    b = admin.get(f"{BASE_URL}/api/internal/patients/{ROMERO_PID}/medical-record")
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    ia = [m["id"] for m in a.json()["medications"]["active"]]
    ib = [m["id"] for m in b.json()["medications"]["active"]]
    assert ia == ib
    names = [m["drug"].lower() for m in b.json()["medications"]["active"]]
    assert any("bisoprolol" in n for n in names) and any("amlodipine" in n for n in names)
    print("encounters dir vs portal:", len(a.json()["encounters"]), len(b.json()["encounters"]))
    ml = admin.get(f"{BASE_URL}/api/internal/patients/{ROMERO_PID}/medications")
    assert ml.status_code == 200
    assert "bisoprolol" in ml.text.lower() and "amlodipine" in ml.text.lower()
    biso = next(m for m in b.json()["medications"]["active"] if "bisoprolol" in m["drug"].lower())
    orig = MONGO.patient_medications.find_one({"id": biso["id"]})
    try:
        r = admin.patch(f"{BASE_URL}/api/internal/patients/{ROMERO_PID}/medications/{biso['id']}", json={"action_type": "discontinue", "note": "QA"})
        assert r.status_code == 200 and r.json()["active"] is False
        r = admin.patch(f"{BASE_URL}/api/internal/patients/{ROMERO_PID}/medications/{biso['id']}", json={"action_type": "continue"})
        assert r.status_code == 200 and r.json()["active"] is True
    finally:
        MONGO.patient_medications.update_one({"id": biso["id"]}, {"$set": {k: orig.get(k) for k in
                                              ("active", "last_prescribed_at", "discontinued_at", "discontinued_by", "updated_at", "history")}})


# B10 audit + dry-run backfill
def test_b10_audit_backfill(admin):
    r = admin.get(f"{BASE_URL}/api/internal/system/medication-history/audit", timeout=60)
    assert r.status_code == 200
    assert {"A_already_represented", "B_safe_candidate", "C_ambiguous", "D_linkage_problem", "E_completed_never_sent"} <= set(r.json()["counts"])
    cnt = MONGO.patient_medications.count_documents({})
    r = admin.post(f"{BASE_URL}/api/internal/system/medication-history/backfill", json={"apply": True}, timeout=60)
    assert r.status_code == 200 and r.json()["apply"] is False and r.json()["counts"]["applied"] == 0
    assert MONGO.patient_medications.count_documents({}) == cnt


# B11 pharmacy intake request_mode
@pytest.mark.parametrize("mode", ["blister_pack", None])
def test_b11_pharmacy_intake(admin, mode):
    body = {"patient_id": MARIA_PID, "pharmacy": "QA Pharmacy", "medications": ["Atorvastatin 20 mg", "Ramipril 10 mg"],
            "medications_structured": [{"drug": "Atorvastatin", "strength": "20 mg"}, {"drug": "Ramipril", "strength": "10 mg"}],
            "received_via": "fax"}
    if mode:
        body["request_mode"] = mode
    r = admin.post(f"{BASE_URL}/api/internal/pharmacy-rx", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    rid = d.get("id") or (d.get("request") or {}).get("id")
    CREATED["prescription_requests"].append(rid)
    doc = MONGO.prescription_requests.find_one({"id": rid})
    assert doc["request_mode"] == mode
    assert doc["request_mode_label"] == ("Blister / Compliance Pack" if mode else None)
    assert len(doc["medications_structured"]) == 2


# R1/R2 regression
def test_r1_old_endpoints(pt):
    meds = pt.get(f"{BASE_URL}/api/portal/medications").json()["medications"]
    r = pt.post(f"{BASE_URL}/api/portal/refill-requests", json={"medication_ids": [meds[0]["id"]], "supply_type": "standard", "requested_months": 1})
    assert r.status_code == 200, r.text
    d = r.json()
    for x in (d.get("requests") or d.get("items") or []):
        CREATED["prescription_requests"].append(x["id"])
    if d.get("batch_id"):
        CREATED["prescription_requests"] += [x["id"] for x in MONGO.prescription_requests.find({"batch_id": d["batch_id"]}, {"id": 1})]
    s = pt.get(f"{BASE_URL}/api/portal/medication-search", params={"q": "Aceta"})
    assert s.status_code == 200 and "aceta" in s.text.lower()


def test_r2_queues(admin):
    assert admin.get(f"{BASE_URL}/api/internal/work").status_code == 200
    assert admin.get(f"{BASE_URL}/api/internal/prescriptions").status_code == 200
    r = requests.get(f"{BASE_URL}/api/public/address/postal-lookup", params={"postal": "M6E4H1"})
    assert r.status_code == 200 and "toronto" in r.text.lower(), r.text
    print(r.text[:300])
