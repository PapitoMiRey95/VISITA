"""Explicit, idempotent stamping of missing practice_id on appointment_requests.

NEVER runs at startup. DRY-RUN by default (zero writes). Apply with --apply.
  python stamp_practice_id.py            # report every record that WOULD be stamped
  python stamp_practice_id.py --apply    # $set practice_id only on records that have none
Evidence used (per record): the linked portal patient's practice_id, else the directory
record's practice, else the single active (default) practice. Records whose patient belongs
to a DIFFERENT practice than the default are reported as CONFLICT and never stamped.
Only active + requested records are in scope by default; pass --include-closed to also
report cancelled/declined/completed/no_show history records (reported separately).
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
ACTIVE = ["requested", "confirmed", "rescheduled"]


async def run(apply: bool, include_closed: bool):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    practices = await db.practices.find({"active": True}, {"_id": 0, "id": 1, "slug": 1, "name": 1}).to_list(50)
    default = practices[0] if len(practices) == 1 else None
    print(f"active practices: {[(p['slug'], p['id'][:8]) for p in practices]} default={default and default['slug']}")
    q = {"$or": [{"practice_id": None}, {"practice_id": {"$exists": False}}]}
    if not include_closed:
        q["status"] = {"$in": ACTIVE}
    rows = await db.appointment_requests.find(q, {"_id": 0, "patient_name": 0, "patient_note": 0}).to_list(5000)
    out = {"would_stamp": [], "conflicts": [], "no_evidence": [], "closed_history": []}
    for a in rows:
        evidence, pid = None, None
        pt = await db.patients.find_one({"id": a.get("patient_id")}, {"_id": 0, "practice_id": 1}) if a.get("patient_id") else None
        if pt and pt.get("practice_id"):
            pid, evidence = pt["practice_id"], "portal patient.practice_id"
        else:
            d = await db.patient_directory.find_one({"$or": [{"id": a.get("directory_id") or a.get("patient_id")},
                                                             {"linked_patient_id": a.get("patient_id")}]}, {"_id": 0, "practice_id": 1})
            if d and d.get("practice_id"):
                pid, evidence = d["practice_id"], "directory.practice_id"
            elif default:
                pid, evidence = default["id"], "single active practice (default)"
        when = a.get("appointment_at") or f"{a.get('confirmed_date') or a.get('preferred_date')} {a.get('confirmed_slot_time') or a.get('confirmed_time') or a.get('preferred_time')}"
        rec = {"ref": a.get("ref_number"), "id": a.get("id"), "status": a.get("status"), "when": when,
               "created_at": (a.get("created_at") or "")[:19], "evidence": evidence, "proposed_practice_id": pid}
        if a.get("status") not in ACTIVE:
            out["closed_history"].append(rec)
            continue
        if not pid:
            out["no_evidence"].append(rec)
        elif default and pid != default["id"]:
            out["conflicts"].append(rec)
        else:
            out["would_stamp"].append(rec)
            if apply:
                await db.appointment_requests.update_one(
                    {"id": a["id"], "$or": [{"practice_id": None}, {"practice_id": {"$exists": False}}]},
                    {"$set": {"practice_id": pid, "practice_id_stamped_by": "stamp_practice_id.py", "practice_id_stamped_at": __import__("datetime").datetime.utcnow().isoformat()}})
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] scanned={len(rows)} would_stamp={len(out['would_stamp'])} conflicts={len(out['conflicts'])} "
          f"no_evidence={len(out['no_evidence'])} closed_history(reported only)={len(out['closed_history'])}")
    for k in ("would_stamp", "conflicts", "no_evidence", "closed_history"):
        for r in out[k]:
            print(f"  {k.upper()}: {r}")
    client.close()
    return out


if __name__ == "__main__":
    asyncio.run(run(apply="--apply" in sys.argv, include_closed="--include-closed" in sys.argv))
