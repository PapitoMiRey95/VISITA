"""Explicit, idempotent back-fill of `appointment_slots` from existing appointments.

NEVER runs at startup. Default is DRY-RUN (report only). Apply with --apply.
  python backfill_slot_locks.py            # dry run + conflict report
  python backfill_slot_locks.py --apply    # create missing locks (never modifies appointments)
Rules: CONFIRMED/rescheduled/completed/no_show -> CONFIRMED lock; requested -> HELD lock;
cancelled with cancellation.free_slot == False -> BLOCKED lock; everything else -> no lock.
Conflicts (two appointments on one slot) are reported for manual review — never auto-resolved.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

import availability as avail_mod
import slots as slots_mod

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def _state_for(a):
    st = a.get("status")
    if st in ("confirmed", "rescheduled", "completed", "no_show"):
        return slots_mod.CONFIRMED
    if st == "requested":
        return slots_mod.HELD
    if st == "cancelled" and (a.get("cancellation") or {}).get("free_slot") is False:
        return slots_mod.BLOCKED
    return None


def _when(a):
    ds = a.get("slot_date") or a.get("confirmed_date")
    t = a.get("slot_time") or a.get("confirmed_slot_time") or avail_mod._norm_time(a.get("confirmed_time") or "")
    if not ds and a.get("status") == "requested":
        o = (a.get("preferred_options") or [{}])[0]
        ds, t = o.get("date"), avail_mod._norm_time(o.get("time") or "")
    return ds, t


async def run(apply: bool):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    await slots_mod.ensure_indexes(db)
    report = {"scanned": 0, "already_locked": 0, "would_create": 0, "created": 0, "skipped_no_time": 0,
              "skipped_inactive": 0, "conflicts": []}
    seen = {}
    async for a in db.appointment_requests.find({}, {"_id": 0}):
        report["scanned"] += 1
        state = _state_for(a)
        if not state:
            report["skipped_inactive"] += 1
            continue
        ds, t = _when(a)
        if not ds or not t:
            report["skipped_no_time"] += 1
            continue
        key = (a.get("practice_id"), slots_mod.slot_start(ds, t))
        if await db[slots_mod.COLL].find_one({"appointment_id": a["id"]}):
            report["already_locked"] += 1
            seen[key] = a["id"]
            continue
        existing = await db[slots_mod.COLL].find_one({"practice_id": key[0], "slot_start": key[1]})
        other = (existing or {}).get("appointment_id") or seen.get(key)
        if other and other != a["id"]:
            report["conflicts"].append({"slot": key[1], "appointment_id": a["id"], "ref": a.get("ref_number"),
                                        "status": a.get("status"), "conflicts_with": other})
            continue
        seen[key] = a["id"]
        report["would_create"] += 1
        if apply:
            try:
                await slots_mod.reserve(db, key[0], ds, t, a["id"], state, actor="backfill")
                report["created"] += 1
            except slots_mod.SlotTaken:
                report["conflicts"].append({"slot": key[1], "appointment_id": a["id"], "ref": a.get("ref_number"),
                                            "status": a.get("status"), "conflicts_with": "unique-index"})
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] scanned={report['scanned']} already_locked={report['already_locked']} "
          f"would_create={report['would_create']} created={report['created']} "
          f"skipped_no_time={report['skipped_no_time']} skipped_inactive={report['skipped_inactive']} "
          f"conflicts={len(report['conflicts'])}")
    for c in report["conflicts"]:
        print("  CONFLICT (manual review):", c)
    client.close()
    return report


if __name__ == "__main__":
    asyncio.run(run(apply="--apply" in sys.argv))
