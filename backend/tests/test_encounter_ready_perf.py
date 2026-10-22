# Enter-Encounter perf optimization: /internal/visits/ready shape + authz, /internal/visits/{id} context
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MARIA_REF = "patient:06f6ee08-58f7-4286-82f5-7c845de99ce1"


def _login(identifier, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"identifier": identifier, "password": password})
    if r.status_code != 200:
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": identifier, "password": password})
    if r.status_code != 200:
        pytest.skip(f"login failed for {identifier}: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def doc():
    return {"Authorization": f"Bearer {_login('PAGUAYO', 'Aguayo-Preview-2026#Tmp')}"}


@pytest.fixture(scope="module")
def staff():
    return {"Authorization": f"Bearer {_login('staff@visita.demo', 'Staff2026!')}"}


class TestVisitReady:
    def test_ready_shape(self, doc):
        t = time.time()
        r = requests.get(f"{BASE_URL}/api/internal/visits/ready", params={"patient_ref": MARIA_REF}, headers=doc)
        print(f"ready latency {(time.time()-t)*1000:.0f}ms")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["patient_ref"] == MARIA_REF
        assert isinstance(d["patient_snapshot"], dict)
        assert "visita_patient_id" in d
        ctx = d["context"]
        names = " ".join(m.get("name", "") or m.get("medication_name", "") or str(m) for m in ctx["medications_active"])
        assert len(ctx["medications_active"]) == 3, ctx["medications_active"]
        for n in ("Atorvastatin", "Ramipril", "Metformin"):
            assert n in names
        assert "recent_appointments" in ctx and ctx["recent_appointments"] is None
        assert "documents" in ctx and ctx["documents"] is None
        assert "server_time" in d
        a = d["active"]
        if a is not None:
            for k in ("id", "ref_number", "started_at", "timer_state"):
                assert k in a
        assert "_id" not in d

    def test_ready_staff_forbidden(self, staff):
        r = requests.get(f"{BASE_URL}/api/internal/visits/ready", params={"patient_ref": MARIA_REF}, headers=staff)
        assert r.status_code == 403

    def test_ready_invalid_ref(self, doc):
        r = requests.get(f"{BASE_URL}/api/internal/visits/ready", params={"patient_ref": "garbage-ref"}, headers=doc)
        assert r.status_code == 400

    def test_ready_unknown_patient(self, doc):
        r = requests.get(f"{BASE_URL}/api/internal/visits/ready", params={"patient_ref": "patient:00000000-0000-0000-0000-000000000000"}, headers=doc)
        assert r.status_code in (400, 404)

    def test_ready_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/internal/visits/ready", params={"patient_ref": MARIA_REF})
        assert r.status_code in (401, 403)


class TestVisitGet:
    def test_visit_get_context(self, doc):
        r = requests.get(f"{BASE_URL}/api/internal/patients/{MARIA_REF}/visits", headers=doc)
        if r.status_code != 200:
            pytest.skip(f"no visit list endpoint: {r.status_code}")
        body = r.json()
        rows = body if isinstance(body, list) else (body.get("items") or body.get("visits") or body.get("rows") or [])
        if not rows:
            pytest.skip("no visits for Maria")
        vid = rows[0]["id"]
        g = requests.get(f"{BASE_URL}/api/internal/visits/{vid}", headers=doc)
        assert g.status_code == 200, g.text
        d = g.json()
        assert d["id"] == vid
        assert len(d["context"]["medications_active"]) == 3
        assert d["context"]["documents"] is None
        assert "timer_state" in d and "server_time" in d
        assert "_id" not in d

    def test_visit_get_404(self, doc):
        g = requests.get(f"{BASE_URL}/api/internal/visits/does-not-exist-xyz", headers=doc)
        assert g.status_code == 404
