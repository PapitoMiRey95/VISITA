"""Family / Caregiver delegated portal access (v1).

A DELEGATE (the authenticated user — a patient helping a relative, or a caregiver-only
account) may act ON BEHALF OF a target patient, strictly limited to explicitly granted
patients, the four v1 permissions, and the patient's own practice. This NEVER creates a
second patient identity, never shares passwords, and never impersonates: every delegated
action is audited with the delegate as actor and the patient as the person acted for.
"""
from datetime import datetime, timezone
import uuid

COLL = "patient_portal_delegates"

# v1 portal capabilities a delegate can be granted.
APPOINTMENTS = "APPOINTMENTS"
RX_REQUESTS = "RX_REQUESTS"
DOCUMENTS = "DOCUMENTS"
REQUEST_STATUS = "REQUEST_STATUS"
HEALTH_CARD_UPDATE = "HEALTH_CARD_UPDATE"
PERMISSIONS = {APPOINTMENTS, RX_REQUESTS, DOCUMENTS, REQUEST_STATUS, HEALTH_CARD_UPDATE}

RELATIONSHIPS = ["Daughter", "Son", "Spouse / Partner", "Parent", "Caregiver",
                 "Legal / Substitute Decision Maker", "Other"]

CONSENT_TYPES = ["Patient consent", "Legal / Substitute Decision Maker", "Other authorized basis"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def clean_permissions(perms):
    """Keep only valid, de-duplicated permissions."""
    return [p for p in PERMISSIONS if p in set(perms or [])]


async def active_grant(db, patient_id, delegate_user_id):
    """The single active grant linking this delegate user to this patient, or None."""
    if not patient_id or not delegate_user_id:
        return None
    return await db[COLL].find_one(
        {"patient_id": patient_id, "delegate_user_id": delegate_user_id, "active": True})


async def grants_for_delegate(db, delegate_user_id):
    """Active grants for a delegate — powers 'People I help manage'."""
    return await db[COLL].find({"delegate_user_id": delegate_user_id, "active": True}).to_list(100)


async def grants_for_patient(db, patient_id):
    """All grants (active + revoked) for a patient — staff Family/Caregiver Access panel."""
    return await db[COLL].find({"patient_id": patient_id}, {"_id": 0}).sort("created_at", -1).to_list(100)


def serialize(g):
    return {k: v for k, v in g.items() if k != "_id"} if g else None
