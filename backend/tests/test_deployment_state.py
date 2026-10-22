"""Deployment & Maintenance state machine — transitions, kind-aware verification, 20-min timeout,
manual issue/resolve, Global Message coexistence, Full Maintenance sync. Preview DB; restores NORMAL at the end."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from pymongo import MongoClient  # noqa: E402

BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8001")
OPS = {"identifier": os.environ.get("TEST_DEVOPS_EMAIL", "devops@visita.demo"), "password": os.environ.get("TEST_DEVOPS_PASSWORD", "DevOps-Preview-2026!Set")}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(x):
    return x


@pytest.fixture(scope="module")
def ops():
    r = requests.post(f"{BASE}/api/platform/auth/login", json=OPS)
    if r.status_code != 200:
        r = requests.post(f"{BASE}/api/auth/login", json={"email": OPS["identifier"], "password": OPS["password"]})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    yield {"Authorization": f"Bearer {tok}"}
    # restore NORMAL + clear announcement/maintenance
    requests.post(f"{BASE}/api/developer/deployment/resolve", json={"confirm": "RESOLVE", "note": "test cleanup"}, headers={"Authorization": f"Bearer {tok}"})
    requests.post(f"{BASE}/api/developer/maintenance-mode", json={"on": False, "confirm": "EXIT"}, headers={"Authorization": f"Bearer {tok}"})
    requests.delete(f"{BASE}/api/developer/announcement", headers={"Authorization": f"Bearer {tok}"})


def dep(ops):
    return requests.get(f"{BASE}/api/developer/deployment", headers=ops).json()


def banner():
    return requests.get(f"{BASE}/api/system/banner").json()


def test_resource_only_same_commit_passes(ops):
    requests.post(f"{BASE}/api/developer/deployment/resolve", json={"confirm": "RESOLVE"}, headers=ops)
    r = requests.post(f"{BASE}/api/developer/deployment/begin-update", json={"kind": "RESOURCE", "note": "tier test"}, headers=ops)
    assert r.status_code == 200 and r.json()["state"] == "UPDATING"
    b = banner(); assert b["state"] == "UPDATING" and b["notice"]["kind"] == "UPDATE"
    results = [requests.post(f"{BASE}/api/developer/deployment/verify", headers=ops).json() for _ in range(3)]
    assert [x["ok"] for x in results] == [True, True, True]
    assert results[-1]["state"] == "NORMAL" and results[-1]["result"] == "SUCCEEDED"
    assert banner()["notice"] is None
    h = dep(ops)["history"][0]; assert h["kind"] == "RESOURCE" and h["result"] == "SUCCEEDED" and h["completed_at"]


def test_code_deploy_wrong_commit_keeps_updating_then_right_commit_passes(ops):
    cur = dep(ops)["release"]["commit"]
    r = requests.post(f"{BASE}/api/developer/deployment/begin-update", json={"kind": "CODE", "expected_commit": "deadbeef0000"}, headers=ops)
    assert r.status_code == 200
    for _ in range(4):
        v = requests.post(f"{BASE}/api/developer/deployment/verify", headers=ops).json()
        assert v["ok"] is False and v["state"] == "UPDATING" and any("commit" in x for x in v["reasons"])
    assert banner()["notice"]["kind"] == "UPDATE"  # failed checks do NOT enter SERVICE_ISSUE
    # simulate the new pod carrying the expected build: set expected to the running commit
    _run(_db().system_state.update_one({"id": "global"}, {"$set": {"deployment.expected_commit": cur}}))
    results = [requests.post(f"{BASE}/api/developer/deployment/verify", headers=ops).json() for _ in range(3)]
    assert results[-1]["state"] == "NORMAL"
    assert dep(ops)["history"][0]["verification"]["failed"] >= 4


def test_timeout_enters_service_issue_and_resolve(ops):
    requests.post(f"{BASE}/api/developer/deployment/begin-update", json={"kind": "HOTFIX", "expected_commit": "nomatch123"}, headers=ops)
    v = requests.post(f"{BASE}/api/developer/deployment/verify", headers=ops).json(); assert v["state"] == "UPDATING"
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _run(_db().system_state.update_one({"id": "global"}, {"$set": {"deployment.verification.deadline_at": past}}))
    v = requests.post(f"{BASE}/api/developer/deployment/verify", headers=ops).json()
    assert v["state"] == "SERVICE_ISSUE"
    b = banner(); assert b["state"] == "SERVICE_ISSUE" and b["notice"]["kind"] == "ISSUE" and "temporarily unavailable" in b["notice"]["message"]
    # healthy checks in SERVICE_ISSUE do not auto-clear; operator resolves
    _run(_db().system_state.update_one({"id": "global"}, {"$set": {"deployment.expected_commit": None}}))
    for _ in range(3):
        v = requests.post(f"{BASE}/api/developer/deployment/verify", headers=ops).json()
    assert v["state"] == "SERVICE_ISSUE" and v["streak"] >= 3
    assert requests.post(f"{BASE}/api/developer/deployment/resolve", json={"confirm": "WRONG"}, headers=ops).status_code == 400
    r = requests.post(f"{BASE}/api/developer/deployment/resolve", json={"confirm": "RESOLVE", "rolled_back": True, "note": "rolled back"}, headers=ops)
    assert r.status_code == 200 and r.json()["state"] == "NORMAL"
    h = dep(ops)["history"][0]; assert h["result"] == "ROLLED_BACK" and h["status"] == "COMPLETED"
    assert banner()["notice"] is None


def test_manual_service_issue_and_global_message_coexist(ops):
    requests.put(f"{BASE}/api/developer/announcement", json={"message": "Clinic closed Friday", "type": "INFO"}, headers=ops)
    requests.post(f"{BASE}/api/developer/deployment/begin-update", json={"kind": "CODE"}, headers=ops)
    assert requests.post(f"{BASE}/api/developer/deployment/service-issue", json={"confirm": "nope"}, headers=ops).status_code == 400
    r = requests.post(f"{BASE}/api/developer/deployment/service-issue", json={"confirm": "ISSUE", "note": "manual"}, headers=ops)
    assert r.status_code == 200 and r.json()["state"] == "SERVICE_ISSUE"
    b = banner()
    assert b["notice"]["kind"] == "ISSUE" and b["announcement"]["message"] == "Clinic closed Friday"  # both present, manual kept
    requests.post(f"{BASE}/api/developer/deployment/resolve", json={"confirm": "RESOLVE"}, headers=ops)
    b = banner(); assert b["notice"] is None and b["announcement"]["active"]
    requests.delete(f"{BASE}/api/developer/announcement", headers=ops)


def test_full_maintenance_sync_and_block(ops):
    r = requests.post(f"{BASE}/api/developer/maintenance-mode", json={"on": True, "confirm": "ENTER", "message": "migration"}, headers=ops)
    assert r.status_code == 200
    b = banner(); assert b["state"] == "MAINTENANCE" and b["notice"]["kind"] == "MAINTENANCE" and b["maintenance"]["on"]
    assert requests.post(f"{BASE}/api/developer/deployment/begin-update", json={"kind": "CODE"}, headers=ops).status_code == 400
    assert dep(ops)["history"][0]["mode"] == "FULL"
    r = requests.post(f"{BASE}/api/developer/maintenance-mode", json={"on": False, "confirm": "EXIT"}, headers=ops)
    assert r.status_code == 200
    b = banner(); assert b["state"] == "NORMAL" and b["notice"] is None
    assert dep(ops)["history"][0]["result"] == "SUCCEEDED"


def test_cron_requires_secret():
    assert requests.post(f"{BASE}/api/cron/deployment-verify").status_code == 401
    secret = os.environ.get("WEBHOOK_CRON_SECRET")
    if secret:
        assert requests.post(f"{BASE}/api/cron/deployment-verify", headers={"Authorization": f"Bearer {secret}"}).status_code == 200


def test_non_operator_forbidden():
    r = requests.get(f"{BASE}/api/developer/deployment")
    assert r.status_code in (401, 403)
