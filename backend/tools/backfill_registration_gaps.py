"""Controlled backfill: canonical patient_directory ← preserved verified portal registration (db.patients).
DRY-RUN by default. `--apply` required to write. Scope (this pass only):
  health_card_issue_date, health_card_expiry_date  — fill when canonical blank
  health_card_version_code                          — fill when canonical blank
  sex / sex_code                                    — fill only when BOTH canonical sex and sex_code are absent/unrecognized
Never overwrites a non-blank canonical value. Names, DOB, HC number, email, phones, address: NOT touched (reported only).
Usage: python tools/backfill_registration_gaps.py [--apply] [--pin 795]"""
import argparse, asyncio, os, sys, json
from datetime import datetime, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from profile_completion import SEX_FROM_CODE, SEX_TO_CODE, _blank  # noqa: E402
from db import audit  # noqa: E402

FILL = (("health_card_version", "health_card_version_code"), ("health_card_issue_date", "health_card_issue_date"), ("health_card_expiry_date", "health_card_expiry_date"))
IDENTITY = (("first_name", "first_name"), ("last_name", "last_name"), ("date_of_birth", "date_of_birth"), ("health_card_number", "health_card_number"))
norm = lambda x: "".join(ch for ch in str(x or "").lower() if ch.isalnum())
mask = lambda v: v if _blank(v) else "*" * max(0, len(str(v)) - 4) + str(v)[-4:]
now_iso = lambda: datetime.now(timezone.utc).isoformat()


async def main(apply: bool, pins: list):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    q = {"portal_status": {"$in": ["ACTIVE", "VERIFIED"]}, "verification_status": "verified", "is_demo": {"$ne": True}, "matched_directory_id": {"$ne": None}}
    plan, review, skipped, examined = [], [], 0, 0
    async for p in db.patients.find(q):
        examined += 1
        d = await db.patient_directory.find_one({"id": p["matched_directory_id"]})
        if not d or d.get("patient_status") not in (None, "ACTIVE"):
            skipped += 1
            continue
        pin = str(d.get("visita_patient_id"))
        if pins and pin not in pins:
            continue
        changes, conflicts = {}, {}
        for pk, dk in FILL:
            pv, dv = p.get(pk), d.get(dk)
            if _blank(pv):
                continue
            pv = pv.strip() if isinstance(pv, str) else pv
            if _blank(dv):
                changes[dk] = pv
            elif norm(pv) != norm(dv):
                conflicts[dk] = {"canonical": dv, "registration": pv}
        psex = (p.get("sex") or "").strip() or None
        dsex = (d.get("sex") or "").strip() or SEX_FROM_CODE.get(str(d.get("sex_code") or "").strip().upper())
        if psex and not dsex:
            changes["sex"] = psex
            if _blank(d.get("sex_code")):
                changes["sex_code"] = SEX_TO_CODE.get(psex, "X")
        elif psex and dsex and psex.lower() != dsex.lower():
            conflicts["sex"] = {"canonical": dsex, "registration": psex}
        for pk, dk in IDENTITY:
            pv, dv = p.get(pk), d.get(dk)
            if not _blank(pv) and not _blank(dv) and norm(pv) != norm(dv):
                conflicts[dk] = {"canonical": mask(dv) if "card" in dk else dv, "registration": mask(pv) if "card" in dk else pv}
        if changes:
            plan.append({"pin": pin, "directory_id": d["id"], "patient_id": p["id"], "set": changes})
        if conflicts:
            review.append({"pin": pin, "directory_id": d["id"], "conflicts": conflicts})
    applied = 0
    if apply:
        for row in plan:
            d = await db.patient_directory.find_one({"id": row["directory_id"]})
            safe = {k: v for k, v in row["set"].items() if _blank(d.get(k))}  # re-check at write time
            if not safe:
                continue
            await db.patient_directory.update_one({"id": row["directory_id"]}, {"$set": {**safe, "updated_at": now_iso()}})
            await audit("canonical_refreshed_from_registration", "patient_directory", row["directory_id"],
                        {"id": "system", "name": "backfill_registration_gaps", "role": "system", "practice_id": d.get("practice_id")},
                        meta={"source": "VERIFIED_PORTAL_REGISTRATION", "link_source": "historical_backfill", "patient_id": row["patient_id"],
                              "changes": {k: {"from": None, "to": v} for k, v in safe.items()}, "conflicts": {}})
            applied += 1
    summary = {"mode": "APPLY" if apply else "DRY_RUN", "records_examined": examined, "records_skipped_no_active_directory": skipped, "records_to_update": len(plan), "applied": applied,
               "field_fill_counts": {k: sum(1 for r in plan if k in r["set"]) for k in ("health_card_issue_date", "health_card_expiry_date", "health_card_version_code", "sex", "sex_code")},
               "review_required": len(review), "plan": plan, "review": review}
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); ap.add_argument("--pin", action="append", default=[])
    a = ap.parse_args(); asyncio.run(main(a.apply, a.pin))
