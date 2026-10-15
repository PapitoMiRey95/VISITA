"""Identity Duplicate Prevention regression tests (synthetic patients only)."""
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
IDS = {}


@pytest.fixture(scope="module")
def staff():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": "staff@visita.demo", "password": "Staff2026!"})
    assert r.status_code == 200, r.text
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"})
    return s


def _syn(staff):
    r = staff.get(f"{BASE}/api/internal/verifications")
    assert r.status_code == 200, r.text
    data = r.json()
    items = data if isinstance(data, list) else data.get("items", [])
    return [i for i in items if i.get("id", "").startswith("syn-")]


def test_01_verifications_list(staff):
    syn = _syn(staff)
    assert len(syn) == 4, f"expected 4 synthetic pending items, got {len(syn)}"
    by_id = {i["id"]: i for i in syn}

    # Categorize
    pat_A = next((i for i in syn if i["identity_state"] in ("LINK_PENDING", "IDENTITY_REVIEW_REQUIRED") and "ALPHAVILLE" in i.get("full_name", "")), None)
    pat_B = next((i for i in syn if i["identity_state"] == "IDENTITY_REVIEW_REQUIRED" and i.get("live_strength") == "review"), None)
    pat_C = next((i for i in syn if i["identity_state"] == "NEW_PATIENT_CANDIDATE"), None)
    pat_D2 = next((i for i in syn if i["identity_state"] == "IDENTITY_REVIEW_REQUIRED" and i.get("live_strength") == "strong" and i["id"] != (pat_A or {}).get("id")), None)

    assert pat_A, f"pat_A missing: {[(i['id'], i['identity_state']) for i in syn]}"
    assert pat_B, "pat_B review missing"
    assert pat_C, "pat_C new missing"
    assert pat_D2, "pat_D2 strong missing"

    # pat_B review live_candidates[0].match_kind == POSSIBLE_IDENTITY_REVIEW
    cands_B = pat_B.get("live_candidates") or []
    assert cands_B and cands_B[0].get("match_kind") == "POSSIBLE_IDENTITY_REVIEW"

    # pat_C NEW_PATIENT_CANDIDATE empty live_candidates
    assert not (pat_C.get("live_candidates") or [])

    IDS["pat_A"] = pat_A["id"]
    IDS["pat_B"] = pat_B["id"]
    IDS["pat_C"] = pat_C["id"]
    IDS["pat_D2"] = pat_D2["id"]

    # dir_A: pat_A live_candidates[0].id (or matched_directory_id)
    pa_live = pat_A.get("live_candidates") or []
    dm = pat_A.get("directory_match") or {}
    IDS["dir_A"] = (pa_live[0].get("id") if pa_live else None) or pat_A.get("matched_directory_id") or (dm.get("candidates") or [{}])[0].get("id")
    # dir_D: pat_D2 live_candidates[0].id or directory_match
    pd_live = pat_D2.get("live_candidates") or []
    IDS["dir_D"] = (pd_live[0].get("id") if pd_live else None) or pat_D2.get("matched_directory_id")
    assert IDS["dir_A"] and IDS["dir_D"], f"dir ids missing: dir_A={IDS['dir_A']} dir_D={IDS['dir_D']}"


def test_02_verify_pat_A_with_confirm_new_blocked(staff):
    r = staff.post(f"{BASE}/api/internal/verifications/{IDS['pat_A']}", json={"decision": "verified", "confirm_new_patient": True})
    assert r.status_code == 409, f"{r.status_code} {r.text}"
    detail = r.json().get("detail") or r.json()
    assert detail.get("code") == "IDENTITY_LINK_REQUIRED", detail
    assert detail.get("candidates"), f"candidates missing: {detail}"

    # Still pending, no PIN
    syn = _syn(staff)
    pa = next((i for i in syn if i["id"] == IDS["pat_A"]), None)
    assert pa is not None, "pat_A dropped from pending"
    assert not pa.get("visita_patient_id")


def test_03_verify_pat_B_review_blocked(staff):
    r = staff.post(f"{BASE}/api/internal/verifications/{IDS['pat_B']}", json={"decision": "verified", "confirm_new_patient": True})
    assert r.status_code == 409, r.text
    d = r.json().get("detail") or r.json()
    assert d.get("code") == "IDENTITY_LINK_REQUIRED", d
    assert d.get("strength") == "review", d


def test_04_verify_pat_C_requires_confirmation_then_succeeds(staff):
    r1 = staff.post(f"{BASE}/api/internal/verifications/{IDS['pat_C']}", json={"decision": "verified"})
    assert r1.status_code == 409, r1.text
    d1 = r1.json().get("detail") or r1.json()
    assert d1.get("code") == "NEW_PATIENT_CONFIRMATION_REQUIRED", d1

    r2 = staff.post(f"{BASE}/api/internal/verifications/{IDS['pat_C']}", json={"decision": "verified", "confirm_new_patient": True})
    assert r2.status_code == 200, r2.text


def test_05_link_pat_D2_to_dir_D_blocked(staff):
    r = staff.post(f"{BASE}/api/internal/patients/{IDS['pat_D2']}/link-directory", json={"directory_id": IDS["dir_D"]})
    assert r.status_code == 409, r.text
    d = r.json().get("detail") or r.json()
    assert d.get("code") == "DIRECTORY_ALREADY_LINKED", d


def test_06_link_pat_D1_to_dir_A_blocked(staff):
    # Find pat_D1 via patient-lookup: syn-pat-* that's portal_linked and not pat_A
    r = staff.get(f"{BASE}/api/internal/patient-lookup", params={"q": "synthetic", "include_pin": "false"})
    assert r.status_code == 200, r.text
    rows = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    pat_D1 = None
    for row in rows:
        pid = row.get("patient_id") or ""
        if pid.startswith("syn-pat-") and row.get("portal_linked") and pid != IDS["pat_A"]:
            pat_D1 = pid
            break
    assert pat_D1, f"pat_D1 not found via lookup: {rows}"
    IDS["pat_D1"] = pat_D1
    r2 = staff.post(f"{BASE}/api/internal/patients/{pat_D1}/link-directory", json={"directory_id": IDS["dir_A"]})
    assert r2.status_code == 409, r2.text
    d = r2.json().get("detail") or r2.json()
    assert d.get("code") == "PORTAL_ALREADY_LINKED", d


def test_07_link_pat_A_and_verify(staff):
    r = staff.post(f"{BASE}/api/internal/patients/{IDS['pat_A']}/link-directory", json={"directory_id": IDS["dir_A"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("visita_patient_id") == "9901", body

    r2 = staff.post(f"{BASE}/api/internal/verifications/{IDS['pat_A']}", json={"decision": "verified"})
    assert r2.status_code == 200, r2.text


def test_08_patient_lookup_collapsed_alphaville(staff):
    r = staff.get(f"{BASE}/api/internal/patient-lookup", params={"q": "synthetic alphaville", "include_pin": "false"})
    assert r.status_code == 200, r.text
    rows = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    assert len(rows) == 1, f"expected 1 collapsed row, got {len(rows)}: {rows}"
    row = rows[0]
    assert row.get("source") == "directory", row
    assert "SYNTHETIC ALPHAVILLE" in (row.get("full_name") or "").upper(), row
    assert row.get("visita_patient_id") == "9901", row
    assert row.get("portal_linked") is True, row
    assert row.get("patient_id") == IDS["pat_A"], row


def test_09_regression_visit_audit():
    r = requests.post(f"{BASE}/api/auth/login", json={"identifier": "PAGUAYO", "password": "Newman2013_!"})
    if r.status_code != 200:
        pytest.skip(f"physician login failed: {r.status_code}")
    tok = r.json()["token"]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}"})
    # Try physician visits list
    for path in ["/api/internal/physician/visits", "/api/internal/visits"]:
        rr = s.get(f"{BASE}{path}")
        if rr.status_code == 200:
            data = rr.json()
            visits = data if isinstance(data, list) else data.get("items") or data.get("visits") or []
            if visits:
                vid = visits[0].get("id") or visits[0].get("visit_id")
                if vid:
                    r2 = s.get(f"{BASE}/api/internal/audit/visit/{vid}")
                    assert r2.status_code == 200, r2.text
                    return
    pytest.skip("no visits available to test audit endpoint")
