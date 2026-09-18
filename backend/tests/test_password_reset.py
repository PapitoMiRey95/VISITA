"""Backend tests for forgot-password / reset-password flow.

Seeds password_resets docs directly against MongoDB to test deterministic paths
(cannot read email content). Restores maria.lopez password at teardown.
"""
import os
import sys
import asyncio
import pytest
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load backend .env so we get MONGO_URL/DB_NAME
load_dotenv("/app/backend/.env")

sys.path.insert(0, "/app/backend")
import auth as authlib  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://visita-admin.preview.emergentagent.com"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

MARIA_EMAIL = "maria.lopez@demo.com"
ORIGINAL_PASSWORD = "Patient2026!"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module", autouse=True)
def restore_maria_password(db):
    """After all tests, restore maria's password to Patient2026!"""
    yield
    async def restore():
        await db.users.update_one(
            {"email": MARIA_EMAIL},
            {"$set": {"password_hash": authlib.hash_password(ORIGINAL_PASSWORD),
                      "must_change_password": False}},
        )
        await db.password_resets.delete_one({})
    _run(restore())
    # sanity check
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": MARIA_EMAIL, "password": ORIGINAL_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Restore failed: {r.status_code} {r.text}"


async def _seed_reset(db, email, code, expires_delta_minutes=15, attempts=0):
    user = await db.users.find_one({"email": email})
    assert user is not None, f"user {email} not seeded"
    uid = str(user["_id"])
    exp = (datetime.now(timezone.utc) + timedelta(minutes=expires_delta_minutes)).isoformat()
    await db.password_resets.update_one(
        {"user_id": uid},
        {"$set": {
            "user_id": uid,
            "code_hash": authlib.hash_password(code),
            "expires_at": exp,
            "attempts": attempts,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return uid


async def _clear_reset(db, email):
    user = await db.users.find_one({"email": email})
    if user:
        await db.password_resets.delete_one({"user_id": str(user["_id"])})


# ---------- Forgot-password enumeration safety ----------
class TestForgotPasswordEnumeration:
    def test_unknown_identifier_returns_generic_ok(self):
        r = requests.post(f"{BASE_URL}/api/auth/forgot-password",
                          json={"identifier": "nobody@nowhere.com"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        msg = (body.get("message") or "").lower()
        # Should not reveal account state
        assert "if an account" in msg or "verification code" in msg
        assert "not found" not in msg
        assert "does not exist" not in msg


# ---------- Reset-password happy & error paths ----------
class TestResetPasswordFlows:
    def test_no_active_reset_returns_400(self, db):
        _run(_clear_reset(db, MARIA_EMAIL))
        r = requests.post(f"{BASE_URL}/api/auth/reset-password", json={
            "identifier": MARIA_EMAIL, "code": "123456", "new_password": "Whatever123!"
        }, timeout=15)
        assert r.status_code == 400
        assert "no active" in r.json().get("detail", "").lower()

    def test_short_password_returns_422(self, db):
        _run(_seed_reset(db, MARIA_EMAIL, "654321"))
        r = requests.post(f"{BASE_URL}/api/auth/reset-password", json={
            "identifier": MARIA_EMAIL, "code": "654321", "new_password": "short"
        }, timeout=15)
        assert r.status_code == 422, r.text

    def test_expired_code_returns_400(self, db):
        _run(_seed_reset(db, MARIA_EMAIL, "654321", expires_delta_minutes=-1))
        r = requests.post(f"{BASE_URL}/api/auth/reset-password", json={
            "identifier": MARIA_EMAIL, "code": "654321", "new_password": "SomethingLong123!"
        }, timeout=15)
        assert r.status_code == 400
        assert "expired" in r.json().get("detail", "").lower()

    def test_wrong_code_then_correct_then_login(self, db):
        # Seed correct code 654321
        _run(_seed_reset(db, MARIA_EMAIL, "654321"))

        # Wrong code -> 400
        r_bad = requests.post(f"{BASE_URL}/api/auth/reset-password", json={
            "identifier": MARIA_EMAIL, "code": "000000", "new_password": "MariaNew2026!"
        }, timeout=15)
        assert r_bad.status_code == 400
        assert "invalid" in r_bad.json().get("detail", "").lower()

        # Correct code -> 200
        r_ok = requests.post(f"{BASE_URL}/api/auth/reset-password", json={
            "identifier": MARIA_EMAIL, "code": "654321", "new_password": "MariaNew2026!"
        }, timeout=15)
        assert r_ok.status_code == 200, r_ok.text
        assert r_ok.json().get("ok") is True

        # Login with new password
        r_login = requests.post(f"{BASE_URL}/api/auth/login", json={
            "identifier": MARIA_EMAIL, "password": "MariaNew2026!"
        }, timeout=15)
        assert r_login.status_code == 200, r_login.text
        data = r_login.json()
        assert "token" in data
        assert data["user"]["role"] == "patient"

        # Old password should NOT work
        r_old = requests.post(f"{BASE_URL}/api/auth/login", json={
            "identifier": MARIA_EMAIL, "password": ORIGINAL_PASSWORD
        }, timeout=15)
        assert r_old.status_code == 401
