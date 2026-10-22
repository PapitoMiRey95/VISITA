# Control Center — operations_operator vs developer_ops permission matrix + audit (iteration_92)
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")


def _env(key):
    for line in open("/app/backend/.env"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


DB = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]


def _plogin(ident, pw):
    r = requests.post(f"{BASE_URL}/api/platform/auth/login", json={"identifier": ident, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def op():
    d = _plogin("operator@visita.demo", "Operator-Preview-2026!Set")
    assert d["user"]["role"] == "operations_operator"
    return {"Authorization": f"Bearer {d['token']}"}


@pytest.fixture(scope="module")
def dev():
    return {"Authorization": f"Bearer {_plogin('devops@visita.demo', 'DevOps-Preview-2026!Set')['token']}"}


@pytest.fixture(scope="module")
def phys():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"identifier": "PAGUAYO", "password": "Aguayo-Preview-2026#Tmp"})
    if r.status_code != 200:
        pytest.skip("physician login failed")
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def pat():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "maria.lopez@demo.com", "password": "Patient2026!"})
    if r.status_code != 200:
        pytest.skip("patient login failed")
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module", autouse=True)
def cleanup(dev):
    yield
    requests.delete(f"{BASE_URL}/api/developer/announcement", headers=dev)
    d = requests.get(f"{BASE_URL}/api/developer/deployment", headers=dev).json()["deployment"]
    if d["state"] == "UPDATING":
        DB.system_state.update_one({"id": "global"}, {"$set": {"deployment.expected_commit": None}})
        requests.post(f"{BASE_URL}/api/developer/deployment/verify", headers=dev)
    d = requests.get(f"{BASE_URL}/api/developer/deployment", headers=dev).json()["deployment"]
    if d["state"] == "SERVICE_ISSUE":
        requests.post(f"{BASE_URL}/api/developer/deployment/resolve", headers=dev, json={"confirm": "RESOLVE"})


DENIED = [
    ("post", "/api/developer/deployment/service-issue", {"confirm": "ISSUE"}),
    ("post", "/api/developer/deployment/resolve", {"confirm": "RESOLVE"}),
    ("put", "/api/developer/deployment/build-info", {"tier": None}),
    ("post", "/api/developer/maintenance-mode", {"on": True, "confirm": "ENTER"}),
    ("get", "/api/developer/platform-config", None),
    ("get", "/api/developer/data-ops/status", None),
    ("post", "/api/developer/platform-config/rollback", {"confirm": "ROLLBACK"}),
]


# Operator reads
@pytest.mark.parametrize("path", ["/api/developer/status", "/api/developer/deployment"])
def test_operator_reads(op, path):
    r = requests.get(BASE_URL + path, headers=op)
    assert r.status_code == 200
    if path.endswith("status"):
        assert "deployment" in r.json()


# Operator denied on high-risk
@pytest.mark.parametrize("method,path,body", DENIED)
def test_operator_denied(op, method, path, body):
    r = getattr(requests, method)(BASE_URL + path, headers=op, json=body)
    assert r.status_code == 403, f"{path} -> {r.status_code}"


# developer_ops allowed on read-only privileged endpoints
@pytest.mark.parametrize("path", ["/api/developer/status", "/api/developer/deployment", "/api/developer/platform-config", "/api/developer/data-ops/status"])
def test_devops_reads(dev, path):
    assert requests.get(BASE_URL + path, headers=dev).status_code == 200


# Physician/patient forbidden everywhere
@pytest.mark.parametrize("who", ["phys", "pat"])
@pytest.mark.parametrize("method,path,body", DENIED + [
    ("get", "/api/developer/status", None), ("get", "/api/developer/deployment", None),
    ("put", "/api/developer/announcement", {"message": "x"}), ("delete", "/api/developer/announcement", None),
    ("post", "/api/developer/deployment/begin-update", {"kind": "CODE"}), ("post", "/api/developer/deployment/verify", None)])
def test_clinical_roles_forbidden(request, who, method, path, body):
    h = request.getfixturevalue(who)
    r = getattr(requests, method)(BASE_URL + path, headers=h, json=body)
    assert r.status_code == 403, f"{who} {path} -> {r.status_code}"


# Operator announcement put/delete + audit actor_role
def test_operator_announcement_and_audit(op, pat):
    r = requests.put(f"{BASE_URL}/api/developer/announcement", headers=op, json={"message": "TEST_operator notice", "type": "INFO"})
    assert r.status_code == 200 and r.json()["active"] is True
    b = requests.get(f"{BASE_URL}/api/system/banner").json()
    assert "TEST_operator notice" in str(b)
    row = DB.audit_logs.find_one({"action": {"$in": ["announcement_published", "announcement_updated"]}}, sort=[("_id", -1)])
    assert row and row.get("actor_role") == "operations_operator", row
    r = requests.delete(f"{BASE_URL}/api/developer/announcement", headers=op)
    assert r.status_code == 200 and r.json()["active"] is False


# Operator begin-update + verify; audit; then devops service-issue/resolve flow
def test_operator_update_and_devops_issue(op, dev):
    st = requests.get(f"{BASE_URL}/api/developer/deployment", headers=dev).json()["deployment"]["state"]
    assert st == "NORMAL", st
    r = requests.post(f"{BASE_URL}/api/developer/deployment/begin-update", headers=op, json={"kind": "CODE", "expected_commit": "zzzz"})
    assert r.status_code == 200, r.text
    assert requests.get(f"{BASE_URL}/api/developer/deployment", headers=op).json()["deployment"]["state"] == "UPDATING"
    b = requests.get(f"{BASE_URL}/api/system/banner").json()
    assert "UPDATE" in str(b)
    row = DB.audit_logs.find_one({"action": "deployment_state_changed"}, sort=[("_id", -1)])
    assert row and row.get("actor_role") == "operations_operator", row
    v = requests.post(f"{BASE_URL}/api/developer/deployment/verify", headers=op)
    assert v.status_code == 200
    # devops-only transitions
    assert requests.post(f"{BASE_URL}/api/developer/deployment/service-issue", headers=op, json={"confirm": "ISSUE"}).status_code == 403
    r = requests.post(f"{BASE_URL}/api/developer/deployment/service-issue", headers=dev, json={"confirm": "ISSUE"})
    assert r.status_code == 200, r.text
    assert requests.post(f"{BASE_URL}/api/developer/deployment/resolve", headers=op, json={"confirm": "RESOLVE"}).status_code == 403
    r = requests.post(f"{BASE_URL}/api/developer/deployment/resolve", headers=dev, json={"confirm": "RESOLVE"})
    assert r.status_code == 200, r.text
    assert requests.get(f"{BASE_URL}/api/developer/deployment", headers=dev).json()["deployment"]["state"] == "NORMAL"


# Maintenance: operator keeps /api/developer access; platform login during maintenance
def test_maintenance_operator_access(op, dev, pat):
    r = requests.post(f"{BASE_URL}/api/developer/maintenance-mode", headers=dev, json={"on": True, "confirm": "ENTER"})
    assert r.status_code == 200
    try:
        assert requests.get(f"{BASE_URL}/api/developer/status", headers=op).status_code == 200
        assert requests.get(f"{BASE_URL}/api/portal/medications", headers=pat).status_code == 503
        lr = requests.post(f"{BASE_URL}/api/platform/auth/login", json={"identifier": "operator@visita.demo", "password": "Operator-Preview-2026!Set"})
        assert lr.status_code == 200, f"platform login during maintenance -> {lr.status_code}"
    finally:
        r = requests.post(f"{BASE_URL}/api/developer/maintenance-mode", headers=dev, json={"on": False, "confirm": "EXIT"})
        assert r.status_code == 200
