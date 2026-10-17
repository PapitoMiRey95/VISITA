import asyncio, json, os, sys, uuid
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from auth import hash_password  # noqa

API = [l.split("=", 1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL")][0] + "/api"
ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
STAFF = ("staff@visita.demo", "Staff2026!")
EMAIL = "zz.reset.synthetic@example.test"
PW = "Synthetic-2026!x"
now = datetime.now(timezone.utc).isoformat()


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    # cleanup from earlier runs
    old = await db.patients.find_one({"last_name": "ZZRESETTEST"})
    if old:
        for c in ("appointments", "prescriptions", "patients", "portal_account_archive"):
            await db[c].delete_many({"patient_id": old["id"]} if c != "patients" else {"id": old["id"]})
        await db.users.delete_many({"$or": [{"patient_id": old["id"]}, {"detached_patient_id": old["id"]}, {"email": EMAIL}]})
        await db.patient_directory.delete_many({"last_name": "ZZRESETTEST"})
    pid, did = str(uuid.uuid4()), str(uuid.uuid4())
    practice = await db.practices.find_one({}, {"id": 1, "slug": 1})
    await db.patient_directory.insert_one({"id": did, "visita_patient_id": "VP-ZZ-0001", "first_name": "Zoe", "last_name": "ZZRESETTEST",
        "date_of_birth": "1990-03-03", "health_card_number": "9999000011", "patient_status": "ACTIVE", "linked_patient_id": pid,
        "norm_first": "ZOE", "norm_last": "ZZRESETTEST", "norm_dob": "1990-03-03", "norm_hcn": "9999000011", "import_source": "synthetic", "imported_at": now, "updated_at": now})
    await db.patients.insert_one({"id": pid, "visita_patient_id": "VP-ZZ-0001", "first_name": "Zoe", "last_name": "ZZRESETTEST", "date_of_birth": "1990-03-03",
        "health_card_number": "9999000011", "health_card_version": "AB", "sex": "F", "phone": "4165550000", "email": EMAIL, "province": "ON", "country": "CA",
        "patient_type": "ohip", "verification_status": "verified", "portal_status": "ACTIVE", "matched_directory_id": did, "canonical_directory_id": did,
        "practice_id": practice["id"], "practice_slug": practice.get("slug"), "preferred_language": "en", "active_status": True, "is_demo": True, "created_at": now, "updated_at": now})
    ures = await db.users.insert_one({"email": EMAIL, "password_hash": hash_password(PW), "name": "Zoe ZZRESETTEST", "role": "patient", "patient_id": pid, "active": True, "email_verified": True, "created_at": now})
    await db.appointments.insert_one({"id": str(uuid.uuid4()), "patient_id": pid, "practice_id": practice["id"], "status": "SCHEDULED", "created_at": now, "synthetic": True})
    await db.prescriptions.insert_one({"id": str(uuid.uuid4()), "patient_id": pid, "status": "SUBMITTED", "created_at": now, "synthetic": True})

    async def snapshot():
        p = await db.patients.find_one({"id": pid}, {"_id": 0})
        d = await db.patient_directory.find_one({"id": did}, {"_id": 0, "identity_history": 0})
        return {"patient": p, "directory": d,
                "appointments": await db.appointments.count_documents({"patient_id": pid}),
                "prescriptions": await db.prescriptions.count_documents({"patient_id": pid}),
                "users_linked": await db.users.count_documents({"patient_id": pid})}

    async with httpx.AsyncClient(timeout=30) as c:
        tok = lambda t: {"Authorization": f"Bearer {t}"}
        adm = (await c.post(f"{API}/auth/login", json={"identifier": ADMIN[0], "password": ADMIN[1]})).json()["token"]
        stf = (await c.post(f"{API}/auth/login", json={"identifier": STAFF[0], "password": STAFF[1]})).json()["token"]
        pat = (await c.post(f"{API}/auth/login", json={"identifier": EMAIL, "password": PW})).json()["token"]
        print("patient /auth/me before:", (await c.get(f"{API}/auth/me", headers=tok(pat))).status_code)
        before = await snapshot()
        print("BEFORE portal-account:", (await c.get(f"{API}/internal/patients/{pid}/portal-account", headers=tok(adm))).json())

        # disable / enable still work
        print("disable:", (await c.post(f"{API}/internal/patients/{pid}/portal-account/disable", headers=tok(adm))).json())
        print("enable:", (await c.post(f"{API}/internal/patients/{pid}/portal-account/enable", headers=tok(adm))).json())

        body = {"reason": "Synthetic test: wrong email", "confirm_text": "RESET PORTAL"}
        r = await c.post(f"{API}/internal/patients/{pid}/portal-account/reset", headers=tok(stf), json=body)
        print("staff reset ->", r.status_code, r.json())
        r = await c.post(f"{API}/internal/patients/{pid}/portal-account/reset", headers=tok(adm), json={"reason": "Synthetic test", "confirm_text": "reset"})
        print("bad confirm ->", r.status_code, r.json())
        r = await c.post(f"{API}/internal/patients/{pid}/portal-account/reset", headers=tok(adm), json={"reason": "x", "confirm_text": "RESET PORTAL"})
        print("short reason ->", r.status_code, r.json())
        # conflict: temporarily unlink directory -> review required
        await db.patient_directory.update_one({"id": did}, {"$set": {"linked_patient_id": None}})
        r = await c.post(f"{API}/internal/patients/{pid}/portal-account/reset", headers=tok(adm), json=body)
        print("conflict ->", r.status_code, r.json())
        await db.patient_directory.update_one({"id": did}, {"$set": {"linked_patient_id": pid}})
        print("users_linked still:", await db.users.count_documents({"patient_id": pid}))

        r = await c.post(f"{API}/internal/patients/{pid}/portal-account/reset", headers=tok(adm), json=body)
        print("RESET ->", r.status_code, r.json())
        after = await snapshot()
        print("AFTER portal-account:", json.dumps((await c.get(f"{API}/internal/patients/{pid}/portal-account", headers=tok(adm))).json(), default=str))
        print("old token /auth/me after:", (await c.get(f"{API}/auth/me", headers=tok(pat))).status_code)
        print("old login after:", (await c.post(f"{API}/auth/login", json={"identifier": EMAIL, "password": PW})).status_code)

        changed = {k: (before["patient"].get(k), after["patient"].get(k)) for k in set(before["patient"]) | set(after["patient"]) if before["patient"].get(k) != after["patient"].get(k)}
        print("PATIENT fields changed:", changed)
        print("DIRECTORY changed:", before["directory"] != after["directory"], "| PIN", before["patient"]["visita_patient_id"], "->", after["patient"]["visita_patient_id"])
        print("appointments", before["appointments"], "->", after["appointments"], "| rx", before["prescriptions"], "->", after["prescriptions"], "| users_linked", before["users_linked"], "->", after["users_linked"])
        u = await db.users.find_one({"_id": ures.inserted_id}, {"_id": 0})
        print("USER doc now:", {k: u.get(k) for k in ("email", "password_hash", "active", "patient_id", "detached_patient_id", "portal_detached", "detach_reason", "email_verified")})
        print("ARCHIVE:", json.dumps(await db.portal_account_archive.find_one({"patient_id": pid}, {"_id": 0}), default=str))
        print("AUDIT:", json.dumps(await db.audit_logs.find_one({"action": "staff_reset_portal_account", "meta.patient_id": pid}, {"_id": 0}), default=str))

        # re-register same person, new email -> must CLAIM same record
        reg = {"first_name": "Zoe", "last_name": "ZZRESETTEST", "date_of_birth": "1990-03-03", "email": "zz.reset.new@example.test", "password": "Fresh-2026!pw",
               "phone": "4165550000", "province": "ON", "country": "CA", "patient_type": "ohip", "health_card_number": "9999000011", "health_card_version": "AB",
               "health_card_issue_date": "2020-01-01", "health_card_expiry_date": "2030-01-01", "sex": "F", "address": "1 Test St", "city": "Toronto", "postal_code": "M1M1M1", "preferred_language": "en"}
        r = await c.post(f"{API}/auth/register", json=reg)
        print("RE-REGISTER ->", r.status_code, {k: v for k, v in r.json().items() if k != "token"} if r.status_code == 200 else r.json())
        nu = r.json().get("user", {}) if r.status_code == 200 else {}
        print("new user patient_id == same pid:", nu.get("patient_id") == pid, "| patients docs w/ this name:", await db.patients.count_documents({"last_name": "ZZRESETTEST"}),
              "| PIN now:", (await db.patients.find_one({"id": pid}))["visita_patient_id"], "| appts:", await db.appointments.count_documents({"patient_id": pid}))
        print("AFTER re-register portal-account:", json.dumps((await c.get(f"{API}/internal/patients/{pid}/portal-account", headers=tok(adm))).json(), default=str)[:300])
        # re-register with the RELEASED original email should also be possible (email released) -> expect 409 now because account exists again
        print("PID for screenshots:", pid)

asyncio.run(main())
