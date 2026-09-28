from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import logging
import os
import json
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
import rx_parser
import availability as avail_mod
import attachments as attach_mod
import billing as billing_mod
import private_reasons
import directory as directory_mod
import email_service
import identity as identity_mod
import notifications as notify_svc
import organizations as orgs_mod
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
        "organization_id": u.get("organization_id"),
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
    health_card_issue_date: Optional[str] = None
    health_card_expiry_date: Optional[str] = None
    province: Optional[str] = None
    country: Optional[str] = None
    address: Optional[str] = None
    unit: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    extra_info: Optional[str] = None
    preferred_language: str = "en"


class LoginBody(BaseModel):
    identifier: Optional[str] = None
    email: Optional[str] = None
    password: str


class GoogleAuthBody(BaseModel):
    session_id: str


class PartnerRegisterBody(BaseModel):
    organization_name: str
    organization_type: str
    contact_first_name: str
    contact_last_name: str
    email: EmailStr
    phone: str
    city: str
    province: str
    password: str = Field(min_length=8)
    confirm_password: str
    address: Optional[str] = None
    website: Optional[str] = None


class PartnerProfileBody(BaseModel):
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    website: Optional[str] = None
    fax: Optional[str] = None
    description: Optional[str] = None
    specialties: Optional[str] = None
    services: Optional[str] = None
    languages: Optional[str] = None
    business_hours: Optional[str] = None
    referral_instructions: Optional[str] = None
    referral_addressed_to: Optional[str] = None  # legacy — kept for compatibility
    referral_destination: Optional[str] = None   # "organization" | "specific_provider"
    referral_provider_id: Optional[str] = None
    photos: Optional[List[str]] = None            # image URLs
    locations: Optional[List[dict]] = None        # [{id,label,address,city,province,postal_code,phone,fax,business_hours}]
    providers: Optional[List[dict]] = None        # [{id,name,specialties}]


class OrgVerificationBody(BaseModel):
    status: str
    note: Optional[str] = None


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
DOB_MIN_AGE = 17
DOB_MAX_AGE = 99


def validate_dob_age(dob_str: str):
    """Enforce patient age 17–99 inclusive using the full DOB vs today (not just
    year math). Raises HTTPException(400) on invalid/out-of-range DOB. Server-side
    guard so a direct API submission cannot bypass the UI."""
    from datetime import date as _date
    try:
        y, m, d = (int(x) for x in (dob_str or "").split("-"))
        dob = _date(y, m, d)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="A valid date of birth is required.")
    today = _date.today()
    if dob > today:
        raise HTTPException(status_code=400, detail="Date of birth cannot be in the future.")
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < DOB_MIN_AGE or age > DOB_MAX_AGE:
        raise HTTPException(status_code=400, detail=f"Patient age must be between {DOB_MIN_AGE} and {DOB_MAX_AGE} years.")


def _parse_iso(s):
    from datetime import date as _date
    y, m, d = (int(x) for x in str(s)[:10].split("-"))
    return _date(y, m, d)


def _derive_expiry_iso(dob_str, year):
    """Expiry month/day come from the DOB; only the year varies. Feb-29 DOB on a
    non-leap expiry year clamps to Feb 28. Mirrors frontend lib/hcDates.js."""
    import calendar
    from datetime import date as _date
    dob = _parse_iso(dob_str)
    dim = calendar.monthrange(year, dob.month)[1]
    day = min(dob.day, dim)
    return _date(year, dob.month, day).isoformat()


def validate_hc_dates(issue_str, expiry_str, dob_str):
    """Server-side guard for OHIP Health Card dates. Both optional. Issue date
    must fall within exactly 5 years ago through today. Expiry must be derived
    from the DOB (month/day) with a year of current..current+5. Rejects a direct
    API submission that bypasses the UI pickers."""
    from datetime import date as _date
    today = _date.today()
    if issue_str:
        try:
            issue = _parse_iso(issue_str)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Health Card issue date must be a valid date.")
        earliest = _date(today.year - 5, today.month, today.day)
        if issue > today:
            raise HTTPException(status_code=400, detail="Health Card issue date cannot be in the future.")
        if issue < earliest:
            raise HTTPException(status_code=400, detail="Health Card issue date cannot be more than 5 years ago.")
    if expiry_str:
        try:
            expiry = _parse_iso(expiry_str)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Health Card expiry date must be a valid date.")
        if not dob_str:
            raise HTTPException(status_code=400, detail="Date of birth is required before setting a Health Card expiry date.")
        if expiry.year < today.year or expiry.year > today.year + 5:
            raise HTTPException(status_code=400, detail="Health Card expiry year must be between this year and 5 years from now.")
        if expiry.isoformat() != _derive_expiry_iso(dob_str, expiry.year):
            raise HTTPException(status_code=400, detail="Health Card expiry day and month must match the date of birth.")


@api.post("/auth/register")
async def register(body: RegisterBody):
    validate_dob_age(body.date_of_birth)
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    # OHIP patients: Health Card number (10 digits) + Version Code (2 letters) required & normalized.
    hc_num, hc_ver = body.health_card_number, body.health_card_version
    if body.patient_type == "ohip":
        try:
            hc_num, hc_ver = identity_mod.normalize_health_card(body.health_card_number, body.health_card_version)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not body.health_card_issue_date:
            raise HTTPException(status_code=400, detail="Health Card issue date is required.")
        if not body.health_card_expiry_date:
            raise HTTPException(status_code=400, detail="Health Card expiry date is required.")
    if not identity_mod.valid_date(body.health_card_issue_date) or not identity_mod.valid_date(body.health_card_expiry_date):
        raise HTTPException(status_code=400, detail="Health Card dates must be valid dates.")
    validate_hc_dates(body.health_card_issue_date, body.health_card_expiry_date, body.date_of_birth)

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
            "message_code": "FORMER_PATIENT_DETECTED",
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
        "date_of_birth": body.date_of_birth, "health_card_number": hc_num,
        "health_card_version": hc_ver,
        "health_card_issue_date": body.health_card_issue_date or None,
        "health_card_expiry_date": body.health_card_expiry_date or None,
        "phone": identity_mod.normalize_phone(body.phone), "email": email,
        "province": body.province, "country": body.country, "extra_info": body.extra_info,
        "address": body.address, "unit": body.unit, "city": body.city, "postal_code": body.postal_code,
        "patient_type": body.patient_type, "verification_status": "pending",
        "portal_status": "PENDING_VERIFICATION",
        "review_queue": review_queue, "directory_match": match,
        "matched_directory_id": match.get("matched_id"),
        "preferred_language": email_service.norm_lang(body.preferred_language),
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
    validate_dob_age(body.date_of_birth)
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
            "message": await get_template("reestablish_care_confirmation"),
            "message_code": "REESTABLISH_CONFIRMATION"}


@api.post("/applications/new-patient")
async def new_patient_request(body: NewPatientRequestBody):
    validate_dob_age(body.date_of_birth)
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
            "message": await get_template("new_patient_request_confirmation"),
            "message_code": "NEW_PATIENT_CONFIRMATION"}


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


# Emergent-managed Google Sign-In — PATIENTS ONLY. Alternative auth method that
# reuses the existing JWT session; it never bypasses registration, identity
# matching, verification, or account-status rules. No account is ever created
# here: an unmatched Google email is rejected.
EMERGENT_SESSION_DATA_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
NO_ACCOUNT_MSG = ("No VIsita EMR account was found for this email. "
                  "Please register or use your existing sign-in.")


@api.post("/auth/google")
async def google_login(body: GoogleAuthBody):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(EMERGENT_SESSION_DATA_URL,
                                    headers={"X-Session-ID": body.session_id})
        resp.raise_for_status()
        profile = resp.json()
    except Exception:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified. Please try again.")

    google_sub = (profile.get("id") or "").strip()
    email = (profile.get("email") or "").strip().lower()
    if not email or not google_sub:
        raise HTTPException(status_code=401, detail="Google sign-in did not return a valid account.")

    # PATIENTS ONLY, exact normalized-email match. Never infer from name/DOB/profile.
    user = await db.users.find_one({"email": email, "role": "patient"})
    if not user:
        await audit("google_login_no_account", "user", email,
                    {"id": None, "name": profile.get("name"), "role": "patient"},
                    meta={"email": email})
        raise HTTPException(status_code=404, detail=NO_ACCOUNT_MSG)

    # Existing account restrictions still apply (suspended/disabled), same as password login.
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="This account has been disabled. Contact the clinic.")

    # Link the Google identity (sub) to this existing user on first login; on later
    # logins the stored sub must match — email alone is not the permanent identity.
    existing_sub = user.get("google_sub")
    if not existing_sub:
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"google_sub": google_sub}})
        await audit("google_account_linked", "user", str(user["_id"]),
                    {"id": str(user["_id"]), "name": user.get("name"), "role": "patient"})
    elif existing_sub != google_sub:
        raise HTTPException(status_code=403,
                            detail="This email is linked to a different Google account. Please use your usual sign-in.")

    await audit("google_login_success", "user", str(user["_id"]),
                {"id": str(user["_id"]), "name": user.get("name"), "role": "patient"})
    token = authlib.create_access_token(str(user["_id"]), user.get("email") or user.get("username"), user["role"])
    return {"token": token, "user": serialize_user(user)}
@api.post("/partner/register")
async def partner_register(body: PartnerRegisterBody):
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    if body.organization_type not in orgs_mod.ORG_TYPES:
        raise HTTPException(status_code=400, detail="Please select a valid organization type.")
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    # Soft duplicate guard (name + city) — flag only, never auto-merge or block.
    nname = orgs_mod.norm_name(body.organization_name)
    dup = await db.organizations.find_one({
        "norm_name": nname,
        "city": {"$regex": f"^{re.escape(body.city.strip())}$", "$options": "i"},
    })

    org_id = str(uuid.uuid4())
    now = now_iso()
    org = {
        "id": org_id,
        "organization_name": body.organization_name.strip(),
        "norm_name": nname,
        "organization_type": body.organization_type,
        "contact_first_name": body.contact_first_name.strip(),
        "contact_last_name": body.contact_last_name.strip(),
        "email": email,
        "phone": identity_mod.normalize_phone(body.phone),
        "city": body.city.strip(),
        "province": body.province.strip(),
        "address": (body.address or "").strip() or None,
        "website": (body.website or "").strip() or None,
        "source": "PARTNER_SUBMITTED",
        "verification_status": "UNVERIFIED",
        "possible_duplicate": bool(dup),
        # Profile fields (built later by the partner in onboarding)
        "postal_code": None, "fax": None, "description": None,
        "specialties": None, "services": None, "languages": None,
        "business_hours": None, "referral_instructions": None,
        "referral_addressed_to": None, "referral_destination": None,
        "referral_provider_id": None, "photos": [], "locations": [], "providers": [],
        "created_at": now, "updated_at": now,
    }
    await db.organizations.insert_one({**org})
    res = await db.users.insert_one({
        "email": email, "password_hash": authlib.hash_password(body.password),
        "name": f"{body.contact_first_name} {body.contact_last_name}".strip(),
        "role": "partner", "organization_id": org_id, "active": True, "created_at": now,
    })
    uid = str(res.inserted_id)
    await audit("register", "organization", org_id,
                {"id": uid, "name": org["organization_name"], "role": "partner"},
                new_status="UNVERIFIED",
                meta={"type": body.organization_type, "source": "PARTNER_SUBMITTED",
                      "possible_duplicate": bool(dup)})
    token = authlib.create_access_token(uid, email, "partner")
    user = await db.users.find_one({"_id": res.inserted_id})
    return {"token": token, "user": serialize_user(user)}


@api.get("/partner/me")
async def partner_me(user: dict = Depends(require_roles("partner"))):
    org = await db.organizations.find_one({"id": user.get("organization_id")})
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return {"user": user, "organization": orgs_mod.serialize_org(org)}


@api.put("/partner/profile")
async def partner_update_profile(body: PartnerProfileBody, user: dict = Depends(require_roles("partner"))):
    org = await db.organizations.find_one({"id": user.get("organization_id")})
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items()}
    if updates.get("phone"):
        updates["phone"] = identity_mod.normalize_phone(updates["phone"])
    if "locations" in updates:
        updates["locations"] = orgs_mod.ensure_ids(updates["locations"], "loc")
    if "providers" in updates:
        # Providers are a SEPARATE entity: canonical records live in the global
        # `providers` registry (stable global id, reusable across organizations),
        # while the org only stores an AFFILIATION (provider_id + which of this
        # org's locations they work at). This lets one provider be affiliated with
        # multiple organizations in the future without duplicating identity.
        valid_loc_ids = {l.get("id") for l in (updates.get("locations")
                         if "locations" in updates else org.get("locations", [])) if l.get("id")}
        now = now_iso()
        affiliations = []
        for p in updates["providers"]:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            specialties = (p.get("specialties") or p.get("specialty") or "").strip()
            loc_ids = [lid for lid in (p.get("location_ids") or []) if lid in valid_loc_ids]
            pid = p.get("id") or p.get("provider_id")
            existing = await db.providers.find_one({"id": pid}) if pid else None
            if existing:
                await db.providers.update_one({"id": pid}, {"$set": {"name": name, "specialties": specialties, "updated_at": now}})
            else:
                pid = f"prov_{uuid.uuid4().hex[:10]}"
                await db.providers.insert_one({"id": pid, "name": name, "specialties": specialties,
                                               "created_by_org_id": user["organization_id"],
                                               "created_at": now, "updated_at": now})
            affiliations.append({"id": pid, "provider_id": pid, "name": name,
                                 "specialty": specialties, "location_ids": loc_ids})
        updates["providers"] = affiliations
    if not updates:
        return {"organization": orgs_mod.serialize_org(org)}
    updates["updated_at"] = now_iso()
    await db.organizations.update_one({"id": user["organization_id"]}, {"$set": updates})
    await audit("update", "organization", user["organization_id"],
                {"id": user["id"], "name": org["organization_name"], "role": "partner"},
                meta={"fields": list(updates.keys())})
    org = await db.organizations.find_one({"id": user["organization_id"]})
    return {"organization": orgs_mod.serialize_org(org)}


@api.get("/partner/org-types")
async def partner_org_types():
    return {"types": orgs_mod.ORG_TYPES}


# ----------------------------- Internal: Organizations directory -----------------------------
@api.get("/internal/organizations")
async def internal_organizations(type: Optional[str] = None, status: Optional[str] = None,
                                 q: Optional[str] = None,
                                 user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if type:
        query["organization_type"] = type
    if status:
        query["verification_status"] = status
    if q:
        qn = q.strip()
        query["$or"] = [
            {"organization_name": {"$regex": re.escape(qn), "$options": "i"}},
            {"email": {"$regex": re.escape(qn), "$options": "i"}},
            {"city": {"$regex": re.escape(qn), "$options": "i"}},
        ]
    docs = await db.organizations.find(query).sort("created_at", -1).to_list(500)
    return [orgs_mod.serialize_org(d) for d in docs]


@api.post("/internal/organizations/{org_id}/verification")
async def set_org_verification(org_id: str, body: OrgVerificationBody,
                               user: dict = Depends(require_roles(*CLINIC_ROLES))):
    if body.status not in orgs_mod.VERIFICATION_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid verification status.")
    org = await db.organizations.find_one({"id": org_id})
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    prev = org.get("verification_status")
    await db.organizations.update_one({"id": org_id},
                                      {"$set": {"verification_status": body.status, "updated_at": now_iso()}})
    # SUSPENDED blocks the partner login; any other status re-enables it. UNVERIFIED stays active.
    await db.users.update_one({"organization_id": org_id, "role": "partner"},
                              {"$set": {"active": body.status != "SUSPENDED"}})
    await audit("status_change", "organization", org_id,
                {"id": user["id"], "name": user["name"], "role": user["role"]},
                old_status=prev, new_status=body.status, meta={"note": body.note})
    org = await db.organizations.find_one({"id": org_id})
    return orgs_mod.serialize_org(org)


# ----------------------------- Internal: Provider registry (read-only) -----------------------------
@api.get("/internal/providers")
async def internal_providers(q: Optional[str] = None,
                             user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Read-only Provider → Organization → Location inspection view for clinic
    staff. Providers are global entities; affiliations (with linked locations)
    are resolved from the organizations collection. No PHI is exposed."""
    providers = await db.providers.find({}).sort("name", 1).to_list(1000)
    orgs = await db.organizations.find({}).to_list(1000)
    rows = [orgs_mod.build_provider_view(p, orgs) for p in providers]
    if q and q.strip():
        qn = q.strip().lower()
        def match(r):
            if qn in (r.get("name") or "").lower():
                return True
            if qn in (r.get("specialties") or "").lower():
                return True
            return any(qn in (a.get("organization_name") or "").lower() for a in r.get("affiliations", []))
        rows = [r for r in rows if match(r)]
    return rows


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
    lang = "en"
    if user.get("patient_id"):
        pat = await db.patients.find_one({"id": user["patient_id"]}, {"preferred_language": 1})
        lang = email_service.norm_lang((pat or {}).get("preferred_language"))
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
            subject=email_service.subject("reset_code", lang),
            html=email_service.reset_code_html(user.get("name"), code, lang=lang),
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


class ActivateValidateBody(BaseModel):
    uid: str
    token: str


class ActivateSetBody(BaseModel):
    uid: str
    token: str
    new_password: str


async def _valid_activation(uid: str, token: str):
    rec = await db.account_activations.find_one({"user_id": uid})
    if not rec or rec.get("used"):
        return None
    try:
        if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
            return None
    except Exception:
        return None
    if not authlib.verify_password(token, rec["token_hash"]):
        return None
    return rec


@api.post("/auth/activate/validate")
async def activate_validate(body: ActivateValidateBody):
    rec = await _valid_activation(body.uid, body.token)
    if not rec:
        raise HTTPException(status_code=400, detail="This activation link is invalid or has expired. Please contact the clinic.")
    try:
        u = await db.users.find_one({"_id": ObjectId(body.uid)})
    except Exception:
        u = None
    if not u:
        raise HTTPException(status_code=400, detail="This activation link is invalid or has expired. Please contact the clinic.")
    return {"ok": True, "email": u.get("email"), "name": u.get("name")}


@api.post("/auth/activate")
async def activate_set(body: ActivateSetBody):
    if len((body.new_password or "")) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    rec = await _valid_activation(body.uid, body.token)
    if not rec:
        raise HTTPException(status_code=400, detail="This activation link is invalid or has expired. Please contact the clinic.")
    try:
        u = await db.users.find_one({"_id": ObjectId(body.uid)})
    except Exception:
        u = None
    if not u:
        raise HTTPException(status_code=400, detail="This activation link is invalid or has expired. Please contact the clinic.")
    await db.users.update_one({"_id": u["_id"]}, {"$set": {
        "password_hash": authlib.hash_password(body.new_password),
        "pending_activation": False, "must_change_password": False,
        "password_changed_at": now_iso(),
    }})
    await db.account_activations.update_one({"user_id": body.uid}, {"$set": {"used": True, "used_at": now_iso()}})
    await audit("account_activated", "user", body.uid,
                {"id": body.uid, "name": u.get("name"), "role": u.get("role")})
    access = authlib.create_access_token(body.uid, u.get("email"), u["role"])
    fresh = await db.users.find_one({"_id": u["_id"]})
    return {"token": access, "user": serialize_user(fresh)}


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
async def get_settings(user: dict = Depends(require_roles("admin", "physician"))):
    s = await db.settings.find_one({"id": "clinic"}, {"_id": 0})
    t = await db.templates.find_one({"id": "templates"}, {"_id": 0})
    return {"settings": s or {}, "templates": (t or {}).get("items", {})}


@api.put("/admin/settings")
async def update_settings(payload: dict, user: dict = Depends(require_roles("admin", "physician"))):
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
async def get_availability(user: dict = Depends(require_roles("admin", "physician"))):
    return await get_availability_doc()


@api.put("/admin/availability")
async def put_availability(payload: dict, user: dict = Depends(require_roles("admin", "physician"))):
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
    # Batch-resolve VISITA PINs so the calendar can be searched by PIN.
    pids = {a.get("patient_id") for a in appts if a.get("patient_id")}
    dids = {a.get("directory_id") for a in appts if a.get("directory_id")}
    pin_map = {}
    if pids:
        async for p in db.patients.find({"id": {"$in": list(pids)}}, {"_id": 0, "id": 1, "visita_patient_id": 1}):
            if p.get("visita_patient_id"):
                pin_map[p["id"]] = p["visita_patient_id"]
    if dids:
        async for d in db.patient_directory.find({"id": {"$in": list(dids)}}, {"_id": 0, "id": 1, "visita_patient_id": 1}):
            if d.get("visita_patient_id"):
                pin_map[d["id"]] = d["visita_patient_id"]
    by_day = {}
    for a in appts:
        by_day.setdefault(a["confirmed_date"], []).append({
            "id": a["id"], "ref_number": a.get("ref_number"),
            "time": a.get("confirmed_slot_time") or avail_mod._norm_time(a.get("confirmed_time") or ""),
            "label": a.get("confirmed_time"), "patient_name": a.get("patient_name"),
            "visita_patient_id": pin_map.get(a.get("patient_id")) or pin_map.get(a.get("directory_id")),
            "status": a.get("status"), "reason": a.get("reason"),
            "appointment_type": a.get("appointment_type"),
            "is_private": bool(a.get("is_private")),
            "source": (a.get("booked_from") or {}).get("source_type") or "appointment",
        })
    for row in day_rows:
        row["appointments"] = sorted(by_day.get(row["date"], []), key=lambda x: x["time"] or "")
        row["day_blocked"] = any(b.get("date") == row["date"] and b.get("block_day")
                                 for b in avail.get("blocked_periods", []))
    return {"timezone": avail.get("timezone"), "duration": avail.get("appointment_duration"), "days": day_rows}

@api.get("/internal/appointment-search")
async def internal_appointment_search(q: str = "", limit: int = 30,
                                      user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Global appointment search across all dates (not limited to a calendar view).
    Matches partial first/last name (case-insensitive) or VISITA PIN. Upcoming
    appointments first (soonest first), then most recent past. Reuses batched PIN
    resolution — no per-row lookups."""
    from datetime import date as _date
    term = (q or "").strip()
    if len(term) < 2:
        return {"results": []}
    limit = min(max(limit, 1), 50)
    status_filter = {"$in": ["confirmed", "rescheduled", "completed", "no_show"]}

    # PIN match -> resolve to patient/directory ids so we can match appointments.
    pin_owner_ids = set()
    if term.isdigit():
        async for p in db.patients.find({"visita_patient_id": term}, {"_id": 0, "id": 1}):
            pin_owner_ids.add(p["id"])
        async for d in db.patient_directory.find({"visita_patient_id": term}, {"_id": 0, "id": 1}):
            pin_owner_ids.add(d["id"])

    name_rx = {"$regex": re.escape(term), "$options": "i"}
    or_clauses = [{"patient_name": name_rx}]
    if pin_owner_ids:
        or_clauses.append({"patient_id": {"$in": list(pin_owner_ids)}})
        or_clauses.append({"directory_id": {"$in": list(pin_owner_ids)}})
    query = {"status": status_filter, "$or": or_clauses}

    appts = await db.appointment_requests.find(query, {"_id": 0}).to_list(400)
    # Batch-resolve VISITA PINs for the matched set.
    pids = {a.get("patient_id") for a in appts if a.get("patient_id")}
    dids = {a.get("directory_id") for a in appts if a.get("directory_id")}
    pin_map = {}
    if pids:
        async for p in db.patients.find({"id": {"$in": list(pids)}}, {"_id": 0, "id": 1, "visita_patient_id": 1}):
            if p.get("visita_patient_id"):
                pin_map[p["id"]] = p["visita_patient_id"]
    if dids:
        async for d in db.patient_directory.find({"id": {"$in": list(dids)}}, {"_id": 0, "id": 1, "visita_patient_id": 1}):
            if d.get("visita_patient_id"):
                pin_map[d["id"]] = d["visita_patient_id"]

    today = _date.today().isoformat()
    results = []
    for a in appts:
        date = a.get("confirmed_date")
        if not date:
            continue
        results.append({
            "id": a["id"], "ref_number": a.get("ref_number"),
            "date": date,
            "time": a.get("confirmed_slot_time") or avail_mod._norm_time(a.get("confirmed_time") or ""),
            "label": a.get("confirmed_time"), "patient_name": a.get("patient_name"),
            "visita_patient_id": pin_map.get(a.get("patient_id")) or pin_map.get(a.get("directory_id")),
            "status": a.get("status"), "reason": a.get("reason"),
            "appointment_type": a.get("appointment_type"),
            "is_private": bool(a.get("is_private")),
            "source": (a.get("booked_from") or {}).get("source_type") or "appointment",
        })
    # Upcoming first (soonest first), then past (most recent first).
    upcoming = sorted([r for r in results if r["date"] >= today], key=lambda r: (r["date"], r["time"] or ""))
    past = sorted([r for r in results if r["date"] < today], key=lambda r: (r["date"], r["time"] or ""), reverse=True)
    return {"results": (upcoming + past)[:limit]}




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


# ============================ PRIVATE / UNINSURED WORKFLOW (Phase 1) ============================
PRIVATE_TYPES = {"private", "tourist", "uninsured"}
PRIVATE_STATUS = {"REQUESTED", "IN_REVIEW", "OFFERED", "AWAITING_PATIENT",
                  "CONFIRMED", "COMPLETED", "DECLINED", "CANCELLED"}
DEFAULT_ETRANSFER_EMAIL = "dufferinpatients@gmail.com"
DEFAULT_PRIVATE_HOURS = "Monday–Wednesday, 5:30 PM–9:00 PM"


async def get_private_config():
    doc = await db.settings.find_one({"id": "private_config"}) or {}
    return {
        "etransfer_email": doc.get("etransfer_email") or DEFAULT_ETRANSFER_EMAIL,
        "private_hours": doc.get("private_hours") or DEFAULT_PRIVATE_HOURS,
        "private_days": doc.get("private_days") or ["mon", "tue", "wed"],
        "private_window": doc.get("private_window") or {"start": "17:30", "end": "21:00"},
    }


class PrivateRequestBody(BaseModel):
    preference_mode: str            # SPECIFIC | OTHER | NO_PREFERENCE
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None
    reason_codes: List[str] = []
    note: Optional[str] = None


class PrivateMessageBody(BaseModel):
    message: str


class PrivateOfferBody(BaseModel):
    date: str
    time: str
    label: Optional[str] = None
    note: Optional[str] = None


class PrivateReasonBody(BaseModel):
    reason: Optional[str] = None


def pr_actor(user):
    return user.get("name") or user.get("email") or "patient"


def serialize_private(pr: dict) -> dict:
    return {k: v for k, v in pr.items() if k != "_id"}


async def _notify_physician_new_private(pr: dict):
    await db.internal_messages.insert_one({
        "id": str(uuid.uuid4()), "ref_number": await next_ref("TSK"),
        "sender_name": "System", "sender_user_id": None,
        "recipient_role": "physician", "patient_id": pr.get("patient_id"),
        "patient_name": pr.get("patient_name"),
        "message": f"New PRIVATE / UNINSURED appointment request {pr['ref_number']} submitted.",
        "status": "pending", "created_at": now_iso(), "updated_at": now_iso(),
        "source": "private_request", "private_request_id": pr["id"],
    })


async def _private_patient_note(pr, title, body):
    if pr.get("patient_id"):
        await notify_svc._in_portal(db, pr["patient_id"], title, body)


async def _create_private_appointment(pr: dict, ds: str, time_str: str, label, actor_name: str):
    avail = await get_availability_doc()
    time24 = avail_mod._norm_time(time_str)
    busy = await get_busy_slots()
    if not avail_mod.is_valid_private_time(time24):
        raise HTTPException(status_code=400, detail=avail_mod.PRIVATE_TIME_ERROR)
    err = avail_mod.private_conflict(avail, ds, time24, busy)
    if err:
        raise HTTPException(status_code=409, detail=err)
    ref = await next_ref("APT")
    appt = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": pr["patient_id"],
        "directory_id": pr.get("directory_id"), "patient_name": pr.get("patient_name"),
        "reason": pr.get("reason_label") or "Private consultation",
        "appointment_type": "PRIVATE", "is_private": True,
        "duration": avail.get("appointment_duration"), "preferred_options": [],
        "status": "confirmed", "confirmed_date": ds,
        "confirmed_time": label or time_str, "confirmed_slot_time": time24,
        "confirmed_display": f"{fmt_date_display(ds)} · {label or time_str}",
        "approved_by": actor_name, "approved_at": now_iso(), "booked_by": actor_name,
        "booked_from": {"source_type": "private_request", "source_id": pr["id"]},
        "assigned_to": None, "internal_notes": [],
        "history": [{"status": "confirmed", "at": now_iso(), "by": actor_name, "note": "Private request confirmed"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.appointment_requests.insert_one({**appt})
    await notify_svc.appointment_confirmed(db, appt)
    appt.pop("_id", None)
    return appt


@api.get("/config/private")
async def config_private(user: dict = Depends(get_current_user)):
    return await get_private_config()


@api.get("/config/reasons")
async def config_reasons(user: dict = Depends(get_current_user)):
    return private_reasons.REASON_TAXONOMY


@api.post("/portal/private-requests")
async def create_private_request(body: PrivateRequestBody, user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    if (p.get("patient_type") or "ohip") not in PRIVATE_TYPES:
        raise HTTPException(status_code=403, detail="This request type is only for private/uninsured/visitor patients.")
    if body.preference_mode not in {"SPECIFIC", "OTHER", "NO_PREFERENCE"}:
        raise HTTPException(status_code=400, detail="Invalid preference selection.")
    labels = private_reasons.validate_path(body.reason_codes)
    if not labels:
        raise HTTPException(status_code=400, detail="Please choose a complete reason for your visit.")
    if body.preference_mode in {"SPECIFIC", "OTHER"} and not (body.preferred_date and body.preferred_time):
        raise HTTPException(status_code=400, detail="Please provide your preferred date and approximate time.")
    now = now_iso()
    actor = pr_actor(user)
    pr = {
        "id": str(uuid.uuid4()), "ref_number": await next_ref("PRV"),
        "patient_id": p["id"], "directory_id": p.get("matched_directory_id"),
        "patient_name": f"{p.get('last_name','')}, {p.get('first_name','')}".strip(", "),
        "patient_type": p.get("patient_type"),
        "preference_mode": body.preference_mode,
        "preferred_date": body.preferred_date, "preferred_time": body.preferred_time,
        "reason_codes": body.reason_codes, "reason_path": labels,
        "reason_label": labels[-1], "note": (body.note or "").strip()[:500] or None,
        "payment_mode": None, "payment_status": "NONE", "status": "REQUESTED",
        "offered_date": None, "offered_time": None, "offered_label": None,
        "confirmed_appointment_id": None,
        "thread": [], "history": [{"status": "REQUESTED", "at": now, "by": actor}],
        "created_at": now, "updated_at": now,
    }
    await db.private_requests.insert_one({**pr})
    await _notify_physician_new_private(pr)
    await audit("private_request_submitted", "private_request", pr["id"], user, new_status="REQUESTED")
    return serialize_private(pr)


@api.get("/portal/private-requests")
async def my_private_requests(user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    return await db.private_requests.find({"patient_id": p["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)


async def _get_owned_private(user, rid):
    p = await get_patient_record(user)
    pr = await db.private_requests.find_one({"id": rid})
    if not pr or pr.get("patient_id") != p["id"]:
        raise HTTPException(status_code=404, detail="Request not found.")
    return p, pr


@api.get("/portal/private-requests/{rid}")
async def my_private_request(rid: str, user: dict = Depends(get_current_user)):
    _, pr = await _get_owned_private(user, rid)
    return serialize_private(pr)


@api.post("/portal/private-requests/{rid}/messages")
async def private_patient_message(rid: str, body: PrivateMessageBody, user: dict = Depends(get_current_user)):
    _, pr = await _get_owned_private(user, rid)
    msg = {"from": "patient", "by": pr_actor(user), "message": body.message.strip()[:1000], "at": now_iso()}
    await db.private_requests.update_one({"id": rid}, {"$push": {"thread": msg}, "$set": {"updated_at": now_iso()}})
    await db.internal_messages.insert_one({
        "id": str(uuid.uuid4()), "ref_number": await next_ref("TSK"), "sender_name": pr.get("patient_name"),
        "recipient_role": "physician", "patient_id": pr.get("patient_id"), "patient_name": pr.get("patient_name"),
        "message": f"Patient replied on private request {pr['ref_number']}.", "status": "pending",
        "created_at": now_iso(), "updated_at": now_iso(), "source": "private_request", "private_request_id": rid,
    })
    await audit("private_request_message", "private_request", rid, user)
    return {"ok": True}


@api.post("/portal/private-requests/{rid}/accept")
async def private_patient_accept(rid: str, user: dict = Depends(get_current_user)):
    _, pr = await _get_owned_private(user, rid)
    if pr.get("status") not in {"OFFERED", "AWAITING_PATIENT"}:
        raise HTTPException(status_code=400, detail="There is no offer awaiting your acceptance.")
    appt = await _create_private_appointment(pr, pr["offered_date"], pr["offered_time"], pr.get("offered_label"), pr_actor(user))
    await db.private_requests.update_one({"id": rid}, {"$set": {
        "status": "CONFIRMED", "confirmed_appointment_id": appt["id"], "updated_at": now_iso()},
        "$push": {"history": {"status": "CONFIRMED", "at": now_iso(), "by": pr_actor(user), "note": "Patient accepted offer"}}})
    await audit("private_appointment_accepted", "private_request", rid, user, new_status="CONFIRMED")
    return {"ok": True, "appointment_id": appt["id"]}


@api.post("/portal/private-requests/{rid}/decline")
async def private_patient_decline(rid: str, body: PrivateReasonBody, user: dict = Depends(get_current_user)):
    _, pr = await _get_owned_private(user, rid)
    if pr.get("status") not in {"OFFERED", "AWAITING_PATIENT"}:
        raise HTTPException(status_code=400, detail="Nothing to decline.")
    await db.private_requests.update_one({"id": rid}, {"$set": {"status": "DECLINED", "updated_at": now_iso()},
        "$push": {"history": {"status": "DECLINED", "at": now_iso(), "by": pr_actor(user), "note": body.reason or "Patient declined offer"}}})
    await audit("private_request_declined", "private_request", rid, user, new_status="DECLINED")
    return {"ok": True}


@api.post("/portal/private-requests/{rid}/cancel")
async def private_patient_cancel(rid: str, body: PrivateReasonBody, user: dict = Depends(get_current_user)):
    _, pr = await _get_owned_private(user, rid)
    if pr.get("status") in {"COMPLETED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="This request can no longer be cancelled.")
    await _cancel_private(pr, pr_actor(user), body.reason)
    await audit("private_request_cancelled", "private_request", rid, user, new_status="CANCELLED")
    return {"ok": True}


async def _cancel_private(pr, actor, reason):
    appt_id = pr.get("confirmed_appointment_id")
    if appt_id:
        appt = await db.appointment_requests.find_one({"id": appt_id})
        if appt and appt.get("status") in {"confirmed", "rescheduled"}:
            await db.appointment_requests.update_one({"id": appt_id}, {"$set": {"status": "cancelled", "updated_at": now_iso()}})
            await notify_svc.cancel_reminders(db, appt_id)
            fresh = await db.appointment_requests.find_one({"id": appt_id}, {"_id": 0})
            await notify_svc.appointment_cancelled(db, fresh, reason=reason)
    await db.private_requests.update_one({"id": pr["id"]}, {"$set": {"status": "CANCELLED", "updated_at": now_iso()},
        "$push": {"history": {"status": "CANCELLED", "at": now_iso(), "by": actor, "note": reason or "Cancelled"}}})


@api.get("/internal/private-requests")
async def internal_private_requests(status: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    q = {"status": status} if status else {}
    return await db.private_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.get("/internal/private-requests/{rid}")
async def internal_private_request(rid: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pr = await db.private_requests.find_one({"id": rid}, {"_id": 0})
    if not pr:
        raise HTTPException(status_code=404, detail="Request not found.")
    invs = await db.invoices.find({"private_request_id": rid}).sort("created_at", -1).to_list(100)
    pr["invoices"] = [billing_mod.invoice_internal(i) for i in invs]
    return pr


@api.post("/internal/private-requests/{rid}/review")
async def internal_private_review(rid: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pr = await db.private_requests.find_one({"id": rid})
    if not pr:
        raise HTTPException(status_code=404, detail="Request not found.")
    if pr.get("status") == "REQUESTED":
        await db.private_requests.update_one({"id": rid}, {"$set": {"status": "IN_REVIEW", "updated_at": now_iso()},
            "$push": {"history": {"status": "IN_REVIEW", "at": now_iso(), "by": user["name"]}}})
        await audit("private_request_reviewed", "private_request", rid, user, new_status="IN_REVIEW")
    return {"ok": True}


@api.post("/internal/private-requests/{rid}/messages")
async def internal_private_message(rid: str, body: PrivateMessageBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pr = await db.private_requests.find_one({"id": rid})
    if not pr:
        raise HTTPException(status_code=404, detail="Request not found.")
    msg = {"from": "clinic", "by": user["name"], "message": body.message.strip()[:1000], "at": now_iso()}
    await db.private_requests.update_one({"id": rid}, {"$push": {"thread": msg}, "$set": {"updated_at": now_iso()}})
    await _private_patient_note(pr, "Message from the clinic", f"The clinic sent a message about your private request {pr['ref_number']}.")
    await audit("private_request_message", "private_request", rid, user)
    return {"ok": True}


@api.post("/internal/private-requests/{rid}/accept-requested")
async def internal_private_accept_requested(rid: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pr = await db.private_requests.find_one({"id": rid})
    if not pr:
        raise HTTPException(status_code=404, detail="Request not found.")
    if pr.get("status") in {"CONFIRMED", "COMPLETED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="This request is already resolved.")
    if pr.get("preference_mode") != "SPECIFIC" or not (pr.get("preferred_date") and pr.get("preferred_time")):
        raise HTTPException(status_code=400, detail="No specific requested time to accept. Offer a date/time instead.")
    appt = await _create_private_appointment(pr, pr["preferred_date"], pr["preferred_time"], None, user["name"])
    await db.private_requests.update_one({"id": rid}, {"$set": {
        "status": "CONFIRMED", "confirmed_appointment_id": appt["id"], "updated_at": now_iso()},
        "$push": {"history": {"status": "CONFIRMED", "at": now_iso(), "by": user["name"], "note": "Accepted requested time"}}})
    await _private_patient_note(pr, "Your private appointment is confirmed", f"Your private request {pr['ref_number']} was confirmed for {appt['confirmed_display']}.")
    await audit("private_appointment_confirmed", "private_request", rid, user, new_status="CONFIRMED")
    return {"ok": True, "appointment_id": appt["id"]}


@api.post("/internal/private-requests/{rid}/offer")
async def internal_private_offer(rid: str, body: PrivateOfferBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pr = await db.private_requests.find_one({"id": rid})
    if not pr:
        raise HTTPException(status_code=404, detail="Request not found.")
    if pr.get("status") in {"CONFIRMED", "COMPLETED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="This request is already resolved.")
    avail = await get_availability_doc()
    busy = await get_busy_slots()
    if not avail_mod.is_valid_private_time(body.time):
        raise HTTPException(status_code=400, detail=avail_mod.PRIVATE_TIME_ERROR)
    err = avail_mod.private_conflict(avail, body.date, avail_mod._norm_time(body.time), busy)
    if err:
        raise HTTPException(status_code=409, detail=err)
    now = now_iso()
    if body.note:
        await db.private_requests.update_one({"id": rid}, {"$push": {"thread": {"from": "clinic", "by": user["name"], "message": body.note.strip()[:1000], "at": now}}})
    await db.private_requests.update_one({"id": rid}, {"$set": {
        "status": "AWAITING_PATIENT", "offered_date": body.date, "offered_time": body.time,
        "offered_label": body.label or body.time, "updated_at": now},
        "$push": {"history": {"status": "AWAITING_PATIENT", "at": now, "by": user["name"],
                              "note": f"Offered {fmt_date_display(body.date)} · {body.label or body.time}"}}})
    await _private_patient_note(pr, "A new appointment time was offered", f"The clinic offered {fmt_date_display(body.date)} · {body.label or body.time} for your private request {pr['ref_number']}. Please accept or decline.")
    await audit("private_appointment_offered", "private_request", rid, user, new_status="AWAITING_PATIENT")
    return {"ok": True}


@api.post("/internal/private-requests/{rid}/decline")
async def internal_private_decline(rid: str, body: PrivateReasonBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pr = await db.private_requests.find_one({"id": rid})
    if not pr:
        raise HTTPException(status_code=404, detail="Request not found.")
    if pr.get("status") in {"COMPLETED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="This request is already resolved.")
    await db.private_requests.update_one({"id": rid}, {"$set": {"status": "DECLINED", "updated_at": now_iso()},
        "$push": {"history": {"status": "DECLINED", "at": now_iso(), "by": user["name"], "note": body.reason or "Declined by clinic"}}})
    await _private_patient_note(pr, "Private appointment request update", f"Your private request {pr['ref_number']} was declined. Please contact the clinic for details.")
    await audit("private_request_declined", "private_request", rid, user, new_status="DECLINED")
    return {"ok": True}


@api.post("/internal/private-requests/{rid}/cancel")
async def internal_private_cancel(rid: str, body: PrivateReasonBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pr = await db.private_requests.find_one({"id": rid})
    if not pr:
        raise HTTPException(status_code=404, detail="Request not found.")
    if pr.get("status") in {"COMPLETED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="This request is already resolved.")
    await _cancel_private(pr, user["name"], body.reason)
    await _private_patient_note(pr, "Private appointment cancelled", f"Your private request {pr['ref_number']} was cancelled.")
    await audit("private_request_cancelled", "private_request", rid, user, new_status="CANCELLED")
    return {"ok": True}


# ============================ PRIVATE / UNINSURED BILLING (Phase 2) ============================
# Invoices + Interac e-Transfer payment-proof handling. Billing is a SEPARATE
# state machine from appointment/request status. Access: owning patient + clinic
# roles only; pharmacy/partner/unrelated patients are denied. No public URLs.
BILLING_MANAGE_ROLES = ("staff", "physician", "admin")   # create / issue / read / set mode
BILLING_VERIFY_ROLES = ("staff", "admin")                # verify receipt + void (financial)


class PaymentModeBody(BaseModel):
    payment_mode: str
    amount: Optional[float] = None
    service_description: Optional[str] = None
    service_code: Optional[str] = None
    internal_note: Optional[str] = None


class InvoiceCreateBody(BaseModel):
    patient_id: str
    private_request_id: Optional[str] = None
    service_description: str
    service_code: Optional[str] = None
    amount: float
    payment_mode: Optional[str] = "INVOICE_AFTER_SERVICE"
    internal_note: Optional[str] = None


class InvoiceUpdateBody(BaseModel):
    service_description: Optional[str] = None
    service_code: Optional[str] = None
    amount: Optional[float] = None
    internal_note: Optional[str] = None


async def _get_invoice_or_404(inv_id: str) -> dict:
    inv = await db.invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return inv


async def _sync_request_billing(rid: Optional[str]):
    """Mirror the latest non-void linked invoice onto the private request's
    payment_status (display only — never touches appointment status)."""
    if not rid:
        return
    pr = await db.private_requests.find_one({"id": rid})
    if not pr:
        return
    mode = pr.get("payment_mode")
    invs = await db.invoices.find({"private_request_id": rid, "status": {"$ne": "VOID"}}).sort("created_at", -1).to_list(50)
    status = "NONE"
    if invs:
        latest = invs[0]["status"]
        status = {"DRAFT": "PENDING" if mode == "PREPAYMENT_REQUIRED" else "NONE",
                  "ISSUED": "PENDING", "PAYMENT_SUBMITTED": "PAYMENT_SUBMITTED",
                  "PAID": "PAID"}.get(latest, "NONE")
    elif mode == "PREPAYMENT_REQUIRED":
        status = "PENDING"
    await db.private_requests.update_one({"id": rid}, {"$set": {"payment_status": status, "updated_at": now_iso()}})


async def _create_invoice(patient: dict, *, service_description, amount, payment_mode,
                          service_code=None, internal_note=None, private_request_id=None,
                          appointment_id=None, is_no_show=False,
                          billing_method=None, billing_meta=None,
                          user, status="DRAFT") -> dict:
    if payment_mode not in billing_mod.PAYMENT_MODES:
        raise HTTPException(status_code=400, detail="Invalid payment mode.")
    amt = billing_mod.normalize_amount(amount)
    desc = (service_description or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="Please provide a service description.")
    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()), "invoice_number": await next_ref("INV"),
        "patient_id": patient["id"],
        "patient_name": f"{patient.get('last_name','')}, {patient.get('first_name','')}".strip(", "),
        "private_request_id": private_request_id,
        "appointment_id": appointment_id, "is_no_show": is_no_show,
        "patient_coverage": patient.get("patient_type"),
        "billing_method": billing_method,
        "service_code": (service_code or "").strip() or None, "service_description": desc,
        "amount": amt, "currency": "CAD",
        "status": status, "payment_mode": payment_mode,
        "issue_date": now[:10] if status == "ISSUED" else None,
        "created_by": user["name"], "created_by_id": user["id"], "created_at": now,
        "issued_at": now if status == "ISSUED" else None,
        "payment_submitted_at": None, "paid_at": None, "voided_at": None,
        "internal_note": (internal_note or "").strip() or None,
        "payment_proof": None, "updated_at": now,
        **(billing_meta or {}),
    }
    await db.invoices.insert_one({**doc})
    await audit("invoice_created", "invoice", doc["id"], user, new_status=status,
                meta={"invoice_number": doc["invoice_number"], "patient_id": patient["id"],
                      "private_request_id": private_request_id, "amount": amt, "payment_mode": payment_mode})
    if status == "ISSUED":
        await audit("invoice_issued", "invoice", doc["id"], user, new_status="ISSUED",
                    meta={"invoice_number": doc["invoice_number"], "patient_id": patient["id"]})
        await notify_svc._in_portal(db, patient["id"], "New invoice",
                                    f"Invoice {doc['invoice_number']} for {doc['service_description']} is now available in your portal.")
    doc.pop("_id", None)
    return doc


async def _notify_clinic_payment_submitted(inv: dict):
    await db.internal_messages.insert_one({
        "id": str(uuid.uuid4()), "ref_number": await next_ref("TSK"),
        "sender_name": inv.get("patient_name"), "sender_user_id": None,
        "recipient_role": "staff", "patient_id": inv.get("patient_id"), "patient_name": inv.get("patient_name"),
        "message": f"Payment proof submitted for invoice {inv['invoice_number']} — pending verification.",
        "status": "pending", "created_at": now_iso(), "updated_at": now_iso(),
        "source": "invoice", "invoice_id": inv["id"],
    })


@api.post("/internal/private-requests/{rid}/payment-mode")
async def set_private_payment_mode(rid: str, body: PaymentModeBody, user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    pr = await db.private_requests.find_one({"id": rid})
    if not pr:
        raise HTTPException(status_code=404, detail="Request not found.")
    if body.payment_mode not in billing_mod.PAYMENT_MODES:
        raise HTTPException(status_code=400, detail="Invalid payment mode.")
    await db.private_requests.update_one({"id": rid}, {"$set": {"payment_mode": body.payment_mode, "updated_at": now_iso()},
        "$push": {"history": {"status": pr.get("status"), "at": now_iso(), "by": user["name"], "note": f"Payment mode set to {body.payment_mode}"}}})
    await audit("payment_mode_set", "private_request", rid, user, meta={"payment_mode": body.payment_mode, "patient_id": pr.get("patient_id")})
    invoice = None
    if body.payment_mode == "PREPAYMENT_REQUIRED":
        if not pr.get("patient_id"):
            raise HTTPException(status_code=400, detail="This request has no linked portal patient to bill.")
        patient = await db.patients.find_one({"id": pr["patient_id"]}, {"_id": 0})
        if not patient:
            raise HTTPException(status_code=400, detail="Linked patient account not found.")
        invoice = await _create_invoice(
            patient, service_description=body.service_description or pr.get("reason_label") or "Private consultation",
            amount=body.amount, payment_mode="PREPAYMENT_REQUIRED", service_code=body.service_code,
            internal_note=body.internal_note, private_request_id=rid, user=user, status="ISSUED")
        await _private_patient_note(pr, "Payment required",
                                    f"Prepayment is required for your private request {pr['ref_number']}. Please open Invoices in your portal to pay by Interac e-Transfer and upload your proof of payment.")
    await _sync_request_billing(rid)
    return {"ok": True, "payment_mode": body.payment_mode,
            "invoice": billing_mod.invoice_internal(invoice) if invoice else None}


@api.post("/internal/invoices")
async def create_invoice(body: InvoiceCreateBody, user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    patient = await db.patients.find_one({"id": body.patient_id}, {"_id": 0})
    if not patient:
        raise HTTPException(status_code=404, detail="Patient account not found. Invoices can only be issued to registered portal patients.")
    mode = body.payment_mode or "INVOICE_AFTER_SERVICE"
    if mode == "NO_PAYMENT_REQUIRED":
        raise HTTPException(status_code=400, detail="An invoice must use a payable mode.")
    if body.private_request_id and not await db.private_requests.find_one({"id": body.private_request_id}):
        raise HTTPException(status_code=404, detail="Linked private request not found.")
    inv = await _create_invoice(patient, service_description=body.service_description, amount=body.amount,
                                payment_mode=mode, service_code=body.service_code, internal_note=body.internal_note,
                                private_request_id=body.private_request_id, user=user, status="DRAFT")
    if body.private_request_id:
        await _sync_request_billing(body.private_request_id)
    return billing_mod.invoice_internal(inv)


# ---- Direct 3rd Party Billing ------------------------------------------------
async def _direct_billing_config(active_only: bool = False) -> dict:
    s = await db.settings.find_one({"id": "clinic"}, {"_id": 0}) or {}
    services = s.get("direct_billing_services") or []
    clean = []
    for x in services:
        code = str(x.get("code") or "").strip()
        desc = (x.get("description") or "").strip()
        if not code or not desc:
            continue
        active = bool(x.get("active", True))
        if active_only and not active:
            continue
        clean.append({
            "code": code,
            "category": (x.get("category") or "OTHER").strip() or "OTHER",
            "description": desc,
            "billing_type": (x.get("billing_type") or "SET_SERVICE"),
            "amount": x.get("amount") if x.get("amount") not in ("",) else None,
            "hourly_rate_override": x.get("hourly_rate_override") if x.get("hourly_rate_override") not in ("",) else None,
            "minimum_fee": x.get("minimum_fee") if x.get("minimum_fee") not in ("",) else None,
            "oma_suggested_amount": x.get("oma_suggested_amount") if x.get("oma_suggested_amount") not in ("",) else None,
            "billing_classification": x.get("billing_classification") or "PATIENT_THIRD_PARTY_BILLABLE",
            "external_payer_note": (x.get("external_payer_note") or "").strip() or None,
            "oma_year": x.get("oma_year"),
            "oma_reference": (x.get("oma_reference") or "").strip() or None,
            "active": active,
            "note": (x.get("note") or "").strip() or None,
        })
    return {"hourly_rate": s.get("direct_billing_hourly_rate"), "services": clean}


async def _service_reason_lookup() -> dict:
    """Read-only map: service_code -> {category, classification} from the current
    catalogue, used only to enrich patient-facing invoice reason messages."""
    cfg = await _direct_billing_config()
    return {s["code"]: {"category": s.get("category"), "classification": s.get("billing_classification")}
            for s in cfg["services"] if s.get("code")}



class DirectBillingConfigBody(BaseModel):
    hourly_rate: Optional[float] = None
    services: Optional[list] = None


class DirectBillingInvoiceBody(BaseModel):
    patient_id: str
    billing_method: str  # SET_SERVICE | TIME_BASED
    payment_mode: Optional[str] = "INVOICE_AFTER_SERVICE"
    internal_note: Optional[str] = None
    service_code: Optional[str] = None          # SET_SERVICE
    description: Optional[str] = None            # TIME_BASED
    whole_hours: Optional[int] = None            # TIME_BASED
    partial_minutes: Optional[int] = None        # TIME_BASED


@api.get("/internal/direct-billing/config")
async def get_direct_billing_config(active_only: bool = False, user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    cfg = await _direct_billing_config(active_only=active_only)
    return {**cfg, "partial_options": billing_mod.PARTIAL_MULTIPLIERS, "max_hours": billing_mod.MAX_WHOLE_HOURS,
            "classifications": sorted(billing_mod.BILLING_CLASSIFICATIONS)}


@api.put("/internal/direct-billing/config")
async def put_direct_billing_config(body: DirectBillingConfigBody, user: dict = Depends(require_roles("admin", "physician"))):
    updates = {}
    if body.hourly_rate is not None:
        updates["direct_billing_hourly_rate"] = billing_mod.normalize_rate(body.hourly_rate)
    if body.services is not None:
        cleaned = []
        for x in body.services:
            x = x or {}
            code = str(x.get("code") or "").strip()
            desc = (x.get("description") or "").strip()
            if not code or not desc:
                continue
            classification = x.get("billing_classification") or "PATIENT_THIRD_PARTY_BILLABLE"
            if classification not in billing_mod.BILLING_CLASSIFICATIONS:
                classification = "PATIENT_THIRD_PARTY_BILLABLE"
            amt = x.get("amount")
            amount = billing_mod.normalize_amount(amt) if amt not in (None, "") else None
            cleaned.append({
                "code": code,
                "category": (x.get("category") or "OTHER").strip() or "OTHER",
                "description": desc,
                "billing_type": "TIME_BASED" if (x.get("billing_type") == "TIME_BASED") else "SET_SERVICE",
                "amount": amount,
                "hourly_rate_override": billing_mod.normalize_rate(x.get("hourly_rate_override")) if x.get("hourly_rate_override") not in (None, "") else None,
                "minimum_fee": billing_mod.normalize_amount(x.get("minimum_fee")) if x.get("minimum_fee") not in (None, "") else None,
                "oma_suggested_amount": billing_mod.normalize_amount(x.get("oma_suggested_amount")) if x.get("oma_suggested_amount") not in (None, "") else None,
                "billing_classification": classification,
                "external_payer_note": (x.get("external_payer_note") or "").strip() or None,
                "oma_year": x.get("oma_year"),
                "oma_reference": (x.get("oma_reference") or "").strip() or None,
                "active": bool(x.get("active", True)),
                "note": (x.get("note") or "").strip() or None,
            })
        updates["direct_billing_services"] = cleaned
    if updates:
        await db.settings.update_one({"id": "clinic"}, {"$set": {**updates, "id": "clinic"}}, upsert=True)
        await audit("update_direct_billing_config", "settings", "clinic", user)
    return await _direct_billing_config()


@api.post("/internal/direct-billing/invoices")
async def create_direct_billing_invoice(body: DirectBillingInvoiceBody, user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    if body.billing_method not in billing_mod.BILLING_METHODS:
        raise HTTPException(status_code=400, detail="Invalid billing method.")
    patient = await db.patients.find_one({"id": body.patient_id}, {"_id": 0})
    if not patient:
        raise HTTPException(status_code=404, detail="Patient account not found. Invoices can only be issued to registered portal patients.")
    mode = body.payment_mode or "INVOICE_AFTER_SERVICE"
    if mode == "NO_PAYMENT_REQUIRED":
        raise HTTPException(status_code=400, detail="An invoice must use a payable mode.")
    cfg = await _direct_billing_config()

    if body.billing_method == "SET_SERVICE":
        svc = billing_mod.resolve_set_service(cfg["services"], body.service_code)
        inv = await _create_invoice(
            patient, service_description=svc["service_description"], amount=svc["amount"],
            payment_mode=mode, service_code=svc["service_code"], internal_note=body.internal_note,
            billing_method="SET_SERVICE", user=user, status="DRAFT")
    else:  # TIME_BASED
        desc = (body.description or "").strip()
        rate = cfg.get("hourly_rate")
        minimum = None
        svc_code = None
        if body.service_code:
            svc = next((x for x in cfg["services"] if str(x["code"]) == str(body.service_code)), None)
            if not svc:
                raise HTTPException(status_code=400, detail="Select a valid time-based service.")
            if (svc.get("billing_type") or "SET_SERVICE") != "TIME_BASED":
                raise HTTPException(status_code=400, detail="That service is not time-based.")
            if not svc.get("active", True):
                raise HTTPException(status_code=400, detail="That service is inactive.")
            if svc.get("billing_classification") == "NO_CHARGE":
                raise HTTPException(status_code=400, detail="This service is No Charge / Unremunerated and cannot generate an invoice.")
            svc_code = svc["code"]
            if svc.get("hourly_rate_override") not in (None, ""):
                rate = svc["hourly_rate_override"]
            minimum = svc.get("minimum_fee")
            if not desc:
                desc = (svc.get("description") or "").strip()
        if not desc:
            raise HTTPException(status_code=400, detail="Please provide a service description.")
        if rate is None:
            raise HTTPException(status_code=400, detail="No hourly rate is configured. Set it in Clinic Settings first.")
        calc = billing_mod.compute_time_based(rate, body.whole_hours, body.partial_minutes, minimum_fee=minimum)
        inv = await _create_invoice(
            patient, service_description=desc, amount=calc["calculated_total"],
            payment_mode=mode, service_code=svc_code, internal_note=body.internal_note,
            billing_method="TIME_BASED", billing_meta=calc, user=user, status="DRAFT")
    return billing_mod.invoice_internal(inv)


@api.get("/internal/invoices")
async def list_invoices(status: Optional[str] = None, patient_id: Optional[str] = None,
                        private_request_id: Optional[str] = None,
                        user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    q = {}
    if status:
        q["status"] = status
    if patient_id:
        q["patient_id"] = patient_id
    if private_request_id:
        q["private_request_id"] = private_request_id
    docs = await db.invoices.find(q).sort("created_at", -1).to_list(1000)
    return [billing_mod.invoice_internal(d) for d in docs]


@api.get("/internal/invoices/{inv_id}")
async def get_invoice(inv_id: str, user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    return billing_mod.invoice_internal(await _get_invoice_or_404(inv_id))


@api.patch("/internal/invoices/{inv_id}")
async def update_invoice(inv_id: str, body: InvoiceUpdateBody, user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    inv = await _get_invoice_or_404(inv_id)
    if inv["status"] != "DRAFT":
        raise HTTPException(status_code=400, detail="Only draft invoices can be edited. Void and re-issue if a correction is needed.")
    updates = {"updated_at": now_iso()}
    if body.service_description is not None:
        updates["service_description"] = body.service_description.strip()
    if body.service_code is not None:
        updates["service_code"] = body.service_code.strip() or None
    if body.amount is not None:
        updates["amount"] = billing_mod.normalize_amount(body.amount)
    if body.internal_note is not None:
        updates["internal_note"] = body.internal_note.strip() or None
    await db.invoices.update_one({"id": inv_id}, {"$set": updates})
    await audit("invoice_updated", "invoice", inv_id, user, meta={"fields": [k for k in updates if k != "updated_at"]})
    return billing_mod.invoice_internal(await db.invoices.find_one({"id": inv_id}))


@api.post("/internal/invoices/{inv_id}/issue")
async def issue_invoice(inv_id: str, user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    inv = await _get_invoice_or_404(inv_id)
    if inv["status"] != "DRAFT":
        raise HTTPException(status_code=400, detail="Only draft invoices can be issued.")
    now = now_iso()
    await db.invoices.update_one({"id": inv_id}, {"$set": {"status": "ISSUED", "issued_at": now, "issue_date": now[:10], "updated_at": now}})
    await audit("invoice_issued", "invoice", inv_id, user, old_status="DRAFT", new_status="ISSUED",
                meta={"invoice_number": inv["invoice_number"], "patient_id": inv["patient_id"]})
    await notify_svc._in_portal(db, inv["patient_id"], "New invoice",
                                f"Invoice {inv['invoice_number']} for {inv['service_description']} is now available in your portal.")
    inv_patient = await db.patients.find_one({"id": inv["patient_id"]}, {"_id": 0})
    if inv_patient and inv_patient.get("email"):
        inv_lang = email_service.norm_lang(inv_patient.get("preferred_language"))
        amt = inv.get("amount")
        amt_disp = f"${amt:,.2f}" if isinstance(amt, (int, float)) else ""
        inv_base = (os.environ.get("APP_BASE_URL") or notify_svc.PORTAL_URL or "").strip().rstrip("/")
        try:
            await email_service.send_email(
                to=inv_patient["email"],
                subject=email_service.subject("invoice_issued", inv_lang),
                html=email_service.invoice_issued_html(
                    inv_patient.get("first_name") or "there", amt_disp, inv_base, lang=inv_lang),
            )
        except Exception as e:
            logger.warning(f"[invoice email] failed: {e}")
    await _sync_request_billing(inv.get("private_request_id"))
    return billing_mod.invoice_internal(await db.invoices.find_one({"id": inv_id}))


@api.post("/internal/invoices/{inv_id}/verify-payment")
async def verify_invoice_payment(inv_id: str, user: dict = Depends(require_roles(*BILLING_VERIFY_ROLES))):
    inv = await _get_invoice_or_404(inv_id)
    if inv["status"] not in {"ISSUED", "PAYMENT_SUBMITTED"}:
        raise HTTPException(status_code=400, detail="Only issued or submitted invoices can be marked paid.")
    now = now_iso()
    await db.invoices.update_one({"id": inv_id}, {"$set": {"status": "PAID", "paid_at": now, "updated_at": now}})
    await audit("payment_verified", "invoice", inv_id, user, old_status=inv["status"], new_status="PAID",
                meta={"invoice_number": inv["invoice_number"], "patient_id": inv["patient_id"]})
    await notify_svc._in_portal(db, inv["patient_id"], "Payment verified",
                                f"Your payment for invoice {inv['invoice_number']} has been verified. Thank you.")
    await _sync_request_billing(inv.get("private_request_id"))
    return billing_mod.invoice_internal(await db.invoices.find_one({"id": inv_id}))


@api.post("/internal/invoices/{inv_id}/void")
async def void_invoice(inv_id: str, body: PrivateReasonBody, user: dict = Depends(require_roles(*BILLING_VERIFY_ROLES))):
    inv = await _get_invoice_or_404(inv_id)
    if inv["status"] == "VOID":
        raise HTTPException(status_code=400, detail="This invoice is already void.")
    now = now_iso()
    await db.invoices.update_one({"id": inv_id}, {"$set": {"status": "VOID", "voided_at": now, "void_reason": (body.reason or None), "updated_at": now}})
    await audit("invoice_voided", "invoice", inv_id, user, old_status=inv["status"], new_status="VOID",
                meta={"invoice_number": inv["invoice_number"], "reason": body.reason, "patient_id": inv["patient_id"]})
    await _sync_request_billing(inv.get("private_request_id"))
    return billing_mod.invoice_internal(await db.invoices.find_one({"id": inv_id}))


@api.get("/internal/invoices/{inv_id}/proof/{att_id}/download")
async def internal_download_proof(inv_id: str, att_id: str, user: dict = Depends(require_roles(*BILLING_MANAGE_ROLES))):
    await _get_invoice_or_404(inv_id)
    return await billing_mod.serve_payment_proof(db, inv_id, att_id)


# ---- Patient-facing billing (owning patient only) ----
async def _get_owned_invoice(user: dict, inv_id: str, allow_draft: bool = False):
    p = await get_patient_record(user)
    inv = await db.invoices.find_one({"id": inv_id})
    if not inv or inv.get("patient_id") != p["id"]:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if inv["status"] == "DRAFT" and not allow_draft:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return p, inv


@api.get("/portal/invoices")
async def my_invoices(user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    cfg = await get_private_config()
    docs = await db.invoices.find({"patient_id": p["id"], "status": {"$ne": "DRAFT"}}).sort("created_at", -1).to_list(500)
    catmap = await _service_reason_lookup()
    return [billing_mod.invoice_public(
        d, cfg["etransfer_email"],
        service_category=(catmap.get(d.get("service_code")) or {}).get("category"),
        service_classification=(catmap.get(d.get("service_code")) or {}).get("classification"),
    ) for d in docs]


@api.get("/portal/invoices/{inv_id}")
async def my_invoice(inv_id: str, user: dict = Depends(get_current_user)):
    _, inv = await _get_owned_invoice(user, inv_id)
    cfg = await get_private_config()
    meta = (await _service_reason_lookup()).get(inv.get("service_code")) or {}
    return billing_mod.invoice_public(inv, cfg["etransfer_email"],
                                      service_category=meta.get("category"),
                                      service_classification=meta.get("classification"))


@api.post("/portal/invoices/{inv_id}/proof")
async def upload_invoice_proof(inv_id: str, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    _, inv = await _get_owned_invoice(user, inv_id)
    if inv["payment_mode"] == "NO_PAYMENT_REQUIRED":
        raise HTTPException(status_code=400, detail="This invoice does not require payment.")
    if inv["status"] not in {"ISSUED", "PAYMENT_SUBMITTED"}:
        raise HTTPException(status_code=400, detail="Payment proof can no longer be uploaded for this invoice.")
    replacing = inv.get("payment_proof") is not None
    meta = await billing_mod.store_payment_proof(
        db, file, inv, {"id": user.get("id"), "name": user.get("name"), "email": user.get("email")})
    now = now_iso()
    await db.invoices.update_one({"id": inv_id}, {"$set": {
        "status": "PAYMENT_SUBMITTED", "payment_submitted_at": now, "payment_proof": meta, "updated_at": now}})
    action = "payment_proof_replaced" if replacing else "payment_proof_uploaded"
    await audit(action, "invoice", inv_id, {"id": user.get("id"), "name": user.get("name"), "role": "patient"},
                new_status="PAYMENT_SUBMITTED",
                meta={"invoice_number": inv["invoice_number"], "attachment_id": meta["attachment_id"], "patient_id": inv["patient_id"]})
    await _notify_clinic_payment_submitted(inv)
    await _sync_request_billing(inv.get("private_request_id"))
    cfg = await get_private_config()
    fresh = await db.invoices.find_one({"id": inv_id})
    meta = (await _service_reason_lookup()).get(fresh.get("service_code")) or {}
    return billing_mod.invoice_public(fresh, cfg["etransfer_email"],
                                      service_category=meta.get("category"),
                                      service_classification=meta.get("classification"))


@api.get("/portal/invoices/{inv_id}/proof/{att_id}/download")
async def download_my_proof(inv_id: str, att_id: str, user: dict = Depends(get_current_user)):
    _, inv = await _get_owned_invoice(user, inv_id)
    return await billing_mod.serve_payment_proof(db, inv_id, att_id)


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
    pending_hc = p.get("pending_health_card")
    inv_open = await db.invoices.count_documents({"patient_id": pid, "status": {"$in": ["ISSUED", "PAYMENT_SUBMITTED"]}})
    inv_total = await db.invoices.count_documents({"patient_id": pid, "status": {"$ne": "DRAFT"}})
    return {
        "patient": {"first_name": p["first_name"], "last_name": p["last_name"],
                    "patient_type": p["patient_type"], "verification_status": p["verification_status"],
                    "visita_patient_id": p.get("visita_patient_id"),
                    "phone": p.get("phone"), "email": p.get("email"),
                    "sex": p.get("sex"),
                    "address": p.get("address"), "unit": p.get("unit"),
                    "city": p.get("city"), "province": p.get("province"),
                    "postal_code": p.get("postal_code"),
                    "health_card_display": identity_mod.format_health_card(p.get("health_card_number"), p.get("health_card_version")),
                    "health_card_issue_date": p.get("health_card_issue_date"),
                    "health_card_expiry_date": p.get("health_card_expiry_date"),
                    "health_card_status": identity_mod.health_card_status(p.get("health_card_expiry_date")),
                    "health_card_update_pending": bool(pending_hc),
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
        "billing": {"open": inv_open, "total": inv_total},
    }


class PhoneUpdateBody(BaseModel):
    phone: str


class HealthCardUpdateBody(BaseModel):
    health_card_number: str
    health_card_version: str
    health_card_issue_date: Optional[str] = None
    health_card_expiry_date: Optional[str] = None


@api.post("/portal/profile/phone")
async def portal_update_phone(body: PhoneUpdateBody, user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    new_phone = identity_mod.normalize_phone(body.phone)
    if len(re.sub(r"\D", "", new_phone)) < 10:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit phone number.")
    old_phone = p.get("phone")
    await db.patients.update_one({"id": p["id"]}, {"$set": {"phone": new_phone, "updated_at": now_iso()}})
    await audit("patient_phone_update", "patient", p["id"],
                {"id": p["id"], "name": p["first_name"], "role": "patient"},
                meta={"field": "phone", "previous": old_phone, "new": new_phone})
    return {"ok": True, "phone": new_phone}


class LanguageBody(BaseModel):
    language: str


@api.post("/portal/language")
async def portal_set_language(body: LanguageBody, user: dict = Depends(get_current_user)):
    """Persist the patient's portal language as the source of truth for emails."""
    p = await get_patient_record(user)
    lang = email_service.norm_lang(body.language)
    await db.patients.update_one({"id": p["id"]}, {"$set": {"preferred_language": lang, "updated_at": now_iso()}})
    return {"ok": True, "preferred_language": lang}



@api.post("/portal/profile/health-card")
async def portal_submit_health_card(body: HealthCardUpdateBody, user: dict = Depends(get_current_user)):
    """Patient updates their Health Card — applied INSTANTLY (no verification queue)."""
    p = await get_patient_record(user)
    try:
        num, ver = identity_mod.normalize_health_card(body.health_card_number, body.health_card_version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not identity_mod.valid_date(body.health_card_issue_date) or not identity_mod.valid_date(body.health_card_expiry_date):
        raise HTTPException(status_code=400, detail="Health Card dates must be valid dates.")
    previous = {
        "health_card_number": p.get("health_card_number"), "health_card_version": p.get("health_card_version"),
        "health_card_issue_date": p.get("health_card_issue_date"), "health_card_expiry_date": p.get("health_card_expiry_date"),
    }
    new_fields = {
        "health_card_number": num, "health_card_version": ver,
        "health_card_issue_date": body.health_card_issue_date or None,
        "health_card_expiry_date": body.health_card_expiry_date or None,
    }
    await db.patients.update_one({"id": p["id"]}, {"$set": {**new_fields, "pending_health_card": None, "updated_at": now_iso()}})
    await audit("patient_health_card_update", "patient", p["id"],
                {"id": p["id"], "name": p["first_name"], "role": "patient"},
                meta={"previous": previous, "new": new_fields})
    return {"ok": True, "health_card_display": identity_mod.format_health_card(num, ver)}


SEX_OPTIONS = ["Male", "Female", "X"]


class SexUpdateBody(BaseModel):
    sex: str


class AddressUpdateBody(BaseModel):
    address: Optional[str] = None
    unit: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None


@api.post("/portal/profile/sex")
async def portal_update_sex(body: SexUpdateBody, user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    val = (body.sex or "").strip()
    if val not in SEX_OPTIONS:
        raise HTTPException(status_code=400, detail="Please select a valid sex.")
    old = p.get("sex")
    await db.patients.update_one({"id": p["id"]}, {"$set": {"sex": val, "updated_at": now_iso()}})
    await audit("patient_sex_update", "patient", p["id"],
                {"id": p["id"], "name": p["first_name"], "role": "patient"},
                meta={"previous": old, "new": val})
    return {"ok": True, "sex": val}


@api.post("/portal/profile/address")
async def portal_update_address(body: AddressUpdateBody, user: dict = Depends(get_current_user)):
    p = await get_patient_record(user)
    fields = {}
    for k, v in {"address": body.address, "unit": body.unit, "city": body.city,
                 "province": body.province, "postal_code": body.postal_code}.items():
        fields[k] = (v.strip() or None) if isinstance(v, str) else v
    previous = {k: p.get(k) for k in fields}
    to_set = {**fields, "updated_at": now_iso()}
    await db.patients.update_one({"id": p["id"]}, {"$set": to_set})
    await audit("patient_address_update", "patient", p["id"],
                {"id": p["id"], "name": p["first_name"], "role": "patient"},
                meta={"previous": previous, "new": fields})
    return {"ok": True, **fields}


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
        return {"role": "physician", "counters": {"rx": rx, "imaging": img, "bloodwork": bld, "messages": pmsg, "doctor_tasks": dmsg, "applications": apps}}
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
    return {"$or": [{f: {"$regex": re.escape(q), "$options": "i"}} for f in fields]}


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
    directory_id: Optional[str] = None
    patient_id: Optional[str] = None
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
    if d:
        # Fields marked (VISITA) are model-ready placeholders for future read-only sync.
        return {
            "directory_id": d["id"],
            "patient_id": d.get("linked_patient_id") or d["id"],
            "source": "directory",
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
    # Portal-only patient (verified account with no linked directory record).
    p = await db.patients.find_one({"id": directory_id})
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return {
        "directory_id": p.get("matched_directory_id"),
        "patient_id": p["id"],
        "source": "portal",
        "first_name": p.get("first_name"), "last_name": p.get("last_name"),
        "visita_patient_id": p.get("visita_patient_id"),
        "date_of_birth": p.get("date_of_birth"), "age": _age_from_dob(p.get("date_of_birth")),
        "phone": p.get("phone"),
        "patient_status": "PORTAL_PATIENT",
        "linked_patient_id": p["id"],
        "medications": [],
        "last_visit_date": None,
        "last_visit_plan": None,
        "current_pharmacy": None,
    }


@api.post("/internal/pharmacy-rx")
async def create_pharmacy_rx(body: PharmacyRxBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    d = await db.patient_directory.find_one({"id": body.directory_id}) if body.directory_id else None
    p = None
    if not d and body.patient_id:
        p = await db.patients.find_one({"id": body.patient_id})
    if not d and not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    meds = [m.strip() for m in body.medications if m and m.strip()]
    if not meds:
        raise HTTPException(status_code=400, detail="Please add at least one requested medication.")
    ref = await next_ref("RX")
    if d:
        patient_name = f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", ")
        rx_patient_id = d.get("linked_patient_id") or d["id"]
        rx_directory_id = d["id"]
        rx_vid = d.get("visita_patient_id")
    else:
        patient_name = f"{p.get('last_name','')}, {p.get('first_name','')}".strip(", ")
        rx_patient_id = p["id"]
        rx_directory_id = p.get("matched_directory_id")
        rx_vid = p.get("visita_patient_id")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "source": "pharmacy",
        "patient_id": rx_patient_id,
        "directory_id": rx_directory_id, "visita_patient_id": rx_vid,
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
                meta={"pharmacy": body.pharmacy, "directory_id": rx_directory_id, "patient_id": rx_patient_id})
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


def _appt_display(a: dict) -> str:
    if a.get("confirmed_display"):
        return a["confirmed_display"]
    if a.get("confirmed_date"):
        return f"{fmt_date_display(a['confirmed_date'])} · {a.get('confirmed_time') or a.get('confirmed_slot_time') or ''}".strip(" ·")
    o = (a.get("preferred_options") or [{}])[0]
    if o.get("date"):
        return f"{fmt_date_display(o['date'])} · {o.get('label') or o.get('time') or ''}".strip(" ·")
    return "—"


def _last_history_at(a: dict, status: str):
    for h in reversed(a.get("history") or []):
        if h.get("status") == status:
            return h.get("by"), h.get("at")
    return None, None


@api.get("/internal/appointments/followups")
async def appt_followups(user: dict = Depends(require_roles("staff", "admin"))):
    """Follow-up lists: patients flagged no-show, and patients the clinic asked
    to reschedule (offered alternate times, or actively rescheduled by staff)."""
    ns = await db.appointment_requests.find({"status": "no_show"}, {"_id": 0}).sort("completed_at", -1).to_list(500)
    no_shows = []
    for a in ns:
        inv = await db.invoices.find_one(
            {"appointment_id": a["id"], "is_no_show": True, "status": {"$ne": "VOID"}}, {"_id": 0})
        no_shows.append({
            "id": a["id"], "ref_number": a.get("ref_number"), "patient_name": a.get("patient_name"),
            "patient_id": a.get("patient_id"), "reason": a.get("reason"),
            "appt_display": _appt_display(a), "actor": a.get("marked_by"), "actor_at": a.get("completed_at"),
            "no_show_invoice": ({"id": inv["id"], "invoice_number": inv["invoice_number"],
                                 "status": inv["status"], "amount": inv["amount"]} if inv else None),
        })

    rs = await db.appointment_requests.find({"$or": [
        {"status": "alternatives_offered"},
        {"rescheduled_by": {"$exists": True, "$nin": [None, "patient"]}},
    ]}, {"_id": 0}).sort("updated_at", -1).to_list(500)
    reschedules = []
    for a in rs:
        if a.get("status") == "alternatives_offered":
            by, at = _last_history_at(a, "alternatives_offered")
            rtype, actor, actor_at = "offered", by, (at or a.get("updated_at"))
        else:
            rtype, actor, actor_at = "staff", a.get("rescheduled_by"), a.get("rescheduled_at")
        reschedules.append({
            "id": a["id"], "ref_number": a.get("ref_number"), "patient_name": a.get("patient_name"),
            "patient_id": a.get("patient_id"), "reason": a.get("reason"),
            "appt_display": _appt_display(a), "status": a.get("status"),
            "resched_type": rtype, "actor": actor, "actor_at": actor_at,
        })
    return {"no_shows": no_shows, "reschedules": reschedules}


@api.post("/internal/appointments/{item_id}/no-show-invoice")
async def issue_no_show_invoice(item_id: str, user: dict = Depends(require_roles("staff", "admin"))):
    """Issue the $40 missed-appointment (no-show) fee to the patient as an invoice."""
    a = await db.appointment_requests.find_one({"id": item_id})
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if a.get("status") != "no_show":
        raise HTTPException(status_code=400, detail="This appointment is not marked as a no-show.")
    if not a.get("patient_id"):
        raise HTTPException(status_code=400, detail="Link a portal patient to this appointment before billing the no-show fee.")
    existing = await db.invoices.find_one({"appointment_id": item_id, "is_no_show": True, "status": {"$ne": "VOID"}})
    if existing:
        raise HTTPException(status_code=400, detail="A no-show invoice already exists for this appointment.")
    patient = await db.patients.find_one({"id": a["patient_id"]}, {"_id": 0})
    if not patient:
        raise HTTPException(status_code=400, detail="Linked patient account not found.")
    inv = await _create_invoice(
        patient, service_description="Missed appointment fee (no-show)", amount=LATE_FEE_AMOUNT,
        payment_mode="INVOICE_AFTER_SERVICE", appointment_id=item_id, is_no_show=True,
        internal_note=f"No-show fee for {a.get('ref_number')} — {_appt_display(a)}", user=user, status="ISSUED")
    await db.appointment_requests.update_one({"id": item_id}, {"$set": {"no_show_invoice_id": inv["id"], "updated_at": now_iso()}})
    return billing_mod.invoice_internal(inv)


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
    elif body.action == "undo_status":
        if old not in ("no_show", "completed"):
            raise HTTPException(status_code=400, detail="Only a completed or no-show appointment can be reverted.")
        updates.update({"status": "confirmed", "reverted_from": old,
                        "reverted_by": user["name"], "reverted_at": now_iso()})
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


# ---------------------- Shared internal attachments (imaging / bloodwork / messages) ----------------------
# PHI-safe: staff/physician/admin only. PDF/JPG/PNG, 15 MB max, served through
# authenticated routes (no public URLs). Referral PDFs keep their own flow above.
@api.post("/internal/{entity_type}/{entity_id}/attachments")
async def upload_attachment(entity_type: str, entity_id: str,
                            file: UploadFile = File(...),
                            user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await attach_mod.store_attachment(db, file, entity_type, entity_id, user)


@api.get("/internal/{entity_type}/{entity_id}/attachments")
async def get_attachments(entity_type: str, entity_id: str,
                          user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await attach_mod.list_attachments(db, entity_type, entity_id)


@api.get("/internal/attachments/{att_id}/download")
async def download_attachment(att_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await attach_mod.serve_attachment(db, att_id)


@api.delete("/internal/attachments/{att_id}")
async def delete_attachment(att_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await attach_mod.soft_delete_attachment(db, att_id, user)


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


@api.get("/internal/verifications/history")
async def verifications_history(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Recently verified/rejected patient registrations — read-only history."""
    docs = await db.patients.find(
        {"verification_status": {"$in": ["verified", "rejected"]}, "verified_at": {"$exists": True, "$ne": None}}
    ).sort("verified_at", -1).limit(100).to_list(100)
    return [{
        "id": p["id"], "first_name": p["first_name"], "last_name": p["last_name"],
        "patient_type": p["patient_type"],
        "verification_status": p.get("verification_status"),
        "visita_patient_id": p.get("visita_patient_id"),
        "linked": bool(p.get("matched_directory_id")),
        "verified_by": p.get("verified_by"),
        "verified_at": p.get("verified_at"),
    } for p in docs]



@api.get("/internal/directory")
async def search_directory(q: Optional[str] = None, status: Optional[str] = None,
                           user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {}
    if status:
        query["patient_status"] = status
    if q:
        qn = q.strip()
        query["$or"] = [
            {"first_name": {"$regex": re.escape(qn), "$options": "i"}},
            {"last_name": {"$regex": re.escape(qn), "$options": "i"}},
            {"norm_hcn": {"$regex": directory_mod.norm_hcn(qn)}},
            {"visita_patient_id": {"$regex": re.escape(qn), "$options": "i"}},
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
        "health_card_display": identity_mod.format_health_card(d.get("health_card_number"), d.get("health_card_version_code")),
        "country": d.get("country"),
        "health_card_issue_date": d.get("health_card_issue_date"),
        "health_card_expiry_date": d.get("health_card_expiry_date"),
        "health_card_status": identity_mod.health_card_status(d.get("health_card_expiry_date")),
        "health_card_update_pending": False,
        "patient_status": d.get("patient_status"),
        "patient_type": d.get("patient_type"),
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
        "home_phone": p.get("home_phone"), "cell_phone": p.get("phone"),
        "email": p.get("email"),
        "address": p.get("address"), "unit": p.get("unit"),
        "city": p.get("city"), "province": p.get("province"), "postal_code": p.get("postal_code"),
        "country": p.get("country"),
        "address_full": ", ".join([x for x in [
            " ".join([str(p.get("address") or ""), (f"#{p.get('unit')}" if p.get("unit") else "")]).strip(),
            p.get("city"), p.get("province"), p.get("postal_code")] if x]),
        "health_card_number": p.get("health_card_number"),
        "health_card_version_code": p.get("health_card_version"),
        "health_card_display": identity_mod.format_health_card(p.get("health_card_number"), p.get("health_card_version")),
        "health_card_issue_date": p.get("health_card_issue_date"),
        "health_card_expiry_date": p.get("health_card_expiry_date"),
        "health_card_status": identity_mod.health_card_status(p.get("health_card_expiry_date")),
        "health_card_update_pending": bool(p.get("pending_health_card")),
        "pending_health_card": p.get("pending_health_card"),
        "patient_status": "PORTAL_PATIENT",
        "patient_type": p.get("patient_type"),
        "current_pharmacy": None,
    }


def _name_tokens_clause(qn: str):
    """Multi-token full-name search: AND each whitespace token across first/last
    name (order-independent), so 'maria lopez' matches first=Maria last=Lopez."""
    toks = [t for t in re.split(r"\s+", (qn or "").strip()) if t]
    if len(toks) < 2:
        return None
    return {"$and": [
        {"$or": [{"first_name": {"$regex": re.escape(t), "$options": "i"}},
                 {"last_name": {"$regex": re.escape(t), "$options": "i"}}]}
        for t in toks
    ]}


def _portal_search_ors(qn: str, include_pin: bool = True):
    ors = [
        {"first_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"last_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"email": {"$regex": re.escape(qn), "$options": "i"}},
        {"health_card_number": {"$regex": re.escape(qn), "$options": "i"}},
        {"date_of_birth": {"$regex": re.escape(qn)}},
    ]
    if include_pin:
        ors.append({"visita_patient_id": {"$regex": re.escape(qn), "$options": "i"}})
    digits = re.sub(r"\D", "", qn)
    if len(digits) >= 3:
        ors.append({"phone": {"$regex": r"\D*".join(digits)}})
    nc = _name_tokens_clause(qn)
    if nc:
        ors.append(nc)
    return ors


# Directory records marked closed/inactive must never surface in current-patient
# lookups. Excluded case-insensitively at the query level (also keeps records
# with no status set). Legacy markers: FORMER_CLOSED / CLOSE / CLOSED / CLOSEZ.
_CLOSED_STATUS_RE = re.compile(r"^\s*(former[_\s-]?closed|closed?|closez)\s*$", re.I)
_ACTIVE_DIR_FILTER = {"patient_status": {"$not": _CLOSED_STATUS_RE}}


async def _search_patients_merged(qn: str, limit: int = 40, include_pin: bool = True):
    """Unified internal patient search: VERIFIED portal patient accounts PLUS
    existing patient_directory records. Verified portal patients are surfaced
    first (so they're never crowded out by many directory matches). Deduped so a
    portal account linked to a directory record appears only once."""
    results, seen_dir, seen_pid = [], set(), set()

    # 1) Verified portal patients first.
    portal = await db.patients.find({
        "verification_status": "verified", "active_status": True, "$or": _portal_search_ors(qn, include_pin),
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

    # 2) Directory records (active only; skip any already shown via a portal link).
    dir_ors = [
        {"first_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"last_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"norm_hcn": {"$regex": directory_mod.norm_hcn(qn)}},
        {"date_of_birth": {"$regex": re.escape(qn)}},
    ]
    if include_pin:
        dir_ors.append({"visita_patient_id": {"$regex": re.escape(qn), "$options": "i"}})
    digits = re.sub(r"\D", "", qn)
    if len(digits) >= 3:
        ph = {"$regex": r"\D*".join(digits)}
        dir_ors += [{"home_phone": ph}, {"cell_phone": ph}]
    nc = _name_tokens_clause(qn)
    if nc:
        dir_ors.append(nc)
    dir_docs = await db.patient_directory.find({"$and": [_ACTIVE_DIR_FILTER, {"$or": dir_ors}]}).limit(limit).to_list(limit)
    for d in dir_docs:
        if d["id"] in seen_dir:
            continue
        results.append(_directory_snapshot(d)); seen_dir.add(d["id"])

    return results[:limit]


@api.get("/internal/patient-lookup")
async def internal_patient_lookup(q: str, include_pin: bool = True, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Read-only GENERAL internal patient search across active portal accounts
    and ACTIVE directory records. Search by name / DOB / phone / email / health
    card (and VISITA PIN when include_pin=true). Closed/inactive directory
    records (FORMER_CLOSED etc.) are excluded at the query level. For the
    Patients page general box, callers pass include_pin=false so PIN is searched
    only via the dedicated PIN endpoint."""
    qn = (q or "").strip()
    if len(qn) < 2:
        return []
    return await _search_patients_merged(qn, limit=40, include_pin=include_pin)


@api.get("/internal/patient-lookup/pin")
async def internal_patient_lookup_pin(pin: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Dedicated VISITA PIN search — EXACT match on the PIN field only, ACTIVE
    patients only. Numeric input only; never matches phone/DOB/health-card/other
    numeric fields. Isolated from the generic multi-field search parser."""
    term = (pin or "").strip()
    if not term.isdigit():
        return []
    results, seen_dir, seen_pid = [], set(), set()
    portal = await db.patients.find({
        "verification_status": "verified", "active_status": True, "visita_patient_id": term,
    }).limit(20).to_list(20)
    for p in portal:
        mdir = p.get("matched_directory_id")
        if mdir and mdir not in seen_dir:
            d = await db.patient_directory.find_one({"id": mdir})
            if d:
                results.append(_directory_snapshot(d)); seen_dir.add(d["id"])
                continue
        if p["id"] not in seen_pid:
            results.append(_portal_patient_snapshot(p)); seen_pid.add(p["id"])
    dir_docs = await db.patient_directory.find({"$and": [_ACTIVE_DIR_FILTER, {"visita_patient_id": term}]}).limit(20).to_list(20)
    for d in dir_docs:
        if d["id"] in seen_dir:
            continue
        results.append(_directory_snapshot(d)); seen_dir.add(d["id"])
    return results


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
    # Auto-assign a unique 4-digit VISITA PIN ONLY for a portal-only patient becoming
    # verified with no existing PIN and no directory link. Never overwrite / never backfill.
    final_pin = updates.get("visita_patient_id") or p.get("visita_patient_id")
    if body.decision == "verified" and not final_pin and not link_dir_id and not p.get("matched_directory_id"):
        new_pin = await identity_mod.assign_visita_pin(db, patient_id)
        if new_pin is None:
            raise HTTPException(status_code=507,
                                detail="No 4-digit VISITA PINs remain (1000-9999 exhausted). Please contact an administrator.")
        updates["visita_patient_id"] = new_pin
        await audit("visita_pin_assigned", "patient", patient_id, user, meta={"visita_patient_id": new_pin})
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
        "account_created_user_id": a.get("account_created_user_id"),
        "created_patient_id": a.get("created_patient_id"),
        "created_visita_patient_id": a.get("created_visita_patient_id"),
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


@api.get("/internal/visita-pin/suggestions")
async def visita_pin_suggestions(count: int = 5, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Return a few currently-unused 4-digit VISITA PIN options for staff to pick from.
    Suggestions are NOT reserved until assigned."""
    import random as _random
    count = max(1, min(int(count or 5), 10))
    used = await identity_mod.collect_used_pins(db)
    pool = [str(n) for n in range(1000, 10000) if str(n) not in used]
    _random.shuffle(pool)
    return {"suggestions": pool[:count]}


class AssignPinBody(BaseModel):
    pin: str


@api.post("/internal/applications/{item_id}/assign-pin")
async def assign_application_pin(item_id: str, body: AssignPinBody,
                                 user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Assign / change the VISITA PIN for the portal patient created from an accepted
    new-patient application. Updates the patient record + its linked directory record
    and re-claims the PIN in the registry."""
    app = await db.patient_applications.find_one({"id": item_id})
    if not app:
        raise HTTPException(status_code=404, detail="Application not found.")
    pid = app.get("created_patient_id")
    if not pid:
        raise HTTPException(status_code=400, detail="No portal patient is linked to this application yet.")
    vid = (body.pin or "").strip()
    if not re.fullmatch(r"\d{4}", vid):
        raise HTTPException(status_code=400, detail="VISITA PIN must be a 4-digit number.")
    p = await db.patients.find_one({"id": pid})
    if not p:
        raise HTTPException(status_code=404, detail="Linked patient not found.")
    old_pin = p.get("visita_patient_id")
    if vid == old_pin:
        return {"ok": True, "visita_patient_id": vid, "changed": False}
    # Uniqueness across patients, directory and the PIN claim registry.
    clash = await db.patients.find_one({"visita_patient_id": vid, "id": {"$ne": pid}})
    clash_dir = await db.patient_directory.find_one({"visita_patient_id": vid, "linked_patient_id": {"$ne": pid}})
    claim = await db.visita_pins.find_one({"_id": vid})
    if clash or clash_dir or (claim and claim.get("patient_id") != pid):
        raise HTTPException(status_code=409, detail=f"VISITA PIN {vid} is already in use.")
    await db.visita_pins.update_one({"_id": vid}, {"$set": {"patient_id": pid, "created_at": now_iso()}}, upsert=True)
    await db.patients.update_one({"id": pid}, {"$set": {"visita_patient_id": vid, "updated_at": now_iso()}})
    if p.get("matched_directory_id"):
        await db.patient_directory.update_one({"id": p["matched_directory_id"]},
                                              {"$set": {"visita_patient_id": vid, "updated_at": now_iso()}})
    await db.patient_applications.update_one({"id": item_id}, {"$set": {"created_visita_patient_id": vid, "updated_at": now_iso()}})
    if old_pin and old_pin != vid:
        # Permanently retire the previous PIN — kept in the registry so it is never
        # suggested again nor reassigned to any other patient.
        await db.visita_pins.update_one({"_id": old_pin}, {"$set": {
            "patient_id": None, "retired": True,
            "retired_from_patient": pid, "retired_at": now_iso()}}, upsert=True)
    await audit("assign_visita_pin", "patient", pid, user,
                meta={"application_id": item_id, "previous": old_pin, "new": vid})
    return {"ok": True, "visita_patient_id": vid, "changed": True}


async def _accept_new_patient(doc, actor):
    """On physician acceptance of a NEW-patient application: create an ACTIVE
    directory record + a portal patient account, email a single-use set-password
    activation link, and drop an in-portal welcome notification. If a user already
    exists for the email, skip account creation."""
    email = (doc.get("email") or "").lower().strip()
    if email and await db.users.find_one({"email": email}):
        return {"account_created": False, "reason": "email_exists"}

    patient_id = str(uuid.uuid4())
    pin = await identity_mod.assign_visita_pin(db, patient_id)
    first, last = doc.get("first_name", ""), doc.get("last_name", "")

    dir_id = str(uuid.uuid4())
    await db.patient_directory.insert_one({
        "id": dir_id, "visita_patient_id": pin,
        "first_name": first, "last_name": last,
        "date_of_birth": directory_mod.norm_dob(doc.get("date_of_birth")),
        "health_card_number": None, "health_card_version_code": None, "sex_code": None,
        "address": doc.get("address"), "unit": None, "city": doc.get("city"),
        "province": doc.get("province"), "postal_code": doc.get("postal_code"),
        "home_phone": None, "cell_phone": doc.get("phone"), "email": email or None,
        "patient_status": directory_mod.ACTIVE, "source_close_marker": None,
        "linked_patient_id": patient_id,
        "norm_first": directory_mod.norm_name(first), "norm_last": directory_mod.norm_name(last),
        "norm_dob": directory_mod.norm_dob(doc.get("date_of_birth")), "norm_hcn": "",
        "import_source": "new_patient_acceptance", "created_from_application_id": doc["id"],
        "imported_at": now_iso(), "updated_at": now_iso(),
    })

    await db.patients.insert_one({
        "id": patient_id, "visita_patient_id": pin,
        "first_name": first, "last_name": last, "date_of_birth": doc.get("date_of_birth"),
        "health_card_number": None, "health_card_version": None,
        "health_card_issue_date": None, "health_card_expiry_date": None,
        "phone": doc.get("phone"), "email": email,
        "address": doc.get("address"), "city": doc.get("city"),
        "province": doc.get("province"), "postal_code": doc.get("postal_code"),
        "country": doc.get("country"), "patient_type": None,
        "verification_status": "verified", "portal_status": "ACTIVE",
        "matched_directory_id": dir_id, "preferred_language": doc.get("preferred_language", "en"),
        "active_status": True, "is_demo": False, "created_from_application_id": doc["id"],
        "created_at": now_iso(), "updated_at": now_iso(),
    })

    res = await db.users.insert_one({
        "email": email, "password_hash": authlib.hash_password(secrets.token_urlsafe(24)),
        "name": f"{first} {last}".strip(), "role": "patient", "patient_id": patient_id,
        "active": True, "pending_activation": True, "created_at": now_iso(),
    })
    uid = str(res.inserted_id)

    token = secrets.token_urlsafe(32)
    await db.account_activations.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "token_hash": authlib.hash_password(token),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(),
        "used": False, "created_at": now_iso(),
    }}, upsert=True)

    portal_url = (os.environ.get("APP_BASE_URL") or notify_svc.PORTAL_URL or "").strip().rstrip("/")
    if email and portal_url and portal_url.startswith("https://"):
        activate_url = f"{portal_url}/activate?uid={uid}&token={token}"
        acct_lang = email_service.norm_lang(doc.get("preferred_language"))
        try:
            await email_service.send_email(
                to=email,
                subject=email_service.subject("account_activation", acct_lang),
                html=email_service.account_activation_html(first or "there", activate_url, lang=acct_lang),
            )
        except Exception as e:
            logger.warning(f"[activation email] failed: {e}")

    await notify_svc._in_portal(db, patient_id, "Welcome to VIsita EMR",
                                "Dr. Aguayo's office has accepted you as a patient. Check your email to set "
                                "your password and activate your patient portal.")
    await audit("new_patient_account_created", "patient", patient_id, actor,
                meta={"application_id": doc["id"], "user_id": uid, "visita_patient_id": pin})
    return {"account_created": True, "user_id": uid, "patient_id": patient_id, "visita_patient_id": pin}


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
            # New-patient acceptance: create ACTIVE directory + portal account + activation email
            elif doc.get("application_type") == "new_patient" and old != "ACCEPTED" and not doc.get("account_created_user_id"):
                result = await _accept_new_patient(doc, user)
                if result.get("account_created"):
                    updates["account_created_user_id"] = result["user_id"]
                    updates["created_patient_id"] = result["patient_id"]
                    updates["created_visita_patient_id"] = result.get("visita_patient_id")
    elif body.action == "send_to_physician":
        updates["internal_status"] = "SENT_TO_PHYSICIAN"
    elif body.action == "waitlist":
        updates["internal_status"] = "WAITING_LIST"
        email = (doc.get("email") or "").lower().strip()
        if email and not doc.get("waitlist_email_sent"):
            wl_lang = email_service.norm_lang(doc.get("preferred_language"))
            try:
                await email_service.send_email(
                    to=email,
                    subject=email_service.subject("waiting_list", wl_lang),
                    html=email_service.waiting_list_html(doc.get("first_name") or "there", lang=wl_lang),
                )
                updates["waitlist_email_sent"] = True
                updates["waitlist_email_at"] = now_iso()
            except Exception as e:
                logger.warning(f"[waitlist email] failed: {e}")
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
    # Pharmacy refill workflow is for current patients only — exclude former/closed records.
    query = {"patient_status": {"$ne": "FORMER_CLOSED"}, "$or": [
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
    if not d or d.get("patient_status") == "FORMER_CLOSED":
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


# ============================================================================
# PHYSICIAN -> PHARMACY : Send Prescription workflow (direction=PHYSICIAN_TO_PHARMACY)
# Separate from the inbound pharmacy->physician refill flow (prescription_requests).
# Canonical record lives in `rx_transmissions`.
# ============================================================================
RX_TX_STATUSES = ("SENT", "VIEWED", "ACKNOWLEDGED")


async def _store_rx_pdf(file) -> dict:
    """Validate + store a physician Rx PDF. PDF only, server-side enforced."""
    ctype = (file.content_type or "").lower()
    fname = (file.filename or "").lower()
    is_pdf = ctype == "application/pdf" or fname.endswith(".pdf")
    if not is_pdf:
        raise HTTPException(status_code=400, detail="Only PDF files are accepted for the Rx attachment.")
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The selected file is empty.")
    if len(data) > MAX_PHARMACY_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 15 MB.")
    if data[:5] != b"%PDF-":
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF.")
    path = f"{storage.APP_NAME}/rx_tx/{uuid.uuid4()}.pdf"
    storage.put_object(path, data, "application/pdf")
    return {"storage_path": path, "original_filename": file.filename,
            "content_type": "application/pdf", "size": len(data), "uploaded_at": now_iso()}


async def _pharmacy_account(pharmacy_id: str):
    """A pharmacy that can receive in the portal == an existing user account with role=pharmacy."""
    return await db.users.find_one({"role": "pharmacy", "pharmacy_id": pharmacy_id})


def _rx_tx_public(t: dict, include_patient: bool = False) -> dict:
    t = {k: v for k, v in t.items() if k != "_id"}
    att = t.get("attachment")
    t["has_attachment"] = bool(att)
    if att:
        t["attachment_filename"] = att.get("original_filename")
    t.pop("attachment", None)  # never expose storage_path
    if not include_patient:
        t.pop("patient_snapshot", None)  # full demographics only on authorized detail views
    meds = t.get("medications") or []
    t["medication_summary"] = (f"{len(meds)} medication(s)" if meds else
                               ("PDF Prescription" if t["has_attachment"] else "—"))
    return t


def _regimen_key(patient_id: str, m: dict) -> str:
    parts = [patient_id, (m.get("drug") or "").lower().strip(),
             (m.get("strength") or "").lower().strip(),
             (m.get("form") or "").lower().strip(),
             (m.get("sig") or "").lower().strip()]
    return "|".join(parts)


async def _resolve_rx_patient(ref: str):
    d = await db.patient_directory.find_one({"id": ref})
    if d:
        return {"patient_id": d.get("linked_patient_id") or d["id"], "directory_id": d["id"],
                "first_name": d.get("first_name"), "last_name": d.get("last_name"),
                "date_of_birth": d.get("date_of_birth"), "visita_patient_id": d.get("visita_patient_id"),
                "phone": d.get("cell_phone") or d.get("home_phone")}
    p = await db.patients.find_one({"id": ref})
    if p:
        return {"patient_id": p["id"], "directory_id": p.get("matched_directory_id"),
                "first_name": p.get("first_name"), "last_name": p.get("last_name"),
                "date_of_birth": p.get("date_of_birth"), "visita_patient_id": p.get("visita_patient_id"),
                "phone": p.get("phone")}
    return None


async def _build_patient_snapshot(patient_ref: str) -> Optional[dict]:
    """Immutable prescription-time patient identity, from the authoritative VIen record
    (directory + linked patient). Only present values are stored; never fabricated.
    Frozen onto the transmission so historical Rx keep the identity as-sent even if the
    patient's demographics change later."""
    d = await db.patient_directory.find_one({"id": patient_ref})
    p = None
    if d and d.get("linked_patient_id"):
        p = await db.patients.find_one({"id": d["linked_patient_id"]})
    elif not d:
        p = await db.patients.find_one({"id": patient_ref})
    base = d or p
    if not base:
        return None

    def g(*keys):
        for src in (base, p or {}, d or {}):
            for k in keys:
                v = src.get(k)
                if v not in (None, ""):
                    return v
        return None

    snap = {
        "first_name": g("first_name"), "last_name": g("last_name"),
        "date_of_birth": g("date_of_birth"), "visita_patient_id": g("visita_patient_id"),
        "address": g("address"), "unit": g("unit"), "city": g("city"),
        "province": g("province"), "postal_code": g("postal_code"),
        "cell_phone": g("cell_phone", "phone"), "home_phone": g("home_phone"),
        "health_card_number": g("health_card_number"),
        "health_card_version": g("health_card_version"),
        "health_card_expiry_date": g("health_card_expiry_date"),
        "patient_type": g("patient_type"),
        "snapshot_at": now_iso(),
    }
    return {k: v for k, v in snap.items() if v not in (None, "")}



async def _remember_patient_medications(tx: dict):
    """'Enter once -> VIen remembers.' Upsert per-patient current regimen + normalized catalog.
    History stays immutable in rx_transmissions; existing docs are never destroyed."""
    pid = tx.get("patient_id")
    now = now_iso()
    for m in (tx.get("medications") or []):
        if not m.get("drug"):
            continue
        key = _regimen_key(pid, m)
        existing = await db.patient_medications.find_one({"regimen_key": key})
        if existing:
            await db.patient_medications.update_one({"regimen_key": key}, {"$set": {
                "last_prescribed_at": tx["sent_at"], "last_tx_id": tx["id"],
                "months": tx.get("months"), "refills": tx.get("refills"),
                "active": True, "updated_at": now}})
        else:
            await db.patient_medications.insert_one({
                "id": str(uuid.uuid4()), "regimen_key": key, "patient_id": pid,
                "drug": m.get("drug"), "action": m.get("action"), "strength": m.get("strength"), "unit": m.get("unit"),
                "form": m.get("form"), "attributes": m.get("attributes") or [],
                "sig": m.get("sig"), "quantity": m.get("quantity"),
                "quantity_unit": m.get("quantity_unit"), "route": m.get("route"),
                "duration_value": m.get("duration_value"), "duration_unit": m.get("duration_unit"),
                "concentration": m.get("concentration"), "prn_reason": m.get("prn_reason"),
                "eye": m.get("eye"), "ear": m.get("ear"), "interval": m.get("interval"),
                "site": m.get("site"), "device": m.get("device"),
                "brand": m.get("brand"), "generic": m.get("generic"),
                "din": m.get("din"), "manufacturer": m.get("manufacturer"),
                "additional_instructions": m.get("additional_instructions"),
                "original_text": m.get("original_text"),
                "months": tx.get("months"), "refills": tx.get("refills"), "note": m.get("note"),
                "last_prescribed_at": tx["sent_at"], "last_tx_id": tx["id"], "active": True,
                "created_at": now, "updated_at": now})
        # normalized medication catalog (no duplicates; keeps original strings seen)
        ckey = "|".join([(m.get("drug") or "").lower().strip(), (m.get("strength") or "").lower().strip(),
                         (m.get("form") or "").lower().strip()])
        await db.medication_catalog.update_one({"catalog_key": ckey}, {
            "$setOnInsert": {"id": str(uuid.uuid4()), "catalog_key": ckey, "drug": m.get("drug"),
                             "strength": m.get("strength"), "unit": m.get("unit"),
                             "form": m.get("form"), "attributes": m.get("attributes") or [],
                             "created_at": now},
            "$addToSet": {"original_texts": m.get("original_text") or ""},
            "$set": {"updated_at": now}}, upsert=True)


async def _remember_physician_rx(physician_id: str, meds: list):
    """Physician-scoped workflow memory: remembers ONLY values from prescriptions
    actually sent by THIS physician. Never crosses providers; suggestions only."""
    now = now_iso()
    for m in (meds or []):
        drug = (m.get("drug") or "").strip()
        if not drug:
            continue
        dk = drug.lower()
        add = {}
        for field, memk in [("strength", "strengths"), ("form", "forms"), ("sig", "sigs"),
                            ("route", "routes"), ("quantity_unit", "quantity_units")]:
            v = (m.get(field) or "").strip()
            if v:
                add[memk] = v
        attrs = [str(a).strip() for a in (m.get("attributes") or []) if str(a).strip()]
        update = {"$set": {"physician_id": physician_id, "drug_key": dk, "drug": drug, "updated_at": now},
                  "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}}
        addto = {k: v for k, v in add.items()}
        if attrs:
            addto["attributes"] = {"$each": attrs}
        if addto:
            update["$addToSet"] = addto
        await db.physician_rx_memory.update_one(
            {"physician_id": physician_id, "drug_key": dk}, update, upsert=True)


class RxParseBody(BaseModel):
    text: str
    patient_ref: Optional[str] = None


@api.post("/internal/rx/parse")
async def internal_rx_parse(body: RxParseBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    parsed = rx_parser.parse_access_rx(body.text)
    # Patient-safety: compare any identity in the pasted text vs the selected patient.
    warnings = []
    ident = parsed.get("identity") or {}
    if body.patient_ref and ident:
        snap = await _resolve_rx_patient(body.patient_ref)
        if snap:
            if ident.get("pin") and snap.get("visita_patient_id") and \
               str(ident["pin"]).strip() != str(snap["visita_patient_id"]).strip():
                warnings.append("PIN in the pasted prescription does not match the selected patient.")
            if ident.get("dob") and snap.get("date_of_birth") and \
               ident["dob"].strip()[:10] not in str(snap["date_of_birth"]):
                warnings.append("Date of birth in the pasted prescription may not match the selected patient.")
            if ident.get("name") and snap.get("last_name"):
                if snap["last_name"].lower() not in ident["name"].lower():
                    warnings.append("Patient name in the pasted prescription may not match the selected patient.")
    parsed["mismatch"] = bool(warnings)
    parsed["warnings"] = warnings
    return parsed


@api.get("/internal/patients/{patient_ref}/medications")
async def internal_patient_medications(patient_ref: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    snap = await _resolve_rx_patient(patient_ref)
    if not snap:
        raise HTTPException(status_code=404, detail="Patient not found.")
    docs = await db.patient_medications.find(
        {"patient_id": snap["patient_id"], "active": True}, {"_id": 0}
    ).sort("last_prescribed_at", -1).to_list(100)
    return docs


@api.get("/internal/patients/{patient_ref}/prescriptions")
async def internal_patient_prescriptions(patient_ref: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Read-only: that patient's past physician->pharmacy prescriptions, grouped as
    whole prescriptions (one transmission -> many meds), for 'Repeat Entire Prescription'.
    Each medication is annotated with newer_available/newer when patient_medications
    holds a more recent, different regimen for the same drug. Never mutates history."""
    snap = await _resolve_rx_patient(patient_ref)
    if not snap:
        raise HTTPException(status_code=404, detail="Patient not found.")
    pid = snap["patient_id"]
    docs = await db.rx_transmissions.find(
        {"patient_id": pid, "direction": "PHYSICIAN_TO_PHARMACY"}
    ).sort("created_at", -1).to_list(50)
    active = await db.patient_medications.find(
        {"patient_id": pid, "active": True}, {"_id": 0}
    ).to_list(300)
    out = []
    for t in docs:
        meds_raw = t.get("medications") or []
        if not meds_raw:
            continue  # PDF-only prescriptions cannot be "repeated" as structured meds
        pub = _rx_tx_public(t)
        annotated = []
        for m in meds_raw:
            mm = dict(m)
            mm["newer_available"] = False
            mm["newer"] = None
            drug_l = (m.get("drug") or "").lower().strip()
            this_key = _regimen_key(pid, m)
            cand = [a for a in active
                    if (a.get("drug") or "").lower().strip() == drug_l
                    and a.get("regimen_key") != this_key
                    and (a.get("last_prescribed_at") or "") > (t.get("sent_at") or "")]
            if cand:
                cand.sort(key=lambda a: a.get("last_prescribed_at") or "", reverse=True)
                n = cand[0]
                mm["newer_available"] = True
                mm["newer"] = {k: n.get(k) for k in (
                    "drug", "action", "strength", "unit", "form", "attributes",
                    "sig", "quantity", "additional_instructions", "note")}
            annotated.append(mm)
        pub["medications"] = annotated
        out.append(pub)
    return out


@api.get("/internal/rx/suggest")
async def internal_rx_suggest(patient_ref: Optional[str] = None, drug: Optional[str] = None,
                              user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Ranked data-entry suggestions (patient -> this-physician -> catalog).
    NOT clinical decision support. Physician memory is strictly scoped to the
    authenticated physician and only reflects prescriptions actually sent."""
    phys_id = user["id"]
    pid = None
    if patient_ref:
        snap = await _resolve_rx_patient(patient_ref)
        if snap:
            pid = snap["patient_id"]

    seen, drugs = set(), []
    def _add(v, src):
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            drugs.append({"value": v, "source": src})

    if pid:
        for d in await db.patient_medications.find(
                {"patient_id": pid, "active": True}, {"_id": 0, "drug": 1, "last_prescribed_at": 1}
        ).sort("last_prescribed_at", -1).to_list(100):
            _add(d.get("drug"), "patient")
    for d in await db.physician_rx_memory.find(
            {"physician_id": phys_id}, {"_id": 0, "drug": 1, "updated_at": 1}
    ).sort("updated_at", -1).to_list(300):
        _add(d.get("drug"), "physician")
    for d in await db.medication_catalog.find({}, {"_id": 0, "drug": 1}).sort("updated_at", -1).to_list(400):
        _add(d.get("drug"), "catalog")

    result = {"drugs": drugs[:120]}

    if drug:
        dl = drug.lower().strip()
        fields = {"strengths": [], "forms": [], "attributes": [], "sigs": [], "routes": [], "quantity_units": []}
        fseen = {k: set() for k in fields}

        def _addf(fk, v, src):
            v = (v or "").strip()
            if v and v.lower() not in fseen[fk]:
                fseen[fk].add(v.lower())
                fields[fk].append({"value": v, "source": src})

        def _collect(doc, src):
            for field, fk in [("strength", "strengths"), ("form", "forms"), ("sig", "sigs"),
                              ("route", "routes"), ("quantity_unit", "quantity_units")]:
                _addf(fk, doc.get(field), src)
            for a in (doc.get("attributes") or []):
                _addf("attributes", str(a), src)

        if pid:
            for doc in await db.patient_medications.find(
                    {"patient_id": pid, "active": True}, {"_id": 0}
            ).sort("last_prescribed_at", -1).to_list(100):
                if (doc.get("drug") or "").lower().strip() == dl:
                    _collect(doc, "patient")
        pm = await db.physician_rx_memory.find_one({"physician_id": phys_id, "drug_key": dl}, {"_id": 0})
        if pm:
            for fk, memk in [("strengths", "strengths"), ("forms", "forms"), ("sigs", "sigs"),
                            ("routes", "routes"), ("quantity_units", "quantity_units"), ("attributes", "attributes")]:
                for v in (pm.get(memk) or []):
                    _addf(fk, str(v), "physician")
        for doc in await db.medication_catalog.find({}, {"_id": 0}).to_list(500):
            if (doc.get("drug") or "").lower().strip() == dl:
                _collect(doc, "catalog")
        result["fields"] = fields

    return result


@api.get("/internal/pharmacies")
async def internal_list_pharmacies(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Pharmacies that can receive a prescription in the Pharmacy Portal = pharmacy accounts."""
    accounts = await db.users.find({"role": "pharmacy"}, {"_id": 0}).to_list(200)
    seen, out = set(), []
    for a in accounts:
        pid = a.get("pharmacy_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append({
            "pharmacy_id": pid, "pharmacy_name": a.get("pharmacy_name"),
            "address": a.get("address") or a.get("pharmacy_address"),
            "phone": a.get("phone") or a.get("pharmacy_phone"),
            "fax": a.get("fax") or a.get("fax_number"),
            "portal": True,
        })
    return sorted(out, key=lambda x: (x.get("pharmacy_name") or "").lower())


@api.post("/internal/send-rx")
async def internal_send_rx(
    patient_ref: str = Form(...),
    pharmacy_id: str = Form(...),
    medications: str = Form("[]"),
    physician_note: str = Form(""),
    months: str = Form(""),
    refills: str = Form(""),
    source_text: str = Form(""),
    confirm: str = Form("true"),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(require_roles(*CLINIC_ROLES)),
):
    # Step 4 (Review & Send) IS the confirmation; no separate checkbox required.

    # --- Patient (server-side resolve; never trust a client-sent name) ---
    snap = None
    d = await db.patient_directory.find_one({"id": patient_ref})
    if d:
        snap = {"patient_id": d.get("linked_patient_id") or d["id"], "directory_id": d["id"],
                "first_name": d.get("first_name"), "last_name": d.get("last_name"),
                "date_of_birth": d.get("date_of_birth"), "visita_patient_id": d.get("visita_patient_id"),
                "phone": d.get("cell_phone") or d.get("home_phone")}
    else:
        p = await db.patients.find_one({"id": patient_ref})
        if p:
            snap = {"patient_id": p["id"], "directory_id": p.get("matched_directory_id"),
                    "first_name": p.get("first_name"), "last_name": p.get("last_name"),
                    "date_of_birth": p.get("date_of_birth"), "visita_patient_id": p.get("visita_patient_id"),
                    "phone": p.get("phone")}
    if not snap:
        raise HTTPException(status_code=404, detail="Patient not found.")

    # --- Pharmacy (must be a real portal account) ---
    acct = await _pharmacy_account(pharmacy_id)
    if not acct:
        raise HTTPException(status_code=400,
                            detail="The selected pharmacy has no Pharmacy Portal account, so it cannot receive prescriptions.")

    # --- Medications (structured, no auto-changes) ---
    try:
        raw_meds = json.loads(medications or "[]")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid medications payload.")
    meds = []
    _OPT = ["route", "duration_value", "duration_unit", "quantity_unit", "concentration",
            "prn_reason", "eye", "ear", "interval", "site", "device",
            "brand", "generic", "din", "manufacturer"]
    for m in (raw_meds if isinstance(raw_meds, list) else []):
        drug = str((m or {}).get("drug") or "").strip()
        if not drug:
            continue
        rec = {
            "drug": drug,
            "action": (str(m.get("action") or "").strip().upper() or None),
            "strength": str(m.get("strength") or "").strip() or None,
            "unit": str(m.get("unit") or "").strip() or None,
            "form": str(m.get("form") or "").strip() or None,
            "attributes": [str(a) for a in (m.get("attributes") or []) if str(a).strip()],
            "sig": str(m.get("sig") or "").strip() or None,
            "quantity": str(m.get("quantity") or "").strip() or None,
            "refills": str(m.get("refills") or "").strip() or None,
            "additional_instructions": str(m.get("additional_instructions") or "").strip() or None,
            "note": str(m.get("note") or "").strip() or None,
            "original_text": str(m.get("original_text") or "").strip() or None,
        }
        for k in _OPT:
            rec[k] = str(m.get(k) or "").strip() or None
        meds.append(rec)

    attachment = await _store_rx_pdf(file) if file is not None else None

    if not meds and not attachment:
        raise HTTPException(status_code=400,
                            detail="Add at least one medication or attach an Rx PDF before sending.")

    clinic = await db.settings.find_one({"id": "clinic"}, {"_id": 0}) or {}
    patient_snapshot = await _build_patient_snapshot(patient_ref)
    now = now_iso()
    tx = {
        "id": str(uuid.uuid4()), "ref_number": await next_ref("RXTX"),
        "direction": "PHYSICIAN_TO_PHARMACY",
        "patient_id": snap["patient_id"], "patient_directory_id": snap.get("directory_id"),
        "patient_name": f"{snap.get('last_name','')}, {snap.get('first_name','')}".strip(", "),
        "patient_dob": snap.get("date_of_birth"), "visita_patient_id": snap.get("visita_patient_id"),
        "patient_snapshot": patient_snapshot,
        "physician_id": user["id"], "physician_name": user.get("name"),
        "clinic_name": clinic.get("clinic_name") or clinic.get("practice_name") or "Dr. Aguayo Family Practice",
        "pharmacy_id": pharmacy_id, "pharmacy_name": acct.get("pharmacy_name"),
        "medications": meds, "physician_note": physician_note.strip() or None,
        "months": (int(months) if str(months).strip().isdigit() else None),
        "refills": (int(refills) if str(refills).strip().isdigit() else None),
        "source_text": source_text.strip() or None,
        "attachment": attachment,
        "status": "SENT",
        "created_at": now, "sent_at": now, "viewed_at": None, "acknowledged_at": None,
        "history": [{"status": "SENT", "at": now, "by": user.get("name")}],
    }
    await db.rx_transmissions.insert_one({**tx})
    await _remember_patient_medications(tx)
    await _remember_physician_rx(user["id"], meds)
    await audit("rx_prescription_created", "rx_transmission", tx["id"], user,
                meta={"pharmacy_id": pharmacy_id, "patient_id": snap["patient_id"], "med_count": len(meds)})
    if attachment:
        await audit("rx_pdf_uploaded", "rx_transmission", tx["id"], user, meta={"pharmacy_id": pharmacy_id})
    await audit("rx_prescription_sent", "rx_transmission", tx["id"], user, new_status="SENT",
                meta={"pharmacy_id": pharmacy_id})

    # Generic, PHI-free notification to the pharmacy account (no meds, no PDF).
    if acct.get("email"):
        pharmacy_alert_html = (
            "<table role='presentation' width='100%'><tr><td style='padding:24px;font-family:Arial,sans-serif;color:#0f172a'>"
            "<h2 style='margin:0 0 12px'>New prescription received</h2>"
            "<p>A new prescription is available in your VIen Pharmacy Portal. "
            "Please sign in to review it under Incoming Prescriptions.</p>"
            "<p style='font-size:12px;color:#888;margin-top:20px'>This message contains no medical information.</p>"
            "</td></tr></table>"
        )
        try:
            await email_service.send_email(
                to=acct["email"],
                subject="New prescription in your VIen Pharmacy Portal",
                html=pharmacy_alert_html,
            )
        except Exception as e:
            logger.warning(f"[rx-tx pharmacy email] failed: {e}")

    return _rx_tx_public(tx, include_patient=True)


@api.get("/internal/send-rx")
async def internal_sent_rx_list(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    docs = await db.rx_transmissions.find({}, {}).sort("created_at", -1).to_list(100)
    return [_rx_tx_public(t) for t in docs]


@api.get("/internal/send-rx/{tx_id}")
async def internal_sent_rx_detail(tx_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    t = await db.rx_transmissions.find_one({"id": tx_id})
    if not t:
        raise HTTPException(status_code=404, detail="Prescription not found.")
    return _rx_tx_public(t, include_patient=True)


@api.get("/internal/send-rx/{tx_id}/attachment")
async def internal_sent_rx_attachment(tx_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    t = await db.rx_transmissions.find_one({"id": tx_id})
    if not t or not t.get("attachment"):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    await audit("rx_pdf_viewed", "rx_transmission", tx_id, user, meta={"by_role": user.get("role")})
    return _serve_attachment(t["attachment"])


# ----- Pharmacy Portal: Incoming Prescriptions (physician -> this pharmacy only) -----
@api.get("/pharmacy/incoming")
async def pharmacy_incoming_list(user: dict = Depends(require_roles("pharmacy"))):
    pid, _ = _pharmacy_of(user)
    docs = await db.rx_transmissions.find(
        {"pharmacy_id": pid, "direction": "PHYSICIAN_TO_PHARMACY"}, {}).sort("created_at", -1).to_list(200)
    items = [_rx_tx_public(t) for t in docs]
    return {"items": items, "unviewed": sum(1 for i in items if i.get("status") == "SENT")}


@api.get("/pharmacy/incoming/{tx_id}")
async def pharmacy_incoming_detail(tx_id: str, user: dict = Depends(require_roles("pharmacy"))):
    pid, _ = _pharmacy_of(user)
    t = await db.rx_transmissions.find_one({"id": tx_id, "pharmacy_id": pid})
    if not t:
        raise HTTPException(status_code=404, detail="Prescription not found.")
    if t.get("status") == "SENT":
        now = now_iso()
        await db.rx_transmissions.update_one({"id": tx_id, "pharmacy_id": pid}, {
            "$set": {"status": "VIEWED", "viewed_at": now, "updated_at": now},
            "$push": {"history": {"status": "VIEWED", "at": now, "by": user.get("pharmacy_name")}}})
        await audit("rx_pharmacy_viewed", "rx_transmission", tx_id,
                    {"id": user["id"], "name": user.get("pharmacy_name"), "role": "pharmacy"}, new_status="VIEWED",
                    meta={"pharmacy_id": pid})
        t = await db.rx_transmissions.find_one({"id": tx_id, "pharmacy_id": pid})
    return _rx_tx_public(t, include_patient=True)


@api.get("/pharmacy/incoming/{tx_id}/attachment")
async def pharmacy_incoming_attachment(tx_id: str, user: dict = Depends(require_roles("pharmacy"))):
    pid, _ = _pharmacy_of(user)
    t = await db.rx_transmissions.find_one({"id": tx_id, "pharmacy_id": pid})
    if not t or not t.get("attachment"):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    await audit("rx_pdf_viewed", "rx_transmission", tx_id,
                {"id": user["id"], "name": user.get("pharmacy_name"), "role": "pharmacy"},
                meta={"pharmacy_id": pid})
    return _serve_attachment(t["attachment"])


@api.post("/pharmacy/incoming/{tx_id}/acknowledge")
async def pharmacy_incoming_acknowledge(tx_id: str, user: dict = Depends(require_roles("pharmacy"))):
    pid, _ = _pharmacy_of(user)
    t = await db.rx_transmissions.find_one({"id": tx_id, "pharmacy_id": pid})
    if not t:
        raise HTTPException(status_code=404, detail="Prescription not found.")
    now = now_iso()
    await db.rx_transmissions.update_one({"id": tx_id, "pharmacy_id": pid}, {
        "$set": {"status": "ACKNOWLEDGED", "acknowledged_at": now, "updated_at": now,
                 "viewed_at": t.get("viewed_at") or now},
        "$push": {"history": {"status": "ACKNOWLEDGED", "at": now, "by": user.get("pharmacy_name")}}})
    await audit("rx_status_changed", "rx_transmission", tx_id,
                {"id": user["id"], "name": user.get("pharmacy_name"), "role": "pharmacy"}, new_status="ACKNOWLEDGED",
                meta={"pharmacy_id": pid})
    return _rx_tx_public(await db.rx_transmissions.find_one({"id": tx_id, "pharmacy_id": pid}), include_patient=True)



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


class InternalPatientEditBody(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    email: Optional[str] = None
    home_phone: Optional[str] = None
    phone: Optional[str] = None  # cell phone
    address: Optional[str] = None
    unit: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    health_card_number: Optional[str] = None
    health_card_version: Optional[str] = None
    health_card_issue_date: Optional[str] = None
    health_card_expiry_date: Optional[str] = None
    visita_patient_id: Optional[str] = None


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_edit_common(body: "InternalPatientEditBody"):
    """Shared field validation for internal patient edits: email format and a
    DOB that is a real, non-future date."""
    if body.email is not None and body.email.strip():
        if not _EMAIL_RE.match(body.email.strip().lower()):
            raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if body.date_of_birth is not None and body.date_of_birth.strip():
        from datetime import date as _date
        try:
            y, m, d = (int(x) for x in body.date_of_birth.split("-"))
            dob = _date(y, m, d)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Enter a valid date of birth.")
        if dob > _date.today():
            raise HTTPException(status_code=400, detail="Date of birth cannot be in the future.")


@api.patch("/internal/patients/{patient_id}")
async def internal_edit_patient(patient_id: str, body: InternalPatientEditBody,
                                user: dict = Depends(require_roles("staff", "admin", "physician"))):
    """Staff/Admin edit of core identity/contact fields. Applies immediately with a
    full audit trail (changed_by/at, field, previous, new). No hard deletes."""
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    _validate_edit_common(body)
    updates, changes = {}, []

    def track(field, new_val):
        old_val = p.get(field)
        if new_val is not None and new_val != old_val:
            updates[field] = new_val
            changes.append({"field": field, "previous": old_val, "new": new_val,
                            "changed_by": user["name"], "changed_at": now_iso()})

    for f in ("first_name", "last_name", "address", "unit", "city", "province", "postal_code", "country"):
        val = getattr(body, f)
        if val is not None:
            track(f, val.strip() or None)
    if body.date_of_birth is not None and body.date_of_birth.strip():
        track("date_of_birth", body.date_of_birth.strip())
    if body.home_phone is not None:
        track("home_phone", identity_mod.normalize_phone(body.home_phone) if body.home_phone.strip() else None)
    # Email is the portal login identity: enforce uniqueness and sync the users doc.
    if body.email is not None and body.email.strip():
        new_email = body.email.strip().lower()
        if new_email != (p.get("email") or "").lower():
            clash_p = await db.patients.find_one({"email": new_email, "id": {"$ne": patient_id}})
            clash_u = await db.users.find_one({"email": new_email, "patient_id": {"$ne": patient_id}})
            if clash_p or clash_u:
                raise HTTPException(status_code=409, detail="Another account already uses that email address.")
            track("email", new_email)
    if body.phone is not None:
        track("phone", identity_mod.normalize_phone(body.phone))
    # Health card: normalize together when either number or version is being set.
    if body.health_card_number is not None or body.health_card_version is not None:
        try:
            num, ver = identity_mod.normalize_health_card(
                body.health_card_number if body.health_card_number is not None else p.get("health_card_number"),
                body.health_card_version if body.health_card_version is not None else p.get("health_card_version"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        track("health_card_number", num)
        track("health_card_version", ver)
    for f in ("health_card_issue_date", "health_card_expiry_date"):
        val = getattr(body, f)
        if val is not None:
            if not identity_mod.valid_date(val):
                raise HTTPException(status_code=400, detail="Health Card dates must be valid dates.")
            track(f, val or None)
    if body.visita_patient_id is not None:
        vid = body.visita_patient_id.strip()
        if vid and vid != p.get("visita_patient_id"):
            if not re.fullmatch(r"\d{4}", vid):
                raise HTTPException(status_code=400, detail="VISITA PIN must be a 4-digit number.")
            clash = await db.patients.find_one({"visita_patient_id": vid, "id": {"$ne": patient_id}})
            clash_dir = await db.patient_directory.find_one({"visita_patient_id": vid, "linked_patient_id": {"$ne": patient_id}})
            claim = await db.visita_pins.find_one({"_id": vid})
            if clash or clash_dir or (claim and claim.get("patient_id") != patient_id):
                raise HTTPException(status_code=409, detail=f"VISITA PIN {vid} is already in use or retired.")
            track("visita_patient_id", vid)

    if not updates:
        return {"ok": True, "changes": 0}
    updates["updated_at"] = now_iso()
    await db.patients.update_one({"id": patient_id}, {"$set": updates})
    await db.patients.update_one({"id": patient_id}, {"$push": {"identity_history": {"$each": changes}}})
    # Keep the portal login (users doc) email in sync with the patient email.
    if "email" in updates:
        await db.users.update_one({"patient_id": patient_id, "role": "patient"},
                                  {"$set": {"email": updates["email"]}})
    if "visita_patient_id" in updates:
        new_vid = updates["visita_patient_id"]
        old_vid = p.get("visita_patient_id")
        # Atomically reserve the new PIN in the registry.
        await db.visita_pins.update_one({"_id": new_vid},
                                        {"$set": {"patient_id": patient_id, "created_at": now_iso()}}, upsert=True)
        # Keep the linked directory record in sync.
        if p.get("matched_directory_id"):
            await db.patient_directory.update_one({"id": p["matched_directory_id"]},
                                                  {"$set": {"visita_patient_id": new_vid, "updated_at": now_iso()}})
        # Permanently retire the previous PIN — never suggested or reassigned.
        if old_vid and old_vid != new_vid:
            await db.visita_pins.update_one({"_id": old_vid}, {"$set": {
                "patient_id": None, "retired": True,
                "retired_from_patient": patient_id, "retired_at": now_iso()}}, upsert=True)
    for ch in changes:
        await audit("patient_identity_edit", "patient", patient_id, user, meta=ch)
    return {"ok": True, "changes": len(changes)}


@api.patch("/internal/patient-directory/{directory_id}")
async def internal_edit_directory(directory_id: str, body: InternalPatientEditBody,
                                  user: dict = Depends(require_roles("staff", "admin", "physician"))):
    """Edit an UNREGISTERED patient's directory record (no portal account). Applies
    immediately with a full audit trail (changed_by/at, field, previous, new)."""
    d = await db.patient_directory.find_one({"id": directory_id})
    if not d:
        raise HTTPException(status_code=404, detail="Directory record not found.")
    _validate_edit_common(body)
    owner_id = d.get("linked_patient_id") or directory_id
    updates, changes = {}, []

    def track(field, new_val):
        old_val = d.get(field)
        if new_val is not None and new_val != old_val:
            updates[field] = new_val
            changes.append({"field": field, "previous": old_val, "new": new_val,
                            "changed_by": user["name"], "changed_at": now_iso()})

    for f in ("first_name", "last_name", "address", "unit", "city", "province", "postal_code", "country"):
        val = getattr(body, f)
        if val is not None:
            track(f, val.strip() or None)
    if body.date_of_birth is not None and body.date_of_birth.strip():
        track("date_of_birth", body.date_of_birth.strip())
    if body.email is not None:
        track("email", body.email.strip().lower() or None)
    if body.home_phone is not None:
        track("home_phone", identity_mod.normalize_phone(body.home_phone) if body.home_phone.strip() else None)
    if body.phone is not None:
        track("cell_phone", identity_mod.normalize_phone(body.phone))
    if body.health_card_number is not None or body.health_card_version is not None:
        try:
            num, ver = identity_mod.normalize_health_card(
                body.health_card_number if body.health_card_number is not None else d.get("health_card_number"),
                body.health_card_version if body.health_card_version is not None else d.get("health_card_version_code"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        track("health_card_number", num)
        track("health_card_version_code", ver)
    for f in ("health_card_issue_date", "health_card_expiry_date"):
        val = getattr(body, f)
        if val is not None:
            if not identity_mod.valid_date(val):
                raise HTTPException(status_code=400, detail="Health Card dates must be valid dates.")
            track(f, val or None)
    if body.visita_patient_id is not None:
        vid = body.visita_patient_id.strip()
        if vid and vid != d.get("visita_patient_id"):
            if not re.fullmatch(r"\d{4}", vid):
                raise HTTPException(status_code=400, detail="VISITA PIN must be a 4-digit number.")
            clash = await db.patients.find_one({"visita_patient_id": vid})
            clash_dir = await db.patient_directory.find_one({"visita_patient_id": vid, "id": {"$ne": directory_id}})
            claim = await db.visita_pins.find_one({"_id": vid})
            if clash or clash_dir or (claim and claim.get("patient_id") != owner_id):
                raise HTTPException(status_code=409, detail=f"VISITA PIN {vid} is already in use or retired.")
            track("visita_patient_id", vid)

    if not updates:
        return {"ok": True, "changes": 0}
    updates["updated_at"] = now_iso()
    await db.patient_directory.update_one({"id": directory_id}, {"$set": updates})
    await db.patient_directory.update_one({"id": directory_id}, {"$push": {"identity_history": {"$each": changes}}})
    if "visita_patient_id" in updates:
        await db.visita_pins.update_one({"_id": updates["visita_patient_id"]},
                                        {"$set": {"patient_id": owner_id, "created_at": now_iso()}}, upsert=True)
    for ch in changes:
        await audit("patient_identity_edit", "patient_directory", directory_id, user, meta=ch)
    return {"ok": True, "changes": len(changes)}



async def internal_health_card_review(patient_id: str, action: str,
                                      user: dict = Depends(require_roles("staff", "admin", "physician"))):
    """Approve or reject a patient-submitted HEALTH CARD UPDATE PENDING proposal."""
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Invalid action.")
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    pending = p.get("pending_health_card")
    if not pending:
        raise HTTPException(status_code=400, detail="No pending Health Card update.")
    if action == "reject":
        await db.patients.update_one({"id": patient_id}, {"$unset": {"pending_health_card": ""}, "$set": {"updated_at": now_iso()}})
        await audit("health_card_update_rejected", "patient", patient_id, user, meta={"proposed": pending.get("display")})
        await notify_patient(patient_id, "Health Card update not approved",
                             "Your Health Card update was reviewed and not approved. Your existing record remains active. Please contact the clinic.")
        return {"ok": True, "status": "rejected"}
    change = {"field": "health_card", "previous": identity_mod.format_health_card(p.get("health_card_number"), p.get("health_card_version")),
              "new": pending.get("display"), "changed_by": user["name"], "changed_at": now_iso()}
    await db.patients.update_one({"id": patient_id}, {
        "$set": {"health_card_number": pending["health_card_number"], "health_card_version": pending["health_card_version"],
                 "health_card_issue_date": pending.get("health_card_issue_date"),
                 "health_card_expiry_date": pending.get("health_card_expiry_date"), "updated_at": now_iso()},
        "$unset": {"pending_health_card": ""},
        "$push": {"identity_history": change},
    })
    await audit("health_card_update_approved", "patient", patient_id, user, meta=change)
    await notify_patient(patient_id, "Health Card update approved",
                         "Your Health Card information has been verified and updated. Thank you.")
    return {"ok": True, "status": "approved"}



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

_DEFAULT_CORS = "https://visitaemr.com,https://www.visitaemr.com,https://visita-admin.preview.emergentagent.com"
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", _DEFAULT_CORS).split(",") if o.strip()],
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
