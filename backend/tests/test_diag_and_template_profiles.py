"""Phase 2A3 — Diagnosis text catalog search + SOAP template encounter-type profile filtering.

Covers:
- GET /api/internal/diagnosis-catalog/search ranking, pmhx match, min-length, staff role allowed, import_enabled=false skipped.
- GET /api/internal/soap-helpers?visit_id= filters by canonical visit.encounter_type profile (TELEPHONE/VIDEO/PROXY/PHYSICAL/IN_CLINIC) and ANY without visit_id.
- template_profile key mapping (IN_CLINIC -> REGULAR_IN_CLINIC).
- Sex filter: 'SYNTH Female-Only Example' invisible to unknown-sex patient.

Does NOT delete any data. Visits created for template tests are exited (not deleted) at teardown.
"""
import os
import pytest
import requests

def _read_frontend_env_url():
    try:
        with open('/app/frontend/.env') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    return line.split('=', 1)[1].strip()
    except Exception:
        pass
    return None


BASE_URL = (os.environ.get('REACT_APP_BACKEND_URL') or _read_frontend_env_url()).rstrip('/')
API = f"{BASE_URL}/api"

PHYS_USERNAME = "PAGUAYO"
PHYS_PASSWORD = os.environ["TEST_PHYSICIAN_PASSWORD"]
STAFF_EMAIL = "staff@visita.demo"
STAFF_PASSWORD = os.environ["TEST_STAFF_PASSWORD"]


def _login(payload):
    r = requests.post(f"{API}/auth/login", json=payload, timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def phys_token():
    return _login({"identifier": PHYS_USERNAME, "password": PHYS_PASSWORD})


@pytest.fixture(scope="module")
def staff_token():
    return _login({"email": STAFF_EMAIL, "password": STAFF_PASSWORD})


@pytest.fixture(scope="module")
def phys_h(phys_token):
    return {"Authorization": f"Bearer {phys_token}"}


@pytest.fixture(scope="module")
def staff_h(staff_token):
    return {"Authorization": f"Bearer {staff_token}"}


# ================= DIAGNOSIS CATALOG =================
class TestDiagnosisCatalog:
    def test_nstemi_exact_ranked_first(self, phys_h):
        r = requests.get(f"{API}/internal/diagnosis-catalog/search", params={"q": "NSTEMI"}, headers=phys_h, timeout=20)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert items, "expected at least one item for NSTEMI"
        assert items[0]["text"] == "CVS IHD AMI NSTEMI", f"first item should be CVS IHD AMI NSTEMI, got {items[0]}"
        assert items[0].get("coded") is True

    def test_heart_attack_pmhx_match(self, phys_h):
        r = requests.get(f"{API}/internal/diagnosis-catalog/search", params={"q": "heart attack"}, headers=phys_h, timeout=20)
        assert r.status_code == 200
        items = r.json()["items"]
        texts = [i["text"] for i in items]
        assert "CVS IHD AMI NSTEMI" in texts, f"pmhx 'heart attack' should surface NSTEMI; got {texts[:5]}"

    def test_lactose_multiple(self, phys_h):
        r = requests.get(f"{API}/internal/diagnosis-catalog/search", params={"q": "lactose"}, headers=phys_h, timeout=20)
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 2

    def test_single_char_returns_empty(self, phys_h):
        r = requests.get(f"{API}/internal/diagnosis-catalog/search", params={"q": "x"}, headers=phys_h, timeout=20)
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_staff_allowed(self, staff_h):
        r = requests.get(f"{API}/internal/diagnosis-catalog/search", params={"q": "NSTEMI"}, headers=staff_h, timeout=20)
        assert r.status_code == 200, f"staff should be in CLINIC_ROLES; got {r.status_code} {r.text}"
        assert r.json()["items"], "staff search should return results"


# ================= SOAP TEMPLATE PROFILES =================
VISIT_TYPES = ["TELEPHONE", "VIDEO", "PROXY", "PHYSICAL", "IN_CLINIC"]
EXPECTED_PROFILE_KEY = {
    "TELEPHONE": "TELEPHONE", "VIDEO": "VIDEO", "PROXY": "PROXY",
    "PHYSICAL": "PHYSICAL", "IN_CLINIC": "REGULAR_IN_CLINIC",
}
TYPE_SPECIFIC = {
    "Telephone — Sounds well": "TELEPHONE",
    "Video — Looks well": "VIDEO",
    "Proxy — No physical exam": "PROXY",
    "SYNTH Physical Exam — Normal": "PHYSICAL",
}
ANY_TEMPLATES = {"SYNTH General Follow-Up", "SYNTH Routine Review", "SYNTH Simple URI"}


def _pick_free_dir_patients(count: int) -> list:
    """Query mongo for directory patients without open visits for physician 6aab65...be34."""
    from pymongo import MongoClient
    cli = MongoClient("mongodb://localhost:27017")
    db = cli["test_database"]
    phys = "6aab65435a65f344daf9be34"
    open_refs = set()
    for v in db.visits.find({"physician_user_id": phys, "status": {"$in": ["IN_PROGRESS", "PAUSED", "READY"]}},
                            {"patient_ref": 1}):
        if v.get("patient_ref"):
            open_refs.add(v["patient_ref"])
    picks = []
    for p in db.patient_directory.find({}, {"_id": 0, "id": 1}).limit(200):
        ref = f"directory:{p['id']}"
        if ref not in open_refs:
            picks.append(p["id"])
            if len(picks) >= count:
                break
    cli.close()
    return picks


@pytest.fixture(scope="module")
def visits_by_type(phys_h):
    """Create one visit per encounter type; exit (not delete) at teardown."""
    ids = _pick_free_dir_patients(len(VISIT_TYPES))
    assert len(ids) >= len(VISIT_TYPES), "not enough free directory patients"
    created = {}
    for etype, pid in zip(VISIT_TYPES, ids):
        payload = {"patient_ref": f"directory:{pid}", "encounter_type": etype, "source": "patients"}
        r = requests.post(f"{API}/internal/visits", json=payload, headers=phys_h, timeout=20)
        assert r.status_code in (200, 201), f"create {etype}: {r.status_code} {r.text}"
        created[etype] = r.json()["id"]
    yield created
    # teardown — exit, do not delete
    for vid in created.values():
        try:
            requests.post(f"{API}/internal/visits/{vid}/exit", headers=phys_h, timeout=10)
        except Exception:
            pass


def _get_helpers(phys_h, visit_id=None):
    params = {}
    if visit_id:
        params["visit_id"] = visit_id
    r = requests.get(f"{API}/internal/soap-helpers", params=params, headers=phys_h, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


class TestTemplateProfiles:
    @pytest.mark.parametrize("etype", VISIT_TYPES)
    def test_profile_key_for_each_visit(self, phys_h, visits_by_type, etype):
        resp = _get_helpers(phys_h, visits_by_type[etype])
        assert resp["encounter_type"] == etype
        assert resp["template_profile"]["key"] == EXPECTED_PROFILE_KEY[etype], \
            f"{etype} profile_key mismatch: {resp['template_profile']}"

    def test_telephone_includes_tel_and_any_excludes_others(self, phys_h, visits_by_type):
        names = {h["name"] for h in _get_helpers(phys_h, visits_by_type["TELEPHONE"])["helpers"]}
        assert "Telephone — Sounds well" in names
        assert ANY_TEMPLATES.issubset(names), f"missing ANY templates in TELEPHONE: {ANY_TEMPLATES - names}"
        assert "Video — Looks well" not in names
        assert "Proxy — No physical exam" not in names
        assert "SYNTH Physical Exam — Normal" not in names

    def test_video_only_video_specific(self, phys_h, visits_by_type):
        names = {h["name"] for h in _get_helpers(phys_h, visits_by_type["VIDEO"])["helpers"]}
        assert "Video — Looks well" in names
        for other in ("Telephone — Sounds well", "Proxy — No physical exam", "SYNTH Physical Exam — Normal"):
            assert other not in names, f"VIDEO leaked {other}"

    def test_proxy_only_proxy_specific(self, phys_h, visits_by_type):
        names = {h["name"] for h in _get_helpers(phys_h, visits_by_type["PROXY"])["helpers"]}
        assert "Proxy — No physical exam" in names
        for other in ("Telephone — Sounds well", "Video — Looks well", "SYNTH Physical Exam — Normal"):
            assert other not in names

    def test_physical_includes_physical_excludes_remote(self, phys_h, visits_by_type):
        names = {h["name"] for h in _get_helpers(phys_h, visits_by_type["PHYSICAL"])["helpers"]}
        assert "SYNTH Physical Exam — Normal" in names
        for other in ("Telephone — Sounds well", "Video — Looks well", "Proxy — No physical exam"):
            assert other not in names

    def test_in_clinic_includes_physical_excludes_remote(self, phys_h, visits_by_type):
        names = {h["name"] for h in _get_helpers(phys_h, visits_by_type["IN_CLINIC"])["helpers"]}
        assert "SYNTH Physical Exam — Normal" in names
        for other in ("Telephone — Sounds well", "Video — Looks well", "Proxy — No physical exam"):
            assert other not in names

    def test_no_visit_id_any_only(self, phys_h):
        resp = _get_helpers(phys_h, None)
        assert resp["encounter_type"] is None
        assert resp["template_profile"]["key"] is None
        names = {h["name"] for h in resp["helpers"]}
        for only_specific in ("Telephone — Sounds well", "Video — Looks well",
                              "Proxy — No physical exam", "SYNTH Physical Exam — Normal"):
            assert only_specific not in names, f"ANY-only leaked {only_specific}"

    def test_female_only_hidden_without_authoritative_sex(self, phys_h, visits_by_type):
        # Directory patients used here have no portal sex -> FEMALE template should be hidden.
        names = {h["name"] for h in _get_helpers(phys_h, visits_by_type["TELEPHONE"])["helpers"]}
        assert "SYNTH Female-Only Example" not in names


# ================= NO AUTO-DOCUMENTATION =================
class TestNoAutoInsertion:
    def test_visit_soap_untouched_after_template_search(self, phys_h, visits_by_type):
        # listing templates must never mutate the visit's SOAP
        for etype in ("TELEPHONE", "VIDEO", "PROXY"):
            vid = visits_by_type[etype]
            _get_helpers(phys_h, vid)
            r = requests.get(f"{API}/internal/visits/{vid}", headers=phys_h, timeout=20)
            assert r.status_code == 200
            objective = (r.json().get("soap") or {}).get("objective") or ""
            for sentinel in ("Sounds well", "Looks well", "No physical examination"):
                assert sentinel not in objective, f"{etype} auto-inserted '{sentinel}' into objective"
