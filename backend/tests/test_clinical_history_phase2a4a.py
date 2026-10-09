"""Phase 2A4A clinical history (PMHx / PSHx / Allergies) — API regression. Run: pytest tests/test_clinical_history_phase2a4a.py"""
import os
import requests

API = (os.environ.get("REACT_APP_BACKEND_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0]) + "/api"
REF = "directory:c5c30d56-acdd-416b-b61d-5cf8aab06a74"
PORTAL_REF = "patient:977ca75a-70bd-48ae-89eb-51e92bff46df"


def _login(ident, pw):
    r = requests.post(f"{API}/auth/login", json={"identifier": ident, "password": pw})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


PHYS = _login("PAGUAYO", "Newman2013_!")
STAFF = _login("staff@visita.demo", "Staff2026!")


def test_condition_add_edit_status():
    r = requests.post(f"{API}/internal/patients/{REF}/conditions", json={"display_text": "TEST Asthma"}, headers=PHYS)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "ACTIVE" and c["patient_ref"] == REF and c["practice_id"]
    r = requests.patch(f"{API}/internal/patients/{REF}/conditions/{c['id']}", json={"notes": "mild", "status": "RESOLVED"}, headers=PHYS)
    assert r.status_code == 200 and r.json()["status"] == "RESOLVED" and r.json()["notes"] == "mild"
    items = requests.get(f"{API}/internal/patients/{REF}/conditions", headers=PHYS).json()["items"]
    assert any(i["id"] == c["id"] for i in items)
    assert items[0]["status"] == "ACTIVE"  # active first


def test_surgery_optional_blank_and_archive():
    r = requests.post(f"{API}/internal/patients/{REF}/surgeries", json={"procedure_text": "TEST Tonsillectomy"}, headers=PHYS)
    assert r.status_code == 200 and r.json()["procedure_date"] is None
    sid = r.json()["id"]
    assert requests.patch(f"{API}/internal/patients/{REF}/surgeries/{sid}", json={"status": "ARCHIVED"}, headers=PHYS).json()["status"] == "ARCHIVED"
    assert requests.post(f"{API}/internal/patients/{REF}/surgeries", json={"procedure_text": "x", "procedure_date": "bad"}, headers=PHYS).status_code == 400


def test_allergy_minimal_and_toggle():
    assert requests.post(f"{API}/internal/patients/{REF}/allergies", json={"allergen": "TEST Latex"}, headers=PHYS).status_code == 400
    r = requests.post(f"{API}/internal/patients/{REF}/allergies", json={"allergen": "TEST Latex", "allergy_type": "OTHER"}, headers=PHYS)
    assert r.status_code == 200 and r.json()["reaction"] is None and r.json()["severity"] is None
    aid = r.json()["id"]
    assert requests.patch(f"{API}/internal/patients/{REF}/allergies/{aid}", json={"severity": "BAD"}, headers=PHYS).status_code == 400
    assert requests.patch(f"{API}/internal/patients/{REF}/allergies/{aid}", json={"status": "INACTIVE", "severity": "MILD"}, headers=PHYS).json()["status"] == "INACTIVE"


def test_staff_read_only():
    assert requests.get(f"{API}/internal/patients/{REF}/allergies", headers=STAFF).status_code == 200
    assert requests.post(f"{API}/internal/patients/{REF}/allergies", json={"allergen": "x", "allergy_type": "DRUG"}, headers=STAFF).status_code == 403


def test_portal_and_directory_refs_share_history():
    a = requests.get(f"{API}/internal/patients/{REF}/conditions", headers=PHYS).json()
    b = requests.get(f"{API}/internal/patients/{PORTAL_REF}/conditions", headers=PHYS).json()
    assert a["patient_ref"] == b["patient_ref"] == REF
    assert [i["id"] for i in a["items"]] == [i["id"] for i in b["items"]]


def test_no_delete_route():
    assert requests.delete(f"{API}/internal/patients/{REF}/conditions/SYNTH-COND-HTN", headers=PHYS).status_code in (404, 405)
