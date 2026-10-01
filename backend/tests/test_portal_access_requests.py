"""Phase A: public portal_access_requests intake + staff review (approve/decline).

Covers:
- public POST /api/portal-access-requests validates + creates PENDING with no grant
- staff list / approve / decline flows
- approve creates ACTIVE patient_portal_delegates grant with the 4 v1 permissions
- approve returns 404 for a non-existent / mismatched patient
- freshly-created caregiver can log in with the one-time temp password,
  has role=caregiver, patient_id=null, must_change_password=true,
  and GET /api/portal/my-delegations returns the managed patient with the 4 perms
- existing caregiver (maria.lopez) still manages Linda
- on_behalf_of guard: caregiver blocked for unmanaged patient
"""
import os
import uuid
import pytest
import requests


def _read_frontend_env():
    try:
        with open('/app/frontend/.env') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    return line.split('=', 1)[1].strip()
    except Exception:
        pass
    return None


BASE_URL = (os.environ.get('REACT_APP_BACKEND_URL') or _read_frontend_env()).rstrip('/')
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "kevinrodriguez9528@gmail.com"
ADMIN_PW = "VisitaAdmin2026!"
MARIA_EMAIL = "maria.lopez@demo.com"
MARIA_PW = "Patient2026!"
CAREGIVER_EMAIL = "robert.helper.qa@demo.com"
CAREGIVER_PW = "Patient2026!"
LINDA_PATIENT_ID = "2f4d3a87-1bce-4c30-8212-cf10e64ce3fc"
PRACTICE_SLUG = "dr-aguayo"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_hdr():
    return _hdr(_login(ADMIN_EMAIL, ADMIN_PW)["token"])


def _mk_payload(email=None, relationship="Son", basis="Patient consent"):
    suffix = uuid.uuid4().hex[:8]
    return {
        "practice_slug": PRACTICE_SLUG,
        "patient_first_name": "Linda",
        "patient_last_name": "Nguyen",
        "patient_date_of_birth": "1958-04-22",
        "first_name": "QA",
        "last_name": f"Caregiver{suffix}",
        "email": email or f"qa.caregiver.{suffix}@demo.com",
        "phone": "4165551234",
        "relationship": relationship,
        "authorization_basis": basis,
        "note": "automated qa",
    }


def _submit_and_fetch(admin_hdr, payload):
    r = requests.post(f"{API}/portal-access-requests", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    lst = requests.get(f"{API}/internal/portal-access-requests",
                       params={"status": "PENDING"}, headers=admin_hdr, timeout=30).json()
    rec = next(x for x in lst if x["requester_email"] == payload["email"])
    return r.json(), rec


# ---------- Public intake ----------
class TestPublicIntake:
    def test_public_submit_creates_pending(self, admin_hdr):
        payload = _mk_payload()
        data, rec = _submit_and_fetch(admin_hdr, payload)
        assert data["ok"] is True
        assert data["ref_number"].startswith("PAR-")
        assert rec["status"] == "PENDING"
        assert rec["linked_patient_id"] is None
        assert rec["resulting_delegate_id"] is None
        assert rec["relationship"] == payload["relationship"]
        assert rec["authorization_basis"] == payload["authorization_basis"]
        assert rec["practice_slug"] == PRACTICE_SLUG

    def test_invalid_email(self):
        p = _mk_payload(); p["email"] = "not-an-email"
        assert requests.post(f"{API}/portal-access-requests", json=p, timeout=30).status_code == 400

    def test_invalid_relationship(self):
        assert requests.post(f"{API}/portal-access-requests",
                             json=_mk_payload(relationship="Foo"), timeout=30).status_code == 400

    def test_invalid_basis(self):
        assert requests.post(f"{API}/portal-access-requests",
                             json=_mk_payload(basis="Nothing"), timeout=30).status_code == 400

    def test_unknown_practice(self):
        p = _mk_payload(); p["practice_slug"] = "does-not-exist-xyz"
        assert requests.post(f"{API}/portal-access-requests", json=p, timeout=30).status_code == 400


# ---------- Approve + fresh caregiver flow ----------
@pytest.fixture(scope="module")
def approved_caregiver(admin_hdr):
    """Submit + approve a new request so we have a freshly-created caregiver account."""
    payload = _mk_payload()
    _, rec = _submit_and_fetch(admin_hdr, payload)
    ap = requests.post(f"{API}/internal/portal-access-requests/{rec['id']}/approve",
                       json={"patient_id": LINDA_PATIENT_ID}, headers=admin_hdr, timeout=30)
    assert ap.status_code == 200, ap.text
    out = ap.json()
    return {"payload": payload, "request_id": rec["id"], **out}


class TestApproveFlow:
    def test_approve_creates_grant_with_4_perms(self, approved_caregiver, admin_hdr):
        out = approved_caregiver
        assert out["ok"] is True
        assert out["patient_id"] == LINDA_PATIENT_ID
        assert out["grant_id"].startswith("del_")
        assert "temp_password" in out and len(out["temp_password"]) >= 6

        # second approve => 409
        ap2 = requests.post(f"{API}/internal/portal-access-requests/{out['request_id']}/approve",
                            json={"patient_id": LINDA_PATIENT_ID}, headers=admin_hdr, timeout=30)
        assert ap2.status_code == 409

        # verify APPROVED linkage
        all_req = requests.get(f"{API}/internal/portal-access-requests", headers=admin_hdr, timeout=30).json()
        rec2 = next(x for x in all_req if x["id"] == out["request_id"])
        assert rec2["status"] == "APPROVED"
        assert rec2["linked_patient_id"] == LINDA_PATIENT_ID
        assert rec2["resulting_delegate_id"] == out["grant_id"]

    def test_fresh_caregiver_login_and_delegations(self, approved_caregiver):
        payload = approved_caregiver["payload"]
        login = requests.post(f"{API}/auth/login",
                              json={"email": payload["email"], "password": approved_caregiver["temp_password"]},
                              timeout=30)
        assert login.status_code == 200, login.text
        u = login.json()["user"]
        assert u.get("role") == "caregiver"
        assert not u.get("patient_id")
        assert u.get("must_change_password") is True

        mg = requests.get(f"{API}/portal/my-delegations", headers=_hdr(login.json()["token"]), timeout=30)
        assert mg.status_code == 200
        body = mg.json()
        # endpoint returns {"has_own_patient": bool, "managing": [...]}
        assert body.get("has_own_patient") is False
        managed = body.get("managing", [])
        linda = [d for d in managed if d.get("patient_id") == LINDA_PATIENT_ID]
        assert len(linda) == 1
        assert set(linda[0]["permissions"]) == {"APPOINTMENTS", "RX_REQUESTS", "DOCUMENTS", "REQUEST_STATUS"}

    def test_approve_bad_patient_404(self, admin_hdr):
        _, rec = _submit_and_fetch(admin_hdr, _mk_payload())
        bad = requests.post(f"{API}/internal/portal-access-requests/{rec['id']}/approve",
                            json={"patient_id": "nonexistent-" + uuid.uuid4().hex},
                            headers=admin_hdr, timeout=30)
        assert bad.status_code == 404


# ---------- Decline ----------
class TestDeclineFlow:
    def test_decline_leaves_no_grant(self, admin_hdr):
        _, rec = _submit_and_fetch(admin_hdr, _mk_payload())
        req_id = rec["id"]
        dc = requests.post(f"{API}/internal/portal-access-requests/{req_id}/decline",
                           json={"review_note": "qa decline"}, headers=admin_hdr, timeout=30)
        assert dc.status_code == 200
        assert dc.json()["ok"] is True
        dc2 = requests.post(f"{API}/internal/portal-access-requests/{req_id}/decline",
                            json={}, headers=admin_hdr, timeout=30)
        assert dc2.status_code == 409
        all_req = requests.get(f"{API}/internal/portal-access-requests", headers=admin_hdr, timeout=30).json()
        rec2 = next(x for x in all_req if x["id"] == req_id)
        assert rec2["status"] == "DECLINED"
        assert rec2["linked_patient_id"] is None
        assert rec2["resulting_delegate_id"] is None


# ---------- Existing caregiver regression + authz ----------
class TestExistingCaregiverRegression:
    def test_maria_still_manages_linda(self):
        tok = _login(MARIA_EMAIL, MARIA_PW)["token"]
        r = requests.get(f"{API}/portal/my-delegations", headers=_hdr(tok), timeout=30)
        assert r.status_code == 200
        managed = r.json().get("managing", [])
        linda = [d for d in managed if d.get("patient_id") == LINDA_PATIENT_ID]
        assert len(linda) == 1

    def test_caregiver_only_robert_my_delegations(self):
        # Documented credential — if password drifted, main-agent needs to re-seed. Skip gracefully.
        r = requests.post(f"{API}/auth/login",
                          json={"email": CAREGIVER_EMAIL, "password": CAREGIVER_PW}, timeout=30)
        if r.status_code != 200:
            pytest.skip(f"robert.helper.qa login not accepting documented password: {r.status_code}")
        tok = r.json()["token"]
        mg = requests.get(f"{API}/portal/my-delegations", headers=_hdr(tok), timeout=30).json()
        linda = [d for d in mg.get("managing", []) if d.get("patient_id") == LINDA_PATIENT_ID]
        assert len(linda) == 1
        assert set(linda[0]["permissions"]) == {"APPOINTMENTS", "RX_REQUESTS", "DOCUMENTS", "REQUEST_STATUS"}


class TestAuthzGuard:
    def test_on_behalf_of_blocked_for_unmanaged_patient(self, approved_caregiver):
        """A freshly-created caregiver cannot act for a patient they don't manage."""
        payload = approved_caregiver["payload"]
        login = requests.post(f"{API}/auth/login",
                              json={"email": payload["email"], "password": approved_caregiver["temp_password"]},
                              timeout=30)
        assert login.status_code == 200
        tok = login.json()["token"]
        # Try to list appointments on behalf of some other patient (maria's own patient_id)
        mtok_resp = _login(MARIA_EMAIL, MARIA_PW)
        other_pid = mtok_resp.get("user", {}).get("patient_id")
        if not other_pid:
            pytest.skip("could not resolve maria's patient_id")
        if other_pid == LINDA_PATIENT_ID:
            pytest.skip("maria's own patient_id matches linda — skip")
        # Use /portal/managed/{patient_id}/summary — must 404 for unmanaged patient
        r = requests.get(f"{API}/portal/managed/{other_pid}/summary",
                         headers=_hdr(tok), timeout=30)
        assert r.status_code in (401, 403, 404), f"expected block, got {r.status_code}: {r.text[:200]}"
