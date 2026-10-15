"""Appointment duplicate prevention (PREVIEW, synthetic data only). Scenarios A-I."""
import os
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
STAFF_PW = os.environ["TEST_STAFF_PASSWORD"]
TAG = f"dupguard-{uuid.uuid4().hex[:6]}"


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro_or_fn):
    """Run a coroutine, or a fn(db) that returns one, on a fresh loop + fresh client."""
    async def go():
        return await (coro_or_fn(_db()) if callable(coro_or_fn) else coro_or_fn)
    return asyncio.run(go())


def _login(identifier, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"identifier": identifier, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _seed(db):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import auth as authlib
    staff = await db.users.find_one({"email": "staff@visita.demo"})
    practice_id = staff["practice_id"]
    out = {"practice_id": practice_id, "patients": []}
    for i in range(2):
        pid, did = str(uuid.uuid4()), str(uuid.uuid4())
        email = f"{TAG}-{i}@synthetic.test"
        await db.patient_directory.insert_one({"id": did, "visita_patient_id": f"T{i}{TAG[-4:]}", "first_name": f"Synth{i}",
                                               "last_name": TAG.upper(), "date_of_birth": "1980-01-01", "status": "ACTIVE",
                                               "linked_patient_id": pid, "practice_id": practice_id, "is_synthetic": True})
        await db.patients.insert_one({"id": pid, "first_name": f"Synth{i}", "last_name": TAG.upper(), "email": email,
                                      "date_of_birth": "1980-01-01", "verification_status": "verified", "portal_status": "ACTIVE",
                                      "matched_directory_id": did, "identity_linked": True, "practice_id": practice_id,
                                      "visita_patient_id": f"T{i}{TAG[-4:]}", "is_synthetic": True})
        await db.users.insert_one({"email": email, "password_hash": authlib.hash_password("Synthetic2026!"), "name": f"Synth{i}",
                                   "role": "patient", "patient_id": pid, "active": True})
        out["patients"].append({"pid": pid, "did": did, "email": email})
    return out


async def _cleanup(seed, db):
    pids = [p["pid"] for p in seed["patients"]]
    dids = [p["did"] for p in seed["patients"]]
    appts = await db.appointment_requests.find({"patient_id": {"$in": pids}}, {"id": 1}).to_list(100)
    ids = [a["id"] for a in appts]
    await db.appointment_slots.delete_many({"appointment_id": {"$in": ids}})
    await db.appointment_day_locks.delete_many({"appointment_id": {"$in": ids}})
    await db.appointment_review_flags.delete_many({"patient_key": {"$in": dids + pids}})
    await db.appointment_requests.delete_many({"id": {"$in": ids}})
    await db.notifications.delete_many({"patient_id": {"$in": pids}})
    await db.users.delete_many({"email": {"$in": [p["email"] for p in seed["patients"]]}})
    await db.patients.delete_many({"id": {"$in": pids}})
    await db.patient_directory.delete_many({"id": {"$in": dids}})


@pytest.fixture(scope="module")
def ctx():
    seed = _run(_seed)
    staff = _login("staff@visita.demo", STAFF_PW)
    p0 = _login(seed["patients"][0]["email"], "Synthetic2026!")
    p1 = _login(seed["patients"][1]["email"], "Synthetic2026!")
    slots = requests.get(f"{BASE}/api/availability/slots", params={"days": 28}, headers=staff, timeout=30).json()["slots"]
    by_date = {}
    for s in slots:
        by_date.setdefault(s["date"], []).append(s)
    # First Monday with >=3 free slots that is at least 2 days out, and the following Tuesday with >=1.
    today = date.today()
    mon = None
    for ds in sorted(by_date):
        d = date.fromisoformat(ds)
        if d.weekday() == 0 and (d - today).days >= 2 and len(by_date[ds]) >= 3:
            tue = (d + timedelta(days=1)).isoformat()
            if by_date.get(tue):
                mon = ds
                break
    assert mon, "no suitable Monday/Tuesday slots"
    yield {**seed, "staff": staff, "p0": p0, "p1": p1, "mon": mon, "tue": (date.fromisoformat(mon) + timedelta(days=1)).isoformat(),
           "mon_slots": by_date[mon], "tue_slots": by_date[(date.fromisoformat(mon) + timedelta(days=1)).isoformat()]}
    _run(lambda db: _cleanup(seed, db))


def _book(hdrs, slot, reason="Synthetic test"):
    return requests.post(f"{BASE}/api/portal/appointments", headers=hdrs, timeout=30, json={
        "reason": reason, "appointment_type": "IN_CLINIC", "acknowledge_existing": True,
        "options": [{"date": slot["date"], "time": slot["time"], "label": slot["label"], "display": slot.get("display")}]})


def _reviews(hdrs):
    return requests.get(f"{BASE}/api/internal/appointments/reviews", headers=hdrs, timeout=30).json()


def _flag_for(ctx, key_pid):
    return [f for f in _reviews(ctx["staff"])["week_flags"] if f["patient_key"] == key_pid]


def test_A_B_C_same_day_block_and_next_day_allowed(ctx):
    r = _book(ctx["p0"], ctx["mon_slots"][0], "Monday first")
    assert r.status_code == 200, r.text
    ctx["monday_appt"] = r.json()
    r2 = _book(ctx["p0"], ctx["mon_slots"][1], "Monday second")
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "SAME_DAY_EXISTS", r2.text
    r3 = _book(ctx["p0"], ctx["tue_slots"][0], "Tuesday")
    assert r3.status_code == 200, r3.text
    ctx["tuesday_appt"] = r3.json()


def test_D_weekly_review_flag(ctx):
    flags = _flag_for(ctx, ctx["patients"][0]["did"])
    assert len(flags) == 1 and flags[0]["count"] == 2 and flags[0]["status"] == "OPEN"
    assert flags[0]["pin"] and flags[0]["patient_name"]
    assert {a["reason"] for a in flags[0]["appointments"]} == {"Monday first", "Tuesday"}


def test_E_cancel_resolves_flag(ctx):
    a = ctx["tuesday_appt"]["id"]
    r = requests.patch(f"{BASE}/api/internal/appointments/{a}", headers=ctx["staff"], timeout=30,
                       json={"action": "cancel", "cancel_reason": "synthetic cleanup"})
    assert r.status_code == 200, r.text
    assert _flag_for(ctx, ctx["patients"][0]["did"]) == []
    flag = _run(lambda db: db.appointment_review_flags.find_one({"patient_key": ctx["patients"][0]["did"]}, {"_id": 0}))
    assert flag["status"] == "RESOLVED" and len(flag["history"]) == 2


def test_F_reschedule_same_day_allowed_other_busy_day_blocked(ctx):
    a = ctx["monday_appt"]["id"]
    s = ctx["mon_slots"][2]
    r = requests.post(f"{BASE}/api/portal/appointments/{a}/reschedule", headers=ctx["p0"], timeout=30,
                      json={"date": s["date"], "time": s["time"], "label": s["label"]})
    assert r.status_code == 200, r.text
    # Book Tuesday again, then try to move Monday onto Tuesday -> blocked.
    t = _book(ctx["p0"], ctx["tue_slots"][0], "Tuesday again")
    assert t.status_code == 200, t.text
    ctx["tuesday2"] = t.json()
    ts = ctx["tue_slots"][1] if len(ctx["tue_slots"]) > 1 else ctx["tue_slots"][0]
    r2 = requests.post(f"{BASE}/api/portal/appointments/{a}/reschedule", headers=ctx["p0"], timeout=30,
                       json={"date": ts["date"], "time": ts["time"], "label": ts["label"]})
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "SAME_DAY_EXISTS", r2.text
    # Monday appt still on Monday with its lock intact.
    lock = _run(lambda db: db.appointment_day_locks.find_one({"appointment_id": a}, {"_id": 0}))
    assert lock and lock["date"] == ctx["mon"]


def test_G_concurrent_only_one_succeeds(ctx):
    p1 = ctx["p1"]
    free = [s for s in ctx["mon_slots"] if s["time"] not in {ctx["mon_slots"][0]["time"], ctx["mon_slots"][2]["time"]}]
    assert len(free) >= 2
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda s: _book(p1, s, "Concurrent"), [free[0], free[1]] * 3))
    codes = [r.status_code for r in results]
    assert codes.count(200) == 1, codes
    assert all(c in (200, 409) for c in codes), codes
    locks = _run(lambda db: db.appointment_day_locks.count_documents({"patient_key": ctx["patients"][1]["did"], "date": ctx["mon"]}))
    assert locks == 1


def test_H_staff_override_requires_reason(ctx):
    free = [s for s in ctx["mon_slots"] if s["time"] not in {ctx["mon_slots"][0]["time"], ctx["mon_slots"][2]["time"]}]
    body = {"directory_id": ctx["patients"][0]["did"], "date": ctx["mon"], "time": free[-1]["time"], "label": free[-1]["label"], "reason": "Override test"}
    r = requests.post(f"{BASE}/api/internal/calendar/book", headers=ctx["staff"], json=body, timeout=30)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SAME_DAY_EXISTS"
    r = requests.post(f"{BASE}/api/internal/calendar/book", headers=ctx["staff"], json={**body, "override_same_day": True}, timeout=30)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "OVERRIDE_REASON_REQUIRED"
    r = requests.post(f"{BASE}/api/internal/calendar/book", headers=ctx["staff"],
                      json={**body, "override_same_day": True, "override_reason": "Procedure follow-up same day"}, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["same_day_override"]["reason"] == "Procedure follow-up same day"
    aud = _run(lambda db: db.audit_logs.find_one({"action": "appointment_same_day_override", "entity_id": r.json()["id"]}))
    assert aud
    dupes = [g for g in _reviews(ctx["staff"])["same_day_duplicates"] if g["patient_key"] == ctx["patients"][0]["did"]]
    assert dupes and dupes[0]["count"] == 2
    # Portal can never override.
    r = _book(ctx["p0"], free[0], "Portal override attempt")
    assert r.status_code == 409


def test_I_other_patient_books_normally(ctx):
    r = _book(ctx["p1"], ctx["tue_slots"][-1], "Other patient")
    assert r.status_code == 200, r.text


def test_audit_events_present(ctx):
    for action in ("appointment_same_day_blocked", "appointment_week_review_created", "appointment_week_review_resolved",
                   "appointment_same_day_override"):
        assert _run(lambda db: db.audit_logs.count_documents({"action": action})) >= 1, action
