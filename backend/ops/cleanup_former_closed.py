"""STAGED cleanup — permanently remove FORMER_CLOSED legacy patients from VIsita Web.

AUTHORITATIVE RULE (Dr. Aguayo, final):
  KEEP   patient_directory.patient_status == "ACTIVE"
  DELETE patient_directory.patient_status == "FORMER_CLOSED"
  `source_close_marker` is NOT authoritative (an ACTIVE row keeps ACTIVE even if
  its marker says CLOSE/CLOSEZ).

SAFETY CONTRACT (do not weaken):
- Targets ONLY patient_directory rows whose patient_status == "FORMER_CLOSED".
  ACTIVE rows are never touched.
- Cascades ONLY to records owned EXCLUSIVELY by a deleted patient:
    * portal patients row linked via directory.linked_patient_id — but ONLY if that
      portal patient is itself NOT active_status==True (else AMBIGUOUS -> skip+report).
    * the user/portal account for a deleted portal patient.
    * appointment_requests referencing a deleted directory record — but ONLY if the
      appointment is NOT tied to any ACTIVE patient (else AMBIGUOUS -> skip+report).
    * appointment_reminders for a deleted appointment.
    * workflow rows (rx/imaging/bloodwork/referrals/patient_referrals/patient_messages/
      notifications/visita_pins) whose patient_id is a deleted portal patient id.
- Anything shared / ambiguous / tied to an ACTIVE patient is SKIPPED and reported,
  never auto-deleted.
- DRY-RUN by default. Executes only when env CONFIRM_CLEANUP == the token below.
- Does NOT touch users/staff/physicians/pharmacies/partners/organizations/providers.
- Does NOT recreate any legacy record. Legacy Access DB/backup is never touched.

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

# Workflow collections keyed by portal patient_id (uuid).
PATIENT_ID_COLLECTIONS = [
    "prescription_requests", "imaging_requests", "bloodwork_requests",
    "referrals", "patient_referrals", "patient_messages", "notifications",
    "visita_pins",
]


async def build_plan(db):
    closed = await db.patient_directory.find(
        {"patient_status": TARGET_STATUS},
        {"_id": 0, "id": 1, "visita_patient_id": 1, "linked_patient_id": 1}).to_list(100000)
    dir_ids = {d["id"] for d in closed}
    vpids = {d.get("visita_patient_id") for d in closed if d.get("visita_patient_id")}
    linked_pids = {d.get("linked_patient_id") for d in closed if d.get("linked_patient_id")}

    active_pt_ids = {p["id"] for p in await db.patients.find(
        {"active_status": True}, {"_id": 0, "id": 1}).to_list(100000)}
    active_dir_ids = {d["id"] for d in await db.patient_directory.find(
        {"patient_status": KEEP_STATUS}, {"_id": 0, "id": 1}).to_list(100000)}

    ambiguous = []
    delete_dir_ids = set(dir_ids)

    # Portal patients linked to a closed directory row.
    portal_delete_ids = set()
    for pid in linked_pids:
        p = await db.patients.find_one({"id": pid}, {"_id": 0, "id": 1, "active_status": 1})
        if not p:
            continue
        if p.get("active_status") is True:
            ambiguous.append(("portal_patient_ACTIVE", pid,
                              "linked FORMER_CLOSED dir row points to an ACTIVE portal patient"))
            # keep the dir row too, to avoid orphaning an active portal patient link
            for d in closed:
                if d.get("linked_patient_id") == pid:
                    delete_dir_ids.discard(d["id"])
        else:
            portal_delete_ids.add(pid)

    user_delete_ids = []
    for pid in portal_delete_ids:
        async for u in db.users.find({"patient_id": pid}, {"_id": 1, "email": 1}):
            user_delete_ids.append(u["_id"])

    # Appointment requests referencing the closed set.
    ar_delete_ids = []
    ar_ambiguous = 0
    async for a in db.appointment_requests.find({}, {"_id": 0}):
        refs_closed = (a.get("directory_id") in dir_ids or a.get("linked_patient_id") in dir_ids
                       or a.get("patient_id") in dir_ids or a.get("patient_id") in portal_delete_ids
                       or (a.get("visita_patient_id") and a.get("visita_patient_id") in vpids))
        if not refs_closed:
            continue
        tied_active = (a.get("patient_id") in active_pt_ids or a.get("linked_patient_id") in active_dir_ids
                       or a.get("directory_id") in active_dir_ids)
        if tied_active:
            ar_ambiguous += 1
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
        "ar_ambiguous": ar_ambiguous,
        "ambiguous": ambiguous,
    }


async def main():
    confirmed = os.environ.get("CONFIRM_CLEANUP", "").strip() == CONFIRM_TOKEN
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    try:
        active_before = await db.patient_directory.count_documents({"patient_status": KEEP_STATUS})
        total_before = await db.patient_directory.estimated_document_count()
        plan = await build_plan(db)

        # Count workflow rows that would be removed (only for deleted portal patients).
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
        print(f"  patient_directory total before ......... {total_before}")
        print(f"  ACTIVE (keep) .......................... {active_before}")
        print(f"  FORMER_CLOSED (target) ................. {plan['closed_count']}")
        print(f"  directory rows to DELETE ............... {len(plan['delete_dir_ids'])}")
        print(f"  portal patients to DELETE ............. {len(plan['portal_delete_ids'])}")
        print(f"  portal user accounts to DELETE ........ {len(plan['user_delete_ids'])}")
        print(f"  appointment_requests to DELETE ........ {len(plan['ar_delete_ids'])}")
        print(f"  appointment_reminders to DELETE ....... {reminder_count}")
        for coll, n in wf_counts.items():
            print(f"  {coll} to DELETE .......... {n}")
        print(f"  expected directory rows AFTER ......... {active_before}")
        if plan["ambiguous"]:
            print(f"  AMBIGUOUS / SKIPPED (reported, not deleted): {len(plan['ambiguous'])}")
            for kind, ident, why in plan["ambiguous"]:
                print(f"     STOP [{kind}] {ident} — {why}")

        if not confirmed:
            print("DRY-RUN only. Re-run with CONFIRM_CLEANUP=GO-CLEANUP-FORMER-CLOSED-APPROVED to apply.")
            return

        # ---- EXECUTE (idempotent, ownership-guarded sets computed above) ----
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
                "ambiguous_skipped": len(plan["ambiguous"]),
                "rule": "delete patient_status==FORMER_CLOSED; keep ACTIVE",
            }, "at": now,
        })
        active_after = await db.patient_directory.count_documents({"patient_status": KEEP_STATUS})
        closed_after = await db.patient_directory.count_documents({"patient_status": TARGET_STATUS})
        print(f"  DELETED directory={del_dir.deleted_count} appts={del_ar.deleted_count} "
              f"reminders={del_rem} users={del_users} workflow={wf_deleted}")
        print(f"  VERIFY: FORMER_CLOSED remaining={closed_after} (expect 0) | ACTIVE remaining={active_after}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
