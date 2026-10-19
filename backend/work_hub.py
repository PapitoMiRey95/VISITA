"""VIen Work Hub — central Clinic ↔ Doctor work inbox (new model; legacy internal_messages untouched).

Collection `work_items`: one document per actionable item with an owner side (PHYSICIAN | CLINIC), a
status (NEW | IN_PROGRESS | WAITING | COMPLETED) and a lightweight events[] history. Source linkage
(source_type/source_id) is reserved for later integration with Rx / Referral / Message / Appointment.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import audit, db, next_ref, now_iso

COLL = "work_items"
CATEGORIES = ["MESSAGE", "REFERRAL_FOLLOWUP", "RESULTS", "INSURANCE_FORM", "LEGAL", "CHART_REQUEST", "APPOINTMENT_CALL", "ADMIN_OTHER"]
CATEGORY_LABELS = {
    "MESSAGE": "Message", "REFERRAL_FOLLOWUP": "Referral / Follow-up", "RESULTS": "Results / Imaging / BW",
    "INSURANCE_FORM": "Insurance / Form", "LEGAL": "Legal", "CHART_REQUEST": "Chart Request",
    "APPOINTMENT_CALL": "Appointment / Call", "ADMIN_OTHER": "Admin / Other",
}
OWNERS = ("PHYSICIAN", "CLINIC")
STATUSES = ("NEW", "IN_PROGRESS", "WAITING", "COMPLETED")
SOURCE_TYPES = ("PRESCRIPTION_REQUEST", "REFERRAL", "PATIENT_MESSAGE", "APPOINTMENT_REQUEST")
CLINIC_ROLES = ("staff", "physician", "admin")


def side_of(user: dict) -> str:
    return "PHYSICIAN" if user.get("role") == "physician" else "CLINIC"


class CreateBody(BaseModel):
    category: str
    message: str
    send_to: str  # PHYSICIAN | CLINIC
    patient_id: Optional[str] = None
    directory_id: Optional[str] = None
    patient_name: Optional[str] = None
    due_at: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None


class ActionBody(BaseModel):
    action: str  # handoff | in_progress | waiting | complete | reply | reopen
    note: Optional[str] = None
    waiting_until: Optional[str] = None


def _event(kind: str, user: dict, text: Optional[str] = None, **extra) -> dict:
    return {"at": now_iso(), "type": kind, "by_id": user["id"], "by_name": user.get("name"), "by_role": user.get("role"),
            "text": (text or "").strip() or None, **extra}


def _valid_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Please enter a valid date.")
    return value


def _actionable_query(user: dict) -> dict:
    return {"practice_id": user.get("practice_id"), "owner_role": side_of(user), "$or": [
        {"status": {"$in": ["NEW", "IN_PROGRESS"]}},
        {"status": "WAITING", "$or": [{"waiting_until": None}, {"waiting_until": {"$lte": now_iso()}}]},
    ]}


async def actionable_count(user: dict) -> int:
    return await db[COLL].count_documents(_actionable_query(user))


def build_router(require_roles) -> APIRouter:
    r = APIRouter()
    guard = Depends(require_roles(*CLINIC_ROLES))

    async def _get(item_id: str, user: dict) -> dict:
        doc = await db[COLL].find_one({"id": item_id, "practice_id": user.get("practice_id")}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Not found.")
        return doc

    @r.get("/internal/work")
    async def list_work(view: str = "my", user: dict = guard):
        """Views: my (owned by my side, actionable incl. due WAITING) | sent | waiting | completed."""
        ps = {"practice_id": user.get("practice_id")}
        side = side_of(user)
        if view == "sent":
            q = {**ps, "created_by": user["id"]}
        elif view == "waiting":
            q = {**ps, "status": "WAITING"}
        elif view == "completed":
            q = {**ps, "status": "COMPLETED"}
        else:
            q = _actionable_query(user)
        sort = [("completed_at", -1)] if view == "completed" else [("updated_at", -1)]
        items = await db[COLL].find(q, {"_id": 0}).sort(sort).limit(300).to_list(300)
        return {"view": view, "side": side, "items": items}

    @r.get("/internal/work/count")
    async def count_work(user: dict = guard):
        return {"count": await actionable_count(user)}

    @r.get("/internal/work/meta")
    async def work_meta(user: dict = guard):
        return {"categories": [{"key": k, "label": CATEGORY_LABELS[k]} for k in CATEGORIES], "side": side_of(user)}

    @r.post("/internal/work")
    async def create_work(body: CreateBody, user: dict = guard):
        if body.category not in CATEGORIES:
            raise HTTPException(status_code=400, detail="Please choose a valid type.")
        if body.send_to not in OWNERS:
            raise HTTPException(status_code=400, detail="Please choose who should receive this.")
        msg = (body.message or "").strip()
        if not msg or len(msg) > 2000:
            raise HTTPException(status_code=400, detail="Please describe what needs to be done.")
        if body.source_type and body.source_type not in SOURCE_TYPES:
            raise HTTPException(status_code=400, detail="Unknown source type.")
        doc = {
            "id": str(uuid.uuid4()), "ref_number": await next_ref("WRK"), "practice_id": user.get("practice_id"),
            "patient_id": body.patient_id, "directory_id": body.directory_id, "patient_name": (body.patient_name or "").strip() or None,
            "category": body.category, "message": msg,
            "created_by": user["id"], "created_by_name": user.get("name"), "created_by_role": user.get("role"),
            "owner_role": body.send_to, "owner_user_id": None,
            "status": "NEW", "due_at": _valid_iso(body.due_at), "waiting_until": None,
            "source_type": body.source_type, "source_id": body.source_id,
            "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None, "completed_by": None,
            "events": [_event("created", user, msg, to_role=body.send_to)],
        }
        await db[COLL].insert_one({**doc})
        await audit("work_item_created", "work_item", doc["id"], user, new_status="NEW",
                    meta={"category": body.category, "owner_role": body.send_to, "has_patient": bool(body.patient_id or body.directory_id)})
        return doc

    @r.get("/internal/work/{item_id}")
    async def get_work(item_id: str, user: dict = guard):
        return await _get(item_id, user)

    @r.post("/internal/work/{item_id}/action")
    async def act_work(item_id: str, body: ActionBody, user: dict = guard):
        doc = await _get(item_id, user)
        old = doc["status"]
        side = side_of(user)
        note = (body.note or "").strip()
        upd = {"updated_at": now_iso()}
        if body.action == "handoff":
            if doc["status"] == "COMPLETED":
                raise HTTPException(status_code=400, detail="This item is already completed.")
            to = "CLINIC" if doc["owner_role"] == "PHYSICIAN" else "PHYSICIAN"
            upd.update({"owner_role": to, "owner_user_id": None, "status": "NEW", "waiting_until": None})
            ev = _event("handoff", user, note, from_role=doc["owner_role"], to_role=to)
        elif body.action == "in_progress":
            upd.update({"status": "IN_PROGRESS", "waiting_until": None})
            ev = _event("status", user, note, status="IN_PROGRESS")
        elif body.action == "waiting":
            upd.update({"status": "WAITING", "waiting_until": _valid_iso(body.waiting_until)})
            ev = _event("waiting", user, note, waiting_until=upd["waiting_until"])
        elif body.action == "complete":
            upd.update({"status": "COMPLETED", "completed_at": now_iso(), "completed_by": user.get("name"), "waiting_until": None})
            ev = _event("completed", user, note)
        elif body.action == "reopen":
            upd.update({"status": "NEW", "completed_at": None, "completed_by": None, "owner_role": side})
            ev = _event("status", user, note, status="NEW")
        elif body.action == "reply":
            if not note:
                raise HTTPException(status_code=400, detail="Please write a short note.")
            ev = _event("reply", user, note)
        else:
            raise HTTPException(status_code=400, detail="Unknown action.")
        await db[COLL].update_one({"id": item_id}, {"$set": upd, "$push": {"events": ev}})
        await audit(f"work_item_{body.action}", "work_item", item_id, user, old_status=old, new_status=upd.get("status", old),
                    meta={"owner_role": upd.get("owner_role", doc["owner_role"])})
        return await _get(item_id, user)

    return r
