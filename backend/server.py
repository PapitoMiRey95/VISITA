from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import logging
import os
import uuid
from typing import Optional

from bson import ObjectId
from fastapi import (APIRouter, Depends, FastAPI, File, Form, HTTPException,
                     Request, Response, UploadFile)
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.cors import CORSMiddleware

import auth as authlib
import storage
from db import (APPT_PATIENT_STATUS, IMG_ACTIVE, IMG_PATIENT_STATUS, MSG_ACTIVE,
                MSG_PATIENT_STATUS, RX_ACTIVE, RX_PATIENT_STATUS, audit, db,
                mask_hcn, next_ref, now_iso)
from seed import seed_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("visita")

app = FastAPI(title="VISITA Web Portal")
api = APIRouter(prefix="/api")

MAX_PDF_BYTES = 15 * 1024 * 1024
CLINIC_ROLES = ("staff", "physician", "admin")


# ----------------------------- Auth plumbing -----------------------------
def serialize_user(u: dict) -> dict:
    return {
        "id": str(u["_id"]),
        "email": u["email"],
        "name": u.get("name"),
        "role": u.get("role"),
        "active": u.get("active", True),
        "patient_id": u.get("patient_id"),
    }


async def get_current_user(request: Request) -> dict:
    token = None
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        token = header[7:]
    if not token:
        token = request.query_params.get("auth")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = authlib.decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    try:
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    except Exception:
        user = None
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    return serialize_user(user)


def require_roles(*roles):
    async def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Not authorized")
        return user
    return dep


async def get_patient_record(user: dict) -> dict:
    if user["role"] != "patient" or not user.get("patient_id"):
        raise HTTPException(status_code=403, detail="Not a patient account")
    p = await db.patients.find_one({"id": user["patient_id"]}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Patient record not found")
    return p


async def require_verified_patient(user: dict = Depends(get_current_user)) -> dict:
    p = await get_patient_record(user)
    if p.get("verification_status") != "verified":
        raise HTTPException(status_code=403, detail="Your account is still pending verification by the clinic.")
    return p


async def notify_patient(patient_id: str, title: str, body: str):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "title": title,
        "body": body,
        "read": False,
        "created_at": now_iso(),
    })


# ----------------------------- Bodies -----------------------------
class RegisterBody(BaseModel):
    patient_type: str
    first_name: str
    last_name: str
    date_of_birth: str
    phone: str
    email: EmailStr
    password: str = Field(min_length=6)
    health_card_number: Optional[str] = None
    health_card_version: Optional[str] = None
    province: Optional[str] = None
    country: Optional[str] = None
    extra_info: Optional[str] = None


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class AppointmentBody(BaseModel):
    reason: str
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None
    alternative_date: Optional[str] = None
    alternative_time: Optional[str] = None
    patient_note: Optional[str] = None


class PrescriptionBody(BaseModel):
    medication_name: str
    strength: Optional[str] = None
    directions: Optional[str] = None
    requested_months: int = 1
    delivery_method: str = "pickup"
    pharmacy_id: Optional[str] = None
    new_pharmacy_details: Optional[str] = None
    patient_note: Optional[str] = None


class ImagingBody(BaseModel):
    imaging_type: str
    body_part: str
    reason: Optional[str] = None
    patient_note: Optional[str] = None


class MessageBody(BaseModel):
    category: str
    subject: Optional[str] = None
    body: str


class UpdateBody(BaseModel):
    internal_status: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    internal_note: Optional[str] = None
    action: Optional[str] = None
    staff_note: Optional[str] = None
    approved_date: Optional[str] = None
    approved_time: Optional[str] = None
    patient_reply: Optional[str] = None


class TaskBody(BaseModel):
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    recipient_role: str
    message: str


class VerifyBody(BaseModel):
    decision: str
    visita_patient_id: Optional[str] = None
    matched_patient_id: Optional[str] = None


# ----------------------------- Auth routes -----------------------------
@api.post("/auth/register")
async def register(body: RegisterBody):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    patient_id = str(uuid.uuid4())
    patient = {
        "id": patient_id, "visita_patient_id": None,
        "first_name": body.first_name.strip(), "last_name": body.last_name.strip(),
        "date_of_birth": body.date_of_birth, "health_card_number": body.health_card_number,
        "health_card_version": body.health_card_version, "phone": body.phone, "email": email,
        "province": body.province, "country": body.country, "extra_info": body.extra_info,
        "patient_type": body.patient_type, "verification_status": "pending",
        "active_status": True, "is_demo": False, "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.patients.insert_one({**patient})
    res = await db.users.insert_one({
        "email": email, "password_hash": authlib.hash_password(body.password),
        "name": f"{body.first_name} {body.last_name}".strip(), "role": "patient",
        "patient_id": patient_id, "active": True, "created_at": now_iso(),
    })
    uid = str(res.inserted_id)
    await audit("register", "patient", patient_id, {"id": uid, "name": patient["first_name"], "role": "patient"})
    token = authlib.create_access_token(uid, email, "patient")
    user = await db.users.find_one({"_id": res.inserted_id})
    return {"token": token, "user": serialize_user(user)}


@api.post("/auth/login")
async def login(body: LoginBody):
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not authlib.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="This account has been disabled. Contact the clinic.")
    token = authlib.create_access_token(str(user["_id"]), email, user["role"])
    return {"token": token, "user": serialize_user(user)}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    if user["role"] == "patient" and user.get("patient_id"):
        p = await db.patients.find_one({"id": user["patient_id"]}, {"_id": 0, "health_card_number": 0})
        return {"user": user, "patient": p}
    return {"user": user}


# ----------------------------- Settings & templates -----------------------------
@api.get("/settings/public")
async def public_settings():
    s = await db.settings.find_one({"id": "clinic"}, {"_id": 0})
    t = await db.templates.find_one({"id": "templates"}, {"_id": 0})
    return {"settings": s or {}, "templates": (t or {}).get("items", {})}


@api.get("/admin/settings")
async def get_settings(user: dict = Depends(require_roles("admin"))):
    s = await db.settings.find_one({"id": "clinic"}, {"_id": 0})
    t = await db.templates.find_one({"id": "templates"}, {"_id": 0})
    return {"settings": s or {}, "templates": (t or {}).get("items", {})}


@api.put("/admin/settings")
async def update_settings(payload: dict, user: dict = Depends(require_roles("admin"))):
    if "settings" in payload:
        await db.settings.update_one({"id": "clinic"}, {"$set": {**payload["settings"], "id": "clinic"}}, upsert=True)
    if "templates" in payload:
        await db.templates.update_one({"id": "templates"}, {"$set": {"id": "templates", "items": payload["templates"]}}, upsert=True)
    await audit("update_settings", "settings", "clinic", user)
    return {"ok": True}


# ----------------------------- Patient portal -----------------------------
@api.get("/portal/pharmacies")
async def portal_pharmacies(user: dict = Depends(get_current_user)):
    return await db.pharmacies.find({}, {"_id": 0}).to_list(200)


@api.post("/portal/appointments")
async def create_appointment(body: AppointmentBody, p: dict = Depends(require_verified_patient)):
    ref = await next_ref("APT")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        **body.model_dump(), "status": "requested", "staff_note": None,
        "approved_date": None, "approved_time": None, "assigned_to": None,
        "internal_notes": [], "history": [{"status": "requested", "at": now_iso(), "by": "patient"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.appointment_requests.insert_one({**doc})
    await audit("create", "appointment", doc["id"], {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="requested")
    doc.pop("_id", None)
    return doc


@api.post("/portal/prescriptions")
async def create_rx(body: PrescriptionBody, p: dict = Depends(require_verified_patient)):
    ref = await next_ref("RX")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        **body.model_dump(), "internal_status": "received", "assigned_to": None,
        "internal_notes": [], "history": [{"status": "received", "at": now_iso(), "by": "patient"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.prescription_requests.insert_one({**doc})
    await audit("create", "prescription", doc["id"], {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="received")
    doc.pop("_id", None)
    return doc


@api.post("/portal/imaging")
async def create_imaging(body: ImagingBody, p: dict = Depends(require_verified_patient)):
    ref = await next_ref("IMG")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        **body.model_dump(), "internal_status": "new", "assigned_to": None,
        "internal_notes": [], "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.imaging_requests.insert_one({**doc})
    await audit("create", "imaging", doc["id"], {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="new")
    doc.pop("_id", None)
    return doc


@api.post("/portal/messages")
async def create_message(body: MessageBody, p: dict = Depends(require_verified_patient)):
    ref = await next_ref("MSG")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        "category": body.category, "subject": body.subject, "body": body.body,
        "sender": "patient", "status": "new", "assigned_to": None,
        "thread": [{"from": "patient", "body": body.body, "at": now_iso()}],
        "internal_notes": [], "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.patient_messages.insert_one({**doc})
    await audit("create", "message", doc["id"], {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="new")
    doc.pop("_id", None)
    return doc


@api.get("/portal/overview")
async def portal_overview(user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    pid = p["id"]
    appts = await db.appointment_requests.find({"patient_id": pid}, {"_id": 0}).to_list(200)
    rxs = await db.prescription_requests.find({"patient_id": pid}, {"_id": 0}).to_list(200)
    imgs = await db.imaging_requests.find({"patient_id": pid}, {"_id": 0}).to_list(200)
    msgs = await db.patient_messages.find({"patient_id": pid}, {"_id": 0}).to_list(200)
    refs = await db.patient_referrals.find({"patient_id": pid}, {"_id": 0}).to_list(200)
    notes = await db.notifications.find({"patient_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(50)

    def pa(items, key, mapping):
        out = []
        for it in items:
            out.append({
                "id": it["id"], "ref_number": it.get("ref_number"), "type": key,
                "created_at": it["created_at"], "updated_at": it.get("updated_at"),
                "status": mapping.get(it.get("internal_status") or it.get("status"), "Received"),
                "summary": it.get("reason") or it.get("medication_name") or it.get("subject") or it.get("body_part") or "",
            })
        return out

    requests = (pa(appts, "Appointment", APPT_PATIENT_STATUS) + pa(rxs, "Prescription", RX_PATIENT_STATUS)
                + pa(imgs, "Imaging", IMG_PATIENT_STATUS) + pa(msgs, "Message", MSG_PATIENT_STATUS))
    requests.sort(key=lambda x: x["created_at"], reverse=True)
    referrals = [{"id": r["id"], "specialty": r.get("specialty"),
                  "status": r.get("patient_visible_status"), "last_updated": r.get("updated_at")} for r in refs]
    return {
        "patient": {"first_name": p["first_name"], "last_name": p["last_name"],
                    "patient_type": p["patient_type"], "verification_status": p["verification_status"]},
        "requests": requests,
        "appointments": [{"id": a["id"], "ref_number": a["ref_number"], "reason": a["reason"],
                          "status": APPT_PATIENT_STATUS.get(a["status"]), "preferred_date": a.get("preferred_date"),
                          "approved_date": a.get("approved_date"), "approved_time": a.get("approved_time"),
                          "staff_note": a.get("staff_note"), "created_at": a["created_at"]} for a in appts],
        "prescriptions": [{"id": r["id"], "ref_number": r["ref_number"], "medication_name": r["medication_name"],
                           "strength": r.get("strength"), "status": RX_PATIENT_STATUS.get(r["internal_status"]),
                           "created_at": r["created_at"]} for r in rxs],
        "imaging": [{"id": i["id"], "ref_number": i["ref_number"], "imaging_type": i["imaging_type"],
                     "body_part": i["body_part"], "status": IMG_PATIENT_STATUS.get(i["internal_status"]),
                     "created_at": i["created_at"]} for i in imgs],
        "messages": [{"id": m["id"], "ref_number": m["ref_number"], "category": m["category"], "subject": m.get("subject"),
                      "thread": m.get("thread", []), "status": MSG_PATIENT_STATUS.get(m["status"]),
                      "created_at": m["created_at"]} for m in msgs],
        "referrals": referrals,
        "notifications": notes,
    }


@api.post("/portal/notifications/read")
async def mark_notes_read(user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    await db.notifications.update_many({"patient_id": p["id"]}, {"$set": {"read": True}})
    return {"ok": True}


# ----------------------------- Internal counters -----------------------------
@api.get("/internal/counters")
async def counters(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    if user["role"] == "physician":
        rx = await db.prescription_requests.count_documents({"internal_status": "waiting_physician"})
        img = await db.imaging_requests.count_documents({"internal_status": "waiting_physician"})
        pmsg = await db.patient_messages.count_documents({"status": "waiting_physician"})
        dmsg = await db.internal_messages.count_documents({"recipient_role": "physician", "status": {"$ne": "completed"}})
        return {"role": "physician", "counters": {"rx": rx, "imaging": img, "messages": pmsg + dmsg}}
    rx = await db.prescription_requests.count_documents({"internal_status": {"$in": RX_ACTIVE}})
    referrals = await db.referrals.count_documents({"ready_to_fax": True, "faxed": False})
    img = await db.imaging_requests.count_documents({"internal_status": {"$in": IMG_ACTIVE}})
    msgs = await db.patient_messages.count_documents({"status": {"$in": MSG_ACTIVE}})
    appts = await db.appointment_requests.count_documents({"status": "requested"})
    tasks = await db.internal_messages.count_documents({"recipient_role": "staff", "status": {"$ne": "completed"}})
    pending_verif = await db.patients.count_documents({"verification_status": "pending", "active_status": True})
    return {"role": user["role"], "counters": {
        "rx": rx, "referrals": referrals, "imaging": img, "messages": msgs,
        "appointments": appts, "doctor_tasks": tasks, "verifications": pending_verif,
    }}


def _search_filter(q: Optional[str], fields):
    if not q:
        return {}
    return {"$or": [{f: {"$regex": q, "$options": "i"}} for f in fields]}


# ----------------------------- Generic request updater -----------------------------
async def _update_request(coll, entity, item_id, body: UpdateBody, user, status_field, notify_title):
    doc = await coll.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    old = doc.get(status_field)
    updates = {"updated_at": now_iso()}
    notify = False
    if body.action == "send_to_physician":
        updates[status_field] = "waiting_physician"
    elif body.action == "review":
        updates[status_field] = "under_review"
    elif body.action == "complete":
        updates[status_field] = "completed"
        updates["completed_at"] = now_iso()
        updates["completed_by"] = user["name"]
        notify = True
    elif body.action == "appointment_required":
        updates[status_field] = "appointment_required"
        updates["completed_at"] = now_iso()
        notify = True
    elif body.internal_status:
        updates[status_field] = body.internal_status
    if body.assigned_to is not None:
        updates["assigned_to"] = body.assigned_to
    mongo_update = {"$set": updates}
    if body.internal_note:
        mongo_update["$push"] = {"internal_notes": {"by": user["name"], "note": body.internal_note, "at": now_iso()}}
    await coll.update_one({"id": item_id}, mongo_update)
    await audit("update", entity, item_id, user, old_status=old, new_status=updates.get(status_field, old))
    if notify:
        await notify_patient(doc["patient_id"], notify_title, f"{notify_title} Please log in to your Patient Portal.")
    return await coll.find_one({"id": item_id}, {"_id": 0})


# ----------------------------- Prescriptions -----------------------------
@api.get("/internal/prescriptions")
async def rx_queue(q: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if user["role"] == "physician":
        query["internal_status"] = "waiting_physician"
    elif status:
        query["internal_status"] = status
    query.update(_search_filter(q, ["patient_name", "medication_name", "ref_number"]))
    return await db.prescription_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.patch("/internal/prescriptions/{item_id}")
async def rx_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await _update_request(db.prescription_requests, "prescription", item_id, body, user,
                                 "internal_status", "Your prescription request has been updated.")


# ----------------------------- Imaging -----------------------------
@api.get("/internal/imaging")
async def img_queue(q: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if user["role"] == "physician":
        query["internal_status"] = "waiting_physician"
    elif status:
        query["internal_status"] = status
    query.update(_search_filter(q, ["patient_name", "body_part", "ref_number"]))
    return await db.imaging_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.patch("/internal/imaging/{item_id}")
async def img_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await _update_request(db.imaging_requests, "imaging", item_id, body, user,
                                 "internal_status", "Your imaging request has been updated.")


# ----------------------------- Messages -----------------------------
@api.get("/internal/messages")
async def msg_queue(q: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if user["role"] == "physician":
        query["status"] = "waiting_physician"
    elif status:
        query["status"] = status
    query.update(_search_filter(q, ["patient_name", "subject", "ref_number", "body"]))
    return await db.patient_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.patch("/internal/messages/{item_id}")
async def msg_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.patient_messages.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    updates = {"updated_at": now_iso()}
    push = {}
    old_status = doc.get("status")
    if body.action == "send_to_physician":
        updates["status"] = "waiting_physician"
    elif body.action == "complete":
        updates.update({"status": "completed", "completed_at": now_iso(), "completed_by": user["name"]})
    elif body.status:
        updates["status"] = body.status
    if body.assigned_to is not None:
        updates["assigned_to"] = body.assigned_to
    if body.internal_note:
        push["internal_notes"] = {"by": user["name"], "note": body.internal_note, "at": now_iso()}
    if body.patient_reply:
        push["thread"] = {"from": "clinic", "body": body.patient_reply, "at": now_iso()}
    mongo_update = {"$set": updates}
    if push:
        mongo_update["$push"] = push
    await db.patient_messages.update_one({"id": item_id}, mongo_update)
    await audit("update", "message", item_id, user, old_status=old_status, new_status=updates.get("status", old_status))
    if updates.get("status") == "completed" or body.patient_reply:
        await notify_patient(doc["patient_id"], "Message update",
                             "The clinic has responded to your message. Please log in to your Patient Portal.")
    return await db.patient_messages.find_one({"id": item_id}, {"_id": 0})


# ----------------------------- Appointments -----------------------------
@api.get("/internal/appointments")
async def appt_queue(q: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if status:
        query["status"] = status
    query.update(_search_filter(q, ["patient_name", "reason", "ref_number"]))
    return await db.appointment_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.patch("/internal/appointments/{item_id}")
async def appt_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.appointment_requests.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    old = doc.get("status")
    updates = {"updated_at": now_iso()}
    notify = None
    if body.action == "approve":
        updates.update({"status": "confirmed", "approved_date": body.approved_date,
                        "approved_time": body.approved_time, "completed_at": now_iso()})
        notify = "Your appointment request has been approved."
    elif body.action == "suggest":
        updates.update({"status": "suggested", "staff_note": body.staff_note})
        notify = "There is an update on your appointment request. Please log in to your Patient Portal."
    elif body.action == "more_info":
        updates.update({"status": "more_info_requested", "staff_note": body.staff_note})
        notify = "We need a little more information about your appointment request. Please log in to your Patient Portal."
    elif body.action == "decline":
        updates.update({"status": "declined", "staff_note": body.staff_note, "completed_at": now_iso()})
        notify = "There is an update on your appointment request. Please log in to your Patient Portal."
    if body.assigned_to is not None:
        updates["assigned_to"] = body.assigned_to
    mongo_update = {"$set": updates, "$push": {"history": {"status": updates.get("status", old), "at": now_iso(), "by": user["name"]}}}
    if body.internal_note:
        mongo_update["$push"]["internal_notes"] = {"by": user["name"], "note": body.internal_note, "at": now_iso()}
    await db.appointment_requests.update_one({"id": item_id}, mongo_update)
    await audit("update", "appointment", item_id, user, old_status=old, new_status=updates.get("status", old))
    if notify:
        await notify_patient(doc["patient_id"], "Appointment update", notify)
    return await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})


# ----------------------------- Internal tasks / intercom -----------------------------
@api.get("/internal/tasks")
async def tasks_queue(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {"recipient_role": "physician"} if user["role"] == "physician" else {"recipient_role": "staff"}
    return await db.internal_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.post("/internal/tasks")
async def create_task(body: TaskBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    ref = await next_ref("TSK")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": body.patient_id, "patient_name": body.patient_name,
        "sender_user_id": user["id"], "sender_name": user["name"], "sender_role": user["role"],
        "recipient_role": body.recipient_role,
        "direction": "task_for_staff" if body.recipient_role == "staff" else "message_for_doctor",
        "message": body.message, "status": "new",
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None, "completed_by": None,
    }
    await db.internal_messages.insert_one({**doc})
    await audit("create", "internal_task", doc["id"], user, new_status="new")
    doc.pop("_id", None)
    return doc


@api.patch("/internal/tasks/{item_id}")
async def update_task(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.internal_messages.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    old = doc.get("status")
    updates = {"updated_at": now_iso()}
    if body.action == "complete":
        updates.update({"status": "completed", "completed_at": now_iso(), "completed_by": user["name"]})
    elif body.action == "send_to_physician":
        updates.update({"recipient_role": "physician", "direction": "message_for_doctor", "status": "open"})
    elif body.status:
        updates["status"] = body.status
    await db.internal_messages.update_one({"id": item_id}, {"$set": updates})
    await audit("update", "internal_task", item_id, user, old_status=old, new_status=updates.get("status", old))
    return await db.internal_messages.find_one({"id": item_id}, {"_id": 0})


# ----------------------------- Referral Ready-to-Fax -----------------------------
@api.get("/internal/referrals")
async def referrals_queue(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await db.referrals.find({"ready_to_fax": True, "faxed": False}, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.get("/internal/referrals/history")
async def referrals_history(q: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {"faxed": True}
    query.update(_search_filter(q, ["patient_name", "specialty", "specialist_name", "ref_number"]))
    return await db.referrals.find(query, {"_id": 0}).sort("faxed_at", -1).to_list(500)


@api.post("/internal/referrals")
async def upload_referral(
    file: UploadFile = File(...),
    patient_name: str = Form(""),
    patient_id: str = Form(""),
    specialty: str = Form(""),
    specialist_name: str = Form(""),
    clinic_name: str = Form(""),
    fax_number: str = Form(""),
    user: dict = Depends(require_roles("physician", "admin")),
):
    if (file.content_type or "").lower() != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted for referral drop-off.")
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 15 MB.")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    path = f"{storage.APP_NAME}/referrals/{uuid.uuid4()}.pdf"
    result = storage.put_object(path, data, "application/pdf")
    ref = await next_ref("REF")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "patient_id": patient_id or None, "patient_name": patient_name or "Unspecified patient",
        "specialty": specialty or None, "specialist_name": specialist_name or None,
        "clinic_name": clinic_name or None, "fax_number": fax_number or None,
        "referral_date": now_iso()[:10], "storage_path": result["path"], "original_filename": file.filename,
        "ready_to_fax": True, "faxed": False, "faxed_at": None, "faxed_by": None,
        "uploaded_by": user["name"], "uploaded_by_id": user["id"],
        "created_at": now_iso(), "updated_at": now_iso(), "is_deleted": False,
    }
    await db.referrals.insert_one({**doc})
    await audit("upload_referral", "referral", doc["id"], user, new_status="ready_to_fax")
    doc.pop("_id", None)
    return doc


@api.get("/internal/referrals/{item_id}/download")
async def download_referral(item_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.referrals.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    data, _ = storage.get_object(doc["storage_path"])
    name = doc.get("patient_name", "Patient").replace(",", "").replace(" ", "_")
    spec = (doc.get("specialty") or "Referral").replace(" ", "_")
    filename = f"Referral_{name}_{spec}_{doc.get('referral_date')}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@api.post("/internal/referrals/{item_id}/fax")
async def mark_faxed(item_id: str, body: UpdateBody, user: dict = Depends(require_roles("staff", "admin"))):
    doc = await db.referrals.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    if doc.get("faxed"):
        raise HTTPException(status_code=400, detail="This referral has already been faxed.")
    await db.referrals.update_one({"id": item_id}, {"$set": {
        "faxed": True, "ready_to_fax": False, "faxed_at": now_iso(), "faxed_by": user["name"], "updated_at": now_iso(),
    }})
    await audit("mark_faxed", "referral", item_id, user, old_status="ready_to_fax", new_status="faxed",
                meta={"fax_number": doc.get("fax_number")})
    return await db.referrals.find_one({"id": item_id}, {"_id": 0})


# ----------------------------- Patient verification -----------------------------
@api.get("/internal/verifications")
async def verifications(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pending = await db.patients.find({"verification_status": "pending", "active_status": True}).sort("created_at", -1).to_list(500)
    out = []
    for p in pending:
        out.append({
            "id": p["id"], "first_name": p["first_name"], "last_name": p["last_name"],
            "date_of_birth": p["date_of_birth"], "phone": p.get("phone"), "email": p.get("email"),
            "patient_type": p["patient_type"], "province": p.get("province"), "country": p.get("country"),
            "extra_info": p.get("extra_info"), "created_at": p["created_at"],
            "health_card_masked": mask_hcn(p.get("health_card_number")),
        })
    return out


@api.post("/internal/verifications/{patient_id}")
async def verify_patient(patient_id: str, body: VerifyBody, user: dict = Depends(require_roles("staff", "admin"))):
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    updates = {"verification_status": body.decision, "updated_at": now_iso(),
               "verified_by": user["name"], "verified_at": now_iso()}
    if body.visita_patient_id:
        updates["visita_patient_id"] = body.visita_patient_id
    await db.patients.update_one({"id": patient_id}, {"$set": updates})
    await audit("verify_patient", "patient", patient_id, user, new_status=body.decision)
    await notify_patient(patient_id, "Account update",
                         "Your portal account has been reviewed. Please log in to your Patient Portal.")
    return {"ok": True}


# ----------------------------- Admin / patients -----------------------------
@api.get("/admin/users")
async def list_users(user: dict = Depends(require_roles("admin"))):
    items = await db.users.find({"role": {"$in": ["staff", "physician", "admin"]}}).sort("created_at", 1).to_list(200)
    return [serialize_user(u) for u in items]


@api.get("/internal/patients")
async def search_patients(q: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {"active_status": True}
    if q:
        query["$or"] = [{"first_name": {"$regex": q, "$options": "i"}},
                        {"last_name": {"$regex": q, "$options": "i"}},
                        {"visita_patient_id": {"$regex": q, "$options": "i"}}]
    return await db.patients.find(query, {"_id": 0, "health_card_number": 0}).limit(50).to_list(50)


@api.get("/")
async def root():
    return {"service": "VISITA Web Portal", "status": "ok"}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.patients.create_index("id")
    await db.referrals.create_index([("ready_to_fax", 1), ("faxed", 1)])
    try:
        storage.init_storage()
        logger.info("Storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    await seed_all(db, authlib)
    logger.info("Startup complete")


@app.on_event("shutdown")
async def shutdown():
    pass
