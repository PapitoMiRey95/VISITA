"""VISITA Web Portal - comprehensive backend API tests.
Covers: auth (all 4 roles), counters, referral upload/download/fax lifecycle,
prescription/appointment/imaging/message workflows, patient verification (masked HCN),
internal tasks, admin settings access control.
"""
import io
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
STAFF = ("staff@visita.demo", "Staff2026!")
PHYS = ("doctor@visita.demo", "Doctor2026!")
MARIA = ("maria.lopez@demo.com", "Patient2026!")
SOFIA = ("sofia.martinez@demo.com", "Patient2026!")  # pending patient


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- session-scoped tokens ----------
@pytest.fixture(scope="session")
def admin_tok():
    return _login(*ADMIN)


@pytest.fixture(scope="session")
def staff_tok():
    return _login(*STAFF)


@pytest.fixture(scope="session")
def phys_tok():
    return _login(*PHYS)


@pytest.fixture(scope="session")
def maria_tok():
    return _login(*MARIA)


# ---------- AUTH ----------
class TestAuth:
    def test_login_admin(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["role"] == "admin"
        assert d["token"]

    def test_login_staff(self):
        r = requests.post(f"{API}/auth/login", json={"email": STAFF[0], "password": STAFF[1]})
        assert r.status_code == 200 and r.json()["user"]["role"] == "staff"

    def test_login_physician(self):
        r = requests.post(f"{API}/auth/login", json={"email": PHYS[0], "password": PHYS[1]})
        assert r.status_code == 200 and r.json()["user"]["role"] == "physician"

    def test_login_patient(self):
        r = requests.post(f"{API}/auth/login", json={"email": MARIA[0], "password": MARIA[1]})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "patient"
        assert r.json()["user"]["patient_id"]

    def test_wrong_password_401(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN[0], "password": "wrong"})
        assert r.status_code == 401

    def test_me_patient(self, maria_tok):
        r = requests.get(f"{API}/auth/me", headers=_h(maria_tok))
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["role"] == "patient"
        assert "patient" in d
        # health card should NOT be present
        assert "health_card_number" not in d["patient"]

    def test_me_staff(self, staff_tok):
        r = requests.get(f"{API}/auth/me", headers=_h(staff_tok))
        assert r.status_code == 200 and r.json()["user"]["role"] == "staff"


# ---------- COUNTERS ----------
class TestCounters:
    def test_staff_counters_baseline(self, staff_tok):
        r = requests.get(f"{API}/internal/counters", headers=_h(staff_tok))
        assert r.status_code == 200
        c = r.json()["counters"]
        # Baseline expected. Some may drift if previous tests ran - log
        print("Counters:", c)
        assert c["rx"] >= 3
        assert c["referrals"] >= 2
        assert c["imaging"] >= 1
        assert c["messages"] >= 4
        assert c["appointments"] >= 5
        assert c["doctor_tasks"] >= 2
        assert c["verifications"] >= 2

    def test_patient_cannot_get_counters(self, maria_tok):
        r = requests.get(f"{API}/internal/counters", headers=_h(maria_tok))
        assert r.status_code == 403


# ---------- REFERRALS ----------
class TestReferrals:
    def test_patient_cannot_list_referrals(self, maria_tok):
        r = requests.get(f"{API}/internal/referrals", headers=_h(maria_tok))
        assert r.status_code == 403

    def test_referral_full_lifecycle(self, phys_tok, staff_tok):
        # baseline counter
        r0 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["referrals"]

        # 1. physician uploads PDF
        pdf_bytes = b"%PDF-1.4\n%test\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        files = {"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        data = {"patient_name": f"TEST_Patient_{uuid.uuid4().hex[:6]}",
                "specialty": "Cardiology", "specialist_name": "Dr. Test",
                "clinic_name": "Test Clinic", "fax_number": "555-1234"}
        up = requests.post(f"{API}/internal/referrals", headers=_h(phys_tok), files=files, data=data)
        assert up.status_code == 200, up.text
        ref = up.json()
        rid = ref["id"]
        assert ref["ready_to_fax"] is True and ref["faxed"] is False

        # counter incremented
        r1 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["referrals"]
        assert r1 == r0 + 1, f"counter did not increase: {r0} -> {r1}"

        # 2. staff sees in queue
        q = requests.get(f"{API}/internal/referrals", headers=_h(staff_tok))
        assert q.status_code == 200
        assert any(x["id"] == rid for x in q.json())

        # 3. staff downloads PDF
        dl = requests.get(f"{API}/internal/referrals/{rid}/download", headers=_h(staff_tok))
        assert dl.status_code == 200, f"download failed: {dl.status_code} {dl.text[:200]}"
        assert dl.headers.get("content-type", "").startswith("application/pdf")
        assert dl.content[:4] == b"%PDF"

        # 4. staff marks faxed
        fx = requests.post(f"{API}/internal/referrals/{rid}/fax", headers=_h(staff_tok), json={})
        assert fx.status_code == 200
        assert fx.json()["faxed"] is True

        # counter decremented
        r2 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["referrals"]
        assert r2 == r0, f"counter after fax should be {r0}, got {r2}"

        # 5. no longer in ready queue, in history
        q2 = requests.get(f"{API}/internal/referrals", headers=_h(staff_tok)).json()
        assert not any(x["id"] == rid for x in q2)
        h = requests.get(f"{API}/internal/referrals/history", headers=_h(staff_tok)).json()
        assert any(x["id"] == rid for x in h)

    def test_existing_seed_referral_download(self, staff_tok):
        """Ensure demo seed referral PDFs are downloadable."""
        q = requests.get(f"{API}/internal/referrals", headers=_h(staff_tok)).json()
        if not q:
            pytest.skip("no ready referrals")
        rid = q[0]["id"]
        dl = requests.get(f"{API}/internal/referrals/{rid}/download", headers=_h(staff_tok))
        assert dl.status_code == 200, f"seed referral download failed: {dl.status_code}"
        assert dl.content[:4] == b"%PDF"


# ---------- PRESCRIPTION WORKFLOW ----------
class TestRxWorkflow:
    def test_rx_lifecycle(self, maria_tok, staff_tok, phys_tok):
        payload = {"medication_name": "TEST_Ibuprofen", "strength": "200mg",
                   "directions": "Once daily", "requested_months": 1, "delivery_method": "pickup"}
        c = requests.post(f"{API}/portal/prescriptions", headers=_h(maria_tok), json=payload)
        assert c.status_code == 200
        rx_id = c.json()["id"]

        # patient overview shows "Received"
        o = requests.get(f"{API}/portal/overview", headers=_h(maria_tok)).json()
        mine = [x for x in o["prescriptions"] if x["id"] == rx_id][0]
        assert mine["status"] == "Received"

        # counter baseline
        rx0 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["rx"]

        # send_to_physician
        r = requests.patch(f"{API}/internal/prescriptions/{rx_id}",
                           headers=_h(staff_tok), json={"action": "send_to_physician"})
        assert r.status_code == 200 and r.json()["internal_status"] == "waiting_physician"

        # patient overview shows "Under Review" (not "waiting_physician")
        o2 = requests.get(f"{API}/portal/overview", headers=_h(maria_tok)).json()
        mine2 = [x for x in o2["prescriptions"] if x["id"] == rx_id][0]
        assert mine2["status"] == "Under Review"
        assert "waiting" not in mine2["status"].lower()

        # complete
        r = requests.patch(f"{API}/internal/prescriptions/{rx_id}",
                           headers=_h(staff_tok), json={"action": "complete"})
        assert r.status_code == 200 and r.json()["internal_status"] == "completed"

        # counter decreased
        rx1 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["rx"]
        assert rx1 == rx0 - 1

        o3 = requests.get(f"{API}/portal/overview", headers=_h(maria_tok)).json()
        mine3 = [x for x in o3["prescriptions"] if x["id"] == rx_id][0]
        assert mine3["status"] == "Completed"


# ---------- APPOINTMENT WORKFLOW ----------
class TestAppointmentWorkflow:
    def test_approve_flow(self, maria_tok, staff_tok):
        p = requests.post(f"{API}/portal/appointments", headers=_h(maria_tok),
                          json={"reason": "TEST_Checkup", "preferred_date": "2026-02-01", "preferred_time": "10:00"})
        assert p.status_code == 200
        aid = p.json()["id"]

        a0 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["appointments"]

        r = requests.patch(f"{API}/internal/appointments/{aid}", headers=_h(staff_tok),
                           json={"action": "approve", "approved_date": "2026-02-02", "approved_time": "10:30"})
        assert r.status_code == 200 and r.json()["status"] == "confirmed"

        a1 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["appointments"]
        assert a1 == a0 - 1

        o = requests.get(f"{API}/portal/overview", headers=_h(maria_tok)).json()
        mine = [x for x in o["appointments"] if x["id"] == aid][0]
        assert mine["status"] == "Appointment Confirmed"

    def test_suggest_more_info_decline(self, maria_tok, staff_tok):
        for action, expected in [("suggest", "suggested"), ("more_info", "more_info_requested"), ("decline", "declined")]:
            p = requests.post(f"{API}/portal/appointments", headers=_h(maria_tok),
                              json={"reason": f"TEST_{action}"})
            aid = p.json()["id"]
            r = requests.patch(f"{API}/internal/appointments/{aid}", headers=_h(staff_tok),
                               json={"action": action, "staff_note": "note"})
            assert r.status_code == 200
            assert r.json()["status"] == expected, f"{action}: expected {expected} got {r.json()['status']}"


# ---------- PATIENT VERIFICATION ----------
class TestVerification:
    def test_pending_patient_blocked(self):
        tok = _login(*SOFIA)
        r = requests.post(f"{API}/portal/appointments", headers=_h(tok), json={"reason": "TEST_pending"})
        assert r.status_code == 403

    def test_hcn_masked_in_verifications(self, staff_tok):
        # register a new pending patient
        email = f"test_reg_{uuid.uuid4().hex[:8]}@demo.com"
        reg = requests.post(f"{API}/auth/register", json={
            "patient_type": "OHIP", "first_name": "TEST", "last_name": "Reg",
            "date_of_birth": "1990-01-01", "phone": "555-0000", "email": email,
            "password": "Patient2026!", "health_card_number": "1234567890AB",
            "health_card_version": "AB", "province": "ON",
        })
        assert reg.status_code == 200

        # login and confirm pending
        tok = _login(email, "Patient2026!")
        me = requests.get(f"{API}/auth/me", headers=_h(tok)).json()
        assert me["patient"]["verification_status"] == "pending"

        # pending patient cannot submit
        r = requests.post(f"{API}/portal/appointments", headers=_h(tok), json={"reason": "TEST_blocked"})
        assert r.status_code == 403

        # staff sees masked HCN
        v = requests.get(f"{API}/internal/verifications", headers=_h(staff_tok)).json()
        mine = [x for x in v if x["email"] == email]
        assert mine, "new pending patient not visible"
        m = mine[0]
        assert "1234567890AB" not in m["health_card_masked"]
        assert "•" in m["health_card_masked"]

        # verify
        vres = requests.post(f"{API}/internal/verifications/{m['id']}", headers=_h(staff_tok),
                             json={"decision": "verified"})
        assert vres.status_code == 200

        # patient can now submit
        r2 = requests.post(f"{API}/portal/appointments", headers=_h(tok), json={"reason": "TEST_after_verify"})
        assert r2.status_code == 200


# ---------- MESSAGES ----------
class TestMessages:
    def test_message_flow(self, maria_tok, staff_tok):
        m = requests.post(f"{API}/portal/messages", headers=_h(maria_tok),
                          json={"category": "general", "subject": "TEST", "body": "hello"})
        assert m.status_code == 200
        mid = m.json()["id"]

        c0 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["messages"]

        # reply
        r = requests.patch(f"{API}/internal/messages/{mid}", headers=_h(staff_tok),
                           json={"patient_reply": "Hi from clinic"})
        assert r.status_code == 200
        thread = r.json()["thread"]
        assert any(t["from"] == "clinic" and "Hi from clinic" in t["body"] for t in thread)

        # patient sees reply
        o = requests.get(f"{API}/portal/overview", headers=_h(maria_tok)).json()
        pm = [x for x in o["messages"] if x["id"] == mid][0]
        assert any(t["from"] == "clinic" for t in pm["thread"])

        # complete
        r2 = requests.patch(f"{API}/internal/messages/{mid}", headers=_h(staff_tok), json={"action": "complete"})
        assert r2.status_code == 200 and r2.json()["status"] == "completed"

        c1 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["messages"]
        assert c1 == c0 - 1


# ---------- IMAGING ----------
class TestImaging:
    def test_imaging_flow(self, maria_tok, staff_tok):
        p = requests.post(f"{API}/portal/imaging", headers=_h(maria_tok),
                          json={"imaging_type": "X-Ray", "body_part": "Chest", "reason": "TEST"})
        assert p.status_code == 200
        iid = p.json()["id"]

        i0 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["imaging"]
        r = requests.patch(f"{API}/internal/imaging/{iid}", headers=_h(staff_tok), json={"action": "complete"})
        assert r.status_code == 200 and r.json()["internal_status"] == "completed"
        i1 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["imaging"]
        assert i1 == i0 - 1


# ---------- TASKS / INTERCOM ----------
class TestTasks:
    def test_physician_creates_task_for_staff(self, phys_tok, staff_tok):
        t0 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["doctor_tasks"]
        r = requests.post(f"{API}/internal/tasks", headers=_h(phys_tok),
                          json={"recipient_role": "staff", "message": "TEST task"})
        assert r.status_code == 200
        tid = r.json()["id"]

        t1 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["doctor_tasks"]
        assert t1 == t0 + 1

        c = requests.patch(f"{API}/internal/tasks/{tid}", headers=_h(staff_tok), json={"action": "complete"})
        assert c.status_code == 200 and c.json()["status"] == "completed"
        t2 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["doctor_tasks"]
        assert t2 == t0


# ---------- ADMIN SETTINGS ----------
class TestAdminSettings:
    def test_admin_can_get_and_put(self, admin_tok):
        g = requests.get(f"{API}/admin/settings", headers=_h(admin_tok))
        assert g.status_code == 200
        current = g.json()
        # update
        new_settings = dict(current.get("settings") or {})
        new_settings["clinic_name"] = "TEST Clinic Name"
        p = requests.put(f"{API}/admin/settings", headers=_h(admin_tok),
                         json={"settings": new_settings, "templates": current.get("templates") or {}})
        assert p.status_code == 200
        g2 = requests.get(f"{API}/admin/settings", headers=_h(admin_tok)).json()
        assert g2["settings"]["clinic_name"] == "TEST Clinic Name"

    def test_staff_forbidden(self, staff_tok):
        r = requests.get(f"{API}/admin/settings", headers=_h(staff_tok))
        assert r.status_code == 403

    def test_patient_forbidden(self, maria_tok):
        r = requests.get(f"{API}/admin/settings", headers=_h(maria_tok))
        assert r.status_code == 403
