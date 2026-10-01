"""Tests for Smart Medication List + Refill (2026-06 preview).

Covers:
- GET /portal/medications (self + delegate + unauthorized)
- POST /portal/refill-requests (single, multi/batch, longer-supply)
- POST /portal/prescriptions/photo (no medication_list mutation)
- Admin internal queue visibility + attachment download
"""
import io
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

PATIENT_EMAIL = "maria.lopez@demo.com"
PATIENT_PW = "Patient2026!"
LINDA_PID = "2f4d3a87-1bce-4c30-8212-cf10e64ce3fc"
ADMIN_EMAIL = "kevinrodriguez9528@gmail.com"
ADMIN_PW = "VisitaAdmin2026!"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def patient_token():
    return _login(PATIENT_EMAIL, PATIENT_PW)


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PW)


@pytest.fixture(scope="module")
def auth(patient_token):
    return {"Authorization": f"Bearer {patient_token}"}


@pytest.fixture(scope="module")
def admin_auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---- GET /portal/medications -----------------------------------------------
class TestPortalMedications:
    def test_self_list(self, auth):
        r = requests.get(f"{API}/portal/medications", headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["pharmacy_label"] == "1670 Dufferin Drug Mart"
        drugs = {m["drug"] for m in data["medications"]}
        # Maria's 3 seeded actives
        assert "Metformin" in drugs
        assert "Ramipril" in drugs
        assert "Atorvastatin" in drugs
        assert len(data["medications"]) == 3

    def test_delegate_linda(self, auth):
        r = requests.get(f"{API}/portal/medications?on_behalf_of={LINDA_PID}",
                         headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        drugs = {m["drug"] for m in r.json()["medications"]}
        assert "Levothyroxine" in drugs
        assert "Amlodipine" in drugs

    def test_unauthorized_patient_404(self, auth):
        bogus = str(uuid.uuid4())
        r = requests.get(f"{API}/portal/medications?on_behalf_of={bogus}",
                         headers=auth, timeout=20)
        assert r.status_code == 404


# ---- POST /portal/refill-requests ------------------------------------------
class TestRefill:
    def test_single_standard(self, auth):
        meds = requests.get(f"{API}/portal/medications", headers=auth, timeout=20).json()["medications"]
        mid = meds[0]["id"]
        r = requests.post(f"{API}/portal/refill-requests", headers=auth,
                          json={"medication_ids": [mid], "supply_type": "standard",
                                "requested_months": 2, "patient_note": "TEST please"},
                          timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["count"] == 1
        assert len(data["requests"]) == 1
        req = data["requests"][0]
        assert req["batch_id"] == data["batch_id"]
        assert req["supply_type"] == "standard"
        assert req["requested_months"] == 2
        assert req["destination_pharmacy_label"] == "1670 Dufferin Drug Mart"
        assert req["source"] == "patient_refill"
        assert req["internal_status"] == "received"
        assert req["patient_note"] == "TEST please"

    def test_multi_shared_batch(self, auth, admin_auth):
        meds = requests.get(f"{API}/portal/medications", headers=auth, timeout=20).json()["medications"]
        ids = [m["id"] for m in meds]
        r = requests.post(f"{API}/portal/refill-requests", headers=auth,
                          json={"medication_ids": ids, "supply_type": "standard",
                                "requested_months": 3},
                          timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["count"] == len(ids)
        batch_ids = {req["batch_id"] for req in data["requests"]}
        assert len(batch_ids) == 1
        # Admin internal queue should see them
        q = requests.get(f"{API}/internal/prescriptions", headers=admin_auth, timeout=20)
        assert q.status_code == 200
        items = q.json() if isinstance(q.json(), list) else q.json().get("items", [])
        seen = [it for it in items if it.get("batch_id") == data["batch_id"]]
        assert len(seen) == len(ids), f"Expected {len(ids)} items in queue for batch, saw {len(seen)}"

    def test_longer_supply_not_auto_approved(self, auth):
        meds = requests.get(f"{API}/portal/medications", headers=auth, timeout=20).json()["medications"]
        mid = meds[0]["id"]
        r = requests.post(f"{API}/portal/refill-requests", headers=auth,
                          json={"medication_ids": [mid], "supply_type": "longer",
                                "requested_months": 6, "travel_note": "TEST travel"},
                          timeout=20)
        assert r.status_code == 200
        req = r.json()["requests"][0]
        assert req["supply_type"] == "longer"
        assert req["internal_status"] == "received"
        assert req["travel_note"] == "TEST travel"
        assert "6" in req["requested_supply_text"]

    def test_longer_other_free_text(self, auth):
        meds = requests.get(f"{API}/portal/medications", headers=auth, timeout=20).json()["medications"]
        mid = meds[0]["id"]
        r = requests.post(f"{API}/portal/refill-requests", headers=auth,
                          json={"medication_ids": [mid], "supply_type": "longer",
                                "requested_supply_text": "12 months - sabbatical"},
                          timeout=20)
        assert r.status_code == 200
        req = r.json()["requests"][0]
        assert req["supply_type"] == "longer"
        assert "sabbatical" in req["requested_supply_text"]
        assert req["internal_status"] == "received"

    def test_empty_selection_400(self, auth):
        r = requests.post(f"{API}/portal/refill-requests", headers=auth,
                          json={"medication_ids": [], "supply_type": "standard"}, timeout=20)
        assert r.status_code == 400

    def test_delegate_refill_on_behalf(self, auth, admin_auth):
        meds = requests.get(f"{API}/portal/medications?on_behalf_of={LINDA_PID}",
                            headers=auth, timeout=20).json()["medications"]
        mid = meds[0]["id"]
        r = requests.post(f"{API}/portal/refill-requests?on_behalf_of={LINDA_PID}",
                          headers=auth,
                          json={"medication_ids": [mid], "supply_type": "standard",
                                "requested_months": 1},
                          timeout=20)
        assert r.status_code == 200
        req = r.json()["requests"][0]
        assert req["patient_name"].startswith("Nguyen"), req["patient_name"]


# ---- POST /portal/prescriptions/photo --------------------------------------
class TestPhotoPath:
    def test_photo_submission_no_med_list_mutation(self, auth, admin_auth):
        before = requests.get(f"{API}/portal/medications", headers=auth, timeout=20).json()
        before_count = len(before["medications"])

        png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        files = {"file": ("test.png", io.BytesIO(png), "image/png")}
        data = {"medication_name": "TEST Mystery Pill", "patient_note": "TEST photo note"}
        r = requests.post(f"{API}/portal/prescriptions/photo", headers=auth,
                          files=files, data=data, timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["source"] == "patient_photo"
        assert doc["review_required"] is True
        assert doc["medication_name"] == "TEST Mystery Pill"
        assert doc.get("attachment")
        rid = doc["id"]

        # Official list unchanged
        after = requests.get(f"{API}/portal/medications", headers=auth, timeout=20).json()
        assert len(after["medications"]) == before_count

        # Admin internal queue sees it with downloadable attachment
        q = requests.get(f"{API}/internal/prescriptions", headers=admin_auth, timeout=20)
        items = q.json() if isinstance(q.json(), list) else q.json().get("items", [])
        found = next((it for it in items if it.get("id") == rid), None)
        assert found is not None, "Photo request not in admin internal queue"
        a = requests.get(f"{API}/internal/prescriptions/{rid}/attachment",
                         headers=admin_auth, timeout=20, allow_redirects=True)
        assert a.status_code == 200, f"Attachment download failed: {a.status_code}"


# ---- Regression: existing queue still renders ------------------------------
class TestRegressionQueue:
    def test_internal_prescriptions_200(self, admin_auth):
        r = requests.get(f"{API}/internal/prescriptions", headers=admin_auth, timeout=20)
        assert r.status_code == 200
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        # should have at least our newly created entries
        assert len(items) > 0
