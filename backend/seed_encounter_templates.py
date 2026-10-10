"""Encounter-type SOAP templates (PREVIEW). Idempotent by key.
- Three physician-selectable Objective templates from encounter_template_profiles.v1 (NOT synthetic, never auto-inserted).
- One clearly SYNTHETIC physical-exam template to verify hiding on Telephone/Video/Proxy (remove before Production)."""
import asyncio
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

TEMPLATES = [
    {"key": "TEL_SOUNDS_WELL", "name": "Telephone — Sounds well", "encounter_types": ["TELEPHONE"], "template_category": "remote_observation",
     "objective_text": "Sounds well over telephone.", "source": "encounter_template_profiles.v1"},
    {"key": "VID_LOOKS_WELL", "name": "Video — Looks well", "encounter_types": ["VIDEO"], "template_category": "remote_observation",
     "objective_text": "Looks well on video.", "source": "encounter_template_profiles.v1"},
    {"key": "PROXY_NO_EXAM", "name": "Proxy — No physical exam", "encounter_types": ["PROXY"], "template_category": "remote_observation",
     "objective_text": "No physical examination performed.", "source": "encounter_template_profiles.v1"},
    {"key": "SYNTH_PHYSICAL_EXAM", "name": "SYNTH Physical Exam — Normal", "encounter_types": ["PHYSICAL"], "template_category": "physical_exam",
     "objective_text": "[SYNTHETIC] Chest clear. Heart sounds normal. Abdomen soft, non-tender.", "synthetic_sample": True},
]


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    practice = await db.practices.find_one({"active": True}, {"_id": 0, "id": 1})
    now = datetime.now(timezone.utc).isoformat()
    for t in TEMPLATES:
        doc = {"id": str(uuid.uuid4()), "sex_filter": "ANY", "yes_no_mode": False, "active": True, "practice_id": practice["id"],
               "physician_user_id": None, "subjective_text": "", "plan_text": "", "created_at": now,
               "created_by": {"id": "seed", "name": "encounter template seed"}, **t}
        doc = {k: v for k, v in doc.items() if k != "encounter_types"}
        await db.soap_helpers.update_one({"key": t["key"], "practice_id": practice["id"]},
                                         {"$setOnInsert": doc, "$set": {"encounter_types": t["encounter_types"], "updated_at": now}}, upsert=True)
        print("seeded", t["key"], t["encounter_types"])


if __name__ == "__main__":
    asyncio.run(main())
