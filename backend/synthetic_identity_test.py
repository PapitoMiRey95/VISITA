"""PREVIEW-ONLY synthetic fixtures for identity-prevention verification.
All records are tagged is_synthetic_test=True, use fake HCNs (TEST-9xxx) and fake contacts.
  python3 synthetic_identity_test.py create | cleanup | index_report"""
import asyncio
import os
import sys
import uuid

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
import directory as dmod  # noqa: E402
TAG = {"is_synthetic_test": True}
NOW = "2026-06-01T00:00:00+00:00"


def dir_doc(first, last, dob, hcn, pin, linked=None):
    return {"id": f"syn-dir-{uuid.uuid4().hex[:8]}", "visita_patient_id": pin, "first_name": first, "last_name": last,
            "norm_first": dmod.norm_name(first), "norm_last": dmod.norm_name(last), "norm_dob": dob, "date_of_birth": dob,
            "health_card_number": hcn, "norm_hcn": dmod.norm_hcn(hcn), "patient_status": "ACTIVE", "patient_type": "ohip",
            "city": "Testville", "province": "ON", "linked_patient_id": linked, "created_at": NOW, "updated_at": NOW, **TAG}


def portal_doc(first, last, dob, hcn, practice_id, middle=None, second=None, matched=None, status="pending"):
    return {"id": f"syn-pat-{uuid.uuid4().hex[:8]}", "visita_patient_id": None, "first_name": first, "last_name": last,
            "middle_name": middle, "second_last_name": second, "date_of_birth": dob, "health_card_number": hcn,
            "health_card_version": "ZZ", "email": f"synthetic+{uuid.uuid4().hex[:6]}@example.test", "phone": "(000) 000-0000",
            "patient_type": "ohip", "verification_status": status, "portal_status": "PENDING_VERIFICATION",
            "review_queue": None, "directory_match": None, "matched_directory_id": matched, "practice_id": practice_id,
            "active_status": True, "is_demo": False, "created_at": NOW, "updated_at": NOW, **TAG}


async def main(cmd):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    if cmd == "cleanup":
        r1 = await db.patients.delete_many(TAG)
        r2 = await db.patient_directory.delete_many(TAG)
        rv = await db.visits.delete_many(TAG)
        ra = await db.audit_logs.count_documents({"entity_id": {"$regex": "^syn-"}})
        r3 = await db.practice_patient_relationships.delete_many({"patient_id": {"$regex": "^syn-pat-"}}) if "practice_patient_relationships" in await db.list_collection_names() else None
        rem = await db.patients.count_documents({"id": {"$regex": "^syn-"}}) + await db.patient_directory.count_documents({"id": {"$regex": "^syn-"}}) + await db.visits.count_documents({"id": {"$regex": "^syn-"}})
        print("removed patients:", r1.deleted_count, "directory:", r2.deleted_count, "visits:", rv.deleted_count, "rels:", r3.deleted_count if r3 else 0, "remaining syn:", rem, "(audit rows about syn ids kept immutable:", ra, ")")
        return
    if cmd == "index_report":
        pipe = [{"$match": {"matched_directory_id": {"$ne": None}, "active_status": True}},
                {"$group": {"_id": "$matched_directory_id", "n": {"$sum": 1}, "ids": {"$push": "$id"}}}, {"$match": {"n": {"$gt": 1}}}]
        dups = await db.patients.aggregate(pipe).to_list(100)
        total = await db.patients.count_documents({"matched_directory_id": {"$ne": None}, "active_status": True})
        print("active portal accounts with matched_directory_id:", total)
        print("directory ids with >1 active portal account:", len(dups), dups)
        print("partial unique index safe:", len(dups) == 0)
        return
    staff = await db.users.find_one({"email": "staff@visita.demo"}, {"practice_id": 1})
    pid = staff["practice_id"]
    if cmd == "create_cleanup":
        # Historical cases (all verified-unlinked unless noted), SYNTHETIC
        # A safe exact-HCN link
        dA = dir_doc("Clean Alpha", "SYNTHCLEAN ALPHA", "1981-02-02", "TEST9100000001", "9911")
        pA = portal_doc("Clean Alpha", "SYNTHCLEAN ALPHA", "1981-02-02", "TEST9100000001", pid, status="verified")
        # B canonical missing expiry, portal has it (+ exact HCN)
        dB = dir_doc("Clean Bravo", "SYNTHCLEAN BRAVO", "1982-03-03", "TEST9100000002", "9912")
        pB = portal_doc("Clean Bravo", "SYNTHCLEAN BRAVO", "1982-03-03", "TEST9100000002", pid, status="verified")
        pB.update({"health_card_expiry_date": "2029-03-28", "health_card_issue_date": "2024-03-28", "email": "synthetic.bravo@example.test"})
        # C conflicting phone/address
        dC = dir_doc("Clean Charlie", "SYNTHCLEAN CHARLIE", "1983-04-04", "TEST9100000003", "9913")
        dC.update({"cell_phone": "(416) 111-1111", "address": "1 Old Test Rd", "city": "Testville"})
        pC = portal_doc("Clean Charlie", "SYNTHCLEAN CHARLIE", "1983-04-04", "TEST9100000003", pid, status="verified")
        pC.update({"phone": "(647) 222-2222", "address": "2 New Test Ave", "city": "Testville"})
        # D shortened portal name vs canonical full (same DOB, no HCN on portal) + historical duplicate PIN
        dD = dir_doc("Testangie Sophia", "SYNTHCLEAN GUARDO HERNANDEZ", "2000-10-30", "TEST9100000004", "9914")
        pD = portal_doc("Testangie", "SYNTHCLEAN GUARDO", "2000-10-30", None, pid, status="verified")
        pD["visita_patient_id"] = "9994"
        # E half-link (portal side only)
        dE = dir_doc("Clean Echo", "SYNTHCLEAN ECHO", "1985-06-06", "TEST9100000005", "9915")
        pE = portal_doc("Clean Echo", "SYNTHCLEAN ECHO", "1985-06-06", "TEST9100000005", pid, status="verified", matched=dE["id"])
        # F directory already linked to another portal account
        pF1 = portal_doc("Clean Fox", "SYNTHCLEAN FOXTROT", "1986-07-07", "TEST9100000006", pid, status="verified")
        dF = dir_doc("Clean Fox", "SYNTHCLEAN FOXTROT", "1986-07-07", "TEST9100000006", "9916", linked=pF1["id"])
        pF1.update({"matched_directory_id": dF["id"], "identity_linked": True, "visita_patient_id": "9916"})
        pF2 = portal_doc("Clean Fox", "SYNTHCLEAN FOXTROT", "1986-07-07", "TEST9100000006", pid, status="verified")
        # G portal duplicate with clinical dependency (visit attached to portal id)
        dG = dir_doc("Clean Golf", "SYNTHCLEAN GOLF", "1987-08-08", "TEST9100000007", "9917")
        pG = portal_doc("Clean Golf", "SYNTHCLEAN GOLF", "1987-08-08", "TEST9100000007", pid, status="verified")
        pG["visita_patient_id"] = "9997"
        visit = {"id": f"syn-vis-{uuid.uuid4().hex[:8]}", "ref_number": "VIS-SYN-G", "patient_ref": f"patient:{pG['id']}", "patient_id": pG["id"],
                 "directory_id": None, "practice_id": pid, "status": "READY_TO_SIGN", "started_at": NOW, "created_at": NOW, **TAG}
        # H identity conflict (same HCN, different DOB)
        dH = dir_doc("Clean Hotel", "SYNTHCLEAN HOTEL", "1988-09-09", "TEST9100000008", "9918")
        pH = portal_doc("Clean Hotel", "SYNTHCLEAN HOTEL", "1988-09-10", "TEST9100000008", pid, status="verified")
        await db.patient_directory.insert_many([dA, dB, dC, dD, dE, dF, dG, dH])
        await db.patients.insert_many([pA, pB, pC, pD, pE, pF1, pF2, pG, pH])
        await db.visits.insert_one(visit)
        print({"A": (pA["id"], dA["id"]), "B": (pB["id"], dB["id"]), "C": (pC["id"], dC["id"]), "D": (pD["id"], dD["id"]),
               "E": (pE["id"], dE["id"]), "F2": (pF2["id"], dF["id"]), "F1": pF1["id"], "G": (pG["id"], dG["id"]), "H": (pH["id"], dH["id"]), "visit": visit["id"]})
        return
    # Case A: existing-patient exact HCN match → IDENTITY_LINK_REQUIRED
    dA = dir_doc("Test Alpha", "SYNTHETIC ALPHAVILLE", "1980-01-15", "TEST9000000001", "9901")
    pA = portal_doc("Test Alpha", "SYNTHETIC ALPHAVILLE", "1980-01-15", "TEST9000000001", pid)
    # Case B: shortened-name + same DOB (no HCN) → POSSIBLE_IDENTITY_REVIEW
    dB = dir_doc("Testangie Sophia", "SYNTHGUARDO HERNANDEZ", "2000-10-30", "TEST9000000002", "9902")
    pB = portal_doc("Testangie", "SYNTHGUARDO", "2000-10-30", None, pid)
    # Case C: true new patient
    pC = portal_doc("Testnew", "SYNTHETIC NEWCOMER", "1999-05-05", "TEST9000000003", pid)
    # Case D: directory already linked to another portal account → link conflict
    pD1 = portal_doc("Test Delta", "SYNTHETIC DELTAVILLE", "1975-07-07", "TEST9000000004", pid, status="verified")
    dD = dir_doc("Test Delta", "SYNTHETIC DELTAVILLE", "1975-07-07", "TEST9000000004", "9904", linked=pD1["id"])
    pD1["matched_directory_id"] = dD["id"]; pD1["identity_linked"] = True; pD1["visita_patient_id"] = "9904"
    pD2 = portal_doc("Test Delta", "SYNTHETIC DELTAVILLE", "1975-07-07", "TEST9000000004", pid)
    await db.patient_directory.insert_many([dA, dB, dD])
    await db.patients.insert_many([pA, pB, pC, pD1, pD2])
    print({"dir_A": dA["id"], "pat_A": pA["id"], "dir_B": dB["id"], "pat_B": pB["id"], "pat_C": pC["id"],
           "dir_D": dD["id"], "pat_D1": pD1["id"], "pat_D2": pD2["id"]})


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "create"))
