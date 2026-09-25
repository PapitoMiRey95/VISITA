"""STAGED cleanup — permanently remove FORMER_CLOSED legacy patients from VIsita Web.

AUTHORITATIVE RULE (Dr. Aguayo, final):
  KEEP   patient_directory.patient_status == "ACTIVE"
  DELETE patient_directory.patient_status == "FORMER_CLOSED"
  `source_close_marker` is NOT authoritative.

PROTECTED / KEEP OVERRIDE (explicit, wins over ANY legacy status):
  PIN 3040 — IZAO, Aracely (returned patient, Dr. Aguayo re-accepted; re-registered).
  Resolved to stable IDs at runtime. Even if a legacy field still says
  FORMER_CLOSED / CLOSE / CLOSED / CLOSEZ, she and everything linked to her
  current identity are EXCLUDED from deletion. If duplicate legacy records for
  her are detected, they are reported and never deleted.

SAFETY CONTRACT (do not weaken):
- Targets ONLY patient_directory rows whose patient_status == "FORMER_CLOSED"
  AND not in the PROTECTED allowlist. ACTIVE rows are never touched.
- Cascades ONLY to records owned EXCLUSIVELY by a deleted (non-protected) patient.
- Anything protected / shared / ambiguous / tied to an ACTIVE patient is SKIPPED
  and reported, never auto-deleted.
- DRY-RUN by default. Executes only when env CONFIRM_CLEANUP == the token below.
- Never touches users/staff/physicians/pharmacies/partners/organizations/providers
  beyond a deleted patient's own exclusive account. Legacy Access DB is never touched.

Run (deployer, AFTER explicit human GO + confirmed Production backup):
    CONFIRM_CLEANUP=GO-CLEANUP-FORMER-CLOSED-APPROVED python -m ops.cleanup_former_closed
Dry-run (default, safe preview — no writes):
    python -m ops.cleanup_former_closed
"""
import os
import asyncio
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from motor.motor_asyncio import AsyncIOMotorClient

CONFIRM_TOKEN = "GO-CLEANUP-FORMER-CLOSED-APPROVED"
TARGET_STATUS = "FORMER_CLOSED"
KEEP_STATUS = "ACTIVE"

# Explicit protected patients (PIN). Protection wins over any legacy status.
PROTECTED_PINS = {"3040"}  # IZAO, Aracely — returned & re-registered
# Name hints used ONLY to surface possible duplicate legacy records for review.
# Never used to auto-delete; only to protect/report her matches.
PROTECTED_NAME_HINTS = [("IZAO", "ARACELY")]

PATIENT_ID_COLLECTIONS = [
    "prescription_requests", "imaging_requests", "bloodwork_requests",
    "referrals", "patient_referrals", "patient_messages", "notifications",
    "visita_pins",
]


async def resolve_protected(db):
    prot_dir = await db.patient_directory.find(
        {"visita_patient_id": {"$in": list(PROTECTED_PINS)}},
        {"_id": 0, "id": 1, "linked_patient_id": 1, "first_name": 1, "last_name": 1,
         "patient_status": 1, "visita_patient_id": 1, "date_of_birth": 1}).to_list(1000)
    prot_pt = await db.patients.find(
        {"visita_patient_id": {"$in": list(PROTECTED_PINS)}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "visita_patient_id": 1,
         "active_status": 1, "date_of_birth": 1}).to_list(1000)
    dir_ids = {d["id"] for d in prot_dir}
    pt_ids = {p["id"] for p in prot_pt} | {d.get("linked_patient_id") for d in prot_dir if d.get("linked_patient_id")}
    pt_ids.discard(None)
    user_ids = set()
    if pt_ids:
        async for u in db.users.find({"patient_id": {"$in": list(pt_ids)}}, {"_id": 1, "email": 1}):
            user_ids.add(u["_id"])
    # Duplicate scan by exact-last / first-hint (report-only).
    dup = []
    for (ln, fn) in PROTECTED_NAME_HINTS:
        for coll in ("patient_directory", "patients"):
            async for r in db[coll].find(
                {"last_name": {"$regex": f"^{ln}$", "$options": "i"},
                 "first_name": {"$regex": fn, "$options": "i"}},
                {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "visita_patient_id": 1}):
                dup.append((coll, r))
    duplicates = dup if (len(prot_dir) > 1 or len(prot_pt) > 1 or len(dup) > 1) else []
    return {"dir": prot_dir, "pt": prot_pt, "dir_ids": dir_ids, "pt_ids": pt_ids,
            "user_ids": user_ids, "duplicates": duplicates}


async def build_plan(db, prot):
    p_dir_ids, p_pt_ids = prot["dir_ids"], prot["pt_ids"]

    closed = await db.patient_directory.find(
        {"patient_status": TARGET_STATUS},
        {"_id": 0, "id": 1, "visita_patient_id": 1, "linked_patient_id": 1}).to_list(100000)
    # Protection wins: drop protected rows / protected PINs from the target set.
    closed = [d for d in closed if d["id"] not in p_dir_ids
              and d.get("visita_patient_id") not in PROTECTED_PINS]
    dir_ids = {d["id"] for d in closed}
    vpids = {d.get("visita_patient_id") for d in closed if d.get("visita_patient_id")}
    linked_pids = {d.get("linked_patient_id") for d in closed if d.get("linked_patient_id")} - p_pt_ids

    active_pt_ids = {p["id"] for p in await db.patients.find(
        {"active_status": True}, {"_id": 0, "id": 1}).to_list(100000)}
    active_dir_ids = {d["id"] for d in await db.patient_directory.find(
        {"patient_status": KEEP_STATUS}, {"_id": 0, "id": 1}).to_list(100000)}

    ambiguous = []
    delete_dir_ids = set(dir_ids)

    portal_delete_ids = set()
    for pid in linked_pids:
        p = await db.patients.find_one({"id": pid}, {"_id": 0, "id": 1, "active_status": 1})
        if not p:
            continue
        if p.get("active_status") is True:
            ambiguous.append(("portal_patient_ACTIVE", pid,
                              "linked FORMER_CLOSED dir row points to an ACTIVE portal patient"))
            for d in closed:
                if d.get("linked_patient_id") == pid:
                    delete_dir_ids.discard(d["id"])
        else:
            portal_delete_ids.add(pid)
    portal_delete_ids -= p_pt_ids

    user_delete_ids = []
    for pid in portal_delete_ids:
        async for u in db.users.find({"patient_id": pid}, {"_id": 1}):
            if u["_id"] not in prot["user_ids"]:
                user_delete_ids.append(u["_id"])

    ar_delete_ids = []
    async for a in db.appointment_requests.find({}, {"_id": 0}):
        refs_protected = (a.get("directory_id") in p_dir_ids or a.get("linked_patient_id") in p_dir_ids
                          or a.get("patient_id") in p_pt_ids or a.get("patient_id") in p_dir_ids
                          or a.get("visita_patient_id") in PROTECTED_PINS)
        if refs_protected:
            continue
        refs_closed = (a.get("directory_id") in dir_ids or a.get("linked_patient_id") in dir_ids
                       or a.get("patient_id") in dir_ids or a.get("patient_id") in portal_delete_ids
                       or (a.get("visita_patient_id") and a.get("visita_patient_id") in vpids))
        if not refs_closed:
            continue
        tied_active = (a.get("patient_id") in active_pt_ids or a.get("linked_patient_id") in active_dir_ids
                       or a.get("directory_id") in active_dir_ids)
        if tied_active:
            ambiguous.append(("appointment_shared", a.get("id"),
                              f"{a.get('ref_number')} references both closed and ACTIVE patient"))
        else:
            ar_delete_ids.append(a["id"])

    return {
        "closed_count": len(dir_ids),
        "delete_dir_ids": delete_dir_ids,
        "portal_delete_ids": portal_delete_ids,
        "user_delete_ids": user_delete_ids,
        "ar_delete_ids": ar_delete_ids,
        "ambiguous": ambiguous,
    }


def _fmt_name(last, first):
    last = (last or "").strip().upper()
    first = " ".join(w[:1].upper() + w[1:].lower() for w in (first or "").strip().split())
    return f"{last}, {first}" if (last and first) else (last or first or "—")


async def main():
    confirmed = os.environ.get("CONFIRM_CLEANUP", "").strip() == CONFIRM_TOKEN
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    try:
        total_before = await db.patient_directory.estimated_document_count()
        active_before = await db.patient_directory.count_documents({"patient_status": KEEP_STATUS})
        prot = await resolve_protected(db)
        plan = await build_plan(db, prot)

        wf_counts = {}
        if plan["portal_delete_ids"]:
            ids = list(plan["portal_delete_ids"])
            for coll in PATIENT_ID_COLLECTIONS:
                wf_counts[coll] = await db[coll].count_documents({"patient_id": {"$in": ids}})
        reminder_count = 0
        if plan["ar_delete_ids"]:
            reminder_count = await db.appointment_reminders.count_documents(
                {"appointment_id": {"$in": plan["ar_delete_ids"]}})

        mode = "EXECUTE" if confirmed else "DRY-RUN"
        print(f"[{mode}] DB={os.environ['DB_NAME']}")

        print("\n-- PROTECTED PATIENT (explicit KEEP override) --")
        found = prot["dir"] or prot["pt"]
        if not found:
            print(f"  PIN {sorted(PROTECTED_PINS)}: NOT FOUND in this DB (resolve in Production).")
        for d in prot["dir"]:
            print(f"  {_fmt_name(d.get('last_name'), d.get('first_name'))}")
            print(f"    PIN: {d.get('visita_patient_id')} · directory id: {d.get('id')} · legacy status: {d.get('patient_status')}")
        for p in prot["pt"]:
            print(f"  {_fmt_name(p.get('last_name'), p.get('first_name'))}")
            print(f"    PIN: {p.get('visita_patient_id')} · patients id: {p.get('id')} · active_status: {p.get('active_status')}")
        if prot["user_ids"]:
            print(f"    protected user/account ids: {len(prot['user_ids'])}")
        print(f"  Cleanup action: KEEP / EXCLUDED (protection wins over any legacy status)")
        if prot["duplicates"]:
            print("  ⚠ DUPLICATE LEGACY RECORDS DETECTED for protected patient — STOP & REVIEW (all protected, none deleted):")
            for coll, r in prot["duplicates"]:
                print(f"     {coll}: id={r.get('id')} name={_fmt_name(r.get('last_name'), r.get('first_name'))} PIN={r.get('visita_patient_id')}")

        expected_after = total_before - len(plan["delete_dir_ids"])
        print("\n-- CLEANUP TOTALS (protected excluded) --")
        print(f"  patient_directory total before ......... {total_before}")
        print(f"  ACTIVE (keep) .......................... {active_before}")
        print(f"  FORMER_CLOSED targeted (after protect) . {plan['closed_count']}")
        print(f"  directory rows to DELETE ............... {len(plan['delete_dir_ids'])}")
        print(f"  portal patients to DELETE ............. {len(plan['portal_delete_ids'])}")
        print(f"  portal user accounts to DELETE ........ {len(plan['user_delete_ids'])}")
        print(f"  appointment_requests to DELETE ........ {len(plan['ar_delete_ids'])}")
        print(f"  appointment_reminders to DELETE ....... {reminder_count}")
        for coll, n in wf_counts.items():
            print(f"  {coll} to DELETE .......... {n}")
        print(f"  expected patient_directory rows AFTER . {expected_after}")
        if plan["ambiguous"]:
            print(f"  AMBIGUOUS / SKIPPED (reported, not deleted): {len(plan['ambiguous'])}")
            for kind, ident, why in plan["ambiguous"]:
                print(f"     STOP [{kind}] {ident} — {why}")

        if not confirmed:
            print("\nDRY-RUN only. Re-run with CONFIRM_CLEANUP=GO-CLEANUP-FORMER-CLOSED-APPROVED to apply.")
            return

        del_dir = await db.patient_directory.delete_many(
            {"id": {"$in": list(plan["delete_dir_ids"])}, "patient_status": TARGET_STATUS})
        del_ar = await db.appointment_requests.delete_many({"id": {"$in": plan["ar_delete_ids"]}})
        del_rem = 0
        if plan["ar_delete_ids"]:
            r = await db.appointment_reminders.delete_many(
                {"appointment_id": {"$in": plan["ar_delete_ids"]}})
            del_rem = r.deleted_count
        wf_deleted = {}
        if plan["portal_delete_ids"]:
            ids = list(plan["portal_delete_ids"])
            for coll in PATIENT_ID_COLLECTIONS:
                r = await db[coll].delete_many({"patient_id": {"$in": ids}})
                wf_deleted[coll] = r.deleted_count
            rp = await db.patients.delete_many({"id": {"$in": ids}})
            wf_deleted["patients"] = rp.deleted_count
        del_users = 0
        if plan["user_delete_ids"]:
            r = await db.users.delete_many({"_id": {"$in": plan["user_delete_ids"]}})
            del_users = r.deleted_count

        await db.audit_logs.insert_one({
            "action": "former_closed_cleanup", "entity": "patient_directory", "entity_id": None,
            "actor": {"id": None, "name": "data-cleanup", "role": "system"},
            "meta": {
                "directory_deleted": del_dir.deleted_count,
                "appointments_deleted": del_ar.deleted_count,
                "reminders_deleted": del_rem,
                "portal_patients_deleted": wf_deleted.get("patients", 0),
                "users_deleted": del_users,
                "workflow_deleted": wf_deleted,
                "protected_pins": sorted(PROTECTED_PINS),
                "protected_dir_ids": sorted(prot["dir_ids"]),
                "protected_pt_ids": sorted(prot["pt_ids"]),
                "ambiguous_skipped": len(plan["ambiguous"]),
                "rule": "delete patient_status==FORMER_CLOSED; keep ACTIVE; protect PIN 3040",
            }, "at": now,
        })
        active_after = await db.patient_directory.count_documents({"patient_status": KEEP_STATUS})
        closed_after = await db.patient_directory.count_documents({"patient_status": TARGET_STATUS})
        print(f"\n  DELETED directory={del_dir.deleted_count} appts={del_ar.deleted_count} "
              f"reminders={del_rem} users={del_users} workflow={wf_deleted}")
        print(f"  VERIFY: FORMER_CLOSED remaining={closed_after} | ACTIVE remaining={active_after}")
        print(f"  PROTECTED PIN {sorted(PROTECTED_PINS)} preserved (dir_ids={sorted(prot['dir_ids'])}, pt_ids={sorted(prot['pt_ids'])})")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
