"""Read-only medication-history audit against the configured DB. Usage: python tools/med_history_audit.py"""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
import med_history
from db import db


async def main():
    r = await med_history.reconcile(apply=False)
    print("COUNTS", r["counts"])
    print("CANDIDATES", r["candidates"][:8])
    print("LINKAGE", r["linkage_problems"][:8])
    print("AMBIGUOUS", r["ambiguous"][:5])
    pids = await db.patient_medications.distinct("patient_id")
    bad = [p for p in pids if not await db.patients.find_one({"id": p}, {"_id": 1})]
    print("patient_medications pids:", len(pids), "| stored under NON-portal ids (directory ids):", len(bad))
    dir_ids = await db.patient_directory.distinct("id")
    print("tx total:", await db.rx_transmissions.count_documents({}), "| tx with patient_id = directory id:",
          await db.rx_transmissions.count_documents({"patient_id": {"$in": dir_ids}}))
    p = await db.patients.find_one({"email": "maria.lopez@demo.com"}, {"_id": 0, "id": 1, "matched_directory_id": 1})
    if p:
        print("maria", p, "| meds:", await db.patient_medications.count_documents({"patient_id": p["id"]}),
              "| tx:", await db.rx_transmissions.count_documents({"$or": [{"patient_id": p["id"]}, {"patient_directory_id": p.get("matched_directory_id")}]}))

asyncio.run(main())
