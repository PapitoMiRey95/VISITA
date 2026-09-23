"""
Backend tests for New-Patient Accept -> Account + Activation flow (iteration 28).

Covers:
- Public POST /api/applications/new-patient creates application
- Physician PATCH /api/internal/applications/{id} {action:'accept'} for a new_patient
  creates: users(pending_activation=True), patients(verified, 4-digit PIN),
  patient_directory(ACTIVE, linked_patient_id).
- POST /api/auth/activate/validate + /api/auth/activate flows:
  * invalid/wrong tokens -> 400
  * password < 8 -> 400
  * successful activation returns {token, user(role=patient)}
  * single-use enforced (second use -> 400)
  * login with new password works
- After activation, GET /api/portal/overview contains a "Welcome to VIen EMR" notification
- Former-return acceptance still flips directory to ACTIVE and does NOT create a new account
"""
import os
import time
import secrets
import pytest
import requests
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import sys

sys.path.insert(0, "/app/backend")
import auth as authlib  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ENV = dotenv_values("/app/backend/.env")
MONGO_URL = ENV["MONGO_URL"].strip('"')
DB_NAME = ENV["DB_NAME"].strip('"')

PHY_USER = "PAGUAYO"
PHY_PW_PRIMARY = "Newman2013_!"
PHY_PW_FALLBACK = "Aguayo#Temp2026"


# ---------- helpers ----------
def _login(identifier, password):
    r = requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password}, timeout=20)
    return r


@pytest.fixture(scope="module")
def phy_token():
    r = _login(PHY_USER, PHY_PW_PRIMARY)
    if r.status_code != 200:
        r = _login(PHY_USER, PHY_PW_FALLBACK)
    assert r.status_code == 200, f"Physician login failed: {r.status_code} {r.text}"
    data = r.json()
    if data.get("must_change_password"):
        pytest.skip("Physician must_change_password gate blocks acceptance testing.")
    return data["token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


async def _db():
    cli = AsyncIOMotorClient(MONGO_URL)
    return cli[DB_NAME], cli


# ---------- 1. Physician login smoke ----------
class TestPhysicianAuth:
    def test_login_ok(self, phy_token):
        assert phy_token and isinstance(phy_token, str)


# ---------- 2. New patient accept + activation full flow ----------
class TestAcceptNewPatient:
    email = None
    app_id = None
    user_id = None
    patient_id = None

    def test_create_new_patient_application(self):
        ts = int(time.time())
        TestAcceptNewPatient.email = f"newpat.iter28.{ts}@resend.dev"
        payload = {
            "first_name": "Iter28",
            "last_name": "TestPatient",
            "date_of_birth": "1990-05-15",
            "phone": "4165551234",
            "email": TestAcceptNewPatient.email,
            "address": "123 Test St",
            "city": "Toronto",
            "province": "ON",
            "postal_code": "M5V1A1",
            "country": "Canada",
            "patient_message": "Iter28 automated test",
        }
        r = requests.post(f"{API}/applications/new-patient", json=payload, timeout=20)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        data = r.json()
        ref = data.get("ref_number") or data.get("id")
        assert ref, f"no ref/id in response: {data}"

        # Lookup real doc id via Mongo (public endpoint returns ref only)
        async def _find():
            db, cli = await _db()
            try:
                doc = await db.patient_applications.find_one({"ref_number": ref})
                assert doc, f"application not found for ref {ref}"
                return doc["id"]
            finally:
                cli.close()
        TestAcceptNewPatient.app_id = asyncio.run(_find())

    def test_physician_accept_creates_account(self, phy_token):
        assert TestAcceptNewPatient.app_id
        r = requests.patch(
            f"{API}/internal/applications/{TestAcceptNewPatient.app_id}",
            json={"action": "accept"},
            headers=_headers(phy_token),
            timeout=25,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"

        async def _check():
            db, cli = await _db()
            try:
                u = await db.users.find_one({"email": TestAcceptNewPatient.email})
                assert u, "users doc not created"
                assert u.get("role") == "patient"
                assert u.get("pending_activation") is True
                TestAcceptNewPatient.user_id = str(u["_id"])
                TestAcceptNewPatient.patient_id = u.get("patient_id")

                p = await db.patients.find_one({"id": TestAcceptNewPatient.patient_id})
                assert p, "patients doc not created"
                assert p.get("verification_status") == "verified"
                assert p.get("visita_patient_id"), "no visita_patient_id"
                assert len(str(p["visita_patient_id"])) == 4 and str(p["visita_patient_id"]).isdigit(), \
                    f"pin not 4-digit: {p.get('visita_patient_id')}"

                d = await db.patient_directory.find_one({"linked_patient_id": TestAcceptNewPatient.patient_id})
                assert d, "directory doc not created"
                assert d.get("patient_status") == "ACTIVE"

                act = await db.account_activations.find_one({"user_id": TestAcceptNewPatient.user_id})
                assert act, "no account_activations row"
                assert act.get("used") is False
            finally:
                cli.close()

        asyncio.run(_check())

    def test_mint_token_and_validate(self):
        """Mint a known token for the created user (since real token was emailed hashed)."""
        assert TestAcceptNewPatient.user_id
        TOKEN = secrets.token_urlsafe(32)
        TestAcceptNewPatient._token = TOKEN

        async def _mint():
            db, cli = await _db()
            try:
                await db.account_activations.update_one(
                    {"user_id": TestAcceptNewPatient.user_id},
                    {"$set": {
                        "user_id": TestAcceptNewPatient.user_id,
                        "token_hash": authlib.hash_password(TOKEN),
                        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(),
                        "used": False,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
            finally:
                cli.close()

        asyncio.run(_mint())

        # invalid token -> 400
        r = requests.post(f"{API}/auth/activate/validate",
                          json={"uid": TestAcceptNewPatient.user_id, "token": "bogus-bogus-bogus"}, timeout=15)
        assert r.status_code == 400

        # valid token -> 200 with email/name
        r = requests.post(f"{API}/auth/activate/validate",
                          json={"uid": TestAcceptNewPatient.user_id, "token": TOKEN}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert data.get("email") == TestAcceptNewPatient.email

    def test_activate_short_password_rejected(self):
        r = requests.post(f"{API}/auth/activate",
                          json={"uid": TestAcceptNewPatient.user_id,
                                "token": TestAcceptNewPatient._token,
                                "new_password": "short1"},
                          timeout=15)
        assert r.status_code == 400

    def test_activate_success_and_single_use(self):
        NEW_PW = "Iter28Pw!ok"
        r = requests.post(f"{API}/auth/activate",
                          json={"uid": TestAcceptNewPatient.user_id,
                                "token": TestAcceptNewPatient._token,
                                "new_password": NEW_PW},
                          timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("token")
        assert data["user"]["role"] == "patient"
        TestAcceptNewPatient._new_pw = NEW_PW
        TestAcceptNewPatient._new_token = data["token"]

        # single-use: second validate should now 400
        r2 = requests.post(f"{API}/auth/activate/validate",
                           json={"uid": TestAcceptNewPatient.user_id,
                                 "token": TestAcceptNewPatient._token}, timeout=15)
        assert r2.status_code == 400

        r3 = requests.post(f"{API}/auth/activate",
                           json={"uid": TestAcceptNewPatient.user_id,
                                 "token": TestAcceptNewPatient._token,
                                 "new_password": "AnotherPw123!"}, timeout=15)
        assert r3.status_code == 400

    def test_login_with_new_password(self):
        r = _login(TestAcceptNewPatient.email, TestAcceptNewPatient._new_pw)
        assert r.status_code == 200, r.text
        tok = r.json()["token"]
        TestAcceptNewPatient._login_token = tok

    def test_portal_overview_has_welcome_notification(self):
        tok = TestAcceptNewPatient._login_token
        r = requests.get(f"{API}/portal/overview", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        notifs = data.get("notifications") or []
        titles = [n.get("title", "") for n in notifs]
        assert any("Welcome to VIen EMR" in t for t in titles), f"Welcome notif missing. titles={titles}"


# ---------- 3. Former return regression ----------
class TestFormerReturnRegression:
    """Former-return accept flips directory record to ACTIVE and does NOT create a new user."""
    ret_email = None
    app_id = None

    def test_create_return_request(self):
        ts = int(time.time())
        TestFormerReturnRegression.ret_email = f"return.iter28.{ts}@resend.dev"
        payload = {
            "first_name": "Ahmed Mohammed",
            "last_name": "KUTBI",
            "date_of_birth": "1990-01-21",
            "health_card_number": "0000000005",
            "phone": "4165550005",
            "email": TestFormerReturnRegression.ret_email,
            "patient_message": "iter28 regression",
        }
        r = requests.post(f"{API}/applications/return-request", json=payload, timeout=20)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        ref = r.json().get("ref_number") or r.json().get("id")
        assert ref
        async def _find():
            db, cli = await _db()
            try:
                doc = await db.patient_applications.find_one({"ref_number": ref})
                assert doc
                return doc["id"]
            finally:
                cli.close()
        TestFormerReturnRegression.app_id = asyncio.run(_find())

    def test_accept_flips_directory_no_new_user(self, phy_token):
        r = requests.patch(
            f"{API}/internal/applications/{TestFormerReturnRegression.app_id}",
            json={"action": "accept"},
            headers=_headers(phy_token),
            timeout=25,
        )
        assert r.status_code == 200, r.text

        async def _check():
            db, cli = await _db()
            try:
                app = await db.patient_applications.find_one({"id": TestFormerReturnRegression.app_id})
                assert app["internal_status"] == "ACCEPTED"
                # Should NOT have created a new user account
                u = await db.users.find_one({"email": TestFormerReturnRegression.ret_email})
                assert u is None, "former-return should NOT create a new user"
                # directory record for KUTBI should be ACTIVE
                if app.get("matched_directory_id"):
                    d = await db.patient_directory.find_one({"id": app["matched_directory_id"]})
                    assert d and d.get("patient_status") == "ACTIVE"
            finally:
                cli.close()

        asyncio.run(_check())
