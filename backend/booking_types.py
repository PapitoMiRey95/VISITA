"""Per-physician patient-facing booking types (what patients / caregivers may self-book).

Collection `physician_booking_config`: {physician_user_id, practice_id, patient_booking_types[], caregiver_booking_types[], updated_at, updated_by}.
Missing document = current behaviour (IN_CLINIC + TELEPHONE for patients, nothing for caregivers).
Internal physician/admin scheduling is NOT governed by this — it only gates new self-service requests.
"""
from typing import Optional

from db import db, now_iso

COLL = "physician_booking_config"
PATIENT_TYPES = ("IN_CLINIC", "TELEPHONE")
CAREGIVER_TYPES = ("PROXY",)
LABELS = {"IN_CLINIC": "In-Clinic", "TELEPHONE": "Telephone", "PROXY": "Proxy / On behalf of patient"}
DEFAULT = {"patient_booking_types": list(PATIENT_TYPES), "caregiver_booking_types": []}


async def config_for(physician_user_id: Optional[str]) -> dict:
    doc = await db[COLL].find_one({"physician_user_id": physician_user_id}, {"_id": 0}) if physician_user_id else None
    return {**DEFAULT, **{k: doc[k] for k in ("patient_booking_types", "caregiver_booking_types") if doc and k in doc}}


async def physician_for_practice(practice_id: Optional[str]) -> Optional[str]:
    """The physician whose availability patients book (single-physician practice model)."""
    pr = await db.practices.find_one({"id": practice_id}, {"_id": 0, "physician_user_id": 1}) if practice_id else None
    if pr and pr.get("physician_user_id"):
        return pr["physician_user_id"]
    u = await db.users.find_one({"role": "physician", **({"practice_id": practice_id} if practice_id else {})}, {"_id": 1})
    return str(u["_id"]) if u else None


async def allowed_types(practice_id: Optional[str], is_delegate: bool) -> list:
    cfg = await config_for(await physician_for_practice(practice_id))
    return list(cfg["patient_booking_types"]) + (list(cfg["caregiver_booking_types"]) if is_delegate else [])


def validate(types: list, allowed: tuple) -> list:
    out = []
    for t in types or []:
        if t not in allowed:
            raise ValueError(t)
        if t not in out:
            out.append(t)
    return out


async def save(physician_user_id: str, practice_id: str, patient_types: list, caregiver_types: list, user: dict) -> dict:
    doc = {"physician_user_id": physician_user_id, "practice_id": practice_id,
           "patient_booking_types": validate(patient_types, PATIENT_TYPES),
           "caregiver_booking_types": validate(caregiver_types, CAREGIVER_TYPES),
           "updated_at": now_iso(), "updated_by": user.get("name")}
    await db[COLL].update_one({"physician_user_id": physician_user_id}, {"$set": doc}, upsert=True)
    return doc
