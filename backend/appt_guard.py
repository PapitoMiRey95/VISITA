"""Patient-level appointment duplicate prevention.

Rules: max ONE active appointment per canonical patient, per practice, per local
(America/Toronto) calendar day. 2+ active appointments in a Mon-Sun week are allowed but
raise a staff review flag. `appointment_day_locks` (unique on practice/patient/day) is the
concurrency guard; `appointment_requests` remains the source of truth.
"""
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from db import audit, now_iso

CLINIC_TZ = ZoneInfo("America/Toronto")
ACTIVE = ["requested", "confirmed", "rescheduled"]
LOCKS, FLAGS = "appointment_day_locks", "appointment_review_flags"
WEEK_FLAG = "MULTIPLE_APPOINTMENTS_WEEK"
WEEK_FLAG_TITLE = "MULTIPLE APPOINTMENTS THIS WEEK — REVIEW"
SAME_DAY_CODE = "SAME_DAY_EXISTS"
SAME_DAY_MSG = ("You already have an appointment on this day. Only one appointment per day is allowed — "
                "please choose another day, or reschedule your existing appointment.")
STAFF_SAME_DAY_MSG = "This patient already has an active appointment on this day."


class SameDayExists(Exception):
    def __init__(self, existing):
        self.existing = existing


def today_local() -> str:
    return datetime.now(CLINIC_TZ).date().isoformat()


def week_start(ds: str) -> str:
    d = date.fromisoformat(ds[:10])
    return (d - timedelta(days=d.weekday())).isoformat()


async def ensure_indexes(db):
    import index_bootstrap as ib
    await ib.ensure_missing(db, LOCKS, [{"keys": [("practice_id", 1), ("patient_key", 1), ("date", 1)], "unique": True},
                                        {"keys": [("appointment_id", 1)]}])
    await ib.ensure_missing(db, FLAGS, [{"keys": [("practice_id", 1), ("patient_key", 1), ("week_start", 1), ("type", 1)], "unique": True}])


async def identity(db, patient_id=None, directory_id=None) -> dict:
    """Canonical refs for a patient: directory id + linked portal id (two-way). The
    directory id is the canonical key when known, else the portal id."""
    refs, pin, name = set(), None, None
    p = await db.patients.find_one({"id": patient_id}, {"_id": 0}) if patient_id else None
    d_id = directory_id or (p or {}).get("matched_directory_id")
    d = None
    if not p and patient_id:
        d = await db.patient_directory.find_one({"id": patient_id}, {"_id": 0})
    if d_id and not d:
        d = await db.patient_directory.find_one({"id": d_id}, {"_id": 0})
    if d:
        refs.add(d["id"])
        if d.get("linked_patient_id"):
            refs.add(d["linked_patient_id"])
            if not p:
                p = await db.patients.find_one({"id": d["linked_patient_id"]}, {"_id": 0})
        pin, name = d.get("visita_patient_id"), f"{d.get('last_name', '')}, {d.get('first_name', '')}"
    if p:
        refs.add(p["id"])
        if p.get("matched_directory_id"):
            refs.add(p["matched_directory_id"])
        pin = pin or p.get("visita_patient_id")
        name = name or f"{p.get('last_name', '')}, {p.get('first_name', '')}"
    if patient_id:
        refs.add(patient_id)
    key = (d or {}).get("id") or (p or {}).get("id") or patient_id
    return {"refs": sorted(refs), "key": key, "pin": pin, "name": (name or "").strip(", ")}


def _when(a):
    ds = a.get("slot_date") or a.get("confirmed_date")
    t = a.get("slot_time") or a.get("confirmed_slot_time")
    if not ds and a.get("status") == "requested":
        o = (a.get("preferred_options") or [{}])[0]
        ds, t = o.get("date") or a.get("preferred_date"), o.get("time")
    return ds, t


def _pfilter(practice_id):
    return {"practice_id": {"$in": [practice_id, None]}} if practice_id else {}


async def active_for(db, practice_id, refs, exclude_id=None):
    q = {"status": {"$in": ACTIVE}, **_pfilter(practice_id),
         "$or": [{"patient_id": {"$in": refs}}, {"directory_id": {"$in": refs}}]}
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    out = []
    async for a in db.appointment_requests.find(q, {"_id": 0}):
        ds, t = _when(a)
        if ds:
            out.append({"id": a["id"], "ref_number": a.get("ref_number"), "date": ds, "time": t,
                        "reason": a.get("reason"), "status": a.get("status"), "patient_id": a.get("patient_id"),
                        "directory_id": a.get("directory_id"), "patient_name": a.get("patient_name"),
                        "same_day_override": a.get("same_day_override")})
    return out


async def same_day(db, practice_id, refs, ds, exclude_id=None):
    return [a for a in await active_for(db, practice_id, refs, exclude_id) if a["date"] == ds]


async def check_same_day(db, practice_id, ident, ds, exclude_id=None, actor=None, source="portal"):
    """Record-based pre-check. Raises SameDayExists (after auditing the block)."""
    dupes = await same_day(db, practice_id, ident["refs"], ds, exclude_id)
    if dupes:
        await audit("appointment_same_day_blocked", "patient", ident["key"], actor,
                    meta={"date": ds, "source": source, "existing_appointment_ids": [d["id"] for d in dupes],
                          "excluded_appointment_id": exclude_id})
        raise SameDayExists(dupes)


async def acquire_day_lock(db, practice_id, patient_key, ds, appointment_id):
    """Atomic per-day lock: the final guard against concurrent same-day bookings."""
    try:
        await db[LOCKS].insert_one({"id": str(uuid.uuid4()), "practice_id": practice_id or None,
                                    "patient_key": patient_key, "date": ds, "appointment_id": appointment_id,
                                    "created_at": now_iso()})
    except DuplicateKeyError:
        raise SameDayExists([])


async def release_day_lock(db, appointment_id):
    await db[LOCKS].delete_many({"appointment_id": appointment_id})


async def move_day_lock(db, practice_id, patient_key, appointment_id, new_ds):
    """Same day -> no-op. New day -> acquire new first, then release old."""
    if await db[LOCKS].find_one({"appointment_id": appointment_id, "date": new_ds}):
        return
    await acquire_day_lock(db, practice_id, patient_key, new_ds, appointment_id)
    await db[LOCKS].delete_many({"appointment_id": appointment_id, "date": {"$ne": new_ds}})


def _detail(dupes, msg):
    return {"code": SAME_DAY_CODE, "message": msg,
            "existing": [{"id": d["id"], "ref_number": d.get("ref_number"), "date": d["date"], "time": d.get("time"),
                          "reason": d.get("reason")} for d in dupes]}


def portal_detail(dupes):
    return _detail(dupes, SAME_DAY_MSG)


def staff_detail(dupes):
    return _detail(dupes, STAFF_SAME_DAY_MSG + " Use the override with a documented reason if this is a clinical exception.")


async def refresh_week_flags(db, practice_id, ident, dates, actor=None):
    """Re-evaluate the weekly review flag for every week touched by `dates`."""
    appts = await active_for(db, practice_id, ident["refs"])
    for ws in {week_start(d) for d in dates if d}:
        we = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
        in_week = sorted([a for a in appts if ws <= a["date"] <= we], key=lambda a: (a["date"], a["time"] or ""))
        key = {"practice_id": practice_id or None, "patient_key": ident["key"], "week_start": ws, "type": WEEK_FLAG}
        flag = await db[FLAGS].find_one(key)
        items = [{k: a.get(k) for k in ("id", "ref_number", "date", "time", "reason", "status")} for a in in_week]
        if len(in_week) >= 2:
            if not flag or flag.get("status") != "OPEN":
                fid = (flag or {}).get("id") or str(uuid.uuid4())
                await db[FLAGS].update_one(key, {"$set": {
                    **key, "id": fid, "title": WEEK_FLAG_TITLE, "status": "OPEN", "patient_name": ident["name"],
                    "pin": ident["pin"], "week_end": we, "appointments": items, "count": len(items),
                    "updated_at": now_iso(), "resolved_at": None},
                    "$setOnInsert": {"created_at": now_iso()},
                    "$push": {"history": {"status": "OPEN", "at": now_iso(), "count": len(items),
                                          "note": "Reopened" if flag else "Created"}}}, upsert=True)
                await audit("appointment_week_review_created", "appointment_review_flag", fid, actor,
                            new_status="OPEN", meta={"week_start": ws, "count": len(items), "patient_key": ident["key"],
                                                     "appointment_ids": [i["id"] for i in items]})
            elif flag.get("appointments") != items:
                await db[FLAGS].update_one(key, {"$set": {"appointments": items, "count": len(items),
                                                          "patient_name": ident["name"], "pin": ident["pin"],
                                                          "updated_at": now_iso()}})
        elif flag and flag.get("status") == "OPEN":
            await db[FLAGS].update_one(key, {"$set": {"status": "RESOLVED", "resolved_at": now_iso(),
                                                      "remaining": items, "updated_at": now_iso()},
                                             "$push": {"history": {"status": "RESOLVED", "at": now_iso(),
                                                                   "count": len(items), "note": "Active count dropped below 2"}}})
            await audit("appointment_week_review_resolved", "appointment_review_flag", flag["id"], actor,
                        old_status="OPEN", new_status="RESOLVED",
                        meta={"week_start": ws, "remaining_count": len(items), "patient_key": ident["key"]})


async def refresh_for_appointment(db, appt, extra_dates=(), actor=None):
    """Convenience: refresh week flags for the appointment's patient/dates."""
    ident = await identity(db, patient_id=appt.get("patient_id"), directory_id=appt.get("directory_id"))
    ds, _ = _when(appt)
    await refresh_week_flags(db, appt.get("practice_id"), ident, [ds, *extra_dates], actor)


async def open_flags(db, practice_id):
    q = {"status": "OPEN", "type": WEEK_FLAG, **_pfilter(practice_id)}
    return await db[FLAGS].find(q, {"_id": 0}).sort("week_start", 1).to_list(500)


async def same_day_duplicates(db, practice_id):
    """Existing active same-day duplicates (today onward) grouped by canonical patient. Read-only."""
    q = {"status": {"$in": ACTIVE}, **_pfilter(practice_id)}
    today = today_local()
    groups, idents = {}, {}
    async for a in db.appointment_requests.find(q, {"_id": 0}):
        ds, t = _when(a)
        if not ds or ds < today:
            continue
        pid = a.get("patient_id") or a.get("directory_id")
        if not pid:
            continue
        if pid not in idents:
            idents[pid] = await identity(db, patient_id=a.get("patient_id"), directory_id=a.get("directory_id"))
        ident = idents[pid]
        groups.setdefault((ident["key"], ds), {"patient_key": ident["key"], "patient_name": ident["name"],
                                               "pin": ident["pin"], "date": ds, "appointments": []})
        groups[(ident["key"], ds)]["appointments"].append(
            {"id": a["id"], "ref_number": a.get("ref_number"), "time": t, "reason": a.get("reason"),
             "status": a.get("status"), "same_day_override": a.get("same_day_override")})
    out = [g for g in groups.values() if len(g["appointments"]) > 1]
    for g in out:
        g["appointments"].sort(key=lambda x: x["time"] or "")
        g["count"] = len(g["appointments"])
    return sorted(out, key=lambda g: (g["date"], g["patient_name"]))
