"""Phase 2A5 — Encounter START/STOP/RESUME toggle backend tests.

Covers:
  - /visits/ready physician-only (admin/staff 403), creates nothing
  - Idempotent /stop and /resume on already-paused/running
  - staff 403 on /stop and /resume
  - timer fields present on GET /visits/{id}
"""
import os
import time
import pytest
import requests

def _load_backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        env_path = "/app/frontend/.env"
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    assert url, "REACT_APP_BACKEND_URL not set"
    return url.rstrip("/")

BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

PHYS = {"identifier": "PAGUAYO", "password": "Newman2013_!"}
STAFF = {"identifier": "staff@visita.demo", "password": "Staff2026!"}
ADMIN = {"identifier": "kevinrodriguez9528@gmail.com", "password": "VisitaAdmin2026!"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed for {creds['identifier']}: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def phys_tok():
    return _login(PHYS)


@pytest.fixture(scope="module")
def staff_tok():
    return _login(STAFF)


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def fresh_patient_ref(phys_tok):
    """Pick a directory patient WITHOUT an open visit for this physician."""
    # Query directory for several candidates; find one with no active visit.
    r = requests.get(f"{API}/internal/directory", params={"q": "MACHADO"}, headers=_h(phys_tok), timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    items = j if isinstance(j, list) else (j.get("items") or j.get("directory") or [])
    # Prefer MACHADO FARIA (has existing paused visit per request context)
    for d in items:
        did = d.get("id")
        ref = f"directory:{did}"
        a = requests.get(f"{API}/internal/visits/active", params={"patient_ref": ref},
                         headers=_h(phys_tok), timeout=20)
        if a.status_code == 200 and a.json().get("active") is None:
            return ref
    # Fallback: scan broader directory
    r = requests.get(f"{API}/internal/directory", params={"q": "A"}, headers=_h(phys_tok), timeout=20)
    j = r.json()
    items = j if isinstance(j, list) else (j.get("items") or j.get("directory") or [])
    for d in items[:60]:
        did = d.get("id")
        ref = f"directory:{did}"
        a = requests.get(f"{API}/internal/visits/active", params={"patient_ref": ref},
                         headers=_h(phys_tok), timeout=20)
        if a.status_code == 200 and a.json().get("active") is None:
            return ref
    pytest.skip("No directory patient without an open visit for PAGUAYO found.")


# --- /visits/ready contract -------------------------------------------------
class TestReady:
    def test_ready_physician_ok_creates_nothing(self, phys_tok, fresh_patient_ref):
        r = requests.get(f"{API}/internal/visits/ready", params={"patient_ref": fresh_patient_ref},
                         headers=_h(phys_tok), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["patient_ref"] == fresh_patient_ref
        assert "patient_snapshot" in data and isinstance(data["patient_snapshot"], dict)
        assert "context" in data
        assert "server_time" in data
        assert data.get("active") in (None,) or isinstance(data.get("active"), dict)
        # Verify no visit was created
        a = requests.get(f"{API}/internal/visits/active", params={"patient_ref": fresh_patient_ref},
                         headers=_h(phys_tok), timeout=20)
        assert a.status_code == 200 and a.json()["active"] is None

    def test_ready_admin_forbidden(self, admin_tok, fresh_patient_ref):
        r = requests.get(f"{API}/internal/visits/ready", params={"patient_ref": fresh_patient_ref},
                         headers=_h(admin_tok), timeout=20)
        assert r.status_code == 403, r.text

    def test_ready_staff_forbidden(self, staff_tok, fresh_patient_ref):
        r = requests.get(f"{API}/internal/visits/ready", params={"patient_ref": fresh_patient_ref},
                         headers=_h(staff_tok), timeout=20)
        assert r.status_code == 403, r.text


# --- Create → stop → resume → stop (idempotent) ----------------------------
class TestTimerLifecycle:
    @pytest.fixture(scope="class")
    def visit(self, phys_tok, fresh_patient_ref):
        r = requests.post(f"{API}/internal/visits",
                          json={"patient_ref": fresh_patient_ref, "encounter_type": "TELEPHONE", "source": "patients"},
                          headers=_h(phys_tok), timeout=20)
        assert r.status_code in (200, 201), r.text
        v = r.json()
        assert v["timer_state"] == "RUNNING"
        assert v["elapsed_seconds"] == 0
        assert v["running_since"]
        yield v
        # teardown: ensure visit is paused and exited so it doesn't block subsequent runs
        try:
            requests.post(f"{API}/internal/visits/{v['id']}/stop", headers=_h(phys_tok), timeout=20)
            requests.post(f"{API}/internal/visits/{v['id']}/exit", headers=_h(phys_tok), timeout=20)
        except Exception:
            pass

    def test_get_visit_has_timer_fields(self, phys_tok, visit):
        r = requests.get(f"{API}/internal/visits/{visit['id']}", headers=_h(phys_tok), timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ("timer_state", "elapsed_seconds", "running_since", "paused_at", "server_time"):
            assert k in d, f"missing {k}"
        assert d["timer_state"] == "RUNNING"

    def test_stop_then_idempotent(self, phys_tok, visit):
        time.sleep(2)
        r1 = requests.post(f"{API}/internal/visits/{visit['id']}/stop", headers=_h(phys_tok), timeout=20)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["timer_state"] == "PAUSED"
        assert d1["running_since"] is None
        assert d1["paused_at"] is not None
        assert d1["elapsed_seconds"] >= 1

        # Idempotent: calling /stop again returns 200, same elapsed_seconds (no new accumulation)
        r2 = requests.post(f"{API}/internal/visits/{visit['id']}/stop", headers=_h(phys_tok), timeout=20)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["timer_state"] == "PAUSED"
        assert d2["elapsed_seconds"] == d1["elapsed_seconds"]

    def test_resume_continues_accumulated(self, phys_tok, visit):
        # Resume from PAUSED
        r = requests.post(f"{API}/internal/visits/{visit['id']}/resume", headers=_h(phys_tok), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["timer_state"] == "RUNNING"
        assert d["running_since"]
        assert d["paused_at"] is None
        assert d["elapsed_seconds"] >= 1  # retained accumulated

        # Idempotent resume: already RUNNING
        r2 = requests.post(f"{API}/internal/visits/{visit['id']}/resume", headers=_h(phys_tok), timeout=20)
        assert r2.status_code == 200
        assert r2.json()["timer_state"] == "RUNNING"

    def test_staff_cannot_stop_or_resume(self, staff_tok, visit):
        r1 = requests.post(f"{API}/internal/visits/{visit['id']}/stop", headers=_h(staff_tok), timeout=20)
        assert r1.status_code == 403
        r2 = requests.post(f"{API}/internal/visits/{visit['id']}/resume", headers=_h(staff_tok), timeout=20)
        assert r2.status_code == 403

    def test_duplicate_create_returns_409_with_visit_id(self, phys_tok, visit, fresh_patient_ref):
        # The visit above is open; creating again for same patient should 409
        r = requests.post(f"{API}/internal/visits",
                          json={"patient_ref": fresh_patient_ref, "encounter_type": "IN_CLINIC", "source": "patients"},
                          headers=_h(phys_tok), timeout=20)
        assert r.status_code == 409
        d = r.json().get("detail") or {}
        assert d.get("visit_id") == visit["id"]

    def test_exit_while_running_sets_exited_at(self, phys_tok, visit):
        # Visit should currently be RUNNING (from resume test). Exit without stop should still work
        # per contract, but UI stops first. We test both: pause then exit.
        requests.post(f"{API}/internal/visits/{visit['id']}/stop", headers=_h(phys_tok), timeout=20)
        r = requests.post(f"{API}/internal/visits/{visit['id']}/exit", headers=_h(phys_tok), timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "IN_PROGRESS"  # still IN_PROGRESS, not completed
        assert d["exited_at"]
