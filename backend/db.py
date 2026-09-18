import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def next_ref(prefix: str) -> str:
    doc = await db.counters.find_one_and_update(
        {"_id": prefix},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return f"{prefix}-{doc['seq']:06d}"


async def audit(action: str, entity_type: str, entity_id: str, actor: dict,
                old_status=None, new_status=None, meta=None):
    await db.audit_logs.insert_one({
        "id": os.urandom(8).hex(),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_id": (actor or {}).get("id"),
        "actor_name": (actor or {}).get("name"),
        "actor_role": (actor or {}).get("role"),
        "old_status": old_status,
        "new_status": new_status,
        "meta": meta or {},
        "created_at": now_iso(),
    })


def mask_hcn(hcn: str) -> str:
    if not hcn:
        return ""
    digits = "".join(c for c in hcn if c.isalnum())
    if len(digits) <= 4:
        return "•••• " + digits
    return "•••• •••• " + digits[-3:]


# ---- Patient-facing status maps (internal wording never leaks) ----
RX_PATIENT_STATUS = {
    "received": "Received",
    "under_review": "Under Review",
    "waiting_physician": "Under Review",
    "completed": "Completed",
    "appointment_required": "Appointment Required",
    "appointment_booked": "Appointment Booked",
}

APPT_PATIENT_STATUS = {
    "requested": "Appointment Requested",
    "alternatives_offered": "Alternative Times Offered",
    "more_info_required": "More Information Requested",
    "confirmed": "Appointment Confirmed",
    "declined": "Declined",
    "cancelled": "Cancelled",
    "completed": "Completed",
    "more_info_requested": "More Information Requested",
    "suggested": "New Time Suggested",
}

IMG_PATIENT_STATUS = {
    "new": "Received",
    "under_review": "Under Review",
    "waiting_physician": "Under Review",
    "completed": "Completed",
    "appointment_required": "Appointment Required",
    "appointment_booked": "Appointment Booked",
}

BLD_PATIENT_STATUS = {
    "new": "Received",
    "under_review": "Under Review",
    "waiting_physician": "Under Review",
    "completed": "Completed",
    "appointment_required": "Appointment Required",
    "appointment_booked": "Appointment Booked",
    "more_info_required": "More Information Requested",
    "declined": "Declined",
}

MSG_PATIENT_STATUS = {
    "new": "Received",
    "open": "Under Review",
    "waiting_physician": "Under Review",
    "completed": "Completed",
    "appointment_booked": "Appointment Booked",
}

RX_ACTIVE = ["received", "under_review", "waiting_physician"]
IMG_ACTIVE = ["new", "under_review", "waiting_physician"]
BLD_ACTIVE = ["new", "under_review", "waiting_physician", "more_info_required"]
MSG_ACTIVE = ["new", "open", "waiting_physician"]
APPT_ACTIVE = ["requested", "more_info_requested"]
