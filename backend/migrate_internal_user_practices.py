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


async def main(dry_run: bool):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    practice = await db.practices.find_one({"slug": "dr-aguayo"})
    if not practice:
        print("ERROR: default dr-aguayo practice not found. Run migrate_practice_backfill.py first.")
        client.close()
        return 1
    pid = practice["id"]
    q = {"role": {"$in": CLINIC_ROLES},
         "$or": [{"practice_id": {"$exists": False}}, {"practice_id": None}]}
    count = await db.users.count_documents(q)
    print(f"=== internal-user practice backfill {'(DRY RUN)' if dry_run else '(APPLY)'} ===")
    print(f"internal users to assign to dr-aguayo ({pid}): {count}")
    if not dry_run and count:
        res = await db.users.update_many(q, {"$set": {"practice_id": pid}})
        print(f"assigned {res.modified_count} users")
    print("=== done ===")
    client.close()
    return 0


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
