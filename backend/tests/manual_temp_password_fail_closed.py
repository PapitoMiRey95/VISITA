"""Preview-only scenario check for temp-password fail-closed login + audit regex hardening.
Creates throwaway users, exercises /api/auth/login, then deletes them."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
import auth as authlib  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

API = "http://localhost:8001/api"
PW = "Tmp-Check-2026!x"
CASES = {
    "regular": {},
    "temp_valid": {"must_change_password": True, "temp_password_expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()},
    "temp_expired": {"must_change_password": True, "temp_password_expires_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
    "temp_malformed": {"must_change_password": True, "temp_password_expires_at": "not-a-date"},
    "no_temp_flag_but_expiry": {"must_change_password": False, "temp_password_expires_at": "garbage"},
}
EXPECT = {"regular": 200, "temp_valid": 200, "temp_expired": 403, "temp_malformed": 403, "no_temp_flag_but_expiry": 200}


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    emails = [f"qa.tmpcheck.{k}@visita.test".lower() for k in CASES]
    await db.users.delete_many({"email": {"$in": emails}})
    results, ok = {}, True
    try:
        for k, extra in CASES.items():
            email = f"qa.tmpcheck.{k}@visita.test".lower()
            await db.users.insert_one({"email": email, "name": f"QA {k}", "role": "patient", "active": True,
                                       "password_hash": authlib.hash_password(PW), **extra})
            r = requests.post(f"{API}/auth/login", json={"email": email, "password": PW}, timeout=20)
            results[k] = (r.status_code, r.json().get("detail") if r.status_code != 200 else "ok")
            if r.status_code != EXPECT[k]:
                ok = False
        bad = requests.post(f"{API}/auth/login", json={"email": emails[0], "password": "wrong"}, timeout=20)
        results["wrong_password"] = (bad.status_code, bad.json().get("detail"))
        ok = ok and bad.status_code == 401
    finally:
        await db.users.delete_many({"email": {"$in": emails}})
        left = await db.users.count_documents({"email": {"$in": emails}})
    for k, v in results.items():
        print(f"{k:28s} -> {v}")
    print("cleanup_remaining:", left)
    print("PASS" if ok and left == 0 else "FAIL")
    return 0 if ok and left == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
