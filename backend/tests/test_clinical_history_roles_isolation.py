"""Phase 2A4A — role gates (admin/staff) + cross-patient isolation for clinical history endpoints."""
import os
import requests

API = (os.environ.get("REACT_APP_BACKEND_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0]) + "/api"
REF = "directory:c5c30d56-acdd-416b-b61d-5cf8aab06a74"


def _login(ident, pw):
    r = requests.post(f"{API}/auth/login", json={"identifier": ident, "password": pw})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


PHYS = _login("PAGUAYO", "Newman2013_!")
STAFF = _login("staff@visita.demo", "Staff2026!")
ADMIN = _login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")


# -- GET works for all three roles ------------------------------------------------
def test_get_conditions_all_three_roles_200():
    for h in (PHYS, STAFF, ADMIN):
        r = requests.get(f"{API}/internal/patients/{REF}/conditions", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["patient_ref"] == REF


# -- Only physician may write ----------------------------------------------------
def test_admin_cannot_post_condition_403():
    r = requests.post(f"{API}/internal/patients/{REF}/conditions", json={"display_text": "QA admin-blocked"}, headers=ADMIN)
    assert r.status_code == 403


def test_staff_cannot_post_surgery_403():
    r = requests.post(f"{API}/internal/patients/{REF}/surgeries", json={"procedure_text": "QA staff-blocked"}, headers=STAFF)
    assert r.status_code == 403


def test_staff_cannot_post_allergy_403():
    r = requests.post(f"{API}/internal/patients/{REF}/allergies", json={"allergen": "QA staff-blocked", "allergy_type": "DRUG"}, headers=STAFF)
    assert r.status_code == 403


# -- Cross-practice / unresolvable patient_ref ------------------------------------
def test_bogus_patient_ref_400():
    r = requests.get(f"{API}/internal/patients/directory:not-a-real-id/conditions", headers=PHYS)
    assert r.status_code == 400


def test_patch_mismatched_patient_ref_404():
    # Create a condition for REF then try to PATCH it under a different (valid?) ref.
    created = requests.post(f"{API}/internal/patients/{REF}/conditions", json={"display_text": "QA mismatch probe"}, headers=PHYS)
    assert created.status_code == 200
    cid = created.json()["id"]
    other_ref = "directory:00000000-0000-0000-0000-000000000000"
    r = requests.patch(f"{API}/internal/patients/{other_ref}/conditions/{cid}", json={"status": "RESOLVED"}, headers=PHYS)
    assert r.status_code in (400, 404)
    # Clean up the probe by archiving/resolving (no delete route)
    requests.patch(f"{API}/internal/patients/{REF}/conditions/{cid}", json={"status": "HISTORICAL"}, headers=PHYS)


# -- Required field validation ---------------------------------------------------
def test_allergy_requires_type_message():
    r = requests.post(f"{API}/internal/patients/{REF}/allergies", json={"allergen": "QA missing-type"}, headers=PHYS)
    assert r.status_code == 400
    assert "allergy_type" in r.text.lower()
