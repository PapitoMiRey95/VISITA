"""Longitudinal PATIENT clinical history (Phase 2A4A): conditions (PMHx), surgeries (PSHx), allergies.
Separate from `visits`. Keyed by canonical patient_ref; practice-isolated; never hard-deleted.
"""
import re
import uuid
from datetime import datetime, timezone

DOMAINS = {
    "conditions": {
        "coll": "patient_conditions", "entity": "condition", "label": "Past Medical Hx",
        "required": "display_text", "status_field": "status",
        "statuses": ("ACTIVE", "RESOLVED", "HISTORICAL"), "default_status": "ACTIVE",
        "text": ("display_text", "notes"), "dates": ("onset_date", "resolved_date"), "enums": {},
    },
    "surgeries": {
        "coll": "patient_surgeries", "entity": "surgery", "label": "Past Surgical Hx",
        "required": "procedure_text", "status_field": "status",
        "statuses": ("ACTIVE", "ARCHIVED"), "default_status": "ACTIVE",
        "text": ("procedure_text", "facility", "surgeon_or_provider", "notes"), "dates": ("procedure_date",), "enums": {},
    },
    "allergies": {
        "coll": "patient_allergies", "entity": "allergy", "label": "Allergies",
        "required": "allergen", "status_field": "status",
        "statuses": ("ACTIVE", "INACTIVE"), "default_status": "ACTIVE",
        "text": ("allergen", "reaction", "notes"), "dates": (),
        "enums": {"allergy_type": ("DRUG", "ENVIRONMENTAL", "FOOD", "OTHER"),
                  "severity": ("MILD", "MODERATE", "SEVERE", "LIFE_THREATENING")},
    },
}
_DATE_RX = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _now():
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db):
    for d in DOMAINS.values():
        await db[d["coll"]].create_index([("practice_id", 1), ("patient_ref", 1), ("status", 1)])
        await db[d["coll"]].create_index("id", unique=True)


def _clean(domain, body: dict, partial: bool) -> dict:
    """Server-side validation. Returns only allowed fields. Raises ValueError."""
    d = DOMAINS[domain]
    out = {}
    for k in d["text"]:
        if k in body:
            v = body[k]
            if v is not None and not isinstance(v, str):
                raise ValueError(f"{k} must be text.")
            v = (v or "").strip() or None
            if len(v or "") > 1000:
                raise ValueError(f"{k} is too long.")
            out[k] = v
    for k in d["dates"]:
        if k in body:
            v = (body[k] or "").strip() if isinstance(body[k], str) else body[k]
            if v and not _DATE_RX.match(v):
                raise ValueError(f"{k} must be YYYY, YYYY-MM or YYYY-MM-DD.")
            out[k] = v or None
    for k, allowed in d["enums"].items():
        if k in body:
            v = body[k] or None
            if v is not None and v not in allowed:
                raise ValueError(f"{k} must be one of {', '.join(allowed)}.")
            out[k] = v
    if "status" in body:
        if body["status"] not in d["statuses"]:
            raise ValueError(f"status must be one of {', '.join(d['statuses'])}.")
        out["status"] = body["status"]
    req = d["required"]
    if not partial and not out.get(req):
        raise ValueError(f"{req} is required.")
    if partial and req in out and not out[req]:
        raise ValueError(f"{req} cannot be blank.")
    if domain == "allergies" and not partial and not out.get("allergy_type"):
        raise ValueError("allergy_type is required.")
    return out


def empty_doc(domain) -> dict:
    d = DOMAINS[domain]
    return {**{k: None for k in d["text"]}, **{k: None for k in d["dates"]}, **{k: None for k in d["enums"]}}


async def list_records(db, domain, practice_id, refs: list):
    d = DOMAINS[domain]
    rows = await db[d["coll"]].find({"practice_id": practice_id, "patient_ref": {"$in": refs}}, {"_id": 0}).to_list(500)
    order = {s: i for i, s in enumerate(d["statuses"])}
    rows.sort(key=lambda r: (order.get(r.get("status"), 99), -(datetime.fromisoformat(r["created_at"]).timestamp())))
    return rows


async def create(db, domain, *, practice_id, identity, visita_patient_id, body: dict, user: dict):
    d = DOMAINS[domain]
    fields = _clean(domain, body, partial=False)
    now = _now()
    actor = {"id": user["id"], "name": user.get("name")}
    doc = {**empty_doc(domain), "id": str(uuid.uuid4()), "practice_id": practice_id,
           "patient_ref": identity["patient_ref"], "patient_id": identity.get("patient_id"),
           "directory_id": identity.get("directory_id"), "visita_patient_id": visita_patient_id,
           "status": d["default_status"], **fields,
           "created_at": now, "updated_at": now, "created_by": actor, "updated_by": actor}
    await db[d["coll"]].insert_one(doc)
    doc.pop("_id", None)
    return doc


async def patch(db, domain, record: dict, body: dict, user: dict):
    """Returns (changed_fields, old_status, new_status, updated_doc)."""
    d = DOMAINS[domain]
    fields = _clean(domain, body, partial=True)
    changed = {k: v for k, v in fields.items() if v != record.get(k)}
    if not changed:
        return [], record["status"], record["status"], record
    now = _now()
    changed.update({"updated_at": now, "updated_by": {"id": user["id"], "name": user.get("name")}})
    await db[d["coll"]].update_one({"id": record["id"]}, {"$set": changed})
    new = await db[d["coll"]].find_one({"id": record["id"]}, {"_id": 0})
    return sorted(k for k in changed if k not in ("updated_at", "updated_by")), record["status"], new["status"], new
