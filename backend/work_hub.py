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
CATEGORIES = ["MESSAGE", "CALL_BOOK_PATIENT", "REFERRAL_FOLLOWUP", "RESULTS", "INSURANCE_FORM", "LEGAL", "CHART_REQUEST", "APPOINTMENT_CALL", "ADMIN_OTHER"]
DOCUMENT_CATEGORIES = ("INSURANCE_FORM", "LEGAL", "CHART_REQUEST")  # eligible for "Signed → Send to Clinic"
PRIORITIES = ("NORMAL", "B2", "B1", "ASAP")  # urgency: ASAP > B1 (~1 wk) > B2 (regular follow-up ~3–4 wks) > NORMAL  # clinic working labels only — no clinical time definition enforced
# Deterministic display text when a physician sends a priority without a written message (never AI-generated).
PRIORITY_DEFAULT_TEXT = {"B1": "Book patient in about 1 week.", "B2": "Book patient within about 3–4 weeks.", "ASAP": "Book patient as soon as possible."}
CATEGORY_LABELS = {
    "MESSAGE": "Message", "CALL_BOOK_PATIENT": "Call / Book Patient", "REFERRAL_FOLLOWUP": "Referral / Follow-up", "RESULTS": "Results / Imaging / BW",
    "INSURANCE_FORM": "Insurance / Form", "LEGAL": "Legal", "CHART_REQUEST": "Chart Request",
    "APPOINTMENT_CALL": "Appointment / Call", "ADMIN_OTHER": "Admin / Other",
}
OWNERS = ("PHYSICIAN", "CLINIC")
STATUSES = ("NEW", "IN_PROGRESS", "WAITING", "COMPLETED")
OUTCOMES = ("COMPLETED", "ALREADY_DONE", "NO_LONGER_NEEDED", "DUPLICATE")  # why an item left active work; status stays COMPLETED
# Staff → Physician context (workflow metadata only, never authorization; separate from physician booking priority).
ATTENTION_LEVELS = ("ROUTINE", "IMPORTANT", "NEEDS_ATTENTION")  # "how soon should the physician review this?"
REQUESTED_ACTIONS = ("REVIEW_DECISION", "PATIENT_INSTRUCTIONS", "SIGN_APPROVE", "PREPARE_DOCUMENT", "FYI", "OTHER")
REFERRAL_SUBTYPES = ("DECLINED", "MORE_INFO_REQUESTED", "PROVIDER_UPDATE", "ACCEPTED_IN_PROCESS", "APPOINTMENT_BOOKED", "FOLLOW_UP_NEEDED")
SOURCE_TYPES = ("PRESCRIPTION_REQUEST", "REFERRAL", "PATIENT_MESSAGE", "APPOINTMENT_REQUEST")
CLINIC_ROLES = ("staff", "physician", "admin")


def side_of(user: dict) -> str:
    return "PHYSICIAN" if user.get("role") == "physician" else "CLINIC"


ROLE_LABEL = {"physician": "Physician", "admin": "Clinic Administrator", "staff": "Clinic Staff"}
QUEUE_LABEL = {"PHYSICIAN": "Any Physician", "CLINIC": "Clinic Staff"}


async def practice_members(practice_id: Optional[str]) -> list:
    """Authoritative source: db.users (active clinic roles of this practice). Position comes from the
    Network org membership role_title when present, else user.position, else the VIen role label.
    Position is routing context only — it never grants permissions."""
    titles = {m["user_id"]: m.get("role_title") async for m in db.org_memberships.find(
        {"status": "ACTIVE", "$or": [{"practice_id": practice_id}, {"practice_id": None}]}, {"_id": 0, "user_id": 1, "role_title": 1})}
    out = []
    async for u in db.users.find({"role": {"$in": list(CLINIC_ROLES)}, "practice_id": practice_id, "active": {"$ne": False}},
                                 {"_id": 1, "name": 1, "role": 1, "position": 1}).sort("name", 1):
        uid = str(u["_id"])
        out.append({"user_id": uid, "name": u.get("name"), "role": u["role"], "side": "PHYSICIAN" if u["role"] == "physician" else "CLINIC",
                    "position": titles.get(uid) or u.get("position") or ROLE_LABEL.get(u["role"], u["role"])})
    return out


async def resolve_target(practice_id: Optional[str], send_to: Optional[str], to_user_id: Optional[str]) -> dict:
    """Returns owner fields for a queue (PHYSICIAN|CLINIC) or a specific practice member."""
    if to_user_id:
        m = next((x for x in await practice_members(practice_id) if x["user_id"] == to_user_id), None)
        if not m:
            raise HTTPException(status_code=400, detail="That person is not an active member of this clinic.")
        return {"owner_role": m["side"], "owner_user_id": m["user_id"], "owner_name": m["name"], "owner_position": m["position"]}
    if send_to not in OWNERS:
        raise HTTPException(status_code=400, detail="Please choose who should receive this.")
    return {"owner_role": send_to, "owner_user_id": None, "owner_name": None, "owner_position": None}


def owns(item: dict, user: dict) -> bool:
    if item.get("owner_user_id"):
        return item["owner_user_id"] == user["id"]
    return item.get("owner_role") == side_of(user)


class CreateBody(BaseModel):
    category: str
    message: Optional[str] = None  # required unless priority is B2/B1/ASAP (deterministic fallback text)
    send_to: Optional[str] = None  # queue: PHYSICIAN | CLINIC
    to_user_id: Optional[str] = None  # specific practice member (takes precedence)
    patient_id: Optional[str] = None
    directory_id: Optional[str] = None
    patient_name: Optional[str] = None
    due_at: Optional[str] = None
    priority: str = "NORMAL"
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    attention_level: Optional[str] = None  # physician-targeted only; None = never assigned (UI falls back to Routine)
    requested_action: Optional[str] = None  # physician-targeted only
    referral_subtype: Optional[str] = None  # REFERRAL_FOLLOWUP only


class ActionBody(BaseModel):
    action: str  # handoff | signed | in_progress | waiting | complete | reply | reopen | priority
    note: Optional[str] = None
    waiting_until: Optional[str] = None
    priority: Optional[str] = None
    outcome: Optional[str] = None  # complete: COMPLETED | ALREADY_DONE | NO_LONGER_NEEDED | DUPLICATE
    send_to: Optional[str] = None  # handoff/signed target queue
    to_user_id: Optional[str] = None  # handoff/signed target member


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
    """Personally assigned to me, or in my side's shared queue (unassigned)."""
    return {"practice_id": user.get("practice_id"), "$and": [
        {"$or": [{"owner_user_id": user["id"]}, {"owner_user_id": None, "owner_role": side_of(user)}]},
        {"$or": [{"status": {"$in": ["NEW", "IN_PROGRESS"]}},
                 {"status": "WAITING", "$or": [{"waiting_until": None}, {"waiting_until": {"$lte": now_iso()}}]}]},
    ]}


async def actionable_count(user: dict) -> int:
    return await db[COLL].count_documents(_actionable_query(user))


async def _position_of(user: dict) -> Optional[str]:
    m = next((x for x in await practice_members(user.get("practice_id")) if x["user_id"] == user["id"]), None)
    return m["position"] if m else ROLE_LABEL.get(user.get("role"))


def _rank(item: dict):
    """My Work order: ASAP → overdue → due today → B1 → B2 → rest; newest-updated first within a group."""
    now = datetime.now(timezone.utc)
    due = None
    if item.get("due_at"):
        try:
            due = datetime.fromisoformat(item["due_at"].replace("Z", "+00:00"))
        except ValueError:
            due = None
    pr = item.get("priority", "NORMAL")
    if pr == "ASAP":
        g = 0
    elif due and due < now:
        g = 1
    elif due and due.astimezone(timezone.utc).date() == now.date():
        g = 2
    elif pr == "B1":
        g = 3
    elif pr == "B2":
        g = 4
    else:
        g = 5
    return (g, item.get("updated_at") and -datetime.fromisoformat(item["updated_at"]).timestamp())


def build_router(require_roles) -> APIRouter:
    r = APIRouter()
    guard = Depends(require_roles(*CLINIC_ROLES))

    async def _get(item_id: str, user: dict) -> dict:
        doc = await db[COLL].find_one({"id": item_id, "practice_id": user.get("practice_id")}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Not found.")
        return doc

    @r.get("/internal/work")
    async def list_work(view: str = "my", include_completed: bool = False, limit: int = 300, offset: int = 0, user: dict = guard):
        """Views: my (owned by my side, actionable incl. due WAITING) | sent (active by default) | waiting | completed (History, paginated)."""
        ps = {"practice_id": user.get("practice_id")}
        side = side_of(user)
        limit = max(1, min(limit, 300))
        offset = max(0, offset)
        if view == "sent":
            q = {**ps, "created_by": user["id"]}
            if not include_completed:
                q["status"] = {"$ne": "COMPLETED"}
        elif view == "waiting":
            q = {**ps, "status": "WAITING"}
        elif view == "completed":
            q = {**ps, "status": "COMPLETED"}
        else:
            q = _actionable_query(user)
        sort = [("completed_at", -1)] if view == "completed" else [("updated_at", -1)]
        items = await db[COLL].find(q, {"_id": 0}).sort(sort).skip(offset).limit(limit + 1).to_list(limit + 1)
        has_more = len(items) > limit
        items = items[:limit]
        if view == "my":
            items.sort(key=_rank)
        for it in items:  # derived, never stored: clinic sent it, physician side currently owns it, still active
            it["awaiting_physician"] = it.get("created_by_role") != "physician" and it.get("owner_role") == "PHYSICIAN" and it.get("status") != "COMPLETED"
        return {"view": view, "side": side, "items": items, "has_more": has_more, "offset": offset, "limit": limit}

    @r.get("/internal/work/count")
    async def count_work(user: dict = guard):
        return {"count": await actionable_count(user)}

    @r.get("/internal/work/meta")
    async def work_meta(user: dict = guard):
        return {"attention_levels": list(ATTENTION_LEVELS), "requested_actions": list(REQUESTED_ACTIONS), "referral_subtypes": list(REFERRAL_SUBTYPES), "categories": [{"key": k, "label": CATEGORY_LABELS[k]} for k in CATEGORIES], "document_categories": list(DOCUMENT_CATEGORIES),
                "priorities": list(PRIORITIES), "side": side_of(user), "user_id": user["id"],
                "members": await practice_members(user.get("practice_id")), "queues": [{"key": k, "label": v} for k, v in QUEUE_LABEL.items()]}

    @r.post("/internal/work")
    async def create_work(body: CreateBody, user: dict = guard):
        if body.category not in CATEGORIES:
            raise HTTPException(status_code=400, detail="Please choose a valid type.")
        target = await resolve_target(user.get("practice_id"), body.send_to, body.to_user_id)
        msg = (body.message or "").strip()
        if len(msg) > 2000:
            raise HTTPException(status_code=400, detail="Please keep the description under 2000 characters.")
        if body.priority not in PRIORITIES:
            raise HTTPException(status_code=400, detail="Please choose a valid priority.")
        if body.priority != "NORMAL" and side_of(user) != "PHYSICIAN":
            raise HTTPException(status_code=403, detail="Only a physician can set B2 / B1 / ASAP priority.")
        message_auto = False
        if not msg:
            if body.priority == "NORMAL":
                raise HTTPException(status_code=400, detail="Please describe what needs to be done.")
            msg, message_auto = PRIORITY_DEFAULT_TEXT[body.priority], True
        if body.source_type and body.source_type not in SOURCE_TYPES:
            raise HTTPException(status_code=400, detail="Unknown source type.")
        attention, requested = None, None
        if target["owner_role"] == "PHYSICIAN":
            if body.attention_level is not None:
                if body.attention_level not in ATTENTION_LEVELS:
                    raise HTTPException(status_code=400, detail="Please choose a valid attention level.")
                attention = body.attention_level
            if body.requested_action is not None:
                if body.requested_action not in REQUESTED_ACTIONS:
                    raise HTTPException(status_code=400, detail="Please choose what you need from the doctor.")
                requested = body.requested_action
        referral_subtype = None
        if body.referral_subtype:
            if body.category != "REFERRAL_FOLLOWUP" or body.referral_subtype not in REFERRAL_SUBTYPES:
                raise HTTPException(status_code=400, detail="Referral outcome applies to Referral items only.")
            referral_subtype = body.referral_subtype
        doc = {
            "id": str(uuid.uuid4()), "ref_number": await next_ref("WRK"), "practice_id": user.get("practice_id"),
            "patient_id": body.patient_id, "directory_id": body.directory_id, "patient_name": (body.patient_name or "").strip() or None,
            "category": body.category, "message": msg, "message_auto": message_auto,
            "created_by": user["id"], "created_by_name": user.get("name"), "created_by_role": user.get("role"),
            **target,
            "status": "NEW", "priority": body.priority, "due_at": _valid_iso(body.due_at), "waiting_until": None,
            "attention_level": attention, "requested_action": requested, "referral_subtype": referral_subtype,
            "signed": False, "appointment_id": None,
            "source_type": body.source_type, "source_id": body.source_id,
            "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None, "completed_by": None,
            "events": [_event("created", user, msg, to_role=target["owner_role"], to_user_id=target["owner_user_id"], to_name=target["owner_name"], to_position=target["owner_position"],
                              from_position=(await _position_of(user)))],
        }
        await db[COLL].insert_one({**doc})
        await audit("work_item_created", "work_item", doc["id"], user, new_status="NEW",
                    meta={"category": body.category, "owner_role": target["owner_role"], "owner_user_id": target["owner_user_id"], "priority": body.priority, "has_patient": bool(body.patient_id or body.directory_id)})
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
        owner_only = body.action in ("handoff", "signed", "in_progress", "waiting", "complete")
        if owner_only and not owns(doc, user):
            raise HTTPException(status_code=403, detail="Only the current owner can do that.")
        frm = {"from_role": doc["owner_role"], "from_user_id": user["id"], "from_name": user.get("name"), "from_position": await _position_of(user)}
        if body.action in ("handoff", "signed"):
            if doc["status"] == "COMPLETED":
                raise HTTPException(status_code=400, detail="This item is already completed.")
            if body.action == "signed" and side != "PHYSICIAN":
                raise HTTPException(status_code=400, detail="Only the physician can mark a document as signed.")
            default_queue = "CLINIC" if doc["owner_role"] == "PHYSICIAN" else "PHYSICIAN"
            target = await resolve_target(user.get("practice_id"), body.send_to or (None if body.to_user_id else default_queue), body.to_user_id)
            upd.update({**target, "status": "NEW", "waiting_until": None})
            if body.action == "signed":
                upd["signed"] = True
            elif target["owner_role"] == "PHYSICIAN":
                upd["signed"] = False
            to = {"to_role": target["owner_role"], "to_user_id": target["owner_user_id"], "to_name": target["owner_name"], "to_position": target["owner_position"]}
            ev = _event("DOCUMENT_SIGNED" if body.action == "signed" else "handoff", user, note or ("Document signed." if body.action == "signed" else None), **frm, **to)
        elif body.action == "priority":
            if side != "PHYSICIAN":
                raise HTTPException(status_code=403, detail="Only a physician can change priority.")
            if body.priority not in PRIORITIES:
                raise HTTPException(status_code=400, detail="Please choose a valid priority.")
            if body.priority == doc.get("priority", "NORMAL"):
                return doc
            upd["priority"] = body.priority
            ev = _event("PRIORITY_CHANGED", user, note, from_priority=doc.get("priority", "NORMAL"), to_priority=body.priority)
        elif body.action == "in_progress":
            upd.update({"status": "IN_PROGRESS", "waiting_until": None})
            ev = _event("status", user, note, status="IN_PROGRESS")
        elif body.action == "waiting":
            upd.update({"status": "WAITING", "waiting_until": _valid_iso(body.waiting_until)})
            ev = _event("waiting", user, note, waiting_until=upd["waiting_until"])
        elif body.action == "complete":
            outcome = body.outcome or "COMPLETED"
            if outcome not in OUTCOMES:
                raise HTTPException(status_code=400, detail="Please choose a valid close outcome.")
            upd.update({"status": "COMPLETED", "completed_at": now_iso(), "completed_by": user.get("name"), "completion_outcome": outcome, "waiting_until": None})
            ev = _event("completed", user, note, outcome=outcome)
        elif body.action == "reopen":
            upd.update({"status": "NEW", "completed_at": None, "completed_by": None, "completion_outcome": None, "owner_role": side, "owner_user_id": user["id"], "owner_name": user.get("name"), "owner_position": await _position_of(user)})
            ev = _event("reopened", user, note)
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
