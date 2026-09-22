from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from bson import ObjectId
from fastapi import (APIRouter, BackgroundTasks, Depends, FastAPI, File, Form,
                     Header, HTTPException, Request, Response, UploadFile)
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.cors import CORSMiddleware

import auth as authlib
import availability as avail_mod
import directory as directory_mod
import email_service
import notifications as notify_svc
import storage
from db import (APPT_PATIENT_STATUS, BLD_ACTIVE, BLD_PATIENT_STATUS, IMG_ACTIVE,
                IMG_PATIENT_STATUS, MSG_ACTIVE, MSG_PATIENT_STATUS, RX_ACTIVE,
                RX_PATIENT_STATUS, audit, db, mask_hcn, next_ref, now_iso)
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
        "email": u.get("email"),
        "username": u.get("username"),
        "name": u.get("name"),
        "role": u.get("role"),
        "active": u.get("active", True),
        "patient_id": u.get("patient_id"),
        "must_change_password": u.get("must_change_password", False),
        "mfa_enabled": u.get("mfa_enabled", False),
        "pharmacy_id": u.get("pharmacy_id"),
        "pharmacy_name": u.get("pharmacy_name"),
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
    identifier: Optional[str] = None
    email: Optional[str] = None
    password: str


class ChangePwBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class ForgotBody(BaseModel):
    identifier: str


class ResetBody(BaseModel):
    identifier: str
    code: str
    new_password: str = Field(min_length=8)


class AppointmentBody(BaseModel):
    reason: str
    options: List[dict] = []  # ranked slots [{date,time,label,display}] max 3
    patient_note: Optional[str] = None
    appointment_type: Optional[str] = None  # IN_CLINIC | TELEPHONE


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


class BloodworkBody(BaseModel):
    reason: str
    patient_note: Optional[str] = Field(default=None, max_length=50)


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
    confirmed_date: Optional[str] = None
    confirmed_time: Optional[str] = None
    confirmed_display: Optional[str] = None
    offered_slots: Optional[List[dict]] = None
    patient_reply: Optional[str] = None
    void_reason: Optional[str] = None


class SelectSlotBody(BaseModel):
    index: int


class BookApptBody(BaseModel):
    source_type: str          # prescription | imaging | bloodwork | message
    source_id: str
    reason: Optional[str] = None
    date: str
    time: str
    label: Optional[str] = None
    display: Optional[str] = None


class ImportApptItem(BaseModel):
    date: str
    time: str
    patient_name: str
    label: Optional[str] = None
    reason: Optional[str] = None


class ImportBreakItem(BaseModel):
    date: str
    start: str
    end: str
    reason: Optional[str] = "Break"


class ImportApptBody(BaseModel):
    appointments: List[ImportApptItem] = []
    breaks: List[ImportBreakItem] = []
    dry_run: bool = False


class LinkPatientBody(BaseModel):
    directory_id: str


class TaskBody(BaseModel):
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    recipient_role: str
    message: str


class VerifyBody(BaseModel):
    decision: str
    visita_patient_id: Optional[str] = None
    matched_patient_id: Optional[str] = None


class ReturnRequestBody(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: str
    health_card_number: Optional[str] = None
    phone: str
    email: EmailStr
    address: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    patient_message: Optional[str] = None
    preferred_language: str = "en"


class NewPatientRequestBody(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: str
    phone: str
    email: EmailStr
    city: Optional[str] = None
    province: Optional[str] = None
    country: Optional[str] = None
    patient_message: Optional[str] = None
    preferred_language: str = "en"


class ApplicationUpdateBody(BaseModel):
    internal_status: Optional[str] = None
    action: Optional[str] = None       # send_to_physician | accept | not_accepting | waitlist | review | close
    internal_note: Optional[str] = None
    staff_message: Optional[str] = None  # neutral, approved message to relay to the patient


# ----------------------------- Patient application helpers -----------------------------
APP_PATIENT_STATUS = {
    "REQUEST_RECEIVED": "Request Received",
    "WAITING_LIST": "On Waiting List",
    "UNDER_REVIEW": "Under Review",
    "SENT_TO_PHYSICIAN": "Under Review",
    "ACCEPTED": "Accepted",
    "NOT_ACCEPTING": "Request Closed",
    "CLOSED": "Request Closed",
}
APP_ACTIVE = ["REQUEST_RECEIVED", "WAITING_LIST", "UNDER_REVIEW", "SENT_TO_PHYSICIAN"]


async def get_template(key: str, default: str = "") -> str:
    t = await db.templates.find_one({"id": "templates"}, {"_id": 0})
    return (t or {}).get("items", {}).get(key, default)


_DISP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date_display(d: Optional[str]) -> str:
    """ISO 'YYYY-MM-DD' -> 'YYYY Mon - DD' for user-facing fallbacks."""
    try:
        y, m, dd = str(d)[:10].split("-")
        return f"{y} {_DISP_MONTHS[int(m) - 1]} - {dd}"
    except Exception:
        return str(d or "")


# ----------------------------- Late-cancellation policy -----------------------------
LATE_FEE_AMOUNT = 40
SELF_SERVICE_CUTOFF_HOURS = 24
WITHIN_24H_MSG = (
    "Online cancellation and rescheduling are no longer available because this appointment is within 24 hours. "
    "Late cancellations are subject to a $40 fee. If you need to cancel or reschedule, please contact Dr. Aguayo's "
    "office. The outstanding fee must be resolved with the clinic before a new appointment can be scheduled.")
OUTSTANDING_FEE_MSG = (
    "Please contact the clinic to resolve the outstanding late-cancellation fee before scheduling another appointment.")


def _hours_until(appt) -> Optional[float]:
    """Hours (America/Toronto aware) until the confirmed appointment, or None."""
    dt = notify_svc.confirmed_dt_utc(appt)
    if not dt:
        return None
    return (dt - datetime.now(timezone.utc)).total_seconds() / 3600.0


async def _has_outstanding_fee(patient_id: str) -> bool:
    return bool(await db.appointment_requests.find_one(
        {"patient_id": patient_id, "late_fee.status": "outstanding"}))


# ----------------------------- Auth routes -----------------------------
@api.post("/auth/register")
async def register(body: RegisterBody):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    # Directory-assisted matching for current-patient registrations
    match = await directory_mod.match_registration(
        db, body.first_name, body.last_name, body.date_of_birth, body.health_card_number)

    # FORMER_CLOSED match: do NOT create a current-patient portal account.
    # Route the person to the neutral re-establish-care request flow instead.
    if match["outcome"] == directory_mod.FORMER_MATCH:
        msg = await get_template("former_patient_detected")
        return {
            "former_detected": True,
            "message": msg,
            "prefill": {
                "first_name": body.first_name, "last_name": body.last_name,
                "date_of_birth": body.date_of_birth, "email": email,
                "phone": body.phone, "health_card_number": body.health_card_number,
                "province": body.province,
            },
        }

    # Duplicate-account guard: an ACTIVE directory record already linked to a portal patient
    if match.get("outcome") == directory_mod.ACTIVE_MATCH and match.get("matched_id"):
        d = await db.patient_directory.find_one({"id": match["matched_id"]})
        if d and d.get("linked_patient_id"):
            raise HTTPException(
                status_code=409,
                detail="It looks like you may already have a portal account. Please sign in or use Forgot Password, or contact the clinic.")

    review_queue = match["outcome"]
    patient_id = str(uuid.uuid4())
    patient = {
        "id": patient_id, "visita_patient_id": None,
        "first_name": body.first_name.strip(), "last_name": body.last_name.strip(),
        "date_of_birth": body.date_of_birth, "health_card_number": body.health_card_number,
        "health_card_version": body.health_card_version, "phone": body.phone, "email": email,
        "province": body.province, "country": body.country, "extra_info": body.extra_info,
        "patient_type": body.patient_type, "verification_status": "pending",
        "portal_status": "PENDING_VERIFICATION",
        "review_queue": review_queue, "directory_match": match,
        "matched_directory_id": match.get("matched_id"),
        "preferred_language": "en",
        "active_status": True, "is_demo": False, "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.patients.insert_one({**patient})
    res = await db.users.insert_one({
        "email": email, "password_hash": authlib.hash_password(body.password),
        "name": f"{body.first_name} {body.last_name}".strip(), "role": "patient",
        "patient_id": patient_id, "active": True, "created_at": now_iso(),
    })
    uid = str(res.inserted_id)
    await audit("register", "patient", patient_id, {"id": uid, "name": patient["first_name"], "role": "patient"},
                meta={"review_queue": review_queue, "match_outcome": match["outcome"]})
    if match.get("candidates"):
        await audit("directory_match_suggested", "patient", patient_id,
                    {"id": uid, "name": patient["first_name"], "role": "patient"},
                    meta={"outcome": match["outcome"], "candidate_count": len(match["candidates"])})
    token = authlib.create_access_token(uid, email, "patient")
    user = await db.users.find_one({"_id": res.inserted_id})
    return {"token": token, "user": serialize_user(user)}


@api.post("/applications/return-request")
async def return_request(body: ReturnRequestBody):
    match = await directory_mod.match_registration(
        db, body.first_name, body.last_name, body.date_of_birth, body.health_card_number)
    ref = await next_ref("APP")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "application_type": "former_return",
        "first_name": body.first_name.strip(), "last_name": body.last_name.strip(),
        "date_of_birth": body.date_of_birth, "health_card_number": body.health_card_number,
        "phone": body.phone, "email": body.email.lower(), "address": body.address,
        "city": body.city, "province": body.province, "postal_code": body.postal_code,
        "patient_message": body.patient_message, "preferred_language": body.preferred_language or "en",
        "directory_match": match, "matched_directory_id": match.get("matched_id"),
        "internal_status": "REQUEST_RECEIVED", "internal_notes": [],
        "accepted_by": None, "accepted_at": None, "previous_status": None, "new_status": None,
        "history": [{"status": "REQUEST_RECEIVED", "at": now_iso(), "by": "patient"}],
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.patient_applications.insert_one({**doc})
    await audit("create", "patient_application", doc["id"],
                {"id": None, "name": f"{body.first_name} {body.last_name}", "role": "patient"},
                new_status="REQUEST_RECEIVED", meta={"type": "former_return"})
    return {"ok": True, "ref_number": ref, "status": APP_PATIENT_STATUS["REQUEST_RECEIVED"],
            "message": await get_template("reestablish_care_confirmation")}


@api.post("/applications/new-patient")
async def new_patient_request(body: NewPatientRequestBody):
    ref = await next_ref("APP")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "application_type": "new_patient",
        "first_name": body.first_name.strip(), "last_name": body.last_name.strip(),
        "date_of_birth": body.date_of_birth, "health_card_number": None,
        "phone": body.phone, "email": body.email.lower(), "address": None,
        "city": body.city, "province": body.province, "country": body.country,
        "patient_message": body.patient_message, "preferred_language": body.preferred_language or "en",
        "directory_match": None, "matched_directory_id": None,
        "internal_status": "REQUEST_RECEIVED", "internal_notes": [],
        "accepted_by": None, "accepted_at": None, "previous_status": None, "new_status": None,
        "history": [{"status": "REQUEST_RECEIVED", "at": now_iso(), "by": "patient"}],
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.patient_applications.insert_one({**doc})
    await audit("create", "patient_application", doc["id"],
                {"id": None, "name": f"{body.first_name} {body.last_name}", "role": "patient"},
                new_status="REQUEST_RECEIVED", meta={"type": "new_patient"})
    return {"ok": True, "ref_number": ref, "status": APP_PATIENT_STATUS["REQUEST_RECEIVED"],
            "message": await get_template("new_patient_request_confirmation")}


@api.post("/auth/login")
async def login(body: LoginBody):
    ident = (body.identifier or body.email or "").strip()
    if not ident:
        raise HTTPException(status_code=400, detail="Please enter your email or username.")
    user = await db.users.find_one({"$or": [
        {"email": ident.lower()},
        {"username": {"$regex": f"^{re.escape(ident)}$", "$options": "i"}},
    ]})
    if not user or not authlib.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials. Please check your email/username and password.")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="This account has been disabled. Contact the clinic.")
    token = authlib.create_access_token(str(user["_id"]), user.get("email") or user.get("username"), user["role"])
    return {"token": token, "user": serialize_user(user)}


@api.post("/auth/change-password")
async def change_password(body: ChangePwBody, user: dict = Depends(get_current_user)):
    doc = await db.users.find_one({"_id": ObjectId(user["id"])})
    if not doc or not authlib.verify_password(body.current_password, doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Your current password is incorrect.")
    if authlib.verify_password(body.new_password, doc["password_hash"]):
        raise HTTPException(status_code=400, detail="New password must be different from the current password.")
    await db.users.update_one({"_id": doc["_id"]}, {"$set": {
        "password_hash": authlib.hash_password(body.new_password),
        "must_change_password": False,
        "password_changed_at": now_iso(),
    }})
    await audit("change_password", "user", user["id"], user)
    return {"ok": True}


async def _find_by_identifier(ident: str):
    ident = (ident or "").strip()
    if not ident:
        return None
    return await db.users.find_one({"$or": [
        {"email": ident.lower()},
        {"username": {"$regex": f"^{re.escape(ident)}$", "$options": "i"}},
    ]})


@api.post("/auth/forgot-password")
async def forgot_password(body: ForgotBody):
    generic = {"ok": True, "message": "If an account matches, a verification code has been sent to the email on file."}
    user = await _find_by_identifier(body.identifier)
    if not user or not user.get("email"):
        return generic
    code = f"{secrets.randbelow(1000000):06d}"
    await db.password_resets.update_one({"user_id": str(user["_id"])}, {"$set": {
        "user_id": str(user["_id"]),
        "code_hash": authlib.hash_password(code),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "attempts": 0,
        "created_at": now_iso(),
    }}, upsert=True)
    try:
        await email_service.send_email(
            to=user["email"],
            subject="Your VISITA password reset code",
            html=email_service.reset_code_html(user.get("name"), code),
        )
    except Exception:
        logger.error("Failed to send reset email")
        raise HTTPException(status_code=502, detail="We couldn't send the email right now. Please try again shortly.")
    await audit("forgot_password", "user", str(user["_id"]),
                {"id": str(user["_id"]), "name": user.get("name"), "role": user.get("role")})
    return generic


@api.post("/auth/reset-password")
async def reset_password(body: ResetBody):
    user = await _find_by_identifier(body.identifier)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    rec = await db.password_resets.find_one({"user_id": str(user["_id"])})
    if not rec:
        raise HTTPException(status_code=400, detail="No active reset request. Please request a new code.")
    if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
        await db.password_resets.delete_one({"user_id": str(user["_id"])})
        raise HTTPException(status_code=400, detail="Your code has expired. Please request a new one.")
    if rec.get("attempts", 0) >= 5:
        await db.password_resets.delete_one({"user_id": str(user["_id"])})
        raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code.")
    if not authlib.verify_password(body.code.strip(), rec["code_hash"]):
        await db.password_resets.update_one({"user_id": str(user["_id"])}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {
        "password_hash": authlib.hash_password(body.new_password),
        "must_change_password": False,
        "password_changed_at": now_iso(),
    }})
    await db.password_resets.delete_one({"user_id": str(user["_id"])})
    await audit("reset_password", "user", str(user["_id"]),
                {"id": str(user["_id"]), "name": user.get("name"), "role": user.get("role")})
    return {"ok": True}


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


async def get_availability_doc():
    doc = await db.settings.find_one({"id": "availability"}, {"_id": 0})
    return doc or avail_mod.DEFAULT_AVAILABILITY


@api.post("/portal/appointments")
async def create_appointment(body: AppointmentBody, p: dict = Depends(require_verified_patient)):
    if await _has_outstanding_fee(p["id"]):
        raise HTTPException(status_code=403, detail=OUTSTANDING_FEE_MSG)
    options = [o for o in (body.options or []) if o.get("date") and o.get("time")][:3]
    if not options:
        raise HTTPException(status_code=400, detail="Please choose at least one preferred appointment time.")
    avail = await get_availability_doc()
    for o in options:
        if not avail_mod.is_within(avail, o.get("date"), o.get("time")):
            raise HTTPException(status_code=400, detail="A selected time is outside the clinic's available hours.")
        if avail_mod.is_past_slot(avail, o.get("date"), o.get("time")):
            raise HTTPException(status_code=400, detail="A selected time is in the past. Please choose an upcoming time.")
    ref = await next_ref("APT")
    opt1 = options[0]
    appt_type = body.appointment_type if body.appointment_type in ("IN_CLINIC", "TELEPHONE") else None
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        "reason": body.reason, "patient_note": body.patient_note,
        "appointment_type": appt_type,
        "preferred_options": options,
        "preferred_date": opt1.get("date"), "preferred_time": opt1.get("label") or opt1.get("time"),
        "status": "requested", "staff_note": None,
        "offered_slots": [], "selected_slot": None,
        "confirmed_date": None, "confirmed_time": None, "confirmed_display": None,
        "approved_by": None, "approved_at": None, "assigned_to": None,
        "internal_notes": [], "history": [{"status": "requested", "at": now_iso(), "by": "patient"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.appointment_requests.insert_one({**doc})
    await audit("create", "appointment", doc["id"], {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="requested")
    doc.pop("_id", None)
    return doc


@api.post("/portal/appointments/{item_id}/select")
async def select_slot(item_id: str, body: SelectSlotBody, user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    doc = await db.appointment_requests.find_one({"id": item_id, "patient_id": p["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    if doc.get("status") != "alternatives_offered":
        raise HTTPException(status_code=400, detail="This request is not awaiting a time selection.")
    slots = doc.get("offered_slots") or []
    if body.index < 0 or body.index >= len(slots):
        raise HTTPException(status_code=400, detail="Invalid option selected.")
    slot = slots[body.index]
    avail = await get_availability_doc()
    if not avail_mod.is_within(avail, slot.get("date"), slot.get("time")):
        raise HTTPException(status_code=409, detail="That time is no longer available. Please contact the clinic.")
    if avail_mod.is_past_slot(avail, slot.get("date"), slot.get("time")):
        raise HTTPException(status_code=409, detail="That time is in the past. Please contact the clinic.")
    updates = {
        "status": "confirmed", "selected_slot": slot,
        "confirmed_date": slot.get("date"), "confirmed_time": slot.get("label") or slot.get("time"),
        "confirmed_slot_time": avail_mod._norm_time(slot.get("time") or ""),
        "confirmed_display": slot.get("display"), "approved_by": "Patient selection",
        "approved_at": now_iso(), "completed_at": now_iso(), "updated_at": now_iso(),
    }
    await db.appointment_requests.update_one({"id": item_id}, {
        "$set": updates,
        "$push": {"history": {"status": "confirmed", "at": now_iso(), "by": "patient-selection"}},
    })
    confirmed = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    await audit("patient_selected_slot", "appointment", item_id, {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="confirmed")
    await notify_svc.appointment_confirmed(db, confirmed)
    return confirmed


class PatientRescheduleBody(BaseModel):
    date: str
    time: str
    label: Optional[str] = None
    display: Optional[str] = None


@api.post("/portal/appointments/{item_id}/cancel")
async def patient_cancel_appointment(item_id: str, user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    appt = await db.appointment_requests.find_one({"id": item_id, "patient_id": p["id"]})
    if not appt:
        raise HTTPException(status_code=404, detail="Not found")
    if appt.get("status") not in ("confirmed", "rescheduled"):
        raise HTTPException(status_code=400, detail="This appointment can't be cancelled online.")
    hrs = _hours_until(appt)
    if hrs is None or hrs < SELF_SERVICE_CUTOFF_HOURS:
        raise HTTPException(status_code=403, detail=WITHIN_24H_MSG)
    await db.appointment_requests.update_one({"id": item_id}, {
        "$set": {"status": "cancelled", "cancelled_by": "patient", "cancelled_at": now_iso(),
                 "completed_at": now_iso(), "updated_at": now_iso()},
        "$push": {"history": {"status": "cancelled", "at": now_iso(), "by": "patient"}}})
    await audit("patient_cancel", "appointment", item_id,
                {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="cancelled")
    fresh = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    await notify_svc.appointment_cancelled(db, fresh)
    return {"ok": True}


@api.post("/portal/appointments/{item_id}/reschedule")
async def patient_reschedule_appointment(item_id: str, body: PatientRescheduleBody,
                                         user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    appt = await db.appointment_requests.find_one({"id": item_id, "patient_id": p["id"]})
    if not appt:
        raise HTTPException(status_code=404, detail="Not found")
    if appt.get("status") not in ("confirmed", "rescheduled"):
        raise HTTPException(status_code=400, detail="This appointment can't be rescheduled online.")
    if await _has_outstanding_fee(p["id"]):
        raise HTTPException(status_code=403, detail=OUTSTANDING_FEE_MSG)
    hrs = _hours_until(appt)
    if hrs is None or hrs < SELF_SERVICE_CUTOFF_HOURS:
        raise HTTPException(status_code=403, detail=WITHIN_24H_MSG)
    time24 = avail_mod._norm_time(body.time)
    avail = await get_availability_doc()
    if not avail_mod.is_within(avail, body.date, time24):
        raise HTTPException(status_code=400, detail="That time is outside the clinic's available hours.")
    if avail_mod.is_past_slot(avail, body.date, time24):
        raise HTTPException(status_code=400, detail="That time is in the past. Please choose an upcoming time.")
    if await _slot_taken(body.date, time24, exclude_id=item_id):
        raise HTTPException(status_code=409, detail="This time is no longer available. Please select another time.")
    display = body.display or f"{fmt_date_display(body.date)} · {body.label or body.time}"
    await db.appointment_requests.update_one({"id": item_id}, {
        "$set": {"status": "confirmed", "confirmed_date": body.date,
                 "confirmed_time": body.label or body.time, "confirmed_slot_time": time24,
                 "confirmed_display": display, "rescheduled_by": "patient",
                 "rescheduled_at": now_iso(), "updated_at": now_iso()},
        "$push": {"history": {"status": "rescheduled", "at": now_iso(), "by": "patient"}}})
    await audit("patient_reschedule", "appointment", item_id,
                {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="confirmed")
    fresh = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    await notify_svc.appointment_rescheduled(db, fresh)
    return {"ok": True}


async def get_busy_slots():
    """VIen EMR is the source of truth: confirmed, rescheduled, completed and
    no-show appointments all occupy (and keep) their slot — completing or marking
    an appointment does NOT reopen its time."""
    appts = await db.appointment_requests.find(
        {"status": {"$in": ["confirmed", "rescheduled", "completed", "no_show"]}, "confirmed_date": {"$ne": None}}).to_list(2000)
    busy = set()
    for a in appts:
        t = a.get("confirmed_slot_time") or avail_mod._norm_time(a.get("confirmed_time") or "")
        if a.get("confirmed_date") and t:
            busy.add(f"{a['confirmed_date']} {t}")
    return busy


@api.get("/availability/slots")
async def availability_slots(days: int = 28, user: dict = Depends(get_current_user)):
    avail = await get_availability_doc()
    busy = await get_busy_slots()
    return {"timezone": avail.get("timezone"), "duration": avail.get("appointment_duration"),
            "slots": avail_mod.generate_slots(avail, days=min(max(days, 1), 60), busy=busy)}


@api.get("/admin/availability")
async def get_availability(user: dict = Depends(require_roles("admin"))):
    return await get_availability_doc()


@api.put("/admin/availability")
async def put_availability(payload: dict, user: dict = Depends(require_roles("admin"))):
    payload["id"] = "availability"
    await db.settings.update_one({"id": "availability"}, {"$set": payload}, upsert=True)
    await audit("update_availability", "settings", "availability", user)
    return {"ok": True}


class BlockTimeBody(BaseModel):
    date: str
    start: str
    end: str
    reason: Optional[str] = None


@api.get("/internal/calendar")
async def internal_calendar(start: Optional[str] = None, days: int = 7,
                            user: dict = Depends(require_roles(*CLINIC_ROLES))):
    from datetime import date as _date
    start = start or _date.today().isoformat()
    days = min(max(days, 1), 42)
    avail = await get_availability_doc()
    busy = await get_busy_slots()
    day_rows = avail_mod.calendar_range(avail, start, days, busy=busy)
    # attach booked appointments per day
    from datetime import date as _d, timedelta as _td
    d0 = _date.fromisoformat(start)
    end = (d0 + _td(days=days - 1)).isoformat()
    appts = await db.appointment_requests.find({
        "confirmed_date": {"$gte": start, "$lte": end},
        "status": {"$in": ["confirmed", "rescheduled", "completed", "no_show"]},
    }, {"_id": 0}).to_list(1000)
    by_day = {}
    for a in appts:
        by_day.setdefault(a["confirmed_date"], []).append({
            "id": a["id"], "ref_number": a.get("ref_number"),
            "time": a.get("confirmed_slot_time") or avail_mod._norm_time(a.get("confirmed_time") or ""),
            "label": a.get("confirmed_time"), "patient_name": a.get("patient_name"),
            "status": a.get("status"), "reason": a.get("reason"),
            "appointment_type": a.get("appointment_type"),
            "source": (a.get("booked_from") or {}).get("source_type") or "appointment",
        })
    for row in day_rows:
        row["appointments"] = sorted(by_day.get(row["date"], []), key=lambda x: x["time"] or "")
        row["day_blocked"] = any(b.get("date") == row["date"] and b.get("block_day")
                                 for b in avail.get("blocked_periods", []))
    return {"timezone": avail.get("timezone"), "duration": avail.get("appointment_duration"), "days": day_rows}


class DayBody(BaseModel):
    date: str


@api.post("/internal/calendar/block-day")
async def block_day(body: DayBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Block every REMAINING open slot for a day. Existing appointments are untouched."""
    avail = await get_availability_doc()
    dur = int(avail.get("appointment_duration") or 30) or 30
    busy = await get_busy_slots()
    from datetime import date as _date
    _, _, open_slots = avail_mod._slots_for_day(avail, _date.fromisoformat(body.date), dur, busy)
    blocks = list(avail.get("blocked_periods", []))
    have = {(b.get("date"), b.get("start")) for b in blocks}
    added = 0
    for s in open_slots:
        st = s["time"]
        if (body.date, st) in have:
            continue
        h, m = st.split(":")
        em = int(h) * 60 + int(m) + dur
        blocks.append({"date": body.date, "start": st, "end": f"{em // 60:02d}:{em % 60:02d}",
                       "reason": "Day blocked", "block_day": True})
        added += 1
    await db.settings.update_one({"id": "availability"}, {"$set": {"blocked_periods": blocks}}, upsert=True)
    await audit("block_day", "settings", "availability", user, meta={"date": body.date, "slots_blocked": added})
    return {"ok": True, "slots_blocked": added}


@api.post("/internal/calendar/unblock-day")
async def unblock_day(body: DayBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Restore only the slots that Block Day created for this date. Appointments untouched."""
    avail = await get_availability_doc()
    blocks = avail.get("blocked_periods", [])
    kept = [b for b in blocks if not (b.get("date") == body.date and b.get("block_day"))]
    removed = len(blocks) - len(kept)
    await db.settings.update_one({"id": "availability"}, {"$set": {"blocked_periods": kept}}, upsert=True)
    await audit("unblock_day", "settings", "availability", user, meta={"date": body.date, "slots_unblocked": removed})
    return {"ok": True, "slots_unblocked": removed}


@api.post("/internal/calendar/block")
async def block_time(body: BlockTimeBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    avail = await get_availability_doc()
    blocks = avail.get("blocked_periods", [])
    blocks.append({"date": body.date, "start": avail_mod._norm_time(body.start),
                   "end": avail_mod._norm_time(body.end), "reason": body.reason or "Blocked"})
    await db.settings.update_one({"id": "availability"}, {"$set": {"blocked_periods": blocks}}, upsert=True)
    await audit("block_time", "settings", "availability", user, meta={"date": body.date})
    return {"ok": True}


class CalendarBookBody(BaseModel):
    directory_id: Optional[str] = None
    patient_id: Optional[str] = None  # verified portal patient (portal-only, no directory record)
    date: str
    time: str
    label: Optional[str] = None
    reason: Optional[str] = None
    appointment_type: Optional[str] = "Office visit"


@api.post("/internal/calendar/book")
async def calendar_book(body: CalendarBookBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    # Resolve the patient identity from either a directory record or a verified portal account.
    if body.directory_id:
        d = await db.patient_directory.find_one({"id": body.directory_id})
        if not d:
            raise HTTPException(status_code=404, detail="Patient not found in directory.")
        appt_patient_id = d.get("linked_patient_id") or d["id"]
        appt_directory_id = d["id"]
        patient_name = f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", ")
    elif body.patient_id:
        p = await db.patients.find_one({"id": body.patient_id})
        if not p:
            raise HTTPException(status_code=404, detail="Patient not found.")
        if p.get("verification_status") != "verified":
            raise HTTPException(status_code=400, detail="Only verified patients can be booked.")
        appt_patient_id = p["id"]
        appt_directory_id = p.get("matched_directory_id")
        patient_name = f"{p.get('last_name','')}, {p.get('first_name','')}".strip(", ")
    else:
        raise HTTPException(status_code=400, detail="A patient must be selected.")
    time24 = avail_mod._norm_time(body.time)
    avail = await get_availability_doc()
    if not avail_mod.is_within(avail, body.date, time24):
        raise HTTPException(status_code=400, detail="That time is outside Dr. Aguayo's configured availability.")
    if avail_mod.is_past_slot(avail, body.date, time24):
        raise HTTPException(status_code=400, detail="That time is in the past. Please choose an upcoming time.")
    if await _slot_taken(body.date, time24):
        raise HTTPException(status_code=409, detail="This time is no longer available. Please select another time.")
    ref = await next_ref("APT")
    appt = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": appt_patient_id,
        "directory_id": appt_directory_id, "patient_name": patient_name,
        "reason": body.reason or "Office visit", "appointment_type": body.appointment_type,
        "duration": avail.get("appointment_duration"), "preferred_options": [],
        "status": "confirmed", "confirmed_date": body.date, "confirmed_time": body.label or body.time,
        "confirmed_slot_time": time24, "confirmed_display": f"{fmt_date_display(body.date)} · {body.label or body.time}",
        "approved_by": user["name"], "approved_at": now_iso(), "booked_by": user["name"],
        "booked_from": {"source_type": "calendar", "source_id": None},
        "assigned_to": None, "internal_notes": [],
        "history": [{"status": "confirmed", "at": now_iso(), "by": user["name"], "note": "Booked from calendar"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.appointment_requests.insert_one({**appt})
    await audit("calendar_book", "appointment", appt["id"], user, new_status="confirmed")
    await notify_svc.appointment_confirmed(db, appt)
    appt.pop("_id", None)
    return appt


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


@api.post("/portal/bloodwork")
async def create_bloodwork(body: BloodworkBody, p: dict = Depends(require_verified_patient)):
    ref = await next_ref("BLD")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        **body.model_dump(), "internal_status": "new", "assigned_to": None,
        "internal_notes": [], "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.bloodwork_requests.insert_one({**doc})
    await audit("create", "bloodwork", doc["id"], {"id": p["id"], "name": p["first_name"], "role": "patient"}, new_status="new")
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
    blds = await db.bloodwork_requests.find({"patient_id": pid}, {"_id": 0}).to_list(200)
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
                + pa(imgs, "Imaging", IMG_PATIENT_STATUS) + pa(blds, "Bloodwork", BLD_PATIENT_STATUS)
                + pa(msgs, "Message", MSG_PATIENT_STATUS))
    requests.sort(key=lambda x: x["created_at"], reverse=True)
    referrals = [{"id": r["id"], "specialty": r.get("specialty"),
                  "status": r.get("patient_visible_status"), "last_updated": r.get("updated_at")} for r in refs]
    def appt_view(a):
        hrs = _hours_until(a) if a.get("status") in ("confirmed", "rescheduled") else None
        return {
            "id": a["id"], "ref_number": a["ref_number"], "reason": a["reason"],
            "status": APPT_PATIENT_STATUS.get(a["status"]), "raw_status": a["status"],
            "appointment_type": a.get("appointment_type"),
            "preferred_options": a.get("preferred_options", []),
            "offered_slots": a.get("offered_slots", []),
            "confirmed_date": a.get("confirmed_date"), "confirmed_time": a.get("confirmed_time"),
            "confirmed_slot_time": a.get("confirmed_slot_time"),
            "confirmed_display": a.get("confirmed_display"),
            "late_fee": a.get("late_fee"),
            "hours_until": hrs,
            "can_self_modify": bool(hrs is not None and hrs >= SELF_SERVICE_CUTOFF_HOURS),
            "staff_note": a.get("staff_note"), "created_at": a["created_at"],
        }
    has_fee = any((a.get("late_fee") or {}).get("status") == "outstanding" for a in appts)
    return {
        "patient": {"first_name": p["first_name"], "last_name": p["last_name"],
                    "patient_type": p["patient_type"], "verification_status": p["verification_status"],
                    "has_outstanding_fee": has_fee},
        "requests": requests,
        "appointments": [appt_view(a) for a in appts],
        "prescriptions": [{"id": r["id"], "ref_number": r["ref_number"], "medication_name": r["medication_name"],
                           "strength": r.get("strength"), "status": RX_PATIENT_STATUS.get(r["internal_status"]),
                           "created_at": r["created_at"]} for r in rxs],
        "imaging": [{"id": i["id"], "ref_number": i["ref_number"], "imaging_type": i["imaging_type"],
                     "body_part": i["body_part"], "status": IMG_PATIENT_STATUS.get(i["internal_status"]),
                     "created_at": i["created_at"]} for i in imgs],
        "bloodwork": [{"id": b["id"], "ref_number": b["ref_number"], "reason": b.get("reason"),
                       "status": BLD_PATIENT_STATUS.get(b["internal_status"]),
                       "created_at": b["created_at"]} for b in blds],
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
        bld = await db.bloodwork_requests.count_documents({"internal_status": "waiting_physician"})
        apps = await db.patient_applications.count_documents({"internal_status": {"$in": APP_ACTIVE}})
        return {"role": "physician", "counters": {"rx": rx, "imaging": img, "bloodwork": bld, "messages": pmsg + dmsg, "applications": apps}}
    rx = await db.prescription_requests.count_documents({"internal_status": {"$in": RX_ACTIVE}})
    referrals = await db.referrals.count_documents({"ready_to_fax": True, "faxed": False})
    img = await db.imaging_requests.count_documents({"internal_status": {"$in": IMG_ACTIVE}})
    bld = await db.bloodwork_requests.count_documents({"internal_status": {"$in": BLD_ACTIVE}})
    msgs = await db.patient_messages.count_documents({"status": {"$in": MSG_ACTIVE}})
    appts = await db.appointment_requests.count_documents({"status": "requested"})
    tasks = await db.internal_messages.count_documents({"recipient_role": "staff", "status": {"$ne": "completed"}})
    pending_verif = await db.patients.count_documents({"verification_status": "pending", "active_status": True})
    apps = await db.patient_applications.count_documents({"internal_status": {"$in": APP_ACTIVE}})
    return {"role": user["role"], "counters": {
        "rx": rx, "referrals": referrals, "imaging": img, "bloodwork": bld, "messages": msgs,
        "appointments": appts, "doctor_tasks": tasks, "verifications": pending_verif, "applications": apps,
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
    if old == "voided" and body.action != "void":
        raise HTTPException(status_code=409, detail="This request is archived (voided) and is read-only.")
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
    elif body.action == "approve" and entity == "prescription":
        updates[status_field] = "approved_process_visita"
        notify = True
    elif body.action == "modify" and entity == "prescription":
        updates[status_field] = "approved_process_visita"
        updates["modified"] = True
        if body.staff_note is not None:
            updates["physician_note"] = body.staff_note
        notify = True
    elif body.action == "more_info":
        updates[status_field] = "more_info_required"
        if body.staff_note is not None:
            updates["staff_note"] = body.staff_note
        notify = True
    elif body.action == "decline":
        updates[status_field] = "declined"
        updates["completed_at"] = now_iso()
        if body.staff_note is not None:
            updates["staff_note"] = body.staff_note
        notify = True
    elif body.action == "void":
        if user["role"] not in ("staff", "admin"):
            raise HTTPException(status_code=403, detail="Only staff or admin can void a request.")
        updates[status_field] = "voided"
        updates["voided_by"] = user["name"]
        updates["voided_at"] = now_iso()
        updates["void_reason"] = body.void_reason or "Other"
        updates["completed_at"] = now_iso()
        # No patient notification for a void — the original record is kept read-only.
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
    else:
        # Hide voided/archived requests from the normal active queue.
        query["internal_status"] = {"$nin": ["voided"]}
    query.update(_search_filter(q, ["patient_name", "medication_name", "ref_number"]))
    return await db.prescription_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.patch("/internal/prescriptions/{item_id}")
async def rx_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await _update_request(db.prescription_requests, "prescription", item_id, body, user,
                                 "internal_status", "Your prescription request has been updated.")


# ----------------------------- Pharmacy Rx intake -----------------------------
class PharmacyRxBody(BaseModel):
    directory_id: str
    pharmacy: str
    medications: List[str]
    selected_active_meds: Optional[List[str]] = []
    duration_qty: Optional[str] = None
    pharmacy_note: Optional[str] = None
    received_via: str  # fax | phone | other
    internal_note: Optional[str] = None


def _age_from_dob(dob: Optional[str]) -> Optional[int]:
    try:
        from datetime import date
        y, m, d = str(dob)[:10].split("-")
        today = date.today()
        return today.year - int(y) - ((today.month, today.day) < (int(m), int(d)))
    except Exception:
        return None


@api.get("/internal/patient-snapshot/{directory_id}")
async def patient_snapshot(directory_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    d = await db.patient_directory.find_one({"id": directory_id})
    if not d:
        raise HTTPException(status_code=404, detail="Patient not found in directory.")
    # Fields marked (VISITA) are model-ready placeholders for future read-only sync.
    return {
        "directory_id": d["id"],
        "first_name": d.get("first_name"), "last_name": d.get("last_name"),
        "visita_patient_id": d.get("visita_patient_id"),
        "date_of_birth": d.get("date_of_birth"), "age": _age_from_dob(d.get("date_of_birth")),
        "phone": d.get("cell_phone") or d.get("home_phone"),
        "patient_status": d.get("patient_status"),
        "linked_patient_id": d.get("linked_patient_id"),
        "medications": d.get("medications", []),                # VISITA (read-only, future)
        "last_visit_date": d.get("last_visit_date"),            # VISITA
        "last_visit_plan": d.get("last_visit_plan"),            # VISITA
        "current_pharmacy": d.get("current_pharmacy"),          # VISITA
    }


@api.post("/internal/pharmacy-rx")
async def create_pharmacy_rx(body: PharmacyRxBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    d = await db.patient_directory.find_one({"id": body.directory_id})
    if not d:
        raise HTTPException(status_code=404, detail="Patient not found in directory.")
    meds = [m.strip() for m in body.medications if m and m.strip()]
    if not meds:
        raise HTTPException(status_code=400, detail="Please add at least one requested medication.")
    ref = await next_ref("RX")
    patient_name = f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", ")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "source": "pharmacy",
        "patient_id": d.get("linked_patient_id") or d["id"],
        "directory_id": d["id"], "visita_patient_id": d.get("visita_patient_id"),
        "patient_name": patient_name,
        "medication_name": "; ".join(meds), "strength": None,
        "medications": meds, "selected_active_meds": body.selected_active_meds or [],
        "pharmacy": body.pharmacy, "duration_qty": body.duration_qty,
        "pharmacy_note": body.pharmacy_note, "received_via": body.received_via,
        "requested_months": None, "delivery_method": "pharmacy",
        "directions": None, "patient_note": None,
        "staff_note": body.internal_note, "intake_by": user["name"],
        "internal_status": "waiting_physician", "assigned_to": None,
        "internal_notes": ([{"by": user["name"], "note": body.internal_note, "at": now_iso()}] if body.internal_note else []),
        "history": [{"status": "waiting_physician", "at": now_iso(), "by": user["name"], "note": "Pharmacy intake"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.prescription_requests.insert_one({**doc})
    await audit("pharmacy_intake", "prescription", doc["id"], user, new_status="waiting_physician",
                meta={"pharmacy": body.pharmacy, "directory_id": d["id"]})
    doc.pop("_id", None)
    return doc


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


# ----------------------------- Bloodwork -----------------------------
@api.get("/internal/bloodwork")
async def bld_queue(q: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if user["role"] == "physician":
        query["internal_status"] = "waiting_physician"
    elif status:
        query["internal_status"] = status
    query.update(_search_filter(q, ["patient_name", "reason", "ref_number"]))
    return await db.bloodwork_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.patch("/internal/bloodwork/{item_id}")
async def bld_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await _update_request(db.bloodwork_requests, "bloodwork", item_id, body, user,
                                 "internal_status", "Your bloodwork request has been updated.")


# ----------------------------- Book appointment from a request -----------------------------
_BOOK_SOURCES = {
    "prescription": (lambda: db.prescription_requests, "internal_status"),
    "imaging": (lambda: db.imaging_requests, "internal_status"),
    "bloodwork": (lambda: db.bloodwork_requests, "internal_status"),
    "message": (lambda: db.patient_messages, "status"),
}


async def _slot_taken(date_str: str, time24: str, exclude_id: Optional[str] = None) -> bool:
    existing = await db.appointment_requests.find(
        {"status": "confirmed", "confirmed_date": date_str}).to_list(200)
    for a in existing:
        if exclude_id and a.get("id") == exclude_id:
            continue
        at = a.get("confirmed_slot_time") or avail_mod._norm_time(a.get("confirmed_time") or "")
        if at == time24:
            return True
    return False


@api.post("/internal/book-appointment")
async def book_appointment(body: BookApptBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    src = _BOOK_SOURCES.get(body.source_type)
    if not src:
        raise HTTPException(status_code=400, detail="Unsupported request type for booking.")
    coll, status_field = src[0](), src[1]
    source = await coll.find_one({"id": body.source_id})
    if not source:
        raise HTTPException(status_code=404, detail="Original request not found.")
    if not source.get("patient_id"):
        raise HTTPException(status_code=400, detail="This request has no linked patient.")
    time24 = avail_mod._norm_time(body.time)
    avail = await get_availability_doc()
    if not avail_mod.is_within(avail, body.date, time24):
        raise HTTPException(status_code=400, detail="That time is outside Dr. Aguayo's configured availability.")
    if await _slot_taken(body.date, time24):
        raise HTTPException(status_code=409, detail="This time is no longer available. Please select another time.")

    ref = await next_ref("APT")
    display = body.display or f"{fmt_date_display(body.date)} · {body.label or body.time}"
    appt = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": source["patient_id"],
        "patient_name": source.get("patient_name"),
        "reason": body.reason or f"Follow-up for {body.source_type} request {source.get('ref_number')}",
        "patient_note": None, "preferred_options": [],
        "preferred_date": body.date, "preferred_time": body.label or body.time,
        "status": "confirmed", "staff_note": None,
        "offered_slots": [], "selected_slot": None,
        "confirmed_date": body.date, "confirmed_time": body.label or body.time,
        "confirmed_slot_time": time24, "confirmed_display": display,
        "approved_by": user["name"], "approved_at": now_iso(),
        "booked_from": {"source_type": body.source_type, "source_id": body.source_id,
                        "source_ref": source.get("ref_number")},
        "booked_by": user["name"], "assigned_to": None, "internal_notes": [],
        "history": [{"status": "confirmed", "at": now_iso(), "by": user["name"], "note": "Booked from request"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.appointment_requests.insert_one({**appt})
    await coll.update_one({"id": body.source_id}, {"$set": {
        status_field: "appointment_booked", "linked_appointment_id": appt["id"],
        "appointment_booked": True, "updated_at": now_iso(),
    }})
    await audit("book_appointment", "appointment", appt["id"], user, new_status="confirmed",
                meta={"source_type": body.source_type, "source_id": body.source_id})
    await notify_patient(source["patient_id"], "Appointment booked",
                         f"An appointment with Dr. Aguayo has been booked for {display}. "
                         "Please log in to your Patient Portal for details.")
    try:
        await notify_svc.appointment_confirmed(db, appt)
    except Exception:
        pass
    appt.pop("_id", None)
    return appt


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
    if (updates.get("status") == "completed" or body.patient_reply) and doc.get("source") != "pharmacy" and doc.get("patient_id"):
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
    do_confirm_notify = False
    do_reschedule_notify = False
    do_offer_notify = False

    if body.action == "approve":
        cdate = body.confirmed_date or (doc.get("preferred_options") or [{}])[0].get("date")
        ctime = body.confirmed_time or (doc.get("preferred_options") or [{}])[0].get("time")
        avail = await get_availability_doc()
        if not avail_mod.is_within(avail, cdate, ctime):
            raise HTTPException(status_code=400, detail="That time is outside Dr. Aguayo's configured availability. Use 'Offer Available Times' instead.")
        time24 = avail_mod._norm_time(ctime)
        if await _slot_taken(cdate, time24, exclude_id=item_id):
            raise HTTPException(status_code=409, detail="This time is no longer available. Please select another time.")
        updates.update({
            "status": "confirmed", "confirmed_date": cdate, "confirmed_time": ctime,
            "confirmed_slot_time": time24, "confirmed_display": body.confirmed_display or f"{fmt_date_display(cdate)} · {ctime}",
            "approved_by": user["name"], "approved_at": now_iso(), "completed_at": now_iso(),
        })
        do_confirm_notify = True
    elif body.action == "reschedule":
        cdate = body.confirmed_date
        ctime = body.confirmed_time
        avail = await get_availability_doc()
        if not avail_mod.is_within(avail, cdate, ctime):
            raise HTTPException(status_code=400, detail="That time is outside Dr. Aguayo's configured availability.")
        time24 = avail_mod._norm_time(ctime)
        if avail_mod.is_past_slot(avail, cdate, time24):
            raise HTTPException(status_code=400, detail="That time is in the past. Please choose an upcoming time.")
        if await _slot_taken(cdate, time24, exclude_id=item_id):
            raise HTTPException(status_code=409, detail="This time is no longer available. Please select another time.")
        updates.update({
            "status": "confirmed", "confirmed_date": cdate, "confirmed_time": ctime,
            "confirmed_slot_time": time24, "confirmed_display": body.confirmed_display or f"{fmt_date_display(cdate)} · {ctime}",
            "rescheduled_by": user["name"], "rescheduled_at": now_iso(),
        })
        do_reschedule_notify = True
    elif body.action == "cancel":
        updates.update({"status": "cancelled", "staff_note": body.staff_note,
                        "cancelled_by": user["name"], "cancelled_at": now_iso(), "completed_at": now_iso()})
    elif body.action == "record_fee":
        updates["late_fee"] = {"amount": LATE_FEE_AMOUNT, "status": "outstanding",
                               "created_by": user["name"], "created_at": now_iso()}
    elif body.action == "mark_fee_paid":
        lf = doc.get("late_fee") or {"amount": LATE_FEE_AMOUNT}
        updates["late_fee"] = {**lf, "status": "paid", "resolved_by": user["name"], "resolved_at": now_iso()}
    elif body.action == "waive_fee":
        lf = doc.get("late_fee") or {"amount": LATE_FEE_AMOUNT}
        updates["late_fee"] = {**lf, "status": "waived", "resolved_by": user["name"], "resolved_at": now_iso()}
    elif body.action == "offer":
        slots = [s for s in (body.offered_slots or []) if s.get("date") and s.get("time")][:3]
        if not slots:
            raise HTTPException(status_code=400, detail="Select at least one available time to offer.")
        updates.update({"status": "alternatives_offered", "offered_slots": slots})
        do_offer_notify = True
    elif body.action == "more_info":
        updates.update({"status": "more_info_required", "staff_note": body.staff_note})
    elif body.action == "decline":
        updates.update({"status": "declined", "staff_note": body.staff_note, "completed_at": now_iso()})
    elif body.action == "complete":
        updates.update({"status": "completed", "completed_at": now_iso(), "completed_by": user["name"]})
    elif body.action == "no_show":
        updates.update({"status": "no_show", "completed_at": now_iso(), "marked_by": user["name"]})
    if body.assigned_to is not None:
        updates["assigned_to"] = body.assigned_to

    mongo_update = {"$set": updates, "$push": {"history": {"status": updates.get("status", old), "at": now_iso(), "by": user["name"]}}}
    if body.internal_note:
        mongo_update["$push"]["internal_notes"] = {"by": user["name"], "note": body.internal_note, "at": now_iso()}
    await db.appointment_requests.update_one({"id": item_id}, mongo_update)
    await audit("update", "appointment", item_id, user, old_status=old, new_status=updates.get("status", old))

    fresh = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    if do_confirm_notify:
        await notify_svc.appointment_confirmed(db, fresh)
    elif do_reschedule_notify:
        await notify_svc.appointment_rescheduled(db, fresh)
    elif do_offer_notify:
        await notify_svc.alternatives_offered(db, fresh)
    elif body.action == "more_info":
        await notify_patient(doc["patient_id"], "Appointment update",
                             "We need a little more information about your appointment request. Please log in to your Patient Portal.")
    elif body.action == "decline":
        await notify_patient(doc["patient_id"], "Appointment update",
                             "There is an update on your appointment request. Please log in to your Patient Portal.")
    elif body.action == "cancel":
        await notify_svc.appointment_cancelled(db, fresh, reason=body.staff_note)
    if body.action in ("decline", "complete", "no_show"):
        await notify_svc.cancel_reminders(db, item_id)
    return fresh


class ApptTypeBody(BaseModel):
    appointment_type: str  # IN_CLINIC | TELEPHONE


@api.patch("/internal/appointments/{item_id}/type")
async def appt_set_type(item_id: str, body: ApptTypeBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    if body.appointment_type not in ("IN_CLINIC", "TELEPHONE"):
        raise HTTPException(status_code=400, detail="Invalid appointment type.")
    doc = await db.appointment_requests.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    old_type = doc.get("appointment_type")
    if old_type == body.appointment_type:
        return await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    await db.appointment_requests.update_one({"id": item_id}, {
        "$set": {"appointment_type": body.appointment_type, "updated_at": now_iso()},
        "$push": {"history": {"status": doc.get("status"), "at": now_iso(), "by": user["name"],
                              "note": f"appointment_type -> {body.appointment_type}"}},
    })
    await audit("set_type", "appointment", item_id, user,
                old_status=old_type or "not_specified", new_status=body.appointment_type)
    fresh = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    # Notify patient only when a CONFIRMED appointment switches between two real types (In-Clinic <-> Telephone).
    if doc.get("status") in ("confirmed", "rescheduled") and old_type in ("IN_CLINIC", "TELEPHONE"):
        await notify_svc.appointment_type_changed(db, fresh)
    return fresh



# ----------------------------- Import existing appointments (one-time, production) -----------------------------
async def _match_directory_by_name(full_name: str):
    """Best-effort directory match by name. Returns (doc_or_None, ambiguous_bool).
    Only returns a doc when EXACTLY ONE record matches (no guessing)."""
    nm = (full_name or "").strip()
    if not nm:
        return None, False
    if "," in nm:
        last, first = [x.strip() for x in nm.split(",", 1)]
    else:
        parts = nm.split()
        first = parts[0] if parts else ""
        last = parts[-1] if len(parts) > 1 else parts[0] if parts else ""
    nf, nl = directory_mod.norm_name(first), directory_mod.norm_name(last)
    if not nl:
        return None, False
    # 1) first + last
    if nf:
        docs = await db.patient_directory.find({"norm_first": nf, "norm_last": nl}).to_list(50)
        if len(docs) == 1:
            return docs[0], False
        if len(docs) > 1:
            return None, True
    # 2) last name only
    docs = await db.patient_directory.find({"norm_last": nl}).to_list(50)
    if len(docs) == 1:
        return docs[0], False
    return None, len(docs) > 1


@api.post("/internal/appointments/import")
async def import_appointments(body: ImportApptBody, user: dict = Depends(require_roles("admin"))):
    """Import EXISTING clinic appointments as CONFIRMED (no confirmation SMS/email).
    Idempotent: an imported appointment on the same date+time is skipped. Reminders
    are scheduled only when a linked appointment is still >24h away."""
    avail = await get_availability_doc()
    summary = {"created": 0, "linked": 0, "link_required": 0, "skipped_duplicate": 0,
               "breaks_added": 0, "breaks_skipped": 0, "items": []}

    for it in body.appointments:
        time24 = avail_mod._norm_time(it.time)
        h, m = time24.split(":")
        label = it.label or avail_mod._label(int(h) * 60 + int(m))
        dup = await db.appointment_requests.find_one(
            {"imported": True, "confirmed_date": it.date, "confirmed_slot_time": time24})
        if dup:
            summary["skipped_duplicate"] += 1
            summary["items"].append({"name": it.patient_name, "date": it.date, "time": time24, "result": "duplicate"})
            continue
        matched, ambiguous = await _match_directory_by_name(it.patient_name)
        link_required = matched is None
        appt = {
            "id": str(uuid.uuid4()), "ref_number": await next_ref("APT"),
            "patient_id": (matched.get("linked_patient_id") or matched["id"]) if matched else None,
            "directory_id": matched["id"] if matched else None,
            "visita_patient_id": matched.get("visita_patient_id") if matched else None,
            "patient_name": (f"{matched.get('last_name','')}, {matched.get('first_name','')}".strip(", ")
                             if matched else it.patient_name),
            "original_imported_name": it.patient_name,
            "patient_link_required": link_required,
            "reason": it.reason or "Imported appointment",
            "patient_note": None, "preferred_options": [],
            "status": "confirmed",
            "confirmed_date": it.date, "confirmed_time": label, "confirmed_slot_time": time24,
            "confirmed_display": f"{fmt_date_display(it.date)} · {label}",
            "imported": True, "import_source": "google_calendar",
            "booked_from": {"source_type": "import", "source_id": None},
            "booked_by": f"Import ({user['name']})", "approved_by": "Imported (Google Calendar)",
            "approved_at": now_iso(), "assigned_to": None, "internal_notes": [],
            "history": [{"status": "confirmed", "at": now_iso(), "by": user["name"],
                         "note": "Imported from Google Calendar"}],
            "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
        }
        if body.dry_run:
            summary["created"] += 1
            summary["items"].append({"name": it.patient_name, "date": it.date, "time": time24,
                                     "result": "linked" if matched else ("ambiguous" if ambiguous else "no_match")})
            continue
        await db.appointment_requests.insert_one({**appt})
        await audit("import_appointment", "appointment", appt["id"], user, new_status="confirmed",
                    meta={"date": it.date, "time": time24, "linked": bool(matched)})
        summary["created"] += 1
        if matched:
            summary["linked"] += 1
        else:
            summary["link_required"] += 1
        # Reminders only when linked AND still more than 24h away (no confirmation notice).
        if matched:
            hrs = _hours_until(appt)
            if hrs is not None and hrs >= SELF_SERVICE_CUTOFF_HOURS:
                await notify_svc.schedule_reminders(db, appt)
        summary["items"].append({"name": it.patient_name, "date": it.date, "time": time24,
                                 "result": "linked" if matched else ("ambiguous" if ambiguous else "no_match"),
                                 "ref": appt["ref_number"]})

    # Break / block records → availability.blocked_periods (deduped)
    if body.breaks and not body.dry_run:
        blocks = list(avail.get("blocked_periods", []))
        existing = {(b.get("date"), b.get("start"), b.get("end")) for b in blocks}
        added = 0
        for br in body.breaks:
            key = (br.date, avail_mod._norm_time(br.start), avail_mod._norm_time(br.end))
            if key in existing:
                summary["breaks_skipped"] += 1
                continue
            blocks.append({"date": br.date, "start": key[1], "end": key[2], "reason": br.reason or "Break"})
            existing.add(key)
            added += 1
        if added:
            await db.settings.update_one({"id": "availability"}, {"$set": {"blocked_periods": blocks}}, upsert=True)
            await audit("import_blocks", "settings", "availability", user, meta={"added": added})
        summary["breaks_added"] = added
    elif body.breaks and body.dry_run:
        summary["breaks_added"] = len(body.breaks)

    return summary


@api.post("/internal/appointments/{item_id}/link-patient")
async def link_appointment_patient(item_id: str, body: LinkPatientBody,
                                   user: dict = Depends(require_roles(*CLINIC_ROLES))):
    appt = await db.appointment_requests.find_one({"id": item_id})
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    d = await db.patient_directory.find_one({"id": body.directory_id})
    if not d:
        raise HTTPException(status_code=404, detail="Patient not found in directory.")
    name = f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", ")
    updates = {
        "patient_id": d.get("linked_patient_id") or d["id"],
        "directory_id": d["id"], "visita_patient_id": d.get("visita_patient_id"),
        "patient_name": name,
        "original_imported_name": appt.get("original_imported_name") or appt.get("patient_name"),
        "patient_link_required": False,
        "linked_by": user["name"], "linked_at": now_iso(), "updated_at": now_iso(),
    }
    await db.appointment_requests.update_one({"id": item_id}, {
        "$set": updates,
        "$push": {"history": {"status": appt.get("status"), "at": now_iso(), "by": user["name"],
                              "note": f"Linked patient {name}"}}})
    await audit("appointment_patient_linked", "appointment", item_id, user, meta={"directory_id": d["id"]})
    fresh = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    if fresh.get("status") in ("confirmed", "rescheduled"):
        hrs = _hours_until(fresh)
        if hrs is not None and hrs >= SELF_SERVICE_CUTOFF_HOURS:
            await notify_svc.schedule_reminders(db, fresh)
    return fresh


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
            "review_queue": p.get("review_queue"),
            "directory_match": p.get("directory_match"),
        })
    return out


@api.get("/internal/directory")
async def search_directory(q: Optional[str] = None, status: Optional[str] = None,
                           user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if status:
        query["patient_status"] = status
    if q:
        qn = q.strip()
        query["$or"] = [
            {"first_name": {"$regex": qn, "$options": "i"}},
            {"last_name": {"$regex": qn, "$options": "i"}},
            {"norm_hcn": {"$regex": directory_mod.norm_hcn(qn)}},
            {"visita_patient_id": {"$regex": qn, "$options": "i"}},
        ]
    docs = await db.patient_directory.find(query).limit(50).to_list(50)
    return [directory_mod.serialize_candidate(d) for d in docs]


def _directory_snapshot(d: dict) -> dict:
    line1 = " ".join([str(d.get("address") or ""), (f"#{d.get('unit')}" if d.get("unit") else "")]).strip()
    address_full = ", ".join([x for x in [line1, d.get("city"), d.get("province"), d.get("postal_code")] if x])
    return {
        "id": d["id"],
        "source": "directory",
        "patient_id": d.get("linked_patient_id"),
        "directory_id": d["id"],
        "first_name": d.get("first_name"), "last_name": d.get("last_name"),
        "full_name": f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", "),
        "visita_patient_id": d.get("visita_patient_id"),
        "date_of_birth": d.get("date_of_birth"), "age": _age_from_dob(d.get("date_of_birth")),
        "home_phone": d.get("home_phone"), "cell_phone": d.get("cell_phone"),
        "email": d.get("email"),
        "address": d.get("address"), "unit": d.get("unit"),
        "city": d.get("city"), "province": d.get("province"), "postal_code": d.get("postal_code"),
        "address_full": address_full,
        "health_card_number": d.get("health_card_number"),
        "health_card_version_code": d.get("health_card_version_code"),
        "patient_status": d.get("patient_status"),
        "current_pharmacy": d.get("current_pharmacy"),
    }


def _portal_patient_snapshot(p: dict) -> dict:
    return {
        "id": p["id"],
        "source": "portal",
        "patient_id": p["id"],
        "directory_id": p.get("matched_directory_id"),
        "first_name": p.get("first_name"), "last_name": p.get("last_name"),
        "full_name": f"{p.get('last_name','')}, {p.get('first_name','')}".strip(", "),
        "visita_patient_id": p.get("visita_patient_id"),  # None -> UI shows "Not assigned"
        "date_of_birth": p.get("date_of_birth"), "age": _age_from_dob(p.get("date_of_birth")),
        "home_phone": None, "cell_phone": p.get("phone"),
        "email": p.get("email"),
        "address": None, "unit": None, "city": None, "province": p.get("province"), "postal_code": None,
        "address_full": None,
        "health_card_number": p.get("health_card_number"),
        "health_card_version_code": p.get("health_card_version"),
        "patient_status": "PORTAL_PATIENT",
        "current_pharmacy": None,
    }


def _portal_search_ors(qn: str):
    ors = [
        {"first_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"last_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"email": {"$regex": re.escape(qn), "$options": "i"}},
        {"health_card_number": {"$regex": re.escape(qn), "$options": "i"}},
        {"visita_patient_id": {"$regex": re.escape(qn), "$options": "i"}},
        {"date_of_birth": {"$regex": re.escape(qn)}},
    ]
    digits = re.sub(r"\D", "", qn)
    if len(digits) >= 3:
        ors.append({"phone": {"$regex": r"\D*".join(digits)}})
    return ors


async def _search_patients_merged(qn: str, limit: int = 40):
    """Unified internal patient search: VERIFIED portal patient accounts PLUS
    existing patient_directory records. Verified portal patients are surfaced
    first (so they're never crowded out by many directory matches). Deduped so a
    portal account linked to a directory record appears only once."""
    results, seen_dir, seen_pid = [], set(), set()

    # 1) Verified portal patients first.
    portal = await db.patients.find({
        "verification_status": "verified", "active_status": True, "$or": _portal_search_ors(qn),
    }).limit(limit).to_list(limit)
    for p in portal:
        mdir = p.get("matched_directory_id")
        if mdir:
            if mdir in seen_dir:
                continue
            d = await db.patient_directory.find_one({"id": mdir})
            if d:
                results.append(_directory_snapshot(d)); seen_dir.add(d["id"])
                continue
        if p["id"] in seen_pid:
            continue
        results.append(_portal_patient_snapshot(p)); seen_pid.add(p["id"])

    # 2) Directory records (skipping any already represented via a linked portal account).
    dir_ors = [
        {"first_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"last_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"norm_hcn": {"$regex": directory_mod.norm_hcn(qn)}},
        {"visita_patient_id": {"$regex": re.escape(qn), "$options": "i"}},
        {"date_of_birth": {"$regex": re.escape(qn)}},
    ]
    digits = re.sub(r"\D", "", qn)
    if len(digits) >= 3:
        ph = {"$regex": r"\D*".join(digits)}
        dir_ors += [{"home_phone": ph}, {"cell_phone": ph}]
    dir_docs = await db.patient_directory.find({"$or": dir_ors}).limit(limit).to_list(limit)
    for d in dir_docs:
        if d["id"] in seen_dir:
            continue
        results.append(_directory_snapshot(d)); seen_dir.add(d["id"])

    return results[:limit]


@api.get("/internal/patient-lookup")
async def internal_patient_lookup(q: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Read-only internal patient search across BOTH the patient_directory and
    VERIFIED portal patient accounts. Search by name / DOB / phone / email /
    health card / VISITA PIN. Deduped; portal-only patients are flagged
    source='portal'. Does not modify any record."""
    qn = (q or "").strip()
    if len(qn) < 2:
        return []
    return await _search_patients_merged(qn, limit=40)


@api.post("/internal/verifications/{patient_id}")
async def verify_patient(patient_id: str, body: VerifyBody, user: dict = Depends(require_roles("staff", "admin"))):
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    was_verified = p.get("verification_status") == "verified"
    updates = {"verification_status": body.decision, "updated_at": now_iso(),
               "verified_by": user["name"], "verified_at": now_iso()}
    if body.decision == "verified":
        updates["portal_status"] = "VERIFIED"
    if body.visita_patient_id:
        updates["visita_patient_id"] = body.visita_patient_id
    # Link to a directory record (stable VISITA-id relationship)
    link_dir_id = body.matched_patient_id or p.get("matched_directory_id")
    if body.decision == "verified" and link_dir_id:
        d = await db.patient_directory.find_one({"id": link_dir_id})
        if d:
            updates["visita_patient_id"] = d.get("visita_patient_id") or updates.get("visita_patient_id")
            updates["matched_directory_id"] = link_dir_id
            await db.patient_directory.update_one({"id": link_dir_id}, {"$set": {
                "linked_patient_id": patient_id, "updated_at": now_iso()}})
            await audit("patient_linked", "patient", patient_id, user, meta={"directory_id": link_dir_id})
    await db.patients.update_one({"id": patient_id}, {"$set": updates})
    await audit("verify_patient", "patient", patient_id, user, new_status=body.decision)
    if body.decision == "verified" and not was_verified:
        fresh = await db.patients.find_one({"id": patient_id}, {"_id": 0})
        await notify_svc.account_verified(db, fresh)
    else:
        await notify_patient(patient_id, "Account update",
                             "Your portal account has been reviewed. Please log in to your Patient Portal.")
    return {"ok": True}


# ----------------------------- Patient Applications (new / former return) -----------------------------
def _serialize_application(a: dict) -> dict:
    return {
        "id": a["id"], "ref_number": a.get("ref_number"), "application_type": a.get("application_type"),
        "first_name": a.get("first_name"), "last_name": a.get("last_name"),
        "date_of_birth": a.get("date_of_birth"), "phone": a.get("phone"), "email": a.get("email"),
        "address": a.get("address"), "city": a.get("city"), "province": a.get("province"),
        "postal_code": a.get("postal_code"), "country": a.get("country"),
        "health_card_masked": mask_hcn(a.get("health_card_number")),
        "patient_message": a.get("patient_message"), "preferred_language": a.get("preferred_language"),
        "internal_status": a.get("internal_status"),
        "patient_visible_status": APP_PATIENT_STATUS.get(a.get("internal_status")),
        "directory_match": a.get("directory_match"), "matched_directory_id": a.get("matched_directory_id"),
        "internal_notes": a.get("internal_notes", []), "history": a.get("history", []),
        "accepted_by": a.get("accepted_by"), "accepted_at": a.get("accepted_at"),
        "created_at": a.get("created_at"), "updated_at": a.get("updated_at"),
    }


@api.get("/internal/applications")
async def applications_queue(type: Optional[str] = None, status: Optional[str] = None,
                             user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if type in ("new_patient", "former_return"):
        query["application_type"] = type
    if status == "active":
        query["internal_status"] = {"$in": APP_ACTIVE}
    elif status:
        query["internal_status"] = status
    docs = await db.patient_applications.find(query).sort("created_at", -1).to_list(500)
    return [_serialize_application(a) for a in docs]


@api.patch("/internal/applications/{item_id}")
async def application_update(item_id: str, body: ApplicationUpdateBody,
                             user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.patient_applications.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    old = doc.get("internal_status")
    updates = {"updated_at": now_iso()}
    push = {}

    final_actions = {"accept": "ACCEPTED", "not_accepting": "NOT_ACCEPTING"}
    if body.action in final_actions:
        # Final clinical decisions are physician-only
        if user["role"] != "physician":
            raise HTTPException(status_code=403, detail="Only the physician can make the final acceptance decision.")
        new_status = final_actions[body.action]
        updates["internal_status"] = new_status
        updates["previous_status"] = old
        updates["new_status"] = new_status
        if body.action == "accept":
            updates["accepted_by"] = user["name"]
            updates["accepted_at"] = now_iso()
            # Former-return acceptance flips the directory record to ACTIVE
            if doc.get("application_type") == "former_return" and doc.get("matched_directory_id"):
                d = await db.patient_directory.find_one({"id": doc["matched_directory_id"]})
                if d:
                    await db.patient_directory.update_one({"id": d["id"]}, {"$set": {
                        "patient_status": directory_mod.ACTIVE,
                        "previous_status": d.get("patient_status"),
                        "reactivated_by": user["name"], "reactivated_at": now_iso(),
                        "reactivation_application_id": item_id, "updated_at": now_iso(),
                    }})
                    await audit("physician_reactivation", "patient_directory", d["id"], user,
                                old_status=directory_mod.FORMER_CLOSED, new_status=directory_mod.ACTIVE,
                                meta={"application_id": item_id})
    elif body.action == "send_to_physician":
        updates["internal_status"] = "SENT_TO_PHYSICIAN"
    elif body.action == "waitlist":
        updates["internal_status"] = "WAITING_LIST"
    elif body.action == "review":
        updates["internal_status"] = "UNDER_REVIEW"
    elif body.action == "close":
        updates["internal_status"] = "CLOSED"
    elif body.internal_status:
        updates["internal_status"] = body.internal_status

    if body.internal_note:
        push["internal_notes"] = {"by": user["name"], "note": body.internal_note, "at": now_iso()}
    if body.staff_message:
        updates["staff_message"] = body.staff_message
    new_stat = updates.get("internal_status", old)
    push_hist = {"status": new_stat, "at": now_iso(), "by": user["name"]}
    mongo_update = {"$set": updates, "$push": {"history": push_hist}}
    if push.get("internal_notes"):
        mongo_update["$push"]["internal_notes"] = push["internal_notes"]
    await db.patient_applications.update_one({"id": item_id}, mongo_update)
    await audit("update", "patient_application", item_id, user, old_status=old, new_status=new_stat,
                meta={"action": body.action})
    fresh = await db.patient_applications.find_one({"id": item_id})
    return _serialize_application(fresh)
# ============================ PHARMACY PORTAL ============================
# External pharmacy role. Locked to a single pharmacy per account. Reuses the
# existing Rx (prescription_requests) and Messages (patient_messages) pipelines.
PHARMACY_UPLOAD_EXT = {
    "application/pdf": "pdf", "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
}
MAX_PHARMACY_UPLOAD_BYTES = 15 * 1024 * 1024


def _pharmacy_of(user: dict):
    pid, name = user.get("pharmacy_id"), user.get("pharmacy_name")
    if not pid or not name:
        raise HTTPException(status_code=403, detail="No pharmacy is associated with this account.")
    return pid, name


def _pharmacy_patient_identity(d: dict) -> dict:
    line1 = " ".join([str(d.get("address") or ""), (f"#{d.get('unit')}" if d.get("unit") else "")]).strip()
    address_full = ", ".join([x for x in [line1, d.get("city"), d.get("postal_code")] if x])
    return {
        "id": d["id"],
        "first_name": d.get("first_name"), "last_name": d.get("last_name"),
        "full_name": f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", "),
        "visita_patient_id": d.get("visita_patient_id"),
        "date_of_birth": d.get("date_of_birth"),
        "home_phone": d.get("home_phone"), "cell_phone": d.get("cell_phone"),
        "address": d.get("address"), "unit": d.get("unit"),
        "city": d.get("city"), "province": d.get("province"), "postal_code": d.get("postal_code"),
        "address_full": address_full,
        "health_card_number": d.get("health_card_number"),
        "health_card_version_code": d.get("health_card_version_code"),
        "patient_status": d.get("patient_status"),
    }


def _serve_attachment(att: dict):
    data, ctype = storage.get_object(att["storage_path"])
    ctype = att.get("content_type") or ctype
    fname = att.get("original_filename") or "attachment"
    return Response(content=data, media_type=ctype,
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


async def _store_pharmacy_upload(file, subdir: str) -> dict:
    ctype = (file.content_type or "").lower()
    fname = (file.filename or "").lower()
    ext = PHARMACY_UPLOAD_EXT.get(ctype)
    if not ext:
        if fname.endswith(".pdf"):
            ext = "pdf"
        elif fname.endswith((".jpg", ".jpeg")):
            ext = "jpg"
        elif fname.endswith(".png"):
            ext = "png"
    if not ext:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, or PDF files are accepted.")
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The selected file is empty.")
    if len(data) > MAX_PHARMACY_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 15 MB.")
    content_type = "application/pdf" if ext == "pdf" else ("image/png" if ext == "png" else "image/jpeg")
    path = f"{storage.APP_NAME}/pharmacy/{subdir}/{uuid.uuid4()}.{ext}"
    storage.put_object(path, data, content_type)
    return {"storage_path": path, "original_filename": file.filename,
            "content_type": content_type, "size": len(data), "uploaded_at": now_iso()}


@api.get("/pharmacy/context")
async def pharmacy_context(user: dict = Depends(require_roles("pharmacy"))):
    pid, name = _pharmacy_of(user)
    return {"pharmacy_id": pid, "pharmacy_name": name, "name": user.get("name"),
            "username": user.get("username")}


@api.get("/pharmacy/patients/search")
async def pharmacy_search(q: str, user: dict = Depends(require_roles("pharmacy"))):
    _pharmacy_of(user)
    qn = (q or "").strip()
    if len(qn) < 2:
        return []
    query = {"$or": [
        {"first_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"last_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"norm_hcn": {"$regex": directory_mod.norm_hcn(qn)}},
        {"visita_patient_id": {"$regex": re.escape(qn), "$options": "i"}},
    ]}
    docs = await db.patient_directory.find(query).limit(25).to_list(25)
    return [_pharmacy_patient_identity(d) for d in docs]


@api.get("/pharmacy/patients/{directory_id}")
async def pharmacy_patient(directory_id: str, user: dict = Depends(require_roles("pharmacy"))):
    _pharmacy_of(user)
    d = await db.patient_directory.find_one({"id": directory_id})
    if not d:
        raise HTTPException(status_code=404, detail="Patient not found in directory.")
    return _pharmacy_patient_identity(d)


@api.post("/pharmacy/rx")
async def pharmacy_create_rx(
    directory_id: str = Form(...),
    medication_name: str = Form(...),
    strength: str = Form(""),
    duration_qty: str = Form(""),
    pharmacy_note: str = Form(""),
    message_to_physician: str = Form(""),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(require_roles("pharmacy")),
):
    pid, pname = _pharmacy_of(user)
    d = await db.patient_directory.find_one({"id": directory_id})
    if not d:
        raise HTTPException(status_code=404, detail="Patient not found in directory.")
    med = medication_name.strip()
    if not med:
        raise HTTPException(status_code=400, detail="Enter the medication name.")
    full_med = f"{med}{(' ' + strength.strip()) if strength.strip() else ''}"
    attachment = await _store_pharmacy_upload(file, "rx") if file is not None else None
    ref = await next_ref("RX")
    patient_name = f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", ")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "source": "pharmacy",
        "patient_id": d.get("linked_patient_id") or d["id"],
        "directory_id": d["id"], "visita_patient_id": d.get("visita_patient_id"),
        "patient_name": patient_name,
        "medication_name": med, "strength": strength.strip() or None,
        "medications": [full_med], "selected_active_meds": [],
        "pharmacy": pname, "pharmacy_id": pid, "duration_qty": duration_qty.strip() or None,
        "pharmacy_note": pharmacy_note.strip() or None, "received_via": "pharmacy_portal",
        "message_to_physician": message_to_physician.strip() or None,
        "requested_months": None, "delivery_method": "pharmacy",
        "directions": None, "patient_note": None,
        "staff_note": None, "intake_by": pname,
        "attachment": attachment,
        "internal_status": "waiting_physician", "assigned_to": None,
        "internal_notes": [],
        "history": [{"status": "waiting_physician", "at": now_iso(), "by": pname, "note": "Pharmacy portal request"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.prescription_requests.insert_one({**doc})
    await audit("pharmacy_portal_rx", "prescription", doc["id"],
                {"id": user["id"], "name": pname, "role": "pharmacy"}, new_status="waiting_physician",
                meta={"pharmacy_id": pid, "directory_id": d["id"], "attachment": bool(attachment)})
    doc.pop("_id", None)
    return doc


@api.get("/pharmacy/rx")
async def pharmacy_rx_list(user: dict = Depends(require_roles("pharmacy"))):
    pid, _ = _pharmacy_of(user)
    # Visibility: ONLY requests actually submitted through THIS authenticated
    # pharmacy account via the portal. Determined by account (pharmacy_id) AND
    # origin (received_via), never by source alone — so staff-entered clinic
    # pharmacy-intake records (pharmacy_id=None) are never exposed here.
    docs = await db.prescription_requests.find(
        {"pharmacy_id": pid, "received_via": "pharmacy_portal"}, {"_id": 0}).sort("created_at", -1).to_list(200)
    for x in docs:
        st = x.get("internal_status")
        x["status_label"] = ("Waiting for Physician to review" if st == "waiting_physician"
                              else RX_PATIENT_STATUS.get(st, "Received"))
    return docs


@api.get("/pharmacy/rx/{item_id}/attachment")
async def pharmacy_rx_attachment(item_id: str, user: dict = Depends(require_roles("pharmacy"))):
    pid, _ = _pharmacy_of(user)
    doc = await db.prescription_requests.find_one({"id": item_id, "pharmacy_id": pid})
    if not doc or not doc.get("attachment"):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return _serve_attachment(doc["attachment"])


@api.get("/internal/prescriptions/{item_id}/attachment")
async def internal_rx_attachment(item_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.prescription_requests.find_one({"id": item_id})
    if not doc or not doc.get("attachment"):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return _serve_attachment(doc["attachment"])


@api.get("/pharmacy/messages")
async def pharmacy_messages(user: dict = Depends(require_roles("pharmacy"))):
    pid, _ = _pharmacy_of(user)
    return await db.patient_messages.find(
        {"source": "pharmacy", "pharmacy_id": pid}, {"_id": 0}).sort("updated_at", -1).to_list(200)


@api.post("/pharmacy/messages")
async def pharmacy_create_message(
    body: str = Form(...),
    subject: str = Form(""),
    patient_directory_id: str = Form(""),
    rx_ref: str = Form(""),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(require_roles("pharmacy")),
):
    pid, pname = _pharmacy_of(user)
    text = body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Enter a message.")
    patient_id, patient_name = None, None
    if patient_directory_id:
        d = await db.patient_directory.find_one({"id": patient_directory_id})
        if d:
            patient_id = d.get("linked_patient_id") or d["id"]
            patient_name = f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", ")
    attachment = await _store_pharmacy_upload(file, "messages") if file is not None else None
    ref = await next_ref("MSG")
    entry = {"from": "pharmacy", "body": text, "at": now_iso()}
    if attachment:
        entry["attachment"] = attachment
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "source": "pharmacy", "pharmacy_id": pid, "pharmacy_name": pname,
        "patient_id": patient_id, "patient_name": patient_name or pname,
        "linked_rx_ref": rx_ref.strip() or None,
        "category": "Pharmacy", "subject": subject.strip() or "Pharmacy message",
        "body": text, "sender": "pharmacy", "status": "new", "assigned_to": None,
        "thread": [entry], "internal_notes": [],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.patient_messages.insert_one({**doc})
    await audit("pharmacy_message", "message", doc["id"],
                {"id": user["id"], "name": pname, "role": "pharmacy"}, new_status="new",
                meta={"pharmacy_id": pid, "patient_linked": bool(patient_id), "attachment": bool(attachment)})
    doc.pop("_id", None)
    return doc


@api.post("/pharmacy/messages/{item_id}/reply")
async def pharmacy_reply_message(
    item_id: str,
    body: str = Form(...),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(require_roles("pharmacy")),
):
    pid, pname = _pharmacy_of(user)
    doc = await db.patient_messages.find_one({"id": item_id, "source": "pharmacy", "pharmacy_id": pid})
    if not doc:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    text = body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Enter a reply.")
    entry = {"from": "pharmacy", "body": text, "at": now_iso()}
    if file is not None:
        entry["attachment"] = await _store_pharmacy_upload(file, "messages")
    await db.patient_messages.update_one({"id": item_id}, {
        "$push": {"thread": entry},
        "$set": {"status": "new", "updated_at": now_iso()}})
    await audit("pharmacy_message_reply", "message", item_id,
                {"id": user["id"], "name": pname, "role": "pharmacy"})
    return await db.patient_messages.find_one({"id": item_id}, {"_id": 0})


@api.get("/pharmacy/messages/{item_id}/attachment/{idx}")
async def pharmacy_msg_attachment(item_id: str, idx: int, user: dict = Depends(require_roles("pharmacy"))):
    pid, _ = _pharmacy_of(user)
    doc = await db.patient_messages.find_one({"id": item_id, "source": "pharmacy", "pharmacy_id": pid})
    thread = (doc or {}).get("thread", [])
    if not doc or idx < 0 or idx >= len(thread) or not thread[idx].get("attachment"):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return _serve_attachment(thread[idx]["attachment"])


@api.get("/internal/messages/{item_id}/attachment/{idx}")
async def internal_msg_attachment(item_id: str, idx: int, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.patient_messages.find_one({"id": item_id})
    thread = (doc or {}).get("thread", [])
    if not doc or idx < 0 or idx >= len(thread) or not thread[idx].get("attachment"):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return _serve_attachment(thread[idx]["attachment"])


class ResetPharmacyPwBody(BaseModel):
    identifier: str
    new_password: str


@api.post("/admin/pharmacy/reset-temp-password")
async def admin_reset_pharmacy_temp_password(body: ResetPharmacyPwBody, user: dict = Depends(require_roles("admin"))):
    """Admin-only rotation of a PHARMACY account's temporary password. Scoped to
    role='pharmacy' targets ONLY — it can never affect admin/physician/staff/patient
    accounts. Sets must_change_password=True so the pharmacy must set their own
    password on next login. Does not touch any other user or record."""
    if len((body.new_password or "").strip()) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    target = await db.users.find_one({
        "username": {"$regex": f"^{re.escape((body.identifier or '').strip())}$", "$options": "i"},
        "role": "pharmacy",
    })
    if not target:
        raise HTTPException(status_code=404, detail="Pharmacy user not found.")
    await db.users.update_one({"_id": target["_id"]}, {"$set": {
        "password_hash": authlib.hash_password(body.new_password),
        "must_change_password": True,
        "password_rotated_at": now_iso(),
    }})
    await audit("reset_pharmacy_temp_password", "user", str(target["_id"]), user,
                meta={"username": target.get("username")})
    return {"ok": True, "username": target.get("username"), "must_change_password": True}





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


@api.post("/cron/appointment-reminders")
async def cron_appointment_reminders(background: BackgroundTasks,
                                     authorization: Optional[str] = Header(None)):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    secret = os.environ.get("WEBHOOK_CRON_SECRET")
    token = (authorization or "").replace("Bearer ", "", 1)
    if not secret or not token or not secrets.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    background.add_task(notify_svc.send_due_reminders, db)
    return {"ok": True, "queued": True}


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
