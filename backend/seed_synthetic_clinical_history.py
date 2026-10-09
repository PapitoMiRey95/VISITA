"""PREVIEW/TEST ONLY — seeds clearly synthetic PMHx / PSHx / Allergy records (synthetic_sample: true)
on the synthetic test patient used by VIS-SAMPLE-HX. Idempotent by id. Never run against Production.
Remove with: db.patient_conditions/patient_surgeries/patient_allergies.deleteMany({synthetic_sample: true})"""
import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

ACTOR = {"id": "synthetic-seed", "name": "SYNTHETIC SEED"}
RECORDS = [
    ("patient_conditions", {"id": "SYNTH-COND-HTN", "display_text": "[SYNTHETIC] Hypertension", "status": "ACTIVE",
                            "onset_date": "2018", "resolved_date": None, "notes": None}),
    ("patient_conditions", {"id": "SYNTH-COND-PNA", "display_text": "[SYNTHETIC] Community-acquired pneumonia", "status": "RESOLVED",
                            "onset_date": "2021-02", "resolved_date": "2021-03", "notes": None}),
    ("patient_surgeries", {"id": "SYNTH-SURG-APPY", "procedure_text": "[SYNTHETIC] Appendectomy", "status": "ACTIVE",
                           "procedure_date": "2005", "facility": None, "surgeon_or_provider": None, "notes": None}),
    ("patient_allergies", {"id": "SYNTH-ALL-PCN", "allergen": "[SYNTHETIC] Penicillin", "allergy_type": "DRUG",
                           "reaction": "Rash", "severity": "MODERATE", "status": "ACTIVE", "notes": None}),
]


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    v = await db.visits.find_one({"ref_number": "VIS-SAMPLE-HX"}, {"_id": 0})
    if not v:
        raise SystemExit("VIS-SAMPLE-HX synthetic visit not found; nothing seeded.")
    now = datetime.now(timezone.utc).isoformat()
    base = {"practice_id": v["practice_id"], "patient_ref": v["patient_ref"], "patient_id": v.get("patient_id"),
            "directory_id": v.get("directory_id"), "visita_patient_id": v.get("visita_patient_id"),
            "synthetic_sample": True, "created_at": now, "updated_at": now, "created_by": ACTOR, "updated_by": ACTOR}
    for coll, rec in RECORDS:
        await db[coll].update_one({"id": rec["id"]}, {"$setOnInsert": {**base, **rec}}, upsert=True)
        print(f"seeded {coll}.{rec['id']} for {v['patient_ref']}")


if __name__ == "__main__":
    asyncio.run(main())
