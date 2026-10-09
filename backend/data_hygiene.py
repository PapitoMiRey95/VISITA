"""TEMPORARY admin-only, token-gated data-hygiene operations (scoped to explicit appointment ids).

Two narrow operations, both idempotent, dry_run by default, never delete/reset:
  stamp_practice_id   -> $set practice_id ONLY on listed records that have none
  backfill_slot_locks -> create missing appointment_slots locks for listed records
Conflicts are always reported and skipped — never auto-resolved.
Remove this module + endpoint after the Production repair is verified.
"""
from datetime import datetime, timezone

import slots as slots_mod

ACTIVE = ["requested", "confirmed", "rescheduled"]
MAX_IDS = 200


def _now():
    return datetime.now(timezone.utc).isoformat()


def _missing_pid(a):
    return not a.get("practice_id")


async def _load(db, ids):
    rows = await db.appointment_requests.find({"id": {"$in": ids}}, {"_id": 0, "patient_note": 0}).to_list(MAX_IDS)
    found = {a["id"]: a for a in rows}
    return found, [i for i in ids if i not in found]


def _rec(a, **extra):
    ds, t = slots_mod._appt_when(a)
    return {"ref": a.get("ref_number"), "id": a.get("id"), "status": a.get("status"), "when": f"{ds} {t}",
            "practice_id": a.get("practice_id"), **extra}


async def stamp_practice_id(db, ids, apply, actor):
    practices = await db.practices.find({"active": True}, {"_id": 0, "id": 1, "slug": 1}).to_list(50)
    if len(practices) != 1:
        return {"error": "stamping requires exactly ONE active practice", "active_practices": practices}
    default = practices[0]
    found, not_found = await _load(db, ids)
    out = {"operation": "stamp_practice_id", "mode": "APPLY" if apply else "DRY-RUN", "default_practice": default,
           "would_stamp": [], "stamped": [], "already_stamped": [], "conflicts": [], "not_active": [], "not_found": not_found}
    for i in ids:
        a = found.get(i)
        if not a:
            continue
        if not _missing_pid(a):
            out["already_stamped"].append(_rec(a))
            continue
        if a.get("status") not in ACTIVE:
            out["not_active"].append(_rec(a))
            continue
        pid, evidence = default["id"], "single active practice (default)"
        pt = await db.patients.find_one({"id": a.get("patient_id")}, {"_id": 0, "practice_id": 1}) if a.get("patient_id") else None
        if pt and pt.get("practice_id"):
            pid, evidence = pt["practice_id"], "portal patient.practice_id"
        rec = _rec(a, evidence=evidence, proposed_practice_id=pid)
        if pid != default["id"]:
            out["conflicts"].append(rec)
            continue
        out["would_stamp"].append(rec)
        if apply:
            r = await db.appointment_requests.update_one(
                {"id": a["id"], "$or": [{"practice_id": None}, {"practice_id": {"$exists": False}}]},
                {"$set": {"practice_id": pid, "practice_id_stamped_by": "data_hygiene", "practice_id_stamped_at": _now()},
                 "$push": {"history": {"action": "practice_id_stamped", "practice_id": pid, "evidence": evidence,
                                       "by": (actor or {}).get("id"), "at": _now()}}})
            if r.modified_count == 1:
                out["stamped"].append(rec)
    out["summary"] = {k: len(out[k]) for k in ("would_stamp", "stamped", "already_stamped", "conflicts", "not_active", "not_found")}
    return out


def _state_for(a):
    st = a.get("status")
    if st in ("confirmed", "rescheduled", "completed", "no_show"):
        return slots_mod.CONFIRMED
    if st == "requested":
        return slots_mod.HELD
    if st == "cancelled" and (a.get("cancellation") or {}).get("free_slot") is False:
        return slots_mod.BLOCKED
    return None


async def backfill_slot_locks(db, ids, apply, actor):
    found, not_found = await _load(db, ids)
    out = {"operation": "backfill_slot_locks", "mode": "APPLY" if apply else "DRY-RUN",
           "would_create": [], "created": [], "already_locked": [], "conflicts": [], "skipped_inactive": [],
           "skipped_no_time": [], "not_found": not_found}
    seen = {}
    for i in ids:
        a = found.get(i)
        if not a:
            continue
        state = _state_for(a)
        if not state:
            out["skipped_inactive"].append(_rec(a))
            continue
        ds, t = slots_mod._appt_when(a)
        if not ds or not t:
            out["skipped_no_time"].append(_rec(a))
            continue
        key = (a.get("practice_id"), slots_mod.slot_start(ds, t))
        if await db[slots_mod.COLL].find_one({"appointment_id": a["id"]}):
            out["already_locked"].append(_rec(a, state=state))
            seen[key] = a["id"]
            continue
        # conflict = existing lock on the slot, another listed record on the slot, or any
        # other ACTIVE appointment record in the DB occupying the same practice slot
        existing = await db[slots_mod.COLL].find_one({"practice_id": key[0], "slot_start": key[1]}, {"_id": 0, "appointment_id": 1})
        others = []
        if existing and existing.get("appointment_id") != a["id"]:
            others.append(existing["appointment_id"])
        if seen.get(key) and seen[key] != a["id"]:
            others.append(seen[key])
        q = {"id": {"$ne": a["id"]}, "status": {"$in": slots_mod.ACTIVE_APPT_STATUSES}, **slots_mod._practice_filter(key[0])}
        async for o in db.appointment_requests.find(q, {"_id": 0, "id": 1, "ref_number": 1, "status": 1, "slot_date": 1, "slot_time": 1,
                                                       "confirmed_date": 1, "confirmed_time": 1, "confirmed_slot_time": 1,
                                                       "preferred_options": 1, "preferred_date": 1, "preferred_time": 1}):
            ods, ot = slots_mod._appt_when(o)
            if ods == ds and ot == t:
                others.append(f"{o.get('ref_number')} ({o.get('status')})")
        if others:
            out["conflicts"].append(_rec(a, state=state, slot_start=key[1], conflicts_with=sorted(set(others))))
            continue
        seen[key] = a["id"]
        rec = _rec(a, state=state, slot_start=key[1])
        out["would_create"].append(rec)
        if apply:
            try:
                await slots_mod.reserve(db, key[0], ds, t, a["id"], state, actor="data_hygiene")
                out["created"].append(rec)
            except slots_mod.SlotTaken:
                out["conflicts"].append(_rec(a, state=state, slot_start=key[1], conflicts_with=["unique-index"]))
    out["summary"] = {k: len(out[k]) for k in ("would_create", "created", "already_locked", "conflicts",
                                                "skipped_inactive", "skipped_no_time", "not_found")}
    return out


# Hard allowlist: the ONLY legacy past requests this operation may ever touch.
STALE_REQUEST_ALLOWLIST = {"APT-000099", "APT-000100", "APT-000103"}


async def close_stale_request(db, ids, apply, actor):
    import availability as avail_mod
    found, not_found = await _load(db, ids)
    out = {"operation": "close_stale_request", "mode": "APPLY" if apply else "DRY-RUN",
           "would_close": [], "closed": [], "already_closed": [], "refused_not_allowlisted": [],
           "refused_not_requested": [], "refused_not_past": [], "not_found": not_found}
    for i in ids:
        a = found.get(i)
        if not a:
            continue
        if a.get("ref_number") not in STALE_REQUEST_ALLOWLIST:
            out["refused_not_allowlisted"].append(_rec(a))
            continue
        if a.get("status") == "cancelled" and (a.get("cancellation") or {}).get("reason") == "stale_past_request":
            out["already_closed"].append(_rec(a))
            continue
        if a.get("status") != "requested":
            out["refused_not_requested"].append(_rec(a))
            continue
        ds, t = slots_mod._appt_when(a)
        if not ds or not avail_mod.is_past_slot(None, ds, t):
            out["refused_not_past"].append(_rec(a))
            continue
        rec = _rec(a, new_status="cancelled", reason="stale_past_request", notify_patient=False)
        out["would_close"].append(rec)
        if apply:
            at = _now()
            r = await db.appointment_requests.update_one(
                {"id": a["id"], "status": "requested"},
                {"$set": {"status": "cancelled", "updated_at": at,
                          "cancellation": {"reason": "stale_past_request", "by": "data_hygiene", "by_id": (actor or {}).get("id"),
                                           "at": at, "free_slot": True, "notified_patient": False}},
                 "$push": {"history": {"action": "cancelled", "status": "cancelled", "note": "Stale legacy request closed (past date, slot taken by a confirmed booking)",
                                       "by": "data_hygiene", "by_id": (actor or {}).get("id"), "at": at}}})
            if r.modified_count == 1:
                out["closed"].append(rec)
    out["summary"] = {k: len(out[k]) for k in ("would_close", "closed", "already_closed", "refused_not_allowlisted",
                                                "refused_not_requested", "refused_not_past", "not_found")}
    return out
