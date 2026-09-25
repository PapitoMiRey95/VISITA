"""Manual verification of /api/auth/google custom logic with the Emergent
session-data call mocked. Single asyncio loop so motor stays valid.
Run from /app/backend: python -m tests.test_google_auth_manual"""
import asyncio
import os
from unittest import mock

import httpx
from pymongo import MongoClient

import server

sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TEMP = ["gtest.active@example.com", "gtest.inactive@example.com"]


def _fake_client(profile, raise_get=False):
    class FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return profile
    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None):
            if raise_get:
                raise RuntimeError("boom")
            return FakeResp()
    return lambda *a, **k: FakeClient()


def setup():
    teardown()
    sync.users.insert_one({"email": "gtest.active@example.com", "role": "patient",
                           "active": True, "name": "GTest Active", "password_hash": "x"})
    sync.users.insert_one({"email": "gtest.inactive@example.com", "role": "patient",
                           "active": False, "name": "GTest Inactive", "password_hash": "x"})


def teardown():
    sync.users.delete_many({"email": {"$in": TEMP}})


async def main():
    setup()
    transport = httpx.ASGITransport(app=server.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    results = []

    async def call(profile, raise_get=False):
        with mock.patch.object(httpx, "AsyncClient", _fake_client(profile, raise_get)):
            return await client.post("/api/auth/google", json={"session_id": "x"})

    r = await call({}, raise_get=True)
    results.append(("verify_failure_401", r.status_code == 401, r.status_code))

    r = await call({"id": "sub_none", "email": "nobody-zzz@example.com", "name": "X"})
    ok = r.status_code == 404 and "No VIsita EMR account was found" in r.json().get("detail", "")
    results.append(("no_account_404", ok, r.status_code))

    r = await call({"id": "sub_admin", "email": "kevinrodriguez9528@gmail.com", "name": "Admin"})
    results.append(("admin_blocked_404", r.status_code == 404, r.status_code))

    r = await call({"id": "sub_123", "email": "gtest.active@example.com", "name": "GTest Active"})
    linked = sync.users.find_one({"email": "gtest.active@example.com"}).get("google_sub")
    ok = r.status_code == 200 and bool(r.json().get("token")) and linked == "sub_123"
    results.append(("active_first_login_200_linked", ok, (r.status_code, linked)))

    r = await call({"id": "sub_123", "email": "gtest.active@example.com", "name": "GTest Active"})
    results.append(("same_sub_relogin_200", r.status_code == 200, r.status_code))

    r = await call({"id": "sub_DIFFERENT", "email": "gtest.active@example.com", "name": "GTest Active"})
    ok = r.status_code == 403 and "different Google account" in r.json().get("detail", "")
    results.append(("sub_mismatch_403", ok, r.status_code))

    r = await call({"id": "sub_inact", "email": "gtest.inactive@example.com", "name": "GTest Inactive"})
    ok = r.status_code == 403 and "disabled" in r.json().get("detail", "")
    results.append(("inactive_blocked_403", ok, r.status_code))

    audit_actions = set(d["action"] for d in sync.audit_logs.find(
        {"action": {"$regex": "^google_"}}).limit(50))
    results.append(("audit_events", {"google_login_no_account", "google_account_linked",
                                     "google_login_success"}.issubset(audit_actions), sorted(audit_actions)))

    await client.aclose()
    teardown()

    print("\n=== Google Auth logic verification ===")
    allok = True
    for name, ok, detail in results:
        allok = allok and ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name} -> {detail}")
    print("=== OVERALL:", "PASS" if allok else "FAIL", "===")


if __name__ == "__main__":
    asyncio.run(main())
