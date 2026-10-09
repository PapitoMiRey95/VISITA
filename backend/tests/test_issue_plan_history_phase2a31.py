"""Phase 2A3.1 — GET /api/internal/patients/{patient_ref}/issue-plan-history

Covers physician/admin/staff access and search variants.
"""
import os
import pytest
import requests
from pathlib import Path


def _env():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL missing")


BASE = _env()
PATIENT_REF = "directory:c5c30d56-acdd-416b-b61d-5cf8aab06a74"
EXCLUDE = "84460a4c-032a-4e71-b9d3-183590d6ae12"
URL = f"{BASE}/api/internal/patients/{PATIENT_REF}/issue-plan-history"


def _login(identifier, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"identifier": identifier, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed {identifier}: {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def phys_h():
    return _login("PAGUAYO", "Newman2013_!")


@pytest.fixture(scope="module")
def staff_h():
    return _login("staff@visita.demo", "Staff2026!")


@pytest.fixture(scope="module")
def admin_h():
    return _login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")


class TestPhysicianIssuePlanHistory:
    def test_default_entries_contains_sample_excludes_vis_000004(self, phys_h):
        r = requests.get(URL, headers=phys_h, params={"exclude": EXCLUDE}, timeout=20)
        assert r.status_code == 200, r.text
        entries = r.json()["entries"]
        refs = [e["ref_number"] for e in entries]
        assert "VIS-SAMPLE-HX" in refs, f"VIS-SAMPLE-HX missing. refs={refs}"
        assert "VIS-000004" not in refs
        sample = next(e for e in entries if e["ref_number"] == "VIS-SAMPLE-HX")
        assert sample["issue"] == "Hypertension, controlled."
        assert sample["plan"] == "Continue ramipril 10 mg. Bloodwork in 6 months."
        assert sample["date"] == "2026-10-01"
        # most recent first - verify sorting by date desc
        dates = [e["date"] for e in entries]
        assert dates == sorted(dates, reverse=True)

    def test_search_ramipril_one_entry(self, phys_h):
        r = requests.get(URL, headers=phys_h, params={"exclude": EXCLUDE, "search": "ramipril"}, timeout=20)
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["ref_number"] == "VIS-SAMPLE-HX"

    def test_search_zzz_zero(self, phys_h):
        r = requests.get(URL, headers=phys_h, params={"exclude": EXCLUDE, "search": "zzz"}, timeout=20)
        assert r.status_code == 200
        assert r.json()["entries"] == []

    def test_search_date_prefix_matches(self, phys_h):
        r = requests.get(URL, headers=phys_h, params={"exclude": EXCLUDE, "search": "2026-10"}, timeout=20)
        assert r.status_code == 200
        assert len(r.json()["entries"]) >= 1

    def test_invalid_patient_ref_returns_400(self, phys_h):
        r = requests.get(f"{BASE}/api/internal/patients/bogus/issue-plan-history", headers=phys_h, timeout=20)
        assert r.status_code == 400


class TestRoleGating:
    def test_staff_forbidden(self, staff_h):
        r = requests.get(URL, headers=staff_h, params={"exclude": EXCLUDE}, timeout=20)
        assert r.status_code == 403

    def test_admin_ok(self, admin_h):
        r = requests.get(URL, headers=admin_h, params={"exclude": EXCLUDE}, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "entries" in data
        # admin sees entries too (practice-scoped, not physician-filtered)
        assert isinstance(data["entries"], list)
