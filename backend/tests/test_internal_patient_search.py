"""Tests for the merged internal patient search + calendar booking fix.

Covers:
  - /api/internal/patient-lookup finds VERIFIED portal-only patients (portal-first)
  - search by email/dob/phone/name/hcn/pin
  - dedup: portal patient linked to a directory record appears once (source='directory')
  - portal-only patient snapshot: source='portal', patient_status='PORTAL_PATIENT', visita_patient_id null
  - /api/internal/directory still returns DIRECTORY-ONLY (regression)
  - /api/internal/calendar/book with portal patient_id -> appt visible in that patient's portal
  - Validation: unverified portal patient 400; missing both ids 400
  - Directory booking still works
"""
import os
import uuid
import asyncio
import pytest
import requests
from datetime import datetime, timedelta, date, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = BASE_URL + "/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

STAFF = ("staff@visita.demo", "Staff2026!")
ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
MARIA_EMAIL = "maria.lopez@demo.com"
MARIA_PW = "Patient2026!"
MARIA_ID = "06f6ee08-58f7-4286-82f5-7c845de99ce1"

# --- helpers -----------------------------------------------------------------

def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"identifier": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text}"
    return r.json()["token"]

def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}

@pytest.fixture(scope="module")
def staff_token():
    return _login(*STAFF)

@pytest.fixture(scope="module")
def maria_token():
    return _login(MARIA_EMAIL, MARIA_PW)

# Track resources to clean up
_created = {"appt_ids": [], "temp_patient_ids": [], "temp_user_ids": []}

@pytest.fixture(scope="module", autouse=True)
def cleanup_after():
    yield
    async def _c():
        cli = AsyncIOMotorClient(MONGO_URL); db = cli[DB_NAME]
        for aid in _created["appt_ids"]:
            await db.appointment_requests.delete_one({"id": aid})
            await db.appointment_reminders.delete_many({"appointment_id": aid})
        # Delete notifications/emails prefixed TEST_ or tied to appt reasons TEST_
        await db.notifications.delete_many({"body": {"$regex": "TEST_", "$options": "i"}})
        await db.outbound_notifications.delete_many({"subject": {"$regex": "Appointment Confirmed"},
                                                    "body": {"$regex": "TEST_"}})
        for pid in _created["temp_patient_ids"]:
            await db.patients.delete_one({"id": pid})
        for uid in _created["temp_user_ids"]:
            from bson import ObjectId
            try:
                await db.users.delete_one({"_id": ObjectId(uid)})
            except Exception:
                pass
        cli.close()
    asyncio.run(_c())

# --- basic auth / lookup --------------------------------------------------

def test_staff_login(staff_token):
    assert staff_token

def test_lookup_by_email_finds_maria(staff_token):
    r = requests.get(f"{API}/internal/patient-lookup", params={"q": MARIA_EMAIL}, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list) and len(data) >= 1
    maria = [x for x in data if x.get("id") == MARIA_ID]
    assert maria, f"Maria not in results: {data}"
    m = maria[0]
    assert m["source"] == "portal"
    assert m["patient_status"] == "PORTAL_PATIENT"
    assert m["visita_patient_id"] in (None, "")
    assert m["patient_id"] == MARIA_ID
    assert m["email"] == MARIA_EMAIL

def test_lookup_by_dob_finds_maria(staff_token):
    r = requests.get(f"{API}/internal/patient-lookup", params={"q": "1972-03-14"}, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert MARIA_ID in ids

def test_lookup_by_phone_finds_maria(staff_token):
    r = requests.get(f"{API}/internal/patient-lookup", params={"q": "416 555 3011"}, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert MARIA_ID in ids, f"Maria not in phone search: {r.json()}"

def test_lookup_by_lastname_surfaces_portal_first(staff_token):
    r = requests.get(f"{API}/internal/patient-lookup", params={"q": "Lopez"}, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 200
    data = r.json()
    portal_positions = [i for i, x in enumerate(data) if x["source"] == "portal"]
    dir_positions = [i for i, x in enumerate(data) if x["source"] == "directory"]
    # Maria must appear
    assert any(x.get("id") == MARIA_ID for x in data)
    # Portal-first invariant: min portal index <= min directory index (if both present)
    if portal_positions and dir_positions:
        assert min(portal_positions) < min(dir_positions), f"Portal not first: {data}"

# --- directory regression ---------------------------------------------------

def test_internal_directory_excludes_portal_only_patient(staff_token):
    r = requests.get(f"{API}/internal/directory", params={"q": "Lopez"}, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 200
    ids = [x.get("id") for x in r.json()]
    assert MARIA_ID not in ids, "Portal-only patient must NOT appear in /internal/directory"

# --- dedup case -------------------------------------------------------------

def test_dedup_portal_linked_to_directory_appears_once(staff_token):
    """Create a temp verified portal patient with matched_directory_id set to
    an existing directory record; ensure the merged search returns a single
    result flagged source='directory'."""
    async def _setup():
        cli = AsyncIOMotorClient(MONGO_URL); db = cli[DB_NAME]
        d = await db.patient_directory.find_one({})
        assert d, "No directory records"
        # Use uncommon token so search is unambiguous
        token = f"Zzdedup{uuid.uuid4().hex[:6]}"
        pid = str(uuid.uuid4())
        doc = {
            "id": pid,
            "first_name": token,
            "last_name": "DEDUPTEST",
            "email": f"{token.lower()}@demo.com",
            "phone": "4165550000",
            "date_of_birth": "1980-01-01",
            "health_card_number": None,
            "verification_status": "verified",
            "active_status": True,
            "patient_type": "portal",
            "matched_directory_id": d["id"],
            "visita_patient_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.patients.insert_one(doc)
        cli.close()
        return pid, token, d["id"]
    pid, token, dir_id = asyncio.run(_setup())
    _created["temp_patient_ids"].append(pid)

    r = requests.get(f"{API}/internal/patient-lookup", params={"q": token}, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 200
    data = r.json()
    # The portal record matches on first_name; directory has no matching first_name for this uuid.
    # So the merged search should find the portal record and replace it with the directory snapshot.
    matched = [x for x in data if x.get("directory_id") == dir_id or x.get("id") == pid]
    assert len(matched) == 1, f"Expected 1 deduped entry, got {len(matched)}: {matched}"
    assert matched[0]["source"] == "directory"
    assert matched[0]["id"] == dir_id

# --- calendar booking -------------------------------------------------------

def _pick_open_slot(staff_token):
    today = date.today().isoformat()
    r = requests.get(f"{API}/internal/calendar", params={"start": today, "days": 21}, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 200, r.text
    for d in r.json()["days"]:
        if d.get("closed") or d.get("day_blocked"):
            continue
        for s in d.get("open_slots", []):
            return d["date"], s["time"], s.get("label") or s["time"]
    return None, None, None

def test_book_portal_patient_visible_in_their_portal(staff_token, maria_token):
    dte, tme, lbl = _pick_open_slot(staff_token)
    assert dte and tme, "No open slot found"
    reason = f"TEST_portal_booking_{uuid.uuid4().hex[:6]}"
    body = {"patient_id": MARIA_ID, "date": dte, "time": tme, "label": lbl, "reason": reason,
            "appointment_type": "Office visit"}
    r = requests.post(f"{API}/internal/calendar/book", json=body, headers=_hdr(staff_token), timeout=20)
    assert r.status_code == 200, f"book -> {r.status_code} {r.text}"
    appt = r.json()
    _created["appt_ids"].append(appt["id"])
    assert appt["patient_id"] == MARIA_ID
    assert appt["status"] == "confirmed"

    # Verify in Maria's portal
    ov = requests.get(f"{API}/portal/overview", headers=_hdr(maria_token), timeout=15)
    assert ov.status_code == 200, ov.text
    appt_ids = [a["id"] for a in ov.json().get("appointments", [])]
    assert appt["id"] in appt_ids, "Booked appointment not in Maria's portal overview"

def test_book_unverified_portal_patient_rejected(staff_token):
    """Create a temp UNverified portal patient and try to book."""
    async def _mk():
        cli = AsyncIOMotorClient(MONGO_URL); db = cli[DB_NAME]
        pid = str(uuid.uuid4())
        await db.patients.insert_one({
            "id": pid, "first_name": "TESTUnv", "last_name": "Patient",
            "email": f"unv{uuid.uuid4().hex[:6]}@demo.com", "phone": "4165550001",
            "date_of_birth": "1990-01-01", "verification_status": "pending",
            "active_status": True, "patient_type": "portal",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        cli.close()
        return pid
    pid = asyncio.run(_mk())
    _created["temp_patient_ids"].append(pid)
    dte, tme, lbl = _pick_open_slot(staff_token)
    r = requests.post(f"{API}/internal/calendar/book", json={
        "patient_id": pid, "date": dte, "time": tme, "label": lbl, "reason": "TEST_unverified"
    }, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"

def test_book_missing_ids_400(staff_token):
    dte, tme, lbl = _pick_open_slot(staff_token)
    r = requests.post(f"{API}/internal/calendar/book", json={
        "date": dte, "time": tme, "label": lbl, "reason": "TEST_missing_ids"
    }, headers=_hdr(staff_token), timeout=15)
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"

def test_book_directory_patient_still_works(staff_token):
    """Regression: directory_id booking still works."""
    async def _get_dir():
        cli = AsyncIOMotorClient(MONGO_URL); db = cli[DB_NAME]
        d = await db.patient_directory.find_one({})
        cli.close()
        return d
    d = asyncio.run(_get_dir())
    assert d
    dte, tme, lbl = _pick_open_slot(staff_token)
    r = requests.post(f"{API}/internal/calendar/book", json={
        "directory_id": d["id"], "date": dte, "time": tme, "label": lbl, "reason": "TEST_directory_book"
    }, headers=_hdr(staff_token), timeout=20)
    assert r.status_code == 200, f"directory book failed: {r.status_code} {r.text}"
    appt = r.json()
    _created["appt_ids"].append(appt["id"])
    expected_pid = d.get("linked_patient_id") or d["id"]
    assert appt["patient_id"] == expected_pid
