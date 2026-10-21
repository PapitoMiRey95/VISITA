# Work Hub structured clinical follow-up (types / reasons / details / clinic action / auto message) — regression tests
import os
import json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
CREATED_LOG = "/app/test_reports/work_hub_structured_created_ids.json"
PATIENT = "QA TEMP Patient"
CREATED = []


def _login(body):
    r = requests.post(f"{API}/auth/login", json=body, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}: {r.text[:200]}")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def phys():
    return _login({"identifier": "PAGUAYO", "email": "PAGUAYO", "password": "Aguayo-Preview-2026#Tmp"})


@pytest.fixture(scope="module")
def staff():
    return _login({"email": "staff@visita.demo", "password": "Staff2026!"})


@pytest.fixture(scope="module", autouse=True)
def record_ids():
    yield
    try:
        prev = json.load(open(CREATED_LOG)) if os.path.exists(CREATED_LOG) else []
    except Exception:
        prev = []
    json.dump(prev + CREATED, open(CREATED_LOG, "w"), indent=1)


def _post(s, body):
    r = s.post(f"{API}/internal/work", json={"patient_name": PATIENT, **body}, timeout=30)
    if r.status_code == 200:
        CREATED.append({"id": r.json()["id"], "ref": r.json()["ref_number"], "category": body.get("category")})
    return r


# ---- meta / catalog ----
def test_meta_catalog(phys):
    r = phys.get(f"{API}/internal/work/meta", timeout=30)
    assert r.status_code == 200
    d = r.json()
    keys = [c["key"] for c in d["categories"]]
    assert len(keys) == 12 and "RESULTS" not in keys
    cat = d["catalog"]
    for k in ("clinical_types", "reasons", "details", "clinic_actions", "call_transfer_code"):
        assert k in cat
    assert cat["call_transfer_code"] == "CALL_TRANSFER_ON_ARRIVAL"
    assert len(cat["clinical_types"]) == 6
    assert d["priorities"] == ["NORMAL", "B2", "B1", "ASAP"]


# ---- physician structured create ----
def test_imaging_auto_message(phys):
    r = _post(phys, {"category": "IMAGING", "clinical_detail": {"modality": "MRI", "body_site": "LIVER"}, "reason_code": "DISCUSS_ABNORMAL",
                     "clinic_action": "CALL_TRANSFER_ON_ARRIVAL", "send_to": "CLINIC"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["structured_summary"] == "MRI · Liver"
    assert d["reason_label"] == "Discuss abnormal result"
    assert d["clinic_action_label"] == "Call patient — put through to me when I arrive"
    assert d["message_auto"] is True
    assert d["message"] == "Imaging · MRI · Liver — Discuss abnormal result. Call patient — put through to me when I arrive."
    g = phys.get(f"{API}/internal/work/{d['id']}", timeout=30).json()
    assert g["structured_summary"] == "MRI · Liver" and g["clinical_detail"]["modality"] == {"code": "MRI", "label": "MRI"}
    assert "_id" not in g


def test_imaging_auto_message_deterministic(phys):
    body = {"category": "IMAGING", "clinical_detail": {"modality": "MRI", "body_site": "LIVER"}, "reason_code": "DISCUSS_ABNORMAL",
            "clinic_action": "CALL_TRANSFER_ON_ARRIVAL", "send_to": "CLINIC"}
    a, b = _post(phys, body).json(), _post(phys, body).json()
    assert a["message"] == b["message"]


def test_bloodwork_order(phys):
    r = _post(phys, {"category": "BLOODWORK", "clinical_detail": {"bloodwork_tests": ["CBC", "LP"]}, "reason_code": "REPEAT_BLOODWORK", "send_to": "CLINIC"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["clinical_detail"]["bloodwork_tests"] == [{"code": "CBC", "label": "CBC / Hgb"}, {"code": "LP", "label": "LP / Lipid Profile"}]
    assert d["structured_summary"] == "CBC / Hgb + LP / Lipid Profile"
    r2 = _post(phys, {"category": "BLOODWORK", "clinical_detail": {"bloodwork_tests": ["LP", "CBC"]}, "reason_code": "REPEAT_BLOODWORK", "send_to": "CLINIC"})
    assert r2.json()["structured_summary"] == "LP / Lipid Profile + CBC / Hgb"


def test_referral_reason_sets_subtype(phys):
    r = _post(phys, {"category": "REFERRAL_FOLLOWUP", "reason_code": "DECLINED", "message": "x", "send_to": "CLINIC"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["referral_subtype"] == "DECLINED" and d["message"] == "x" and d["message_auto"] is False


def test_asap_call_transfer_empty_message(phys):
    r = _post(phys, {"category": "CALL_BOOK_PATIENT", "reason_code": "CALL_TRANSFER_ON_ARRIVAL", "priority": "ASAP", "send_to": "CLINIC"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["priority"] == "ASAP" and d["message_auto"] is True
    assert "Book patient as soon as possible." not in d["message"]  # transfer instruction suppresses booking text


def test_other_text(phys):
    r = _post(phys, {"category": "PROCEDURE_SURGERY", "clinical_detail": {"procedure": "OTHER", "other_text": "Vasectomy"}, "reason_code": "BOOK_PROCEDURE", "send_to": "CLINIC"})
    assert r.status_code == 200, r.text
    assert r.json()["structured_summary"] == "Vasectomy"


# ---- validation ----
@pytest.mark.parametrize("body,code", [
    ({"category": "RESULTS", "message": "x", "send_to": "CLINIC"}, 400),
    ({"category": "MESSAGE", "message": "x", "reason_code": "REVIEW_RESULT", "send_to": "CLINIC"}, 400),
    ({"category": "IMAGING", "reason_code": "DECLINED", "send_to": "CLINIC"}, 400),
    ({"category": "IMAGING", "send_to": "CLINIC"}, 400),
    ({"category": "IMAGING", "clinical_detail": {"modality": "PET"}, "send_to": "CLINIC"}, 400),
    ({"category": "IMAGING", "clinical_detail": {"bloodwork_tests": ["CBC"]}, "send_to": "CLINIC"}, 400),
    ({"category": "IMAGING", "clinical_detail": {"modality": ["MRI", "CT"]}, "send_to": "CLINIC"}, 400),
    ({"category": "IMAGING", "clinical_detail": {"modality": "MRI"}, "clinic_action": "BOGUS", "send_to": "CLINIC"}, 400),
])
def test_validation_physician(phys, body, code):
    r = _post(phys, body)
    assert r.status_code == code, r.text
    assert "detail" in r.json()


def test_staff_priority_forbidden(staff):
    r = _post(staff, {"category": "MESSAGE", "message": "x", "priority": "B1", "send_to": "PHYSICIAN"})
    assert r.status_code == 403


# ---- staff attention workflow unchanged ----
def test_staff_referral_to_physician(staff):
    r = _post(staff, {"category": "REFERRAL_FOLLOWUP", "send_to": "PHYSICIAN", "attention_level": "IMPORTANT", "requested_action": "FYI",
                      "reason_code": "MORE_INFO_REQUESTED", "clinic_action": "CALL_PATIENT", "message": "QA staff referral"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["attention_level"] == "IMPORTANT" and d["requested_action"] == "FYI" and d["owner_role"] == "PHYSICIAN"
    assert d["referral_subtype"] == "MORE_INFO_REQUESTED" and d["message"] == "QA staff referral"
    g = staff.get(f"{API}/internal/work/{d['id']}", timeout=30).json()
    assert g["attention_level"] == "IMPORTANT" and g["requested_action"] == "FYI"


# ---- legacy path ----
def test_legacy_message(phys):
    r = _post(phys, {"category": "MESSAGE", "message": "QA legacy msg", "send_to": "CLINIC"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["reason_code"] is None and d["clinical_detail"] is None and d["message_auto"] is False and d["structured_summary"] is None


def test_message_required_normal(phys):
    r = _post(phys, {"category": "MESSAGE", "send_to": "CLINIC"})
    assert r.status_code == 400


def test_legacy_results_items_listed(phys):
    found = []
    for view in ("my", "sent", "waiting", "completed"):
        r = phys.get(f"{API}/internal/work", params={"view": view, "include_completed": True}, timeout=30)
        assert r.status_code == 200
        found += [i for i in r.json()["items"] if i["category"] == "RESULTS"]
    print("legacy RESULTS items visible:", [i["ref_number"] for i in found])
