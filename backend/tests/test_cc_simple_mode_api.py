# Control Center SIMPLE mode — API permission + audit checks (iteration_91)
import os
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


@pytest.fixture(scope="module")
def devops_token():
    r = requests.post(f"{BASE_URL}/api/platform/auth/login", json={"identifier": "devops@visita.demo", "password": "DevOps-Preview-2026!Set"})
    if r.status_code != 200:
        pytest.skip(f"devops login failed {r.status_code}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def physician_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"identifier": "PAGUAYO", "password": "Aguayo-Preview-2026#Tmp"})
    if r.status_code != 200:
        pytest.skip(f"physician login failed {r.status_code}")
    return r.json()["token"]


# Permissions
def test_physician_forbidden_on_deployment(physician_token):
    r = requests.get(f"{BASE_URL}/api/developer/deployment", headers={"Authorization": f"Bearer {physician_token}"})
    assert r.status_code == 403


def test_devops_can_read_deployment(devops_token):
    r = requests.get(f"{BASE_URL}/api/developer/deployment", headers={"Authorization": f"Bearer {devops_token}"})
    assert r.status_code == 200
    d = r.json()
    assert "deployment" in d and "state" in d["deployment"]
    assert isinstance(d.get("history"), list)


# Audit rows exist for SIMPLE-mode actions
@pytest.mark.parametrize("action", ["deployment_state_changed", "maintenance_mode_entered", "announcement_published"])
def test_audit_rows_exist(action):
    db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
    n = db.audit_logs.count_documents({"action": action})
    assert n > 0, f"no audit rows for {action}"
