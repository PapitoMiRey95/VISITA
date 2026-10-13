"""Scoped PREVIEW import of legacy tblAPE Annual Exam month -> patient_directory.annual_exam_month.
Rules: ACTIVE canonical directory patient only (exact 10-digit OHIP match, no fuzzy), no patient creation,
skip unmapped / review / ambiguous / multi-profile / blank month. Idempotent on import_key.
Usage: python import_ape_annual.py <csv> <manifest.json> [--apply]"""
import asyncio
import collections
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
SOURCE_TYPE = "LEGACY_TBLAPE_ANNUAL"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
digits = lambda s: re.sub(r"\D", "", s or "")


async def preflight(db, rows):
    dmap = collections.defaultdict(list)
    async for d in db.patient_directory.find({}, {"_id": 0, "id": 1, "health_card_number": 1, "patient_status": 1, "annual_exam_month": 1, "annual_exam_month_source": 1}):
        if len(digits(d.get("health_card_number"))) == 10:
            dmap[digits(d["health_card_number"])].append(d)
    pmap = collections.defaultdict(list)
    async for p in db.patients.find({}, {"_id": 0, "id": 1, "health_card_number": 1, "matched_directory_id": 1}):
        if len(digits(p.get("health_card_number"))) == 10:
            pmap[digits(p["health_card_number"])].append(p)
    skipped, plan = collections.Counter(), {}
    for r in rows:
        if r["needs_review"] == "True":
            skipped["review_conflict"] += 1
            continue
        k = digits(r["legacy_mcp_raw"])
        if len(k) != 10:
            skipped["review_conflict"] += 1
            continue
        hits = dmap.get(k, [])
        canon = {("directory", d["id"]) for d in hits} | {("directory", p["matched_directory_id"]) if p.get("matched_directory_id") else ("patient", p["id"]) for p in pmap.get(k, [])}
        if not canon:
            skipped["unmapped"] += 1
            continue
        if len(canon) > 1 or next(iter(canon))[0] != "directory":
            skipped["review_conflict"] += 1
            continue
        if hits[0]["patient_status"] != "ACTIVE":
            skipped["not_active"] += 1
            continue
        if not r["annual_exam_month"]:
            skipped["blank_month"] += 1
            continue
        assert r["annual_exam_month"] in MONTHS, r
        plan.setdefault(hits[0]["id"], []).append(r)
    multi = [c for c, v in plan.items() if len(v) > 1]
    for c in multi:
        skipped["review_conflict"] += len(plan.pop(c))
    return plan, skipped, len(dmap)


async def main(argv):
    rows = list(csv.DictReader(open(argv[0], encoding="utf-8-sig", newline="")))
    manifest = json.load(open(argv[1]))
    assert manifest["counts"]["normalized_annual_profiles"] == len(rows) == 1214
    assert manifest["annual_exam_contract"]["field"] == "annual_exam_month" and manifest["identity_contract"]["do_not_create_patients"]
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    plan, skipped, _ = await preflight(db, rows)
    report = {"directory_total": await db.patient_directory.count_documents({}), "directory_active": await db.patient_directory.count_documents({"patient_status": "ACTIVE"}),
              "profiles": len(rows), "eligible_active_mapped_with_month": len(plan), "will_write": len(plan), "skipped": dict(skipped),
              "check_total": len(plan) + sum(skipped.values())}
    print("PREFLIGHT", report)
    if "--apply" not in argv:
        return
    now = datetime.now(timezone.utc).isoformat()
    written = unchanged = 0
    for did, (r,) in plan.items():
        src = {"source_type": SOURCE_TYPE, "import_key": r["import_key"], "legacy_mcp_raw": r["legacy_mcp_raw"], "legacy_itemnos": r["legacy_itemnos"], "imported_at": now}
        res = await db.patient_directory.update_one({"id": did, "patient_status": "ACTIVE", "annual_exam_month_source.import_key": {"$ne": r["import_key"]}},
                                                    {"$set": {"annual_exam_month": r["annual_exam_month"], "annual_exam_month_source": src, "updated_at": now}})
        written += res.modified_count
        unchanged += 1 - res.modified_count
    print("APPLIED", {"written": written, "already_imported_unchanged": unchanged, "directory_total_after": await db.patient_directory.count_documents({}),
                      "docs_with_month": await db.patient_directory.count_documents({"annual_exam_month": {"$in": list(MONTHS)}})})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
