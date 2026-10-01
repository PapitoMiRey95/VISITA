"""Stage B — PREVIEW migration: assign internal clinic users (staff/physician/admin)
to the default dr-aguayo practice so server-side practice scoping works.

EXPLICIT + IDEMPOTENT. NOT wired into startup.
    python migrate_internal_user_practices.py            # apply
    python migrate_internal_user_practices.py --dry-run  # report only
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
CLINIC_ROLES = ["staff", "physician", "admin"]


async def run(db, dry_run: bool = False) -> dict:
    """Importable entry point. Returns a safe summary (no secrets, no raw docs)."""
    practice = await db.practices.find_one({"slug": "dr-aguayo"})
    if not practice:
        return {
            "migration": "internal_user_practices",
            "mode": "dry-run" if dry_run else "apply",
            "examined": 0, "changed": 0, "ok": False,
            "errors": ["default dr-aguayo practice not found; run practice_backfill first"],
        }
    pid = practice["id"]
    q = {"role": {"$in": CLINIC_ROLES},
         "$or": [{"practice_id": {"$exists": False}}, {"practice_id": None}]}
    count = await db.users.count_documents(q)
    changed = 0
    if count and not dry_run:
        res = await db.users.update_many(q, {"$set": {"practice_id": pid}})
        changed = res.modified_count
    return {
        "migration": "internal_user_practices",
        "mode": "dry-run" if dry_run else "apply",
        "examined": count, "changed": changed, "ok": True, "errors": [],
    }


async def main(dry_run: bool):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    summary = await run(db, dry_run)
    print(summary)
    client.close()
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
