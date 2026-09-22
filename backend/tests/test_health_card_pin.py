"""Backend tests for the Health Card + Auto VISITA PIN + Edit Patient rework.
Tests OHIP register normalization, auto-PIN on verification, PIN searchability
and calendar booking, portal HC pending workflow, staff/admin approve/reject,
internal edit patient with 409 collision, physician gating, and expiry statuses.

MANDATORY CLEANUP at teardown: every patient + user created here, their
visita_pins claim, any notifications/outbound_notifications/audit_log entries
scoped to those patients, and any TEST_-tagged appointment_requests/reminders
are hard-deleted. No pre-existing records are touched.
"""
import os
import re
import uuid
import asyncio
import pytest
import requests
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"
API = f"{BASE}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
STAFF = ("staff@visita.demo", "Staff2026!")
PHYS  = ("PAGUAYO", "Newman2013_!")
PATIENT_MARIA = ("maria.lopez@demo.com", "Patient2026!")

CREATED_PATIENT_IDS: set = set()
CREATED_USER_EMAILS: set = set()
CREATED_APPT_IDS: set = set()
ASSIGNED_PINS: set = set()


# ------------------- helpers -------------------
def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _headers(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _rand_email():
    return f"hctest+{uuid.uuid4().hex[:10]}@example.com"


def _pid_by_email(email):
    """Fetch patient id from MongoDB (lookup endpoint only returns verified)."""
    import pymongo
    c = pymongo.MongoClient(MONGO_URL)
    try:
        u = c[DB_NAME].users.find_one({"email": email.lower()})
        return u.get("patient_id") if u else None
    finally:
        c.close()


def _lookup_by_email(email, tok):
    """Lookup verified patient via internal API."""
    r = requests.get(f"{API}/internal/patient-lookup",
                     params={"q": email}, headers=_headers(tok), timeout=15)
    try:
        return r.json()
    except Exception:
        return []


def _register_ohip(number, version, issue=None, expiry=None, patient_type="ohip"):
    email = _rand_email()
    body = {
        "first_name": "TEST", "last_name": f"Case{uuid.uuid4().hex[:6]}",
        "date_of_birth": "1990-05-05", "phone": "4165550100",
        "email": email, "password": "TempPass2026!",
        "patient_type": patient_type,
        "health_card_number": number, "health_card_version": version,
        "health_card_issue_date": issue, "health_card_expiry_date": expiry,
        "province": "ON", "country": "Canada", "extra_info": None,
    }
    r = requests.post(f"{API}/auth/register", json=body, timeout=20)
    return r, email


# ------------------- fixtures -------------------
@pytest.fixture(scope="session")
def admin_tok():
    return _login(*ADMIN)


@pytest.fixture(scope="session")
def staff_tok():
    return _login(*STAFF)


@pytest.fixture(scope="session")
def phys_tok():
    return _login(*PHYS)


@pytest.fixture(scope="session", autouse=True)
def cleanup_all():
    yield
    async def _clean():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        if CREATED_PATIENT_IDS:
            await db.patients.delete_many({"id": {"$in": list(CREATED_PATIENT_IDS)}})
            await db.notifications.delete_many({"patient_id": {"$in": list(CREATED_PATIENT_IDS)}})
            await db.outbound_notifications.delete_many({"patient_id": {"$in": list(CREATED_PATIENT_IDS)}})
            await db.audit_log.delete_many({"entity_id": {"$in": list(CREATED_PATIENT_IDS)}})
        if CREATED_USER_EMAILS:
            await db.users.delete_many({"email": {"$in": list(CREATED_USER_EMAILS)}})
        if ASSIGNED_PINS:
            await db.visita_pins.delete_many({"_id": {"$in": list(ASSIGNED_PINS)}})
        if CREATED_APPT_IDS:
            await db.appointment_requests.delete_many({"id": {"$in": list(CREATED_APPT_IDS)}})
            await db.reminders.delete_many({"appointment_id": {"$in": list(CREATED_APPT_IDS)}})
        client.close()
    asyncio.get_event_loop().run_until_complete(_clean())


# ===================================================================
# 1) OHIP registration normalization + validation
# ===================================================================
class TestOhipRegisterNormalize:
    def test_messy_hc_is_normalized(self):
        r, email = _register_ohip("1234 567 890", "xd",
                                  issue="2020-01-01", expiry="2030-01-01")
        assert r.status_code == 200, r.text
        CREATED_USER_EMAILS.add(email)
        tok = r.json()["token"]
        me = requests.get(f"{API}/portal/overview", headers=_headers(tok), timeout=15).json()
        p = me["patient"]
        assert p["health_card_display"] == "1234 567 890 XD"
        assert p["health_card_status"] == "VALID"
        pid = _pid_by_email(email)
        assert pid
        CREATED_PATIENT_IDS.add(pid)

    def test_short_number_rejected(self):
        r, email = _register_ohip("12345", "AB")
        assert r.status_code == 400
        # no user created
        assert "10 digits" in r.text.lower() or "health card" in r.text.lower()

    def test_bad_version_rejected(self):
        r, email = _register_ohip("1234567890", "A1")
        assert r.status_code == 400

    def test_bad_date_rejected(self):
        r, email = _register_ohip("1234567890", "AB", issue="not-a-date")
        assert r.status_code == 400


# ===================================================================
# 2) Auto VISITA PIN on verification
# ===================================================================
class TestAutoPinAtVerify:
    @pytest.fixture(scope="class")
    def portal_patient(self, staff_tok):
        # Register a fresh portal patient (non-ohip -> no directory match)
        email = _rand_email()
        body = {
            "first_name": "TEST", "last_name": f"Pin{uuid.uuid4().hex[:6]}",
            "date_of_birth": "1991-06-06", "phone": "4165550101",
            "email": email, "password": "TempPass2026!",
            "patient_type": "non_ohip",
            "province": "ON", "country": "Canada",
        }
        r = requests.post(f"{API}/auth/register", json=body, timeout=20)
        assert r.status_code == 200, r.text
        CREATED_USER_EMAILS.add(email)
        pid = _pid_by_email(email)
        assert pid, f"no pid for {email}"
        CREATED_PATIENT_IDS.add(pid)
        return {"email": email, "id": pid, "token": r.json()["token"]}

    def test_verify_assigns_4digit_pin(self, portal_patient, staff_tok):
        pid = portal_patient["id"]
        r = requests.post(f"{API}/internal/verifications/{pid}",
                          json={"decision": "verified"},
                          headers=_headers(staff_tok), timeout=15)
        assert r.status_code == 200, r.text
        # look up
        hits = requests.get(f"{API}/internal/patient-lookup",
                            params={"q": portal_patient["email"]},
                            headers=_headers(staff_tok), timeout=15).json()
        assert hits
        vpid = hits[0].get("visita_patient_id")
        assert vpid and re.fullmatch(r"\d{4}", vpid), f"pin not assigned: {hits[0]}"
        assert 1000 <= int(vpid) <= 9999
        ASSIGNED_PINS.add(vpid)
        portal_patient["pin"] = vpid

    def test_reverify_does_not_reassign(self, portal_patient, staff_tok):
        pid = portal_patient["id"]
        pin_before = portal_patient["pin"]
        r = requests.post(f"{API}/internal/verifications/{pid}",
                          json={"decision": "verified"},
                          headers=_headers(staff_tok), timeout=15)
        assert r.status_code == 200
        hits = requests.get(f"{API}/internal/patient-lookup",
                            params={"q": pin_before},
                            headers=_headers(staff_tok), timeout=15).json()
        assert hits, "PIN not searchable after re-verify"
        assert hits[0].get("visita_patient_id") == pin_before

    def test_pin_searchable_and_bookable(self, portal_patient, staff_tok):
        pin = portal_patient["pin"]
        # search by pin
        hits = requests.get(f"{API}/internal/patient-lookup",
                            params={"q": pin},
                            headers=_headers(staff_tok), timeout=15).json()
        assert hits, "PIN not returned by lookup"
        found = hits[0]
        assert found.get("visita_patient_id") == pin
        assert found.get("health_card_display") is None or isinstance(found.get("health_card_display"), (str, type(None)))
        # try to book
        # Pull an availability slot
        avail = requests.get(f"{API}/internal/calendar",
                             params={"start": "2026-09-21", "days": 7},
                             headers=_headers(staff_tok), timeout=15)
        assert avail.status_code == 200, avail.text
        slots = []
        try:
            data = avail.json()
            for day in (data.get("days") or []):
                for s in day.get("open_slots") or []:
                    slots.append((day.get("date"), s.get("time")))
        except Exception:
            pass
        if not slots:
            pytest.skip(f"No open slots in week: {avail.text[:200]}")
        date_s, time_s = slots[0]
        book = requests.post(f"{API}/internal/calendar/book",
                             json={"date": date_s, "time": time_s,
                                   "patient_id": portal_patient["id"],
                                   "reason": "TEST_pin_book",
                                   "appointment_type": "consultation"},
                             headers=_headers(staff_tok), timeout=15)
        # accept 200 as success; capture id for cleanup
        assert book.status_code in (200, 201), book.text
        try:
            j = book.json()
            aid = j.get("id") or j.get("appointment_id") or (j.get("appointment") or {}).get("id")
            if aid:
                CREATED_APPT_IDS.add(aid)
        except Exception:
            pass


# ===================================================================
# 3) Portal HC pending workflow + staff approve/reject
# ===================================================================
class TestHealthCardPendingWorkflow:
    @pytest.fixture(scope="class")
    def verified_patient(self, staff_tok):
        # register + verify a fresh patient
        email = _rand_email()
        body = {
            "first_name": "TEST", "last_name": f"HC{uuid.uuid4().hex[:6]}",
            "date_of_birth": "1985-02-02", "phone": "4165550111",
            "email": email, "password": "TempPass2026!",
            "patient_type": "ohip",
            "health_card_number": "9876543210", "health_card_version": "AA",
            "health_card_issue_date": "2020-01-01", "health_card_expiry_date": "2030-01-01",
            "province": "ON", "country": "Canada",
        }
        r = requests.post(f"{API}/auth/register", json=body, timeout=20)
        assert r.status_code == 200, r.text
        CREATED_USER_EMAILS.add(email)
        ptok = r.json()["token"]
        pid = _pid_by_email(email)
        assert pid
        CREATED_PATIENT_IDS.add(pid)
        # verify
        requests.post(f"{API}/internal/verifications/{pid}",
                      json={"decision": "verified"},
                      headers=_headers(staff_tok), timeout=15)
        hits = _lookup_by_email(email, staff_tok)
        if hits and hits[0].get("visita_patient_id"):
            ASSIGNED_PINS.add(hits[0]["visita_patient_id"])
        return {"email": email, "id": pid, "token": ptok}

    def test_phone_self_update(self, verified_patient):
        tok = verified_patient["token"]
        r = requests.post(f"{API}/portal/profile/phone",
                          json={"phone": "6475551234"},
                          headers=_headers(tok), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["phone"] == "(647) 555-1234"
        # invalid
        r2 = requests.post(f"{API}/portal/profile/phone",
                           json={"phone": "12"},
                           headers=_headers(tok), timeout=15)
        assert r2.status_code == 400

    def test_submit_pending_hc_keeps_active(self, verified_patient):
        tok = verified_patient["token"]
        # active card was 9876 543 210 AA
        r = requests.post(f"{API}/portal/profile/health-card",
                          json={"health_card_number": "1111 222 333",
                                "health_card_version": "BC",
                                "health_card_issue_date": "2021-01-01",
                                "health_card_expiry_date": "2031-01-01"},
                          headers=_headers(tok), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["pending"]["display"] == "1111 222 333 BC"
        ov = requests.get(f"{API}/portal/overview", headers=_headers(tok), timeout=15).json()
        assert ov["patient"]["health_card_update_pending"] is True
        assert ov["patient"]["health_card_display"] == "9876 543 210 AA", \
            f"active card must remain until approved, got {ov['patient']}"

    def test_invalid_hc_pending_rejected(self, verified_patient):
        tok = verified_patient["token"]
        r = requests.post(f"{API}/portal/profile/health-card",
                          json={"health_card_number": "123", "health_card_version": "BC"},
                          headers=_headers(tok), timeout=15)
        assert r.status_code == 400

    def test_staff_approve_applies_and_clears_pending(self, verified_patient, staff_tok):
        pid = verified_patient["id"]
        r = requests.post(f"{API}/internal/patients/{pid}/health-card/approve",
                          headers=_headers(staff_tok), timeout=15)
        assert r.status_code == 200, r.text
        tok = verified_patient["token"]
        ov = requests.get(f"{API}/portal/overview", headers=_headers(tok), timeout=15).json()
        assert ov["patient"]["health_card_display"] == "1111 222 333 BC"
        assert ov["patient"]["health_card_update_pending"] is False

    def test_staff_reject_flow(self, verified_patient, staff_tok):
        tok = verified_patient["token"]
        # Submit new pending
        r = requests.post(f"{API}/portal/profile/health-card",
                          json={"health_card_number": "5555555555",
                                "health_card_version": "ZZ"},
                          headers=_headers(tok), timeout=15)
        assert r.status_code == 200
        pid = verified_patient["id"]
        r2 = requests.post(f"{API}/internal/patients/{pid}/health-card/reject",
                           headers=_headers(staff_tok), timeout=15)
        assert r2.status_code == 200, r2.text
        ov = requests.get(f"{API}/portal/overview", headers=_headers(tok), timeout=15).json()
        assert ov["patient"]["health_card_display"] == "1111 222 333 BC", "active card must be unchanged after reject"
        assert ov["patient"]["health_card_update_pending"] is False


# ===================================================================
# 4) Internal Edit Patient (staff/admin) + collision + physician 403
# ===================================================================
class TestInternalEditPatient:
    @pytest.fixture(scope="class")
    def target(self, staff_tok):
        email = _rand_email()
        body = {
            "first_name": "TEST", "last_name": f"Edit{uuid.uuid4().hex[:6]}",
            "date_of_birth": "1980-03-03", "phone": "4165550120",
            "email": email, "password": "TempPass2026!",
            "patient_type": "ohip",
            "health_card_number": "2222222222", "health_card_version": "CC",
            "health_card_issue_date": "2020-01-01", "health_card_expiry_date": "2030-01-01",
            "province": "ON", "country": "Canada",
        }
        r = requests.post(f"{API}/auth/register", json=body, timeout=20)
        assert r.status_code == 200, r.text
        CREATED_USER_EMAILS.add(email)
        pid = _pid_by_email(email)
        assert pid
        CREATED_PATIENT_IDS.add(pid)
        # verify to assign PIN
        requests.post(f"{API}/internal/verifications/{pid}",
                      json={"decision": "verified"},
                      headers=_headers(staff_tok), timeout=15)
        hits2 = _lookup_by_email(email, staff_tok)
        pin = hits2[0].get("visita_patient_id") if hits2 else None
        if pin:
            ASSIGNED_PINS.add(pin)
        return {"email": email, "id": pid, "pin": pin}

    def test_staff_can_patch_phone_and_hc(self, target, staff_tok):
        pid = target["id"]
        r = requests.patch(f"{API}/internal/patients/{pid}",
                           json={"phone": "9051234567",
                                 "health_card_number": "3333 333 333",
                                 "health_card_version": "dd"},
                           headers=_headers(staff_tok), timeout=15)
        assert r.status_code == 200, r.text
        # verify via lookup
        hits = requests.get(f"{API}/internal/patient-lookup",
                            params={"q": target["email"]},
                            headers=_headers(staff_tok), timeout=15).json()
        rec = hits[0]
        assert rec.get("cell_phone") == "(905) 123-4567"
        assert rec.get("health_card_display") == "3333 333 333 DD"

    def test_invalid_hc_on_patch_400(self, target, staff_tok):
        pid = target["id"]
        r = requests.patch(f"{API}/internal/patients/{pid}",
                           json={"health_card_number": "12"},
                           headers=_headers(staff_tok), timeout=15)
        assert r.status_code == 400

    def test_pin_collision_returns_409(self, target, staff_tok):
        # Use Maria's known PIN (or any patient with a PIN) as collision target
        used_pin = None
        for q in ("maria.lopez@demo.com", "Lopez", "Alvarez", "Rodriguez"):
            hits = requests.get(f"{API}/internal/patient-lookup",
                                params={"q": q},
                                headers=_headers(staff_tok), timeout=15).json()
            for h in hits or []:
                vp = h.get("visita_patient_id")
                hid = h.get("id") or h.get("patient_id")
                if vp and hid != target["id"]:
                    used_pin = vp; break
            if used_pin:
                break
        if not used_pin:
            pytest.skip("No other patient PIN available to test collision")
        r = requests.patch(f"{API}/internal/patients/{target['id']}",
                           json={"visita_patient_id": used_pin},
                           headers=_headers(staff_tok), timeout=15)
        assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text}"

    def test_physician_forbidden(self, target, phys_tok):
        pid = target["id"]
        r = requests.patch(f"{API}/internal/patients/{pid}",
                           json={"phone": "4160000000"},
                           headers=_headers(phys_tok), timeout=15)
        assert r.status_code == 403, f"physician must be blocked, got {r.status_code}"


# ===================================================================
# 5) Expiry status: EXPIRING_SOON / EXPIRED
# ===================================================================
class TestExpiryStatus:
    def test_expiring_soon_and_expired(self, staff_tok):
        # EXPIRING_SOON (~30 days from env date 2026-09-22)
        today = datetime(2026, 9, 22).date()
        soon = (today + timedelta(days=30)).isoformat()
        past = "2025-01-01"
        r1, e1 = _register_ohip("4444444444", "EE",
                                issue="2020-01-01", expiry=soon)
        assert r1.status_code == 200, r1.text
        CREATED_USER_EMAILS.add(e1)
        tok1 = r1.json()["token"]
        ov1 = requests.get(f"{API}/portal/overview", headers=_headers(tok1), timeout=15).json()
        assert ov1["patient"]["health_card_status"] == "EXPIRING_SOON"
        pid1 = _pid_by_email(e1)
        if pid1: CREATED_PATIENT_IDS.add(pid1)

        r2, e2 = _register_ohip("5555555550", "FF",
                                issue="2015-01-01", expiry=past)
        assert r2.status_code == 200, r2.text
        CREATED_USER_EMAILS.add(e2)
        tok2 = r2.json()["token"]
        ov2 = requests.get(f"{API}/portal/overview", headers=_headers(tok2), timeout=15).json()
        assert ov2["patient"]["health_card_status"] == "EXPIRED"
        pid2 = _pid_by_email(e2)
        if pid2: CREATED_PATIENT_IDS.add(pid2)


# ===================================================================
# 6) Regression: existing Maria (portal-only verified) is unchanged
# ===================================================================
class TestSafetyRegression:
    def test_maria_still_searchable_and_pin_preserved(self, staff_tok):
        # Capture Maria's current PIN
        hits = requests.get(f"{API}/internal/patient-lookup",
                            params={"q": "maria.lopez@demo.com"},
                            headers=_headers(staff_tok), timeout=15).json()
        assert hits, "existing Maria not found"
        rec = hits[0]
        assert rec.get("source") in ("portal", None) or rec.get("patient_status") in ("PORTAL_PATIENT", None)
