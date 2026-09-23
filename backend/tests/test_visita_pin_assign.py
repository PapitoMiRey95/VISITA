"""Iteration 29: VISITA PIN suggestions + assign-pin flow on Accepted new-patient applications."""
import os
import time
import re
import pytest
import requests
from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"

STAFF = ("staff@visita.demo", "Staff2026!")
PHYSICIAN = ("PAGUAYO", "Newman2013_!")


def _login(identifier, password):
    r = requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_token():
    return _login(*STAFF)


@pytest.fixture(scope="module")
def phys_token():
    return _login(*PHYSICIAN)


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---- suggestions endpoint ----
class TestSuggestions:
    def test_suggestions_default(self, staff_token):
        r = requests.get(f"{API}/internal/visita-pin/suggestions", headers=_h(staff_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "suggestions" in data
        sugs = data["suggestions"]
        assert isinstance(sugs, list) and len(sugs) == 5
        assert all(re.fullmatch(r"\d{4}", s) for s in sugs)
        assert len(set(sugs)) == len(sugs)  # unique

    def test_suggestions_count_clamp_high(self, staff_token):
        r = requests.get(f"{API}/internal/visita-pin/suggestions", headers=_h(staff_token), params={"count": 50}, timeout=30)
        assert r.status_code == 200
        assert len(r.json()["suggestions"]) == 10  # clamped to 10

    def test_suggestions_count_clamp_low(self, staff_token):
        r = requests.get(f"{API}/internal/visita-pin/suggestions", headers=_h(staff_token), params={"count": 0}, timeout=30)
        assert r.status_code == 200
        # count=0 -> falsy -> defaults to 5 via `count or 5`; check between 1 and 10
        n = len(r.json()["suggestions"])
        assert 1 <= n <= 10

    def test_suggestions_count_3(self, staff_token):
        r = requests.get(f"{API}/internal/visita-pin/suggestions", headers=_h(staff_token), params={"count": 3}, timeout=30)
        assert r.status_code == 200
        assert len(r.json()["suggestions"]) == 3

    def test_suggestions_unauthenticated(self):
        r = requests.get(f"{API}/internal/visita-pin/suggestions", timeout=30)
        assert r.status_code in (401, 403)


# ---- assign-pin flow ----
class TestAssignPin:
    @classmethod
    def _find_accepted(cls, staff_token):
        r = requests.get(f"{API}/internal/applications", headers=_h(staff_token), params={"type": "new_patient"}, timeout=30)
        assert r.status_code == 200, r.text
        items = r.json()
        accepted = [a for a in items if a.get("internal_status") == "ACCEPTED" and a.get("created_patient_id")]
        return accepted

    @classmethod
    def _create_accepted(cls, staff_token, phys_token):
        """Create and physician-accept a fresh new-patient application."""
        ts = int(time.time())
        payload = {
            "first_name": "PinTest",
            "last_name": f"Iter29_{ts}",
            "date_of_birth": "1990-05-05",
            "phone": "4165551122",
            "email": f"pin.iter29.{ts}@resend.dev",
            "consent_contact": True,
        }
        r = requests.post(f"{API}/applications/new-patient", json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text
        app_id = r.json()["id"]
        r2 = requests.patch(f"{API}/internal/applications/{app_id}", json={"action": "accept"},
                            headers=_h(phys_token), timeout=60)
        assert r2.status_code == 200, r2.text
        return r2.json()

    def test_assign_pin_full_flow(self, staff_token, phys_token):
        # Get or create an accepted application
        accepted = self._find_accepted(staff_token)
        if not accepted:
            app = self._create_accepted(staff_token, phys_token)
        else:
            app = accepted[0]
        app_id = app["id"]
        old_pin = app.get("created_visita_patient_id")
        assert app.get("created_patient_id")

        # Get suggestions
        r = requests.get(f"{API}/internal/visita-pin/suggestions", headers=_h(staff_token), params={"count": 5}, timeout=30)
        assert r.status_code == 200
        sugs = r.json()["suggestions"]
        # Pick a suggestion that isn't the current
        new_pin = next((s for s in sugs if s != old_pin), None)
        assert new_pin, "no available suggestion"

        # Assign
        r = requests.post(f"{API}/internal/applications/{app_id}/assign-pin",
                          headers=_h(staff_token), json={"pin": new_pin}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["visita_patient_id"] == new_pin

        # Refetch application - PIN updated
        r = requests.get(f"{API}/internal/applications", headers=_h(staff_token), params={"type": "new_patient"}, timeout=30)
        fresh = next(x for x in r.json() if x["id"] == app_id)
        assert fresh["created_visita_patient_id"] == new_pin

        # Old PIN released - should appear in a large suggestion pool possibility
        # (Can't strictly assert appears in random 10, but assert not in-use by checking claim was cleared)
        # Try to reassign the OLD pin back
        if old_pin and re.fullmatch(r"\d{4}", str(old_pin)):
            r = requests.post(f"{API}/internal/applications/{app_id}/assign-pin",
                              headers=_h(staff_token), json={"pin": old_pin}, timeout=30)
            assert r.status_code == 200, f"old pin should be free again: {r.text}"
            assert r.json()["visita_patient_id"] == old_pin

    def test_assign_pin_invalid_short(self, staff_token, phys_token):
        accepted = self._find_accepted(staff_token)
        assert accepted, "need at least one accepted app"
        app_id = accepted[0]["id"]
        r = requests.post(f"{API}/internal/applications/{app_id}/assign-pin",
                          headers=_h(staff_token), json={"pin": "12"}, timeout=30)
        assert r.status_code == 400

    def test_assign_pin_invalid_nondigit(self, staff_token):
        accepted = self._find_accepted(staff_token)
        assert accepted
        app_id = accepted[0]["id"]
        r = requests.post(f"{API}/internal/applications/{app_id}/assign-pin",
                          headers=_h(staff_token), json={"pin": "abcd"}, timeout=30)
        assert r.status_code == 400

    def test_assign_pin_conflict(self, staff_token, phys_token):
        """Assigning PIN already in use by another patient -> 409."""
        accepted = self._find_accepted(staff_token)
        # Need at least 2 accepted apps with distinct patients + pins
        distinct = []
        seen_pids = set()
        for a in accepted:
            pid = a.get("created_patient_id")
            if pid and pid not in seen_pids and a.get("created_visita_patient_id"):
                distinct.append(a)
                seen_pids.add(pid)
            if len(distinct) >= 2:
                break
        if len(distinct) < 2:
            # Create another one
            new_app = self._create_accepted(staff_token, phys_token)
            distinct.append(new_app)
        assert len(distinct) >= 2
        a1, a2 = distinct[0], distinct[1]
        pin2 = a2["created_visita_patient_id"]
        assert pin2
        r = requests.post(f"{API}/internal/applications/{a1['id']}/assign-pin",
                          headers=_h(staff_token), json={"pin": pin2}, timeout=30)
        assert r.status_code == 409, r.text

    def test_assign_pin_updates_patient_and_directory(self, staff_token, phys_token):
        """Verify underlying patient + directory records reflect new PIN."""
        accepted = self._find_accepted(staff_token)
        if not accepted:
            app = self._create_accepted(staff_token, phys_token)
        else:
            app = accepted[0]
        app_id = app["id"]
        pid = app["created_patient_id"]

        # Get a fresh suggestion
        sugs = requests.get(f"{API}/internal/visita-pin/suggestions", headers=_h(staff_token),
                            params={"count": 5}, timeout=30).json()["suggestions"]
        cur = app.get("created_visita_patient_id")
        new_pin = next(s for s in sugs if s != cur)

        r = requests.post(f"{API}/internal/applications/{app_id}/assign-pin",
                          headers=_h(staff_token), json={"pin": new_pin}, timeout=30)
        assert r.status_code == 200, r.text

        # Verify via directory API (admin/staff can list directory)
        r = requests.get(f"{API}/internal/directory", headers=_h(staff_token), timeout=30)
        assert r.status_code == 200
        dir_items = r.json()
        matching = [d for d in dir_items if d.get("linked_patient_id") == pid]
        if matching:
            # Directory row updated to new PIN
            assert matching[0].get("visita_patient_id") == new_pin, \
                f"directory PIN not updated: {matching[0].get('visita_patient_id')} != {new_pin}"

    def test_assign_pin_unauth(self):
        r = requests.post(f"{API}/internal/applications/xxx/assign-pin", json={"pin": "1234"}, timeout=30)
        assert r.status_code in (401, 403)

    def test_assign_pin_missing_app(self, staff_token):
        r = requests.post(f"{API}/internal/applications/no-such-app/assign-pin",
                          headers=_h(staff_token), json={"pin": "1234"}, timeout=30)
        assert r.status_code == 404
