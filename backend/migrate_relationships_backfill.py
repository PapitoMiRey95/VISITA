"""Stage C — idempotent backfill of patient_provider_relationships.

Derives a per-practice relationship for every existing portal patient and every
open patient application. Safe to re-run (upsert_relationship de-dupes). Does NOT
create canonical identities, modify patients/directory, or merge clinical records.

Usage:
  python migrate_relationships_backfill.py            # execute
  python migrate_relationships_backfill.py --dry-run  # report only
"""
import argparse
import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

import relationships as rel_mod

APP_ACTIVE = ["REQUEST_RECEIVED", "WAITING_LIST", "UNDER_REVIEW", "SENT_TO_PHYSICIAN"]


def _patient_status(p):
    vs = p.get("verification_status")
    if vs == "verified" or p.get("portal_status") in ("VERIFIED", "ACTIVE"):
        return rel_mod.ACTIVE
    if vs == "rejected":
        return rel_mod.INACTIVE
    return rel_mod.APPLICANT


async def _duplicate_directory_rows(db):
    """Returns count of (practice_id, directory_id) pairs with >1 relationship row.
    Any value > 0 means the no-duplicate-canonical-identity invariant was violated."""
    pipeline = [
        {"$match": {"directory_id": {"$ne": None}}},
        {"$group": {"_id": {"p": "$practice_id", "d": "$directory_id"}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$count": "dups"},
    ]
    res = await db[rel_mod.COLL].aggregate(pipeline).to_list(1)
    return res[0]["dups"] if res else 0


async def run(db, dry_run: bool = False) -> dict:
    """Importable entry point. Returns a safe summary (counts only, no PHI/raw docs).
    Aborts (ok=False) if duplicate canonical-identity rows are detected."""
    patients_processed = 0
    skipped_no_practice = 0

    patients = await db.patients.find({"active_status": True}).to_list(100000)
    for p in patients:
        if not p.get("practice_id"):
            skipped_no_practice += 1
            continue
        status = _patient_status(p)
        if not dry_run:
            await rel_mod.upsert_relationship(
                db, practice_id=p["practice_id"], status=status,
                directory_id=p.get("matched_directory_id"), patient_id=p["id"],
                visita_patient_id=p.get("visita_patient_id"),
                by="backfill", source="backfill")
        patients_processed += 1

    apps = await db.patient_applications.find({"internal_status": {"$in": APP_ACTIVE}}).to_list(100000)
    app_count = 0
    for a in apps:
        if not a.get("practice_id"):
            skipped_no_practice += 1
            continue
        if not dry_run:
            await rel_mod.upsert_relationship(
                db, practice_id=a["practice_id"], status=rel_mod.APPLICANT,
                directory_id=a.get("matched_directory_id"), application_id=a["id"],
                by="backfill", source="backfill")
        app_count += 1

    total_rel = await db[rel_mod.COLL].count_documents({})
    status_breakdown = {}
    for s in (rel_mod.ACTIVE, rel_mod.APPLICANT, rel_mod.FORMER, rel_mod.INACTIVE):
        status_breakdown[s] = await db[rel_mod.COLL].count_documents({"status": s})
    dups = await _duplicate_directory_rows(db)
    errors = [] if dups == 0 else [f"{dups} duplicate (practice, directory) relationship group(s) detected"]
    return {
        "migration": "relationships_backfill",
        "mode": "dry-run" if dry_run else "apply",
        "patients_processed": patients_processed,
        "open_applications_processed": app_count,
        "skipped_no_practice": skipped_no_practice,
        "relationships_total": total_rel,
        "status_breakdown": status_breakdown,
        "duplicate_groups": dups,
        "ok": dups == 0,
        "errors": errors,
    }


async def main(dry_run: bool):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    summary = await run(db, dry_run)
    print(summary)
    client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        print("MONGO_URL and DB_NAME must be set in the environment.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(args.dry_run))
