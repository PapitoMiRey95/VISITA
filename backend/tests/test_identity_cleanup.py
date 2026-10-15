"""Identity Cleanup backend tests (synthetic ids only). PREVIEW."""
import os
import sys
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
# Reads /app/frontend/.env fallback if env not set
if "REACT_APP_BACKEND_URL" not in os.environ:
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass

STAFF_EMAIL = "staff@visita.demo"
STAFF_PW = os.environ["TEST_STAFF_PASSWORD"]
PATIENT_EMAIL = "maria.lopez@demo.com"
PATIENT_PW = "Patient2026!"

# IDs come from create_cleanup output passed via env
IDS = {
    "A": (os.environ.get("A_PAT"), os.environ.get("A_DIR")),
    "B": (os.environ.get("B_PAT"), os.environ.get("B_DIR")),
    "C": (os.environ.get("C_PAT"), os.environ.get("C_DIR")),
    "D": (os.environ.get("D_PAT"), os.environ.get("D_DIR")),
    "E": (os.environ.get("E_PAT"), os.environ.get("E_DIR")),
    "F2": (os.environ.get("F2_PAT"), os.environ.get("F2_DIR")),
    "F1": os.environ.get("F1_PAT"),
    "G": (os.environ.get("G_PAT"), os.environ.get("G_DIR")),
    "H": (os.environ.get("H_PAT"), os.environ.get("H_DIR")),
}


@pytest.fixture(scope="session")
def staff_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PW})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def patient_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": PATIENT_EMAIL, "password": PATIENT_PW})
    if r.status_code != 200:
        pytest.skip("patient login failed")
    return r.json()["token"]


@pytest.fixture(scope="session")
def sh(staff_token):
    return {"Authorization": f"Bearer {staff_token}"}


# --- Queue & authz ---
def test_queue_returns_synthetic_classes(sh):
    r = requests.get(f"{BASE_URL}/api/internal/identity-cleanup", headers=sh)
    assert r.status_code == 200, r.text
    rows = r.json()
    by_pat = {row["portal"]["id"]: row for row in rows}
    expected = {
        IDS["A"][0]: "SAFE_LINK_CANDIDATE",
        IDS["B"][0]: "SAFE_LINK_CANDIDATE",
        IDS["C"][0]: "SAFE_LINK_CANDIDATE",
        IDS["D"][0]: "POSSIBLE_MATCH_REVIEW",
        IDS["E"][0]: "HALF_LINK",
        IDS["F2"][0]: "MULTIPLE_PORTAL_ACCOUNTS",
        IDS["G"][0]: "CLINICAL_HISTORY_REVIEW_REQUIRED",
        IDS["H"][0]: "IDENTITY_CONFLICT",
    }
    for pid, cls in expected.items():
        assert pid in by_pat, f"missing portal {pid} in queue"
        assert by_pat[pid]["class"] == cls, f"{pid} expected {cls}, got {by_pat[pid]['class']}"
    # D evidence
    d_ev = by_pat[IDS["D"][0]]["evidence"]
    assert "EXACT_DOB" in d_ev and "SHORTENED_NAME" in d_ev


def test_authz_patient_blocked(patient_token):
    r = requests.get(f"{BASE_URL}/api/internal/identity-cleanup",
                     headers={"Authorization": f"Bearer {patient_token}"})
    assert r.status_code in (401, 403)


def test_case_detail_g_has_clinical(sh):
    pid, did = IDS["G"]
    r = requests.get(f"{BASE_URL}/api/internal/identity-cleanup/{pid}?directory_id={did}", headers=sh)
    assert r.status_code == 200
    data = r.json()
    assert data["class"] == "CLINICAL_HISTORY_REVIEW_REQUIRED"
    assert data["dependencies"]["portal"]["visits"] == 1
    assert data["dependencies"]["portal"]["has_clinical"] is True
    assert data["can_link"] is False


def test_apply_fields_before_link_409(sh):
    pid, did = IDS["B"]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/apply-fields",
                      headers=sh, json={"directory_id": did, "selections": []})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NOT_LINKED"


# --- A: safe link ---
def test_a_link_and_lookup(sh):
    pid, did = IDS["A"]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/link",
                      headers=sh, json={"directory_id": did})
    assert r.status_code == 200, r.text
    assert r.json()["visita_patient_id"] == "9911"
    # lookup
    r = requests.get(f"{BASE_URL}/api/internal/patient-lookup",
                     headers=sh, params={"q": "synthclean alpha", "include_pin": "false"})
    assert r.status_code == 200
    data = r.json()
    if isinstance(data, dict):
        data = data.get("items", [])
    hits = [x for x in data if x.get("visita_patient_id") == "9911" or x.get("pin") == "9911"]
    assert len(hits) == 1, f"expected exactly one row with PIN 9911, got {hits}"
    hit = hits[0]
    assert hit.get("source") == "directory"
    assert hit.get("portal_linked") in (True, "true")


# --- B: link, apply fields, complete ---
def test_b_link_apply_complete(sh):
    pid, did = IDS["B"]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/link",
                      headers=sh, json={"directory_id": did})
    assert r.status_code == 200, r.text
    sel = [{"field": "health_card_expiry_date", "action": "USE_PORTAL"},
           {"field": "email", "action": "USE_PORTAL"}]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/apply-fields",
                      headers=sh, json={"directory_id": did, "selections": sel})
    assert r.status_code == 200, r.text
    applied = r.json()["applied"]
    fields = {a["field"] for a in applied}
    assert "health_card_expiry_date" in fields and "email" in fields
    # verify via case
    r = requests.get(f"{BASE_URL}/api/internal/identity-cleanup/{pid}?directory_id={did}", headers=sh)
    exp = next(f for f in r.json()["fields"] if f["field"] == "health_card_expiry_date")
    assert exp["canonical"] == "2029-03-28"
    # complete
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/complete",
                      headers=sh, json={"outcome": "completed"})
    assert r.status_code == 200
    # no longer in queue
    r = requests.get(f"{BASE_URL}/api/internal/identity-cleanup", headers=sh)
    assert all(row["portal"]["id"] != pid for row in r.json())


# --- C: link, apply only cell_phone, keep address ---
def test_c_link_apply_mixed(sh):
    pid, did = IDS["C"]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/link",
                      headers=sh, json={"directory_id": did})
    assert r.status_code == 200, r.text
    sel = [{"field": "cell_phone", "action": "USE_PORTAL"},
           {"field": "address", "action": "KEEP_CANONICAL"}]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/apply-fields",
                      headers=sh, json={"directory_id": did, "selections": sel})
    assert r.status_code == 200
    data = r.json()
    applied_fields = {a["field"] for a in data["applied"]}
    assert "cell_phone" in applied_fields
    assert "address" not in applied_fields
    # verify address unchanged
    r = requests.get(f"{BASE_URL}/api/internal/identity-cleanup/{pid}?directory_id={did}", headers=sh)
    addr = next(f for f in r.json()["fields"] if f["field"] == "address")
    assert addr["canonical"] == "1 Old Test Rd"


# --- D: possible match, identity-critical name ---
def test_d_link_and_name_critical(sh):
    pid, did = IDS["D"]
    # case detail: name CONFLICT with KEEP_CANONICAL
    r = requests.get(f"{BASE_URL}/api/internal/identity-cleanup/{pid}?directory_id={did}", headers=sh)
    assert r.status_code == 200
    name_row = next(f for f in r.json()["fields"] if f["field"] == "name")
    assert name_row["state"] == "CONFLICT"
    assert name_row["recommendation"] == "KEEP_CANONICAL"
    # link
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/link",
                      headers=sh, json={"directory_id": did})
    assert r.status_code == 200, r.text
    assert r.json()["visita_patient_id"] == "9914"
    # apply name USE_PORTAL without confirm → skipped
    sel = [{"field": "name", "action": "USE_PORTAL"}]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/apply-fields",
                      headers=sh, json={"directory_id": did, "selections": sel})
    assert r.status_code == 200
    data = r.json()
    assert data["applied"] == []
    assert any(s["reason"] == "IDENTITY_CRITICAL_CONFIRMATION_REQUIRED" for s in data["skipped"])
    # with confirm
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/apply-fields",
                      headers=sh, json={"directory_id": did, "selections": sel, "confirm_identity_critical": True})
    assert r.status_code == 200
    assert any(a["field"] == "name" for a in r.json()["applied"])


# --- E: half-link repair ---
def test_e_half_link_repair(sh):
    pid, did = IDS["E"]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/repair-half-link",
                      headers=sh, json={"directory_id": did})
    assert r.status_code == 200, r.text
    # verify both sides consistent via case
    r = requests.get(f"{BASE_URL}/api/internal/identity-cleanup/{pid}?directory_id={did}", headers=sh)
    assert r.json()["link_state"] == "LINKED"


# --- F2: multi-portal, G: clinical, H: conflict → 409 ---
def test_f2_multi_portal_blocked(sh):
    pid, did = IDS["F2"]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/link",
                      headers=sh, json={"directory_id": did})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "MULTIPLE_PORTAL_ACCOUNTS"


def test_g_clinical_blocked(sh):
    pid, did = IDS["G"]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/link",
                      headers=sh, json={"directory_id": did})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CLINICAL_HISTORY_REVIEW_REQUIRED"


def test_h_identity_conflict_blocked(sh):
    pid, did = IDS["H"]
    r = requests.post(f"{BASE_URL}/api/internal/identity-cleanup/{pid}/link",
                      headers=sh, json={"directory_id": did})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "IDENTITY_CONFLICT"


# --- Regression ---
def test_verifications_regression(sh):
    r = requests.get(f"{BASE_URL}/api/internal/verifications", headers=sh)
    assert r.status_code == 200
