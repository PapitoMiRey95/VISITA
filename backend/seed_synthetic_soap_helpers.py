"""PREVIEW/TEST ONLY — seeds clearly synthetic SOAP helpers (synthetic_sample: true). Idempotent by key.
Never run against Production. Remove synthetic records before any production deploy."""
import asyncio
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SYNTH = [
    {"key": "SYNTH_FOLLOWUP", "name": "SYNTH General Follow-Up", "sex_filter": "ANY",
     "subjective_text": "[SYNTHETIC] Patient returns for routine follow-up. Reports feeling generally well.",
     "objective_text": "[SYNTHETIC] Alert, comfortable, no acute distress.",
     "plan_text": "[SYNTHETIC] Continue current management. Review again as scheduled."},
    {"key": "SYNTH_URI", "name": "SYNTH Simple URI", "sex_filter": "ANY",
     "subjective_text": "[SYNTHETIC] Nasal congestion and sore throat for several days. No shortness of breath.",
     "objective_text": "[SYNTHETIC] Afebrile. Throat mildly erythematous. Chest clear.",
     "plan_text": "[SYNTHETIC] Supportive care discussed. Return if symptoms worsen."},
    {"key": "SYNTH_REVIEW", "name": "SYNTH Routine Review", "sex_filter": "ANY",
     "subjective_text": "[SYNTHETIC] Routine periodic review requested.", "objective_text": "",
     "plan_text": "[SYNTHETIC] Routine review completed. Next review in one year."},
    {"key": "SYNTH_FEMALE_ONLY", "name": "SYNTH Female-Only Example", "sex_filter": "FEMALE",
     "subjective_text": "[SYNTHETIC] Female-filtered helper example text.", "objective_text": "", "plan_text": ""},
    {"key": "SYNTH_INACTIVE", "name": "SYNTH Inactive Example", "sex_filter": "ANY", "active": False,
     "subjective_text": "[SYNTHETIC] Should never appear.", "objective_text": "", "plan_text": ""},
    {"key": "SYNTH_OTHER_PRACTICE", "name": "SYNTH Other Practice Example", "sex_filter": "ANY", "practice_id": "other-practice-test",
     "subjective_text": "[SYNTHETIC] Should never appear.", "objective_text": "", "plan_text": ""},
]


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    practice = await db.practices.find_one({"active": True}, {"_id": 0, "id": 1})
    now = datetime.now(timezone.utc).isoformat()
    for h in SYNTH:
        doc = {"id": str(uuid.uuid4()), "yes_no_mode": False, "active": True, "practice_id": practice["id"], "physician_user_id": None,
               "created_at": now, "updated_at": now, "created_by": {"id": "seed", "name": "synthetic seed"}, "updated_by": None,
               "synthetic_sample": True, **h}
        r = await db.soap_helpers.update_one({"key": h["key"]}, {"$setOnInsert": doc}, upsert=True)
        print(h["key"], "inserted" if r.upserted_id else "exists")


asyncio.run(main())
