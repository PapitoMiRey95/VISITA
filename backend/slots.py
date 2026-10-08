"""Shared appointment slot reservation layer (authoritative active locks).

`appointment_slots` holds ONE document per actively reserved/blocked slot:
  {id, practice_id, slot_start "YYYY-MM-DDTHH:MM", date, time, appointment_id,
   state HELD|CONFIRMED|BLOCKED, created_at, updated_at, created_by}
A UNIQUE index on (practice_id, slot_start) is the final server-side guard:
two simultaneous reservations can never both succeed. Appointment history always
lives in `appointment_requests`; this collection is only the reservation layer.
"""
import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

import availability as avail_mod

COLL = "appointment_slots"
HELD, CONFIRMED, BLOCKED = "HELD", "CONFIRMED", "BLOCKED"
ACTIVE_APPT_STATUSES = ["requested", "confirmed", "rescheduled", "completed", "no_show"]
SLOT_TAKEN_MSG = "This time is no longer available. Please select another time."


class SlotTaken(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def slot_start(date_str: str, time_str: str) -> str:
    return f"{date_str}T{avail_mod._norm_time(time_str)}"


def canonical_fields(date_str: str, time_str: str) -> dict:
    """Canonical appointment time fields stored on every new/updated appointment."""
    t24 = avail_mod._norm_time(time_str)
    return {"slot_date": date_str, "slot_time": t24, "appointment_at": f"{date_str}T{t24}"}


async def ensure_indexes(db):
    await db[COLL].create_index([("practice_id", 1), ("slot_start", 1)], unique=True)
    await db[COLL].create_index("appointment_id")


async def reserve(db, practice_id, date_str, time_str, appointment_id, state, actor=None):
    """Atomically reserve a slot. Raises SlotTaken if another active lock exists."""
    t24 = avail_mod._norm_time(time_str)
    doc = {
        "id": str(uuid.uuid4()), "practice_id": practice_id, "slot_start": slot_start(date_str, t24),
        "date": date_str, "time": t24, "appointment_id": appointment_id, "state": state,
        "created_by": actor, "created_at": _now(), "updated_at": _now(),
    }
    try:
        await db[COLL].insert_one(doc)
    except DuplicateKeyError:
        raise SlotTaken()
    doc.pop("_id", None)
    return doc


async def release(db, appointment_id):
    """Free every active lock owned by this appointment (history untouched)."""
    await db[COLL].delete_many({"appointment_id": appointment_id})


async def set_state(db, appointment_id, state):
    await db[COLL].update_many({"appointment_id": appointment_id}, {"$set": {"state": state, "updated_at": _now()}})


async def lock_for(db, appointment_id):
    return await db[COLL].find_one({"appointment_id": appointment_id}, {"_id": 0})


def _practice_filter(practice_id):
    # Single-physician availability: a missing practice_id (legacy patient/appointment) must
    # never hide an occupying record, so None means "all practices".
    if practice_id is None:
        return {}
    return {"practice_id": {"$in": [practice_id, None]}}


async def busy_set(db, practice_id=None) -> set:
    """'YYYY-MM-DD HH:MM' strings occupied for availability. Union of the lock layer
    and legacy appointment records (so un-migrated data is still protected)."""
    busy = set()
    q = _practice_filter(practice_id)
    async for s in db[COLL].find(q, {"_id": 0, "date": 1, "time": 1}):
        busy.add(f"{s['date']} {s['time']}")
    # Authoritative occupancy = every active appointment record (any schema generation),
    # regardless of whether its lock row exists. Locks only add concurrency protection.
    lq = {"status": {"$in": ACTIVE_APPT_STATUSES}, **_practice_filter(practice_id)}
    async for a in db.appointment_requests.find(lq, {"_id": 0, "confirmed_date": 1, "confirmed_time": 1,
                                                      "confirmed_slot_time": 1, "slot_date": 1, "slot_time": 1,
                                                      "status": 1, "preferred_options": 1, "preferred_date": 1,
                                                      "preferred_time": 1}):
        ds, t = _appt_when(a)
        if ds and t:
            busy.add(f"{ds} {t}")
    return busy


def _appt_when(a):
    """(date, 'HH:MM') for any appointment schema generation; requested records fall back
    to their first preferred option."""
    ds = a.get("slot_date") or a.get("confirmed_date")
    t = a.get("slot_time") or a.get("confirmed_slot_time") or avail_mod._norm_time(a.get("confirmed_time") or "")
    if (not ds or not t) and a.get("status") == "requested":
        o = (a.get("preferred_options") or [{}])[0]
        ds = ds or o.get("date") or a.get("preferred_date")
        t = t or avail_mod._norm_time(o.get("time") or a.get("preferred_time") or "")
    return ds, t


async def is_free(db, practice_id, date_str, time_str, exclude_appointment_id=None, duration=None) -> bool:
    """Authoritative pre-check: no lock AND no active appointment record overlaps the slot
    (any schema generation). The unique index in reserve() is the final concurrency guard."""
    t24 = avail_mod._norm_time(time_str)
    lock = await db[COLL].find_one({**_practice_filter(practice_id), "slot_start": slot_start(date_str, t24)})
    if lock and lock.get("appointment_id") != exclude_appointment_id:
        return False
    dur = int(duration or 30)
    want = avail_mod._to_min(t24)
    q = {"status": {"$in": ACTIVE_APPT_STATUSES}, **_practice_filter(practice_id),
         "$or": [{"slot_date": date_str}, {"confirmed_date": date_str}, {"preferred_date": date_str},
                 {"preferred_options.date": date_str}]}
    if exclude_appointment_id:
        q["id"] = {"$ne": exclude_appointment_id}
    async for a in db.appointment_requests.find(q, {"_id": 0, "id": 1, "status": 1, "slot_date": 1, "slot_time": 1,
                                                     "confirmed_date": 1, "confirmed_slot_time": 1, "confirmed_time": 1,
                                                     "preferred_options": 1, "preferred_date": 1, "preferred_time": 1}):
        ds, t = _appt_when(a)
        if ds != date_str or not t:
            continue
        b = avail_mod._to_min(t)
        if b < want + dur and want < b + dur:
            return False
    return True


async def move(db, practice_id, appointment_id, new_date, new_time, state, actor=None, duration=None):
    """Atomic change of time: reserve the new slot FIRST, then release the old one.
    If reservation fails nothing changes."""
    old = await db[COLL].find({"appointment_id": appointment_id}, {"_id": 0, "id": 1, "slot_start": 1}).to_list(10)
    target = slot_start(new_date, new_time)
    same = [o for o in old if o.get("slot_start") == target]
    if same:
        await set_state(db, appointment_id, state)
        return await lock_for(db, appointment_id)
    if not await is_free(db, practice_id, new_date, new_time, exclude_appointment_id=appointment_id, duration=duration):
        raise SlotTaken()
    new_lock = await reserve(db, practice_id, new_date, new_time, appointment_id, state, actor)
    if old:
        await db[COLL].delete_many({"id": {"$in": [o["id"] for o in old]}})
    return new_lock
