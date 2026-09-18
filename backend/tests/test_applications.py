"""Backend tests for VISITA Patient Applications workflow (former + new-patient).

Covers:
- POST /api/auth/register: former detection, active match, unmatched
- POST /api/applications/return-request, /api/applications/new-patient
- GET /api/internal/applications (filters, staff/physician access)
- PATCH /api/internal/applications/{id} (staff cannot accept; physician can; former_return accept flips directory)
- GET /api/internal/counters includes 'applications'
- GET /api/internal/verifications exposes review_queue + directory_match
- GET /api/internal/directory?q= search
"""
import os
import uuid
import time
import pytest
import requests

def _read_frontend_env():
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE = _read_frontend_env().rstrip("/") + "/api"

STAFF = ("staff@visita.demo", "Staff2026!")
ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
PHYS_USER = "PAGUAYO"
PHYS_TEMP = "Aguayo#Temp2026"
PHYS_NEW = "AguayoTest#2026New"  # used only for the duration of this run


def _login(identifier, password):
    r = requests.post(f"{BASE}/auth/login", json={"identifier": identifier, "password": password}, timeout=15)
    return r


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def staff_token():
    r = _login(*STAFF)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    r = _login(*ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def physician_token():
    # try temp -> may be forced change; try new-password fallback
    r = _login(PHYS_USER, PHYS_TEMP)
    if r.status_code == 200 and r.json().get("user", {}).get("must_change_password"):
        token = r.json()["token"]
        rc = requests.post(f"{BASE}/auth/change-password",
                           json={"current_password": PHYS_TEMP, "new_password": PHYS_NEW},
                           headers=_auth(token), timeout=15)
        assert rc.status_code == 200, rc.text
        # re-login with new pwd
        r2 = _login(PHYS_USER, PHYS_NEW)
        assert r2.status_code == 200, r2.text
        yield r2.json()["token"]
        # teardown: reset password back to temp + must_change_password true
        try:
            token2 = _login(PHYS_USER, PHYS_NEW).json()["token"]
            requests.post(f"{BASE}/auth/change-password",
                          json={"current_password": PHYS_NEW, "new_password": PHYS_TEMP},
                          headers=_auth(token2), timeout=15)
        except Exception:
            pass
        return
    if r.status_code == 200:
        yield r.json()["token"]
        return
    # try with saved new pwd if temp already changed
    r3 = _login(PHYS_USER, PHYS_NEW)
    if r3.status_code == 200:
        yield r3.json()["token"]
        return
    pytest.skip(f"physician login failed: {r.status_code} {r.text}")


def _uniq_email(tag):
    return f"TEST_{tag}_{uuid.uuid4().hex[:8]}@example.com"


# ---------- REGISTER: former, active, unmatched ----------

class TestRegister:
    def test_former_detected_no_account_created(self):
        payload = {
            "patient_type": "ohip",
            "first_name": "Ahmed Mohammed", "last_name": "KUTBI",
            "date_of_birth": "1990-01-21", "health_card_number": "0000000005",
            "phone": "4165550001",
            "email": _uniq_email("former"),
            "password": "TestPass123!",
            "province": "ON",
        }
        r = requests.post(f"{BASE}/auth/register", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("former_detected") is True
        assert "message" in data and data["message"]
        assert "prefill" in data
        assert data["prefill"]["email"] == payload["email"].lower()
        assert "token" not in data
        # verify no user created
        r2 = _login(payload["email"], payload["password"])
        assert r2.status_code == 401

    def test_active_match_creates_account_with_active_review_queue(self, staff_token):
        payload = {
            "patient_type": "ohip",
            "first_name": "Alejandro", "last_name": "ROMERO CUAHUEY",
            "date_of_birth": "1958-04-22", "health_card_number": "0000000111",
            "phone": "4165550002",
            "email": _uniq_email("active"),
            "password": "TestPass123!",
            "province": "ON",
        }
        r = requests.post(f"{BASE}/auth/register", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data
        assert data["user"]["email"] == payload["email"].lower()
        # verify via internal/verifications
        vr = requests.get(f"{BASE}/internal/verifications", headers=_auth(staff_token), timeout=15)
        assert vr.status_code == 200
        rows = vr.json()
        mine = [v for v in rows if v.get("email") == payload["email"].lower()]
        assert mine, "new active-match patient not in verifications"
        v = mine[0]
        assert v.get("review_queue") == "ACTIVE_MATCH"
        dm = v.get("directory_match") or {}
        assert dm.get("outcome") == "ACTIVE_MATCH"
        assert dm.get("candidates"), "directory_match.candidates missing"

    def test_unmatched_creates_account_with_unmatched_review_queue(self, staff_token):
        uniq = uuid.uuid4().hex[:8].upper()
        payload = {
            "patient_type": "ohip",
            "first_name": f"TestFN{uniq}", "last_name": f"TestLN{uniq}",
            "date_of_birth": "1970-05-15", "health_card_number": f"99{uniq[:8]}",
            "phone": "4165550003",
            "email": _uniq_email("unmatched"),
            "password": "TestPass123!",
            "province": "ON",
        }
        r = requests.post(f"{BASE}/auth/register", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        assert "token" in r.json()
        vr = requests.get(f"{BASE}/internal/verifications", headers=_auth(staff_token), timeout=15)
        rows = vr.json()
        mine = [v for v in rows if v.get("email") == payload["email"].lower()]
        assert mine
        assert mine[0].get("review_queue") == "UNMATCHED_CURRENT_PATIENT"


# ---------- APPLICATIONS: return-request + new-patient (public) ----------

@pytest.fixture(scope="module")
def former_return_app_id():
    payload = {
        "first_name": "Ahmed Mohammed", "last_name": "KUTBI",
        "date_of_birth": "1990-01-21", "health_card_number": "0000000005",
        "phone": "4165550010", "email": _uniq_email("return"),
        "city": "Toronto", "province": "ON", "postal_code": "M1A1A1",
        "patient_message": "Please re-establish care",
    }
    r = requests.post(f"{BASE}/applications/return-request", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["ref_number"].startswith("APP-")
    assert "message" in data and data["message"]
    return {"ref": data["ref_number"], "payload": payload}


@pytest.fixture(scope="module")
def new_patient_app_id():
    payload = {
        "first_name": "NewPt", "last_name": f"Applicant{uuid.uuid4().hex[:6]}",
        "date_of_birth": "1985-03-10",
        "phone": "4165550020", "email": _uniq_email("newpt"),
        "city": "Toronto", "province": "ON", "country": "Canada",
        "patient_message": "Looking for a family doctor",
    }
    r = requests.post(f"{BASE}/applications/new-patient", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["ref_number"].startswith("APP-")
    return {"ref": data["ref_number"], "payload": payload}


class TestApplicationsPublic:
    def test_former_return_created(self, former_return_app_id):
        assert former_return_app_id["ref"].startswith("APP-")

    def test_new_patient_created(self, new_patient_app_id):
        assert new_patient_app_id["ref"].startswith("APP-")


# ---------- INTERNAL: list, filter, counter ----------

class TestInternalListAndCounters:
    def test_list_and_filters(self, staff_token, former_return_app_id, new_patient_app_id):
        rf = requests.get(f"{BASE}/internal/applications?type=former_return", headers=_auth(staff_token), timeout=15)
        assert rf.status_code == 200
        refs = [a["ref_number"] for a in rf.json()]
        assert former_return_app_id["ref"] in refs
        assert new_patient_app_id["ref"] not in refs
        rn = requests.get(f"{BASE}/internal/applications?type=new_patient", headers=_auth(staff_token), timeout=15)
        assert rn.status_code == 200
        refs2 = [a["ref_number"] for a in rn.json()]
        assert new_patient_app_id["ref"] in refs2
        assert former_return_app_id["ref"] not in refs2
        ra = requests.get(f"{BASE}/internal/applications", headers=_auth(staff_token), timeout=15)
        all_refs = [a["ref_number"] for a in ra.json()]
        assert former_return_app_id["ref"] in all_refs
        assert new_patient_app_id["ref"] in all_refs

    def test_counters_include_applications_staff(self, staff_token, former_return_app_id, new_patient_app_id):
        r = requests.get(f"{BASE}/internal/counters", headers=_auth(staff_token), timeout=15)
        assert r.status_code == 200
        c = r.json()["counters"]
        assert "applications" in c
        assert c["applications"] >= 2

    def test_counters_include_applications_physician(self, physician_token):
        r = requests.get(f"{BASE}/internal/counters", headers=_auth(physician_token), timeout=15)
        assert r.status_code == 200
        assert "applications" in r.json()["counters"]

    def test_directory_search(self, staff_token):
        r = requests.get(f"{BASE}/internal/directory?q=KUTBI", headers=_auth(staff_token), timeout=15)
        assert r.status_code == 200
        rows = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        assert any("KUTBI" in (x.get("last_name") or "").upper() for x in rows)


# ---------- PATCH: staff cannot accept, physician can + directory flip ----------

def _get_app_id_by_ref(token, ref):
    r = requests.get(f"{BASE}/internal/applications", headers=_auth(token), timeout=15)
    for a in r.json():
        if a["ref_number"] == ref:
            return a["id"]
    return None


class TestApplicationUpdate:
    def test_staff_cannot_accept(self, staff_token, new_patient_app_id):
        app_id = _get_app_id_by_ref(staff_token, new_patient_app_id["ref"])
        assert app_id
        r = requests.patch(f"{BASE}/internal/applications/{app_id}",
                           json={"action": "accept"}, headers=_auth(staff_token), timeout=15)
        assert r.status_code == 403, r.text

    def test_staff_can_do_intermediate_actions(self, staff_token, new_patient_app_id):
        app_id = _get_app_id_by_ref(staff_token, new_patient_app_id["ref"])
        # waitlist
        r = requests.patch(f"{BASE}/internal/applications/{app_id}",
                           json={"action": "waitlist", "internal_note": "TEST note"},
                           headers=_auth(staff_token), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["internal_status"] == "WAITING_LIST"
        # review
        r = requests.patch(f"{BASE}/internal/applications/{app_id}",
                           json={"action": "review"}, headers=_auth(staff_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["internal_status"] == "UNDER_REVIEW"
        # send_to_physician
        r = requests.patch(f"{BASE}/internal/applications/{app_id}",
                           json={"action": "send_to_physician"}, headers=_auth(staff_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["internal_status"] == "SENT_TO_PHYSICIAN"

    def test_physician_accepts_former_return_flips_directory(self, physician_token, staff_token, former_return_app_id):
        app_id = _get_app_id_by_ref(staff_token, former_return_app_id["ref"])
        assert app_id
        r = requests.patch(f"{BASE}/internal/applications/{app_id}",
                           json={"action": "accept"}, headers=_auth(physician_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["internal_status"] == "ACCEPTED"
        assert body.get("accepted_by")
        # follow-up: registering same person should NOT be former_detected anymore
        time.sleep(0.5)
        followup = {
            "patient_type": "ohip",
            "first_name": "Ahmed Mohammed", "last_name": "KUTBI",
            "date_of_birth": "1990-01-21", "health_card_number": "0000000005",
            "phone": "4165550099",
            "email": _uniq_email("reactivated"),
            "password": "TestPass123!",
            "province": "ON",
        }
        r2 = requests.post(f"{BASE}/auth/register", json=followup, timeout=15)
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data.get("former_detected") is not True
        assert "token" in data
