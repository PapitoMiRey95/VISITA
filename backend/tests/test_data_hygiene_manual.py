"""Manual E2E for the temporary data-hygiene endpoint (Preview). Creates TEMP fixtures, cleans them up."""
import asyncio
import json
import os
import sys
import urllib.request
import uuid

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
API = [l.split("=", 1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL")][0]
TOKEN_ENV = os.environ["MAINTENANCE_TOKEN"]


def post(path, body, jwt):
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 hygiene-test"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST", headers=headers)
    return json.load(urllib.request.urlopen(req))


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    jwt = post("/api/auth/login", {"email": "kevinrodriguez9528@gmail.com", "password": "VisitaAdmin2026!"}, "")["token"]
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    base = {"patient_id": None, "created_at": "2026-10-01T00:00:00", "history": [], "reason": "hygiene-test"}
    await db.appointment_requests.insert_many([
        {**base, "id": a, "ref_number": "TST-A", "status": "confirmed", "confirmed_date": "2031-01-06", "confirmed_slot_time": "11:30"},
        {**base, "id": b, "ref_number": "TST-B", "status": "requested", "preferred_options": [{"date": "2031-01-06", "time": "11:30"}]},
        {**base, "id": c, "ref_number": "TST-C", "status": "confirmed", "confirmed_date": "2031-01-06", "confirmed_slot_time": "12:00"},
    ])
    ids = [a, b, c]
    try:
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "stamp_practice_id", "appointment_ids": ids}, jwt)
        print("stamp dry:", r["summary"]); assert r["summary"]["would_stamp"] == 3 and r["summary"]["stamped"] == 0
        assert (await db.appointment_requests.find_one({"id": a})).get("practice_id") is None
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "stamp_practice_id", "appointment_ids": ids, "dry_run": False}, jwt)
        print("stamp apply:", r["summary"], [x["ref"] for x in r["stamped"]]); assert r["summary"]["stamped"] == 3
        doc = await db.appointment_requests.find_one({"id": a}, {"_id": 0})
        assert doc["practice_id"] == r["default_practice"]["id"] and doc["history"][-1]["action"] == "practice_id_stamped" and doc["reason"] == "hygiene-test"
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "stamp_practice_id", "appointment_ids": ids, "dry_run": False}, jwt)
        print("stamp re-apply (idempotent):", r["summary"]); assert r["summary"]["already_stamped"] == 3 and r["summary"]["stamped"] == 0
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "backfill_slot_locks", "appointment_ids": ids}, jwt)
        print("backfill dry:", r["summary"], "conflicts:", [(x["ref"], x["conflicts_with"]) for x in r["conflicts"]])
        assert r["summary"]["would_create"] == 1 and r["summary"]["conflicts"] == 2
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "backfill_slot_locks", "appointment_ids": ids, "dry_run": False}, jwt)
        print("backfill apply:", r["summary"]); assert r["summary"]["created"] == 1 and r["summary"]["conflicts"] == 2
        assert await db.appointment_slots.count_documents({"appointment_id": {"$in": ids}}) == 1
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "backfill_slot_locks", "appointment_ids": ids, "dry_run": False}, jwt)
        print("backfill re-apply:", r["summary"]); assert r["summary"]["already_locked"] == 1 and r["summary"]["created"] == 0
        n = await db.audit_logs.count_documents({"action": "data_hygiene", "meta.ids": a})
        print("audit rows:", n); assert n == 6
        # close_stale_request: allowlisted past (ok), allowlisted future (refused), non-allowlisted past (refused)
        s1, s2, s3 = (str(uuid.uuid4()) for _ in range(3))
        ids2 = [s1, s2, s3]
        await db.appointment_requests.insert_many([
            {**base, "id": s1, "ref_number": "APT-000099", "status": "requested", "preferred_options": [{"date": "2026-10-07", "time": "14:30"}]},
            {**base, "id": s2, "ref_number": "APT-000100", "status": "requested", "preferred_options": [{"date": "2031-10-07", "time": "14:30"}]},
            {**base, "id": s3, "ref_number": "APT-000107", "status": "requested", "preferred_options": [{"date": "2026-10-07", "time": "14:30"}]},
        ])
        ids += ids2
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "close_stale_request", "appointment_ids": ids2 + [a]}, jwt)
        print("close dry:", r["summary"])
        assert r["summary"] == {"would_close": 1, "closed": 0, "already_closed": 0, "refused_not_allowlisted": 2,
                                "refused_not_requested": 0, "refused_not_past": 1, "not_found": 0}
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "close_stale_request", "appointment_ids": ids2, "dry_run": False}, jwt)
        print("close apply:", r["summary"]); assert r["summary"]["closed"] == 1 and r["closed"][0]["id"] == s1
        d = await db.appointment_requests.find_one({"id": s1}, {"_id": 0})
        assert d["status"] == "cancelled" and d["cancellation"]["reason"] == "stale_past_request" and d["history"][-1]["action"] == "cancelled" and d["reason"] == "hygiene-test"
        assert (await db.appointment_requests.find_one({"id": s2}))["status"] == "requested"
        assert (await db.appointment_requests.find_one({"id": s3}))["status"] == "requested"
        assert await db.outbound_notifications.count_documents({"created_at": {"$gt": d["cancellation"]["at"]}}) == 0
        r = post("/api/internal/admin/data-hygiene", {"token": TOKEN_ENV, "operation": "close_stale_request", "appointment_ids": ids2, "dry_run": False}, jwt)
        print("close re-apply:", r["summary"]); assert r["summary"]["already_closed"] == 1 and r["summary"]["closed"] == 0
        print("ALL PASS")
    finally:
        await db.appointment_requests.delete_many({"id": {"$in": ids}})
        await db.appointment_slots.delete_many({"appointment_id": {"$in": ids}})
        await db.audit_logs.delete_many({"action": "data_hygiene", "meta.ids": {"$in": ids}})


asyncio.run(main())
