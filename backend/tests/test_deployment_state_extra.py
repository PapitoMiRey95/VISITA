"""Deployment & Maintenance — extended regression (iteration 90): response shape, role auth, patient 503 in
Full Maintenance, audit rows, tier persistence, public base URL, and state-machine edge cases.
Run sequentially: pytest -p no:xdist tests/test_deployment_state_extra.py"""
import os
import sys

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
load_dotenv("/app/frontend/.env")
from pymongo import MongoClient  # noqa: E402

BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8001")
PUBLIC = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OPS = {"identifier": "devops@visita.demo", "password": "DevOps-Preview-2026!Set"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _tok(path, body):
    r = requests.post(f"{BASE}/api{path}", json=body)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def ops():
    h = _tok("/platform/auth/login", OPS)
    yield h
    requests.post(f"{BASE}/api/developer/deployment/resolve", json={"confirm": "RESOLVE", "note": "cleanup"}, headers=h)
    requests.post(f"{BASE}/api/developer/maintenance-mode", json={"on": False, "confirm": "EXIT"}, headers=h)
    requests.delete(f"{BASE}/api/developer/announcement", headers=h)


@pytest.fixture(scope="module")
def physician():
    return _tok("/auth/login", {"identifier": "PAGUAYO", "password": "Aguayo-Preview-2026#Tmp"})


@pytest.fixture(scope="module")
def patient():
    return _tok("/auth/login", {"email": "maria.lopez@demo.com", "password": "Patient2026!"})


def dep(ops):
    return requests.get(f"{BASE}/api/developer/deployment", headers=ops).json()


def post(ops, path, body=None):
    return requests.post(f"{BASE}/api/developer{path}", json=body or {}, headers=ops)


def banner():
    return requests.get(f"{BASE}/api/system/banner").json()


def to_normal(ops):
    post(ops, "/deployment/resolve", {"confirm": "RESOLVE"})
    if banner()["maintenance"]["on"]:
        post(ops, "/maintenance-mode", {"on": False, "confirm": "EXIT"})


# --- shape + auth ---
def test_get_deployment_shape_via_public_url(ops):
    r = requests.get(f"{PUBLIC}/api/developer/deployment", headers=ops)
    assert r.status_code == 200
    d = r.json()
    assert d["deployment"]["state"] in ("NORMAL", "UPDATING", "MAINTENANCE", "SERVICE_ISSUE")
    v = d["deployment"]["verification"]
    assert v["required"] == 3 and "streak" in v and "deadline_at" in v and isinstance(v["checks"], list)
    assert isinstance(d["history"], list) and "commit" in d["release"]
    assert set(d["probe"]) >= {"api", "database", "storage", "readiness"}
    assert list(d["kinds"]) == ["CODE", "RESOURCE", "HOTFIX"] and d["timeout_min"] == 20


def test_physician_forbidden(physician):
    assert requests.get(f"{BASE}/api/developer/deployment", headers=physician).status_code == 403
    assert requests.post(f"{BASE}/api/developer/deployment/begin-update", json={"kind": "CODE"}, headers=physician).status_code == 403


def test_cron_wrong_secret_and_public(ops):
    assert requests.post(f"{PUBLIC}/api/cron/deployment-verify", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = requests.post(f"{PUBLIC}/api/cron/deployment-verify", headers={"Authorization": f"Bearer {os.environ['WEBHOOK_CRON_SECRET']}"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_invalid_kind_400(ops):
    to_normal(ops)
    assert post(ops, "/deployment/begin-update", {"kind": "BOGUS"}).status_code == 400


def test_tier_persists(ops):
    r = requests.put(f"{BASE}/api/developer/deployment/build-info", json={"tier": "TEST_tier 0.5vCPU"}, headers=ops)
    assert r.status_code == 200
    assert dep(ops)["deployment"]["build"]["tier"] == "TEST_tier 0.5vCPU"


# --- kind-aware: RESOURCE ignores expected_commit ---
def test_resource_ignores_expected_commit(ops):
    to_normal(ops)
    post(ops, "/deployment/begin-update", {"kind": "RESOURCE", "expected_commit": "zzzz"})
    v = post(ops, "/deployment/verify").json()
    assert v["ok"] is True, v
    to_normal(ops)


# --- announcement coexistence while UPDATING ---
def test_announcement_with_updating(ops):
    to_normal(ops)
    requests.put(f"{BASE}/api/developer/announcement", json={"message": "TEST_ann", "type": "INFO"}, headers=ops)
    post(ops, "/deployment/begin-update", {"kind": "CODE", "expected_commit": "zzzz"})
    b = banner()
    assert b["notice"]["kind"] == "UPDATE" and b["announcement"]["message"] == "TEST_ann"
    to_normal(ops)
    assert banner()["announcement"]["active"] is True
    requests.delete(f"{BASE}/api/developer/announcement", headers=ops)
    assert banner()["announcement"] is None


# --- Full maintenance blocks patient API with MAINTENANCE_MODE ---
def test_patient_503_in_maintenance(ops, patient):
    to_normal(ops)
    assert post(ops, "/maintenance-mode", {"on": True, "confirm": "ENTER", "message": "TEST_mx"}).status_code == 200
    import time; time.sleep(5.5)  # middleware cache TTL 5s
    r = requests.get(f"{BASE}/api/portal/me", headers=patient)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "MAINTENANCE_MODE"
    assert post(ops, "/maintenance-mode", {"on": False, "confirm": "EXIT"}).status_code == 200
    assert dep(ops)["history"][0]["result"] == "SUCCEEDED"


def test_audit_rows_exist(ops):
    rows = list(_db().audit_logs.find({"action": "deployment_state_changed"}, {"_id": 0}).sort("created_at", -1).limit(200))
    pairs = {(r.get("old_status"), r.get("new_status")) for r in rows}
    for p in [("NORMAL", "UPDATING"), ("UPDATING", "NORMAL"), ("NORMAL", "MAINTENANCE"), ("MAINTENANCE", "NORMAL")]:
        assert p in pairs, (p, pairs)


# --- edge cases (state-machine integrity) ---
def test_exit_maintenance_does_not_clear_service_issue(ops):
    """EXIT maintenance while SERVICE_ISSUE (maintenance off) should not silently flip to NORMAL / mark SUCCEEDED."""
    to_normal(ops)
    post(ops, "/deployment/begin-update", {"kind": "CODE", "expected_commit": "zzzz"})
    post(ops, "/deployment/service-issue", {"confirm": "ISSUE"})
    dep_id = dep(ops)["deployment"]["deployment_id"]
    post(ops, "/maintenance-mode", {"on": False, "confirm": "EXIT"})
    st = banner()["state"]
    row = _db().deployment_history.find_one({"id": dep_id}, {"_id": 0})
    to_normal(ops)
    assert st == "SERVICE_ISSUE" and row["result"] != "SUCCEEDED", f"state={st} history_result={row['result']}"


def test_manual_issue_from_normal_creates_new_row(ops):
    """Manual ISSUE from NORMAL must not overwrite the previous (completed) deployment's history row."""
    to_normal(ops)
    post(ops, "/deployment/begin-update", {"kind": "RESOURCE", "note": "TEST_prev"})
    for _ in range(3):
        post(ops, "/deployment/verify")
    prev_id = dep(ops)["history"][0]["id"]
    assert dep(ops)["history"][0]["result"] == "SUCCEEDED"
    post(ops, "/deployment/service-issue", {"confirm": "ISSUE"})
    prev = _db().deployment_history.find_one({"id": prev_id}, {"_id": 0})
    to_normal(ops)
    assert prev["result"] == "SUCCEEDED", f"previous row overwritten -> result={prev['result']} status={prev['status']}"


def test_enter_maintenance_while_updating_closes_soft_row(ops):
    to_normal(ops)
    post(ops, "/deployment/begin-update", {"kind": "CODE", "expected_commit": "zzzz"})
    soft_id = dep(ops)["deployment"]["deployment_id"]
    post(ops, "/maintenance-mode", {"on": True, "confirm": "ENTER"})
    post(ops, "/maintenance-mode", {"on": False, "confirm": "EXIT"})
    row = _db().deployment_history.find_one({"id": soft_id}, {"_id": 0})
    to_normal(ops)
    assert row["status"] != "IN_PROGRESS", "SOFT row left IN_PROGRESS forever after maintenance superseded it"
