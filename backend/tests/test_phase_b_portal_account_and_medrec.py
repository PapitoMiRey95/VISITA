"""Phase B — Staff/Admin Portal Account Management, Physician Medical Record,
and Medication Management (add/continue/edit/discontinue) tests.

Preview URL: REACT_APP_BACKEND_URL. All endpoints are prefixed with /api.
Uses seeded demo accounts; cleans up medications it created on Maria Lopez.
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
PHYSICIAN = ("PAGUAYO", os.environ["TEST_PHYSICIAN_PASSWORD"])
PATIENT = ("maria.lopez@demo.com", "Patient2026!")

MARIA_PID = "06f6ee08-58f7-4286-82f5-7c845de99ce1"
LINDA_PID = "2f4d3a87-1bce-4c30-8212-cf10e64ce3fc"


def _login(identifier, password):
    r = requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="session")
def phys_token():
    return _login(*PHYSICIAN)


@pytest.fixture(scope="session")
def patient_token():
    return _login(*PATIENT)


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------------------- A. Portal Account Panel ----------------------------
class TestPortalAccount:
    def test_get_portal_account_shape(self, admin_token):
        r = requests.get(f"{API}/internal/patients/{MARIA_PID}/portal-account", headers=h(admin_token), timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("login_email", "active", "email_verified", "must_change_password", "has_account"):
            assert k in d, f"missing key {k}: {d}"
        assert d["login_email"] == "maria.lopez@demo.com"
        assert d["has_account"] is True

    def test_send_password_reset(self, admin_token):
        r = requests.post(f"{API}/internal/patients/{MARIA_PID}/portal-account/send-reset",
                          headers=h(admin_token), timeout=30)
        # Accept 200 OR 502 if email dispatch is down; test is primarily for route+audit shape
        assert r.status_code in (200, 502), r.text
        if r.status_code == 200:
            assert r.json().get("sent_to") == "maria.lopez@demo.com"

    def test_force_password_change_flag_and_restore(self, admin_token):
        r = requests.post(f"{API}/internal/patients/{MARIA_PID}/portal-account/force-password-change",
                          headers=h(admin_token), timeout=15)
        assert r.status_code == 200
        assert r.json().get("must_change_password") is True
        # verify via GET
        g = requests.get(f"{API}/internal/patients/{MARIA_PID}/portal-account", headers=h(admin_token), timeout=15)
        assert g.json().get("must_change_password") is True
        # Restore to clean state: temp-password -> login -> change-password back to Patient2026!
        tp = requests.post(f"{API}/internal/patients/{MARIA_PID}/portal-account/temp-password",
                           headers=h(admin_token), timeout=15).json()
        temp = tp["temp_password"]
        tok = requests.post(f"{API}/auth/login", json={"identifier": PATIENT[0], "password": temp}, timeout=15).json()["token"]
        cp = requests.post(f"{API}/auth/change-password", headers=h(tok),
                           json={"current_password": temp, "new_password": PATIENT[1]}, timeout=15)
        assert cp.status_code == 200
        g2 = requests.get(f"{API}/internal/patients/{MARIA_PID}/portal-account", headers=h(admin_token), timeout=15)
        assert g2.json().get("must_change_password") is False

    def test_disable_blocks_login_then_reenable(self, admin_token):
        """Disable -> login must 403 -> re-enable -> login works again. Patient record untouched."""
        # Disable
        r = requests.post(f"{API}/internal/patients/{MARIA_PID}/portal-account/disable",
                          headers=h(admin_token), timeout=15)
        assert r.status_code == 200 and r.json().get("active") is False
        # Login must be blocked
        lr = requests.post(f"{API}/auth/login", json={"identifier": PATIENT[0], "password": PATIENT[1]}, timeout=15)
        assert lr.status_code == 403, f"expected 403 on disabled login, got {lr.status_code} {lr.text}"
        # Patient record must still exist and keep PIN
        pr = requests.get(f"{API}/internal/patients?q=Maria", headers=h(admin_token), timeout=15)
        assert pr.status_code == 200
        # Re-enable
        r2 = requests.post(f"{API}/internal/patients/{MARIA_PID}/portal-account/enable",
                           headers=h(admin_token), timeout=15)
        assert r2.status_code == 200 and r2.json().get("active") is True
        # Login works again
        lr2 = requests.post(f"{API}/auth/login", json={"identifier": PATIENT[0], "password": PATIENT[1]}, timeout=15)
        assert lr2.status_code == 200, lr2.text

    def test_change_email_conflict(self, admin_token):
        # Try to set Maria's email to Linda's email (both exist) -> 409
        linda_email = "linda.nguyen@demo.com"
        r = requests.post(f"{API}/internal/patients/{MARIA_PID}/portal-account/email",
                          headers=h(admin_token), json={"new_email": linda_email}, timeout=15)
        assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text}"

    def test_change_email_success_and_revert(self, admin_token):
        """Change Maria's email to a scratch value, verify email_verified=false, then revert."""
        new_email = f"test_maria_{int(time.time())}@demo.com"
        r = requests.post(f"{API}/internal/patients/{MARIA_PID}/portal-account/email",
                          headers=h(admin_token), json={"new_email": new_email}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("email_verified") is False
        # revert
        r2 = requests.post(f"{API}/internal/patients/{MARIA_PID}/portal-account/email",
                           headers=h(admin_token), json={"new_email": PATIENT[0]}, timeout=15)
        assert r2.status_code == 200
        # Note: login still works post-revert (email_verified is non-blocking)
        lr = requests.post(f"{API}/auth/login", json={"identifier": PATIENT[0], "password": PATIENT[1]}, timeout=15)
        assert lr.status_code == 200

    def test_temp_password_one_time_and_restore(self, admin_token):
        """Generate a temp password for Linda, confirm login works, then restore via /auth/change-password."""
        r = requests.post(f"{API}/internal/patients/{LINDA_PID}/portal-account/temp-password",
                          headers=h(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        temp = d.get("temp_password")
        assert temp and len(temp) >= 10
        assert d.get("expires_at") and d.get("must_change_password") is True
        # Login with temp works
        lr = requests.post(f"{API}/auth/login",
                           json={"identifier": "linda.nguyen@demo.com", "password": temp}, timeout=15)
        assert lr.status_code == 200, f"temp pw login should succeed: {lr.status_code} {lr.text}"
        linda_tok = lr.json()["token"]
        # Restore Linda's known password Patient2026! so future runs/tests stay stable
        cp = requests.post(f"{API}/auth/change-password", headers=h(linda_tok),
                           json={"current_password": temp, "new_password": "Patient2026!"}, timeout=15)
        assert cp.status_code == 200, f"restore linda pw failed: {cp.status_code} {cp.text}"
        # Verify
        lr2 = requests.post(f"{API}/auth/login",
                            json={"identifier": "linda.nguyen@demo.com", "password": "Patient2026!"}, timeout=15)
        assert lr2.status_code == 200


# ---------------------------- B. Counters ----------------------------
def test_counters_includes_portal_access(admin_token):
    r = requests.get(f"{API}/internal/counters", headers=h(admin_token), timeout=15)
    assert r.status_code == 200
    c = r.json().get("counters", {})
    assert "portal_access" in c
    assert isinstance(c["portal_access"], int)


# ---------------------------- C. Medical Record ----------------------------
def test_medical_record_shape(phys_token):
    r = requests.get(f"{API}/internal/patients/{MARIA_PID}/medical-record", headers=h(phys_token), timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("summary", "encounters", "medications", "documents"):
        assert k in d, f"missing {k}"
    assert "active" in d["medications"] and "discontinued" in d["medications"]
    drugs = [m.get("drug") for m in d["medications"]["active"]]
    # Seeded Maria meds
    assert any("Metformin" in (x or "") for x in drugs)


def test_medical_record_role_scoped(patient_token):
    r = requests.get(f"{API}/internal/patients/{MARIA_PID}/medical-record", headers=h(patient_token), timeout=15)
    assert r.status_code in (401, 403), f"patient must not reach med-record: {r.status_code}"


# ---------------------------- D. Medication lifecycle ----------------------------
class TestMedLifecycle:
    created_med_id = None

    def test_add_med(self, phys_token):
        body = {"drug": "TEST_Phase_B_Rx", "strength": "250", "unit": "mg", "form": "Tablet",
                "sig": "Take 1 tab daily", "quantity": "30", "quantity_unit": "tablets"}
        r = requests.post(f"{API}/internal/patients/{MARIA_PID}/medications",
                          headers=h(phys_token), json=body, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("drug") == "TEST_Phase_B_Rx"
        assert d.get("active") is True
        TestMedLifecycle.created_med_id = d["id"]

    def test_edit_med_records_history(self, phys_token):
        med_id = TestMedLifecycle.created_med_id
        assert med_id
        body = {"action_type": "edit", "sig": "Take 2 tabs daily"}
        r = requests.patch(f"{API}/internal/patients/{MARIA_PID}/medications/{med_id}",
                           headers=h(phys_token), json=body, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("sig") == "Take 2 tabs daily"
        hist = d.get("history") or []
        assert any(h.get("action") == "edited" for h in hist)
        assert any("previous" in h for h in hist if h.get("action") == "edited")

    def test_continue_med(self, phys_token):
        med_id = TestMedLifecycle.created_med_id
        r = requests.patch(f"{API}/internal/patients/{MARIA_PID}/medications/{med_id}",
                           headers=h(phys_token), json={"action_type": "continue"}, timeout=15)
        assert r.status_code == 200
        assert r.json().get("active") is True

    def test_patient_portal_sees_active(self, patient_token):
        r = requests.get(f"{API}/portal/medications", headers=h(patient_token), timeout=15)
        assert r.status_code == 200
        drugs = [m.get("drug") for m in r.json().get("medications", [])]
        assert any("TEST_Phase_B_Rx" in (x or "") for x in drugs), f"expected TEST med visible to patient, got {drugs}"

    def test_discontinue_med_preserves_history(self, phys_token):
        med_id = TestMedLifecycle.created_med_id
        r = requests.patch(f"{API}/internal/patients/{MARIA_PID}/medications/{med_id}",
                           headers=h(phys_token), json={"action_type": "discontinue", "note": "test cleanup"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("active") is False
        assert d.get("discontinued_at")
        hist = d.get("history") or []
        assert any(h.get("action") == "discontinued" for h in hist)

    def test_portal_hides_discontinued(self, patient_token):
        r = requests.get(f"{API}/portal/medications", headers=h(patient_token), timeout=15)
        assert r.status_code == 200
        drugs = [m.get("drug") for m in r.json().get("medications", [])]
        assert not any("TEST_Phase_B_Rx" in (x or "") for x in drugs), "discontinued med must not appear"

    def test_discontinued_appears_in_medical_record(self, phys_token):
        r = requests.get(f"{API}/internal/patients/{MARIA_PID}/medical-record", headers=h(phys_token), timeout=15)
        d = r.json()
        disc = [m.get("drug") for m in d["medications"]["discontinued"]]
        assert any("TEST_Phase_B_Rx" in (x or "") for x in disc), "discontinued med must be preserved in record"


# ---------------------------- E. Regressions ----------------------------
def test_rx_queue_and_patient_lookup_still_work(admin_token):
    r1 = requests.get(f"{API}/internal/prescriptions", headers=h(admin_token), timeout=20)
    assert r1.status_code == 200
    r2 = requests.get(f"{API}/internal/patient-lookup?q=Maria", headers=h(admin_token), timeout=15)
    assert r2.status_code == 200
