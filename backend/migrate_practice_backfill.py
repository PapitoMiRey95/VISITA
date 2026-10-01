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
    "internal_messages",
    "private_requests",
    "invoices",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def ensure_default_practice(db, dry_run: bool):
    existing = await db.practices.find_one({"slug": DEFAULT_SLUG})
    if existing:
        return existing, {"existed": True, "created": False, "slug": existing.get("slug"),
                          "active": existing.get("active")}
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
    if not dry_run:
        await db.practices.insert_one({**practice})
    return practice, {"existed": False, "created": (not dry_run), "slug": DEFAULT_SLUG,
                      "active": True}


async def backfill(db, practice_id: str, dry_run: bool):
    collections, total_examined, total_changed = [], 0, 0
    for coll in WORKFLOW_COLLECTIONS:
        missing = {"$or": [{"practice_id": {"$exists": False}}, {"practice_id": None}]}
        count = await db[coll].count_documents(missing)
        changed = 0
        if count and not dry_run:
            res = await db[coll].update_many(
                missing, {"$set": {"practice_id": practice_id, "practice_backfilled_at": now_iso()}})
            changed = res.modified_count
        collections.append({"name": coll, "examined": count, "changed": changed})
        total_examined += count
        total_changed += changed
    return collections, total_examined, total_changed


async def run(db, dry_run: bool = False) -> dict:
    """Importable entry point. Returns a safe summary (no secrets, no raw docs)."""
    errors = []
    practice, pinfo = await ensure_default_practice(db, dry_run)
    collections, total_examined, total_changed = await backfill(db, practice["id"], dry_run)
    return {
        "migration": "practice_backfill",
        "mode": "dry-run" if dry_run else "apply",
        "practice": pinfo,
        "collections": collections,
        "total_examined": total_examined,
        "total_changed": total_changed,
        "ok": True,
        "errors": errors,
    }


async def main(dry_run: bool):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    summary = await run(db, dry_run)
    print(summary)
    client.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    asyncio.run(main(dry))
