"""Stage A — PREVIEW migration: create the default Dr. Aguayo practice and stamp
practice_id on existing patient-workflow records.

EXPLICIT + IDEMPOTENT. This is NOT wired into application startup. Run manually:

    python migrate_practice_backfill.py            # apply
    python migrate_practice_backfill.py --dry-run  # report only, no writes

Safe to re-run: it only creates the practice if missing and only stamps records
that do not already carry a practice_id.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

DEFAULT_SLUG = "dr-aguayo"
DEFAULT_CODE = "AGUAYO"

# Patient-workflow collections that must carry the care-ownership scope.
WORKFLOW_COLLECTIONS = [
    "patients",
    "patient_applications",
    "appointment_requests",
    "prescription_requests",
    "imaging_requests",
    "bloodwork_requests",
    "patient_referrals",
    "referrals",
    "patient_updates",
    "patient_messages",
    "private_requests",
    "invoices",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def ensure_default_practice(db, dry_run: bool) -> dict:
    existing = await db.practices.find_one({"slug": DEFAULT_SLUG})
    if existing:
        print(f"[practice] default practice already exists: id={existing['id']} slug={existing['slug']}")
        return existing
    settings = await db.settings.find_one({"id": "clinic"}) or {}
    physician = await db.users.find_one({"role": "physician"})
    practice = {
        "id": str(uuid.uuid4()),
        "slug": DEFAULT_SLUG,
        "registration_code": DEFAULT_CODE,
        "physician_user_id": str(physician["_id"]) if physician else None,
        "physician_name": settings.get("physician_name") or (physician.get("name") if physician else "Dr. Pablo Aguayo"),
        "clinic_name": settings.get("clinic_name") or "",
        "clinic_phone": settings.get("clinic_phone") or "",
        "clinic_address": settings.get("clinic_address") or "",
        "active": True,
        "is_default": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if dry_run:
        print(f"[practice] WOULD CREATE default practice slug={DEFAULT_SLUG} "
              f"physician={practice['physician_name']!r} clinic={practice['clinic_name']!r}")
        return practice
    await db.practices.insert_one({**practice})
    print(f"[practice] CREATED default practice id={practice['id']} slug={practice['slug']} "
          f"physician={practice['physician_name']!r}")
    return practice


async def backfill(db, practice_id: str, dry_run: bool):
    total = 0
    for coll in WORKFLOW_COLLECTIONS:
        missing = {"$or": [{"practice_id": {"$exists": False}}, {"practice_id": None}]}
        count = await db[coll].count_documents(missing)
        if count == 0:
            print(f"[backfill] {coll:24s} already fully scoped (0 to update)")
            continue
        if dry_run:
            print(f"[backfill] {coll:24s} WOULD stamp {count} record(s)")
        else:
            res = await db[coll].update_many(
                missing, {"$set": {"practice_id": practice_id, "practice_backfilled_at": now_iso()}})
            print(f"[backfill] {coll:24s} stamped {res.modified_count} record(s)")
        total += count
    print(f"[backfill] total records {'to update' if dry_run else 'updated'}: {total}")


async def main(dry_run: bool):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    print(f"=== Stage A practice backfill {'(DRY RUN)' if dry_run else '(APPLY)'} ===")
    practice = await ensure_default_practice(db, dry_run)
    await backfill(db, practice["id"], dry_run)
    print("=== done ===")
    client.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    asyncio.run(main(dry))
