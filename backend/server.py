from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import asyncio
import logging
import sys
import os
import json
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from fastapi import (APIRouter, BackgroundTasks, Depends, FastAPI, File, Form,
                     Header, HTTPException, Request, Response, UploadFile)
from pydantic import BaseModel, EmailStr, Field
from fastapi.responses import JSONResponse
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
import relationships as rel_mod
import delegates as delegates_mod
import slots as slots_mod
import data_hygiene as hygiene_mod
import visits as visits_mod
import soap_helpers as helpers_mod
import clinical_history as history_mod
import diagnosis_catalog as diag_mod
import diagnosis as dx_mod
import service_coding as svc_mod
import audit_view as audit_mod
import metrics as metrics_mod
import names as names_mod
import identity_cleanup as cleanup_mod
import appt_guard as guard_mod
import index_bootstrap as ib_mod
import catalog_import as catalog_import_mod
import system_state as sys_mod
import platform_config as pc_mod
import storage
import work_hub as work_mod
import booking_types as bt_mod
import profile_completion as prof_mod
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
OPS_ROLES = ("developer_ops",)  # installation-level operator ONLY — organization admins never inherit this


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
        "practice_id": u.get("practice_id"),
        "encounter_enabled": encounter_pilot_allows(u),
        "theme": u.get("theme") if u.get("theme") in ("light", "dark") else "light",
    }


def encounter_pilot_allows(u: dict) -> bool:
    """Encounter/Visit pilot gate. ENCOUNTER_PILOT_USERS (comma-separated usernames/emails)
    restricts the Encounter workstation to those users; unset = no extra restriction."""
    allow = {x.strip().lower() for x in os.environ.get("ENCOUNTER_PILOT_USERS", "").split(",") if x.strip()}
    if not allow:
        return u.get("role") == "physician"
    return u.get("role") == "physician" and bool({(u.get("username") or "").lower(), (u.get("email") or "").lower()} & allow)


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
    out = serialize_user(user)
    if payload.get("ws"):
        # VIen Network workspace session: identity stays the person's own; role/practice come from an ACTIVE membership.
        m = await db.org_memberships.find_one({"id": payload["ws"], "user_id": str(user["_id"])}, {"_id": 0})
        if not m or m["status"] != "ACTIVE":
            raise HTTPException(status_code=403, detail={"code": "WORKSPACE_INACTIVE", "message": "Your access to this organization is not active."})
        out.update(role="staff", base_role=user.get("role"), practice_id=m["org_id"], allowed_modules=m.get("modules", []),
                   workspace={"membership_id": m["id"], "org_id": m["org_id"], "org_name": m["org_name"], "role_title": m["role_title"]})
    return out


def require_roles(*roles):
    async def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Not authorized")
        return user
    return dep


def require_visit_access(*roles):
    """Role check + Encounter pilot allowlist (physicians outside the pilot get 403)."""
    async def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Not authorized")
        if user["role"] == "physician" and not user.get("encounter_enabled"):
            raise HTTPException(status_code=403, detail="The Encounter workstation is not enabled for your account yet.")
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


class PortalCtx:
    """Resolved portal actor: either the patient acting for themselves, or a delegate
    acting on behalf of a granted patient. Carries the target patient record plus
    correct audit attribution."""
    def __init__(self, patient: dict, user: dict, grant: dict = None):
        self.patient = patient
        self.user = user
        self.grant = grant

    @property
    def is_delegate(self) -> bool:
        return self.grant is not None

    def audit_actor(self) -> dict:
        if self.grant:
            return {"id": self.user["id"], "name": self.user.get("name"), "role": self.user.get("role")}
        return {"id": self.patient["id"], "name": self.patient["first_name"], "role": "patient"}

    def audit_meta(self, extra: dict = None) -> dict:
        m = dict(extra or {})
        if self.grant:
            m["acted_by_user_id"] = self.user["id"]
            m["on_behalf_of_patient_id"] = self.patient["id"]
            m["delegate_relationship"] = self.grant.get("relationship")
        return m


def portal_access(permission: str = None):
    """Dependency factory for portal endpoints that support delegated access.
    No `on_behalf_of` -> the authenticated verified patient acts for themselves.
    With `on_behalf_of` (header X-On-Behalf-Of or query param) -> enforce an ACTIVE
    delegate grant, the required permission, the patient's practice, and verification,
    all SERVER-SIDE. Unauthorized direct-ID access returns 404 (no existence leak)."""
    async def dep(request: Request, user: dict = Depends(get_current_user)) -> PortalCtx:
        pid = request.headers.get("X-On-Behalf-Of") or request.query_params.get("on_behalf_of")
        if pid:
            grant = await delegates_mod.active_grant(db, pid, user["id"])
            if not grant:
                raise HTTPException(status_code=404, detail="Not found")
            if permission and permission not in grant.get("permissions", []):
                raise HTTPException(status_code=403, detail="This action isn't included in your access for this person.")
            p = await db.patients.find_one({"id": pid}, {"_id": 0})
            if not p or p.get("practice_id") != grant.get("practice_id"):
                raise HTTPException(status_code=404, detail="Not found")
            if p.get("verification_status") != "verified":
                raise HTTPException(status_code=403, detail="This person's account is still pending verification by the clinic.")
            return PortalCtx(p, user, grant)
        p = await get_patient_record(user)
        if p.get("verification_status") != "verified":
            raise HTTPException(status_code=403, detail="Your account is still pending verification by the clinic.")
        return PortalCtx(p, user, None)
    return dep


async def notify_patient(patient_id: str, title: str, body: str):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "title": title,
        "body": body,
        "read": False,
        "created_at": now_iso(),
    })


# ---- Smart medication list + refill helpers ----
# v1 destination pharmacy for patient refills: the clinic's established pharmacy.
# Resolved from the practice's configured relationship when present, else the
# clinic default. Kept extensible for future VIen-connected pharmacies.
DEFAULT_CLINIC_PHARMACY_LABEL = "1670 Dufferin Drug Mart"


async def _refill_pharmacy_label(patient: dict) -> str:
    pr_id = (patient or {}).get("practice_id")
    if pr_id:
        pr = await db.practices.find_one({"id": pr_id}, {"_id": 0, "default_pharmacy_name": 1})
        if pr and pr.get("default_pharmacy_name"):
            return pr["default_pharmacy_name"]
    return DEFAULT_CLINIC_PHARMACY_LABEL


def _med_strength_display(d: dict) -> str:
    """Simple patient-facing strength string from the authoritative medication."""
    s = " ".join([str(x).strip() for x in (d.get("strength"), d.get("unit")) if x]).strip()
    return s or (d.get("strength") or "")


async def _notify_patient_rx_sent(req: dict):
    """No-PHI patient update + in-portal notification + generic email when a
    patient-originated prescription request is sent to the pharmacy."""
    pid = req.get("patient_id")
    if not pid:
        return
    await db.patient_updates.insert_one({
        "id": str(uuid.uuid4()), "patient_id": pid, "type": "prescription_sent",
        "source_type": "prescription", "source_id": req.get("id"),
        "title": "Prescription sent to your pharmacy",
        "body": "Your prescription request has been processed and sent to your pharmacy.",
        "read": False, "created_at": now_iso(),
    })
    await notify_patient(pid, "Prescription sent to your pharmacy",
                         "Your prescription has been sent to your pharmacy. Sign in to the Patient Portal for details.")
    p = await db.patients.find_one({"id": pid}, {"_id": 0})
    # Tracked send: records sent / failed / skipped_no_email (e.g. directory-only patient).
    lang = notify_svc._lang(p)
    html = email_service.generic_update_html((p or {}).get("first_name") or "", "Prescription sent to your pharmacy",
                                             "Your prescription has been sent to your pharmacy. Sign in to the Patient Portal for details.",
                                             notify_svc.PORTAL_URL, lang=lang)
    await notify_svc._send_email(db, pid, (p or {}).get("email"),
                                 email_service.subject("rx_sent", lang), html,
                                 kind="prescription_sent", ref=req.get("ref_number"))


def _clean_name(v) -> str:
    return (str(v or "").strip() or "there")


# ----------------------------- Bodies -----------------------------
class RegisterBody(BaseModel):
    patient_type: str
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    second_last_name: Optional[str] = None
    date_of_birth: str
    sex: Optional[str] = None
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
    practice_slug: Optional[str] = None
    practice_code: Optional[str] = None
    practice_id: Optional[str] = None


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
    options: List[dict] = []  # exactly ONE slot [{date,time,label,display}] (legacy list shape)
    patient_note: Optional[str] = None
    appointment_type: Optional[str] = None  # IN_CLINIC | TELEPHONE
    acknowledge_existing: bool = False      # deliberate continuation when an upcoming appt/request exists


class PrescriptionBody(BaseModel):
    medication_name: str
    strength: Optional[str] = None
    directions: Optional[str] = None
    requested_months: int = 1
    delivery_method: str = "pickup"
    pharmacy_id: Optional[str] = None
    new_pharmacy_details: Optional[str] = None
    patient_note: Optional[str] = None


class RefillRequestBody(BaseModel):
    medication_ids: List[str] = []
    supply_type: str = "standard"               # standard | longer
    requested_months: Optional[int] = None      # 1/2/3 (standard) or 4/5/6 (longer)
    requested_supply_text: Optional[str] = None  # free text when "Other"
    travel_note: Optional[str] = None
    patient_note: Optional[str] = None


class PrescriptionRequestBody(BaseModel):
    medication_name: str                         # exactly as selected/typed
    medication_entry_source: str = "CATALOG"     # CATALOG | MANUAL
    drug: Optional[str] = None
    brand: Optional[str] = None
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
    cancel_reason: Optional[str] = None   # admin cancel / decline reason (required for cancel)
    free_slot: Optional[bool] = None      # admin cancel: True = free the time, False = keep blocked


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
    override_same_day: bool = False
    override_reason: Optional[str] = None


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
    confirm_new_patient: bool = False


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
    practice_slug: Optional[str] = None
    practice_code: Optional[str] = None
    practice_id: Optional[str] = None


class NewPatientRequestBody(BaseModel):
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    second_last_name: Optional[str] = None
    date_of_birth: str
    phone: str
    email: EmailStr
    address: Optional[str] = None
    unit: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    has_ohip: Optional[bool] = None
    had_family_doctor: Optional[bool] = None
    join_reason: Optional[str] = None
    reason_other: Optional[str] = None
    status_in_canada: Optional[str] = None
    patient_message: Optional[str] = None
    preferred_language: str = "en"
    practice_slug: Optional[str] = None
    practice_code: Optional[str] = None
    practice_id: Optional[str] = None


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


def _appt_when(a: dict):
    """(date, time24) from canonical fields, falling back to legacy confirmed_* fields."""
    ds = a.get("slot_date") or a.get("confirmed_date")
    t = a.get("slot_time") or a.get("confirmed_slot_time") or avail_mod._norm_time(a.get("confirmed_time") or "")
    if not ds and a.get("status") == "requested":
        o = (a.get("preferred_options") or [{}])[0]
        ds, t = o.get("date"), avail_mod._norm_time(o.get("time") or "")
    return ds, t


async def _upcoming_for_patient(patient_id: str):
    """Future CONFIRMED appointments or active REQUESTED/HELD requests for this patient."""
    today = date.today().isoformat()
    items = await db.appointment_requests.find(
        {"patient_id": patient_id, "status": {"$in": ["requested", "confirmed", "rescheduled"]}}, {"_id": 0}).to_list(50)
    return [a for a in items if a.get("status") == "requested" or (_appt_when(a)[0] or "") >= today]


def _validate_bookable(avail, ds, t24, allow_past=False):
    if not avail_mod.is_within(avail, ds, t24):
        raise HTTPException(status_code=400, detail="That time is outside the clinic's available hours.")
    if not allow_past and avail_mod.is_past_slot(avail, ds, t24):
        raise HTTPException(status_code=400, detail="That time is in the past. Please choose an upcoming time.")


async def _reserve_or_409(practice_id, ds, t24, appt_id, state, actor):
    avail = await get_availability_doc()
    dur = int((avail or {}).get("appointment_duration") or 30)
    if not await slots_mod.is_free(db, practice_id, ds, t24, exclude_appointment_id=appt_id, duration=dur):
        raise HTTPException(status_code=409, detail=slots_mod.SLOT_TAKEN_MSG)
    try:
        return await slots_mod.reserve(db, practice_id, ds, t24, appt_id, state, actor)
    except slots_mod.SlotTaken:
        raise HTTPException(status_code=409, detail=slots_mod.SLOT_TAKEN_MSG)


async def _guard_new_booking(practice_id, ident, ds, appt_id, actor, source, override=False, override_reason=None):
    """Patient-level same-day rule for a NEW appointment. Portal callers never pass override.
    Returns the override record (or None) to stamp on the appointment."""
    try:
        await guard_mod.check_same_day(db, practice_id, ident, ds, actor=actor, source=source)
    except guard_mod.SameDayExists as e:
        if source == "portal":
            raise HTTPException(status_code=409, detail=guard_mod.portal_detail(e.existing))
        if not override:
            raise HTTPException(status_code=409, detail=guard_mod.staff_detail(e.existing))
        reason = (override_reason or "").strip()
        if not reason:
            raise HTTPException(status_code=400, detail={"code": "OVERRIDE_REASON_REQUIRED",
                                                         "message": "A reason is required to book a second same-day appointment."})
        rec = {"reason": reason, "by": actor.get("name"), "by_role": actor.get("role"), "at": now_iso(),
               "existing_appointment_ids": [d["id"] for d in e.existing]}
        await audit("appointment_same_day_override", "appointment", appt_id, actor,
                    meta={"date": ds, "patient_key": ident["key"], **rec})
        return rec
    try:
        await guard_mod.acquire_day_lock(db, practice_id, ident["key"], ds, appt_id)
    except guard_mod.SameDayExists:
        await audit("appointment_same_day_blocked", "patient", ident["key"], actor,
                    meta={"date": ds, "source": source, "concurrent": True})
        detail = guard_mod.portal_detail([]) if source == "portal" else guard_mod.staff_detail([])
        raise HTTPException(status_code=409, detail=detail)
    return None


async def _guard_move(practice_id, ident, appt_id, new_ds, actor, source):
    """Same-day rule for RESCHEDULING an existing appointment (never counts itself)."""
    try:
        await guard_mod.check_same_day(db, practice_id, ident, new_ds, exclude_id=appt_id, actor=actor, source=source)
        await guard_mod.move_day_lock(db, practice_id, ident["key"], appt_id, new_ds)
    except guard_mod.SameDayExists as e:
        detail = guard_mod.portal_detail(e.existing) if source == "portal" else guard_mod.staff_detail(e.existing)
        raise HTTPException(status_code=409, detail=detail)


# ----------------------------- Synthetic test patients -----------------------------
SYNTHETIC_MARKER = "SYNTHETIC TEST PATIENT — NOT FOR REAL CLINICAL CARE"
SYNTHETIC_BLOCK_MSG = "Blocked: this is a SYNTHETIC TEST PATIENT. External/real-world actions (Rx transmission, billing, requisitions, portal linking, notifications) are disabled."


async def is_synthetic_patient(*ids) -> bool:
    ids = [i for i in ids if i]
    if not ids:
        return False
    if await db.patient_directory.find_one({"id": {"$in": ids}, "is_synthetic": True}, {"_id": 1}):
        return True
    return bool(await db.patients.find_one({"id": {"$in": ids}, "is_synthetic": True}, {"_id": 1}))


async def block_synthetic(*ids, what: str, user: dict = None):
    """403 for real-world side effects on synthetic test patients (audited)."""
    if await is_synthetic_patient(*ids):
        await audit("synthetic_side_effect_blocked", "patient", next(i for i in ids if i), user, meta={"what": what})
        raise HTTPException(status_code=403, detail={"code": "SYNTHETIC_PATIENT", "message": SYNTHETIC_BLOCK_MSG})


def _confirmed_fields(ds, t24, label=None, display=None):
    lbl = label or avail_mod._label(avail_mod._to_min(t24))
    return {**slots_mod.canonical_fields(ds, t24), "confirmed_date": ds, "confirmed_time": lbl,
            "confirmed_slot_time": t24, "confirmed_display": display or f"{fmt_date_display(ds)} · {lbl}"}


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
    must fall within exactly 5 years ago through today. Expiry year must be
    current..current+5 and fall after the issue date; the DOB-derived month/day is
    UI assistance only (printed card is authoritative)."""
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
        # DOB-derived month/day is the smart DEFAULT in the UI, not a hard rule: the printed card is authoritative.
        if issue_str and expiry <= _parse_iso(issue_str):
            raise HTTPException(status_code=400, detail="Health Card expiry date must be after the issue date.")


# ----------------------------- Practices (care-ownership context) -----------------------------
# A "practice" is the physician/clinic context a registration belongs to. It is the
# minimal care-ownership tenant for the patient workflow (distinct from the referral
# `organizations`/`providers` registry). The slug is a routing identifier only — NOT
# a security credential. Scoping/queue isolation is layered on in Stage B.
DEFAULT_PRACTICE_SLUG = "dr-aguayo"


def _public_practice(p: dict) -> dict:
    return {
        "id": p["id"], "slug": p.get("slug"),
        "physician_name": p.get("physician_name"), "clinic_name": p.get("clinic_name"),
        "clinic_phone": p.get("clinic_phone"), "clinic_address": p.get("clinic_address"),
    }


async def resolve_practice(practice_id: Optional[str] = None, slug: Optional[str] = None,
                           code: Optional[str] = None, allow_default: bool = True) -> Optional[dict]:
    """Resolve the registration practice context. Priority: explicit id > slug > code.
    When nothing is supplied and allow_default is set, fall back to the single active
    practice (keeps the current single-practice behavior unchanged). An explicitly
    supplied-but-unknown id/slug/code resolves to None so callers can reject it."""
    if practice_id:
        return await db.practices.find_one({"id": practice_id, "active": True}, {"_id": 0})
    if slug:
        return await db.practices.find_one({"slug": slug.strip().lower(), "active": True}, {"_id": 0})
    if code:
        return await db.practices.find_one({"registration_code": code.strip().upper(), "active": True}, {"_id": 0})
    if allow_default:
        actives = await db.practices.find({"active": True}, {"_id": 0}).to_list(2)
        if len(actives) == 1:
            return actives[0]
        return await db.practices.find_one({"slug": DEFAULT_PRACTICE_SLUG, "active": True}, {"_id": 0})
    return None


async def resolve_practice_for_registration(body) -> dict:
    """Resolve + require a practice for a registration/application submission. Raises
    400 if an explicit slug/code/id was provided but did not match any active practice."""
    explicit = bool(getattr(body, "practice_id", None) or getattr(body, "practice_slug", None)
                    or getattr(body, "practice_code", None))
    p = await resolve_practice(getattr(body, "practice_id", None), getattr(body, "practice_slug", None),
                               getattr(body, "practice_code", None), allow_default=not explicit)
    if not p:
        raise HTTPException(status_code=400,
                            detail="We couldn't identify your clinic. Please use the link from your clinic or enter a valid registration code.")
    return p


@api.get("/practices")
async def list_practices(q: Optional[str] = None):
    """Public, minimal clinic lookup for the generic registration fallback. No secrets."""
    query = {"active": True}
    if q:
        query["$or"] = [{"physician_name": {"$regex": q, "$options": "i"}},
                        {"clinic_name": {"$regex": q, "$options": "i"}}]
    docs = await db.practices.find(query).sort("physician_name", 1).to_list(50)
    return [_public_practice(p) for p in docs]


@api.get("/practices/by-code/{code}")
async def practice_by_code(code: str):
    p = await resolve_practice(code=code, allow_default=False)
    if not p:
        raise HTTPException(status_code=404, detail="That registration code was not recognized.")
    return _public_practice(p)


@api.get("/practices/{slug}")
async def practice_by_slug(slug: str):
    p = await resolve_practice(slug=slug, allow_default=False)
    if not p:
        raise HTTPException(status_code=404, detail="Clinic not found.")
    return _public_practice(p)


@api.get("/internal/my-practice")
async def my_practice(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """The caller's own practice registration context for the Registration QR —
    slug + display names only. No internal ids, no registration_code."""
    pid = user.get("practice_id")
    p = await db.practices.find_one({"id": pid, "active": True}, {"_id": 0}) if pid else None
    if not p:
        raise HTTPException(status_code=404, detail="No active practice is associated with your account.")
    return {
        "slug": p.get("slug"),
        "physician_name": p.get("physician_name"),
        "clinic_name": p.get("clinic_name"),
        "clinic_phone": p.get("clinic_phone"),
        "clinic_address": p.get("clinic_address"),
        "register_path": f"/register/{p.get('slug')}",
    }


def _combine_name(base: str, extra: Optional[str]) -> str:
    """Combine a base name with an optional supplemental part (middle name or
    second last name) into a single normalized string — used for directory
    matching and display only, never for storage of the core field."""
    parts = [(base or "").strip(), (extra or "").strip()]
    return " ".join(p for p in parts if p)


def _full_display_name(first: str, middle: Optional[str], last: Optional[str],
                       second_last: Optional[str]) -> str:
    given = _combine_name(first, middle)
    family = _combine_name(last, second_last)
    return " ".join(p for p in [given, family] if p).strip()


REGISTER_REQUIRED = [("first_name", "First name"), ("last_name", "Last name"), ("date_of_birth", "Date of birth"),
                     ("sex", "Sex"), ("phone", "Primary phone"), ("address", "Street address"), ("city", "City"),
                     ("province", "Province"), ("postal_code", "Postal code")]
REGISTER_REQUIRED_OHIP = [("health_card_number", "Health Card number"), ("health_card_version", "Version Code"),
                          ("health_card_issue_date", "Health Card issue date"), ("health_card_expiry_date", "Health Card expiry date")]


def _register_missing(body: "RegisterBody") -> list:
    """Server-side required-field check (never trust disabled buttons). Middle name,
    second last name and unit stay optional. OHIP fields only on the OHIP branch."""
    req = list(REGISTER_REQUIRED) + (list(REGISTER_REQUIRED_OHIP) if body.patient_type == "ohip" else [])
    missing = [{"field": f, "label": lbl} for f, lbl in req if not str(getattr(body, f, "") or "").strip()]
    if body.sex and body.sex not in ("Male", "Female", "X"):
        missing.append({"field": "sex", "label": "Sex"})
    return missing


@api.post("/auth/register")
async def register(body: RegisterBody):
    missing = _register_missing(body)
    if missing:
        raise HTTPException(status_code=400, detail={
            "code": "MISSING_FIELDS", "fields": [m["field"] for m in missing],
            "message": "Please complete: " + ", ".join(m["label"] for m in missing) + "."})
    validate_dob_age(body.date_of_birth)
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    # Supplemental name parts (optional) — stored separately, never appended into
    # the core first_name/last_name. For directory matching ONLY we combine them
    # so the existing match behavior stays identical to before.
    middle = (body.middle_name or "").strip() or None
    second_last = (body.second_last_name or "").strip() or None
    base_first, base_last = body.first_name.strip(), body.last_name.strip()
    match_first = _combine_name(base_first, middle)
    match_last = _combine_name(base_last, second_last)
    full_name = _full_display_name(base_first, middle, base_last, second_last)

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

    # Directory-assisted matching for current-patient registrations (uses the
    # combined names to keep the existing match behavior unchanged).
    match = await directory_mod.match_registration(
        db, match_first, match_last, body.date_of_birth, body.health_card_number)

    # FORMER_CLOSED is historical/reference data only. It no longer grants a
    # special re-establish route: treat the person as NOT currently active and
    # send them through the normal New Patient Application, like any prospective
    # patient. No account is created here; the frontend switches to the apply form.
    if match["outcome"] == directory_mod.FORMER_MATCH:
        return {
            "application_required": True,
            "message_code": "APPLICATION_REQUIRED",
            "prefill": {
                "first_name": body.first_name, "last_name": body.last_name,
                "date_of_birth": body.date_of_birth, "email": email,
                "phone": body.phone, "province": body.province,
            },
        }

    # Duplicate-account guard: an ACTIVE directory record already linked to a portal patient.
    if match.get("outcome") == directory_mod.ACTIVE_MATCH and match.get("matched_id"):
        d = await db.patient_directory.find_one({"id": match["matched_id"]})
        linked_pid = d.get("linked_patient_id") if d else None
        if linked_pid:
            linked = await db.patients.find_one({"id": linked_pid})
            # If the linked record is an UNCLAIMED bridge record (created so a caregiver
            # could be granted access) and has no login yet, let the real patient CLAIM
            # it now — preserving the PIN, history and delegate grants — instead of
            # blocking registration or creating a duplicate patient.
            is_unclaimed = linked and (linked.get("is_unclaimed") or linked.get("has_login") is False) \
                and not await db.users.find_one({"patient_id": linked_pid})
            if is_unclaimed:
                res = await db.users.insert_one({
                    "email": email, "password_hash": authlib.hash_password(body.password),
                    "name": full_name, "role": "patient",
                    "patient_id": linked_pid, "active": True, "created_at": now_iso(),
                })
                uid = str(res.inserted_id)
                await db.patients.update_one({"id": linked_pid}, {"$set": {
                    "email": email, "phone": identity_mod.normalize_phone(body.phone),
                    "middle_name": middle, "second_last_name": second_last,
                    "health_card_number": hc_num, "health_card_version": hc_ver,
                    "health_card_issue_date": body.health_card_issue_date or linked.get("health_card_issue_date"),
                    "health_card_expiry_date": body.health_card_expiry_date or linked.get("health_card_expiry_date"),
                    "sex": (body.sex or linked.get("sex")),
                    "address": body.address or linked.get("address"), "unit": body.unit or linked.get("unit"),
                    "city": body.city or linked.get("city"), "postal_code": body.postal_code or linked.get("postal_code"),
                    "province": body.province or linked.get("province"), "country": body.country or linked.get("country"),
                    "patient_type": body.patient_type, "preferred_language": email_service.norm_lang(body.preferred_language),
                    "portal_status": "ACTIVE", "verification_status": "verified",
                    "is_unclaimed": False, "has_login": True,
                    "claimed_at": now_iso(), "updated_at": now_iso(),
                }})
                await audit("claim_unclaimed_portal_patient", "patient", linked_pid,
                            {"id": uid, "name": body.first_name, "role": "patient"},
                            meta={"directory_id": d["id"], "email": email})
                token = authlib.create_access_token(uid, email, "patient")
                user = await db.users.find_one({"_id": res.inserted_id})
                return {"token": token, "user": serialize_user(user)}
            raise HTTPException(
                status_code=409,
                detail="It looks like you may already have a portal account. Please sign in or use Forgot Password, or contact the clinic.")

    review_queue = match["outcome"]
    practice = await resolve_practice_for_registration(body)
    patient_id = str(uuid.uuid4())
    patient = {
        "id": patient_id, "visita_patient_id": None,
        "first_name": base_first, "last_name": base_last,
        "middle_name": middle, "second_last_name": second_last,
        "date_of_birth": body.date_of_birth, "health_card_number": hc_num,
        "health_card_version": hc_ver,
        "sex": (body.sex or None),
        "health_card_issue_date": body.health_card_issue_date or None,
        "health_card_expiry_date": body.health_card_expiry_date or None,
        "phone": identity_mod.normalize_phone(body.phone), "email": email,
        "province": body.province, "country": body.country, "extra_info": body.extra_info,
        "address": body.address, "unit": body.unit, "city": body.city, "postal_code": body.postal_code,
        "patient_type": body.patient_type, "verification_status": "pending",
        "portal_status": "PENDING_VERIFICATION",
        "review_queue": review_queue, "directory_match": match,
        "matched_directory_id": match.get("matched_id"),
        "practice_id": practice["id"], "practice_slug": practice.get("slug"),
        "preferred_language": email_service.norm_lang(body.preferred_language),
        "active_status": True, "is_demo": False, "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.patients.insert_one({**patient})
    res = await db.users.insert_one({
        "email": email, "password_hash": authlib.hash_password(body.password),
        "name": full_name, "role": "patient",
        "patient_id": patient_id, "active": True, "created_at": now_iso(),
    })
    uid = str(res.inserted_id)
    await audit("register", "patient", patient_id, {"id": uid, "name": patient["first_name"], "role": "patient"},
                meta={"review_queue": review_queue, "match_outcome": match["outcome"]})
    if match.get("candidates"):
        await audit("directory_match_suggested", "patient", patient_id,
                    {"id": uid, "name": patient["first_name"], "role": "patient"},
                    meta={"outcome": match["outcome"], "candidate_count": len(match["candidates"])})
    # Stage C — record the per-practice relationship for this canonical patient.
    # ACTIVE_MATCH = already an active patient at this practice; everything else
    # (unmatched/ambiguous self-declared) is an applicant until staff verify/link.
    rel_status = rel_mod.ACTIVE if match.get("outcome") == directory_mod.ACTIVE_MATCH else rel_mod.APPLICANT
    await rel_mod.upsert_relationship(
        db, practice_id=practice["id"], status=rel_status,
        directory_id=match.get("matched_id"), patient_id=patient_id,
        visita_patient_id=None, by=patient["first_name"], source="registration")
    token = authlib.create_access_token(uid, email, "patient")
    user = await db.users.find_one({"_id": res.inserted_id})
    try:
        await notify_svc.generic_update(
            db, patient_id, "Registration received",
            "Thank you for registering with Dr. Aguayo's practice. The clinic will verify your identity and "
            "you will receive another email when your Patient Portal account is active.",
            "registration_received", ref=patient_id)
    except Exception as e:
        logger.warning(f"[register] notification failed: {e}")
    return {"token": token, "user": serialize_user(user)}


@api.post("/applications/return-request")
async def return_request(body: ReturnRequestBody):
    """LEGACY / DORMANT — the 'Request to Re-establish Care' flow has been removed
    from the VIen patient journey. This endpoint is no longer referenced by any UI
    and should not be called. It is retained (read-only/dormant) only so historical
    `former_return` applications remain processable. Former patients now use the
    normal New Patient Application (POST /applications/new-patient)."""
    validate_dob_age(body.date_of_birth)
    practice = await resolve_practice_for_registration(body)
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
        "practice_id": practice["id"], "practice_slug": practice.get("slug"),
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
    practice = await resolve_practice_for_registration(body)
    ref = await next_ref("APP")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "application_type": "new_patient",
        "first_name": body.first_name.strip(), "last_name": body.last_name.strip(),
        "middle_name": (body.middle_name or "").strip() or None,
        "second_last_name": (body.second_last_name or "").strip() or None,
        "date_of_birth": body.date_of_birth, "health_card_number": None,
        "phone": body.phone, "email": body.email.lower(),
        "address": body.address, "unit": body.unit,
        "city": body.city, "province": body.province, "postal_code": body.postal_code, "country": body.country,
        "coverage": "OHIP" if body.has_ohip else ("PRIVATE_UNINSURED" if body.has_ohip is False else None),
        "had_family_doctor": body.had_family_doctor,
        "join_reason": body.join_reason, "reason_other": body.reason_other,
        "status_in_canada": body.status_in_canada,
        "patient_message": body.patient_message, "preferred_language": body.preferred_language or "en",
        "directory_match": None, "matched_directory_id": None,
        "practice_id": practice["id"], "practice_slug": practice.get("slug"),
        "internal_status": "REQUEST_RECEIVED", "internal_notes": [],
        "accepted_by": None, "accepted_at": None, "previous_status": None, "new_status": None,
        "history": [{"status": "REQUEST_RECEIVED", "at": now_iso(), "by": "patient"}],
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.patient_applications.insert_one({**doc})
    await audit("create", "patient_application", doc["id"],
                {"id": None, "name": f"{body.first_name} {body.last_name}", "role": "patient"},
                new_status="REQUEST_RECEIVED", meta={"type": "new_patient"})
    # Stage C — applicant relationship at this practice (no canonical identity yet).
    await rel_mod.upsert_relationship(
        db, practice_id=practice["id"], status=rel_mod.APPLICANT,
        application_id=doc["id"], by="patient", source="application")
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
    # One-time temp passwords expire: block login once expired so the user must get a new one.
    exp = user.get("temp_password_expires_at")
    if user.get("must_change_password") and exp:
        try:
            expired = datetime.fromisoformat(exp) < datetime.now(timezone.utc)
        except Exception:
            logger.warning("temp_password_expires_at unparseable for user %s; failing closed", str(user["_id"]))
            expired = True
        if expired:
            raise HTTPException(status_code=403,
                                detail="Your temporary password has expired. Please contact the clinic for a new one.")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now_iso()}})
    token = authlib.create_access_token(str(user["_id"]), user.get("email") or user.get("username"), user["role"])
    return {"token": token, "user": serialize_user(user)}


@api.post("/platform/auth/login")
async def platform_login(body: LoginBody):
    """Installation-level operator sign-in: ONLY role developer_ops. Independent of any
    practice/organization membership. Any other role (or unknown identifier) gets the same
    generic 401 so no role information leaks."""
    ident = (body.identifier or body.email or "").strip()
    if not ident:
        raise HTTPException(status_code=400, detail="Please enter your email or username.")
    user = await db.users.find_one({"role": "developer_ops", "$or": [
        {"email": ident.lower()},
        {"username": {"$regex": f"^{re.escape(ident)}$", "$options": "i"}},
    ]})
    if not user or not authlib.verify_password(body.password, user["password_hash"]):
        await audit("platform_login_failed", "user", ident.lower(), {"id": None, "name": None, "role": "developer_ops"})
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if not user.get("active", True) or user.get("platform_suspended"):
        raise HTTPException(status_code=403, detail="This platform account is suspended.")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now_iso(), "last_platform_login_at": now_iso()}})
    await audit("platform_login", "user", str(user["_id"]), {"id": str(user["_id"]), "name": user.get("name"), "role": user["role"]})
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

class EmailChangeRequestBody(BaseModel):
    new_email: EmailStr
    current_password: str


class EmailChangeVerifyBody(BaseModel):
    code: str


@api.post("/portal/account/email/request")
async def portal_email_change_request(body: EmailChangeRequestBody, user: dict = Depends(get_current_user)):
    """Patient/caregiver changes THEIR OWN login email. Requires current password,
    sends a 6-digit code to the NEW address; the email is only swapped after the
    code is verified. Conflict-checked so we never overwrite another user."""
    doc = await db.users.find_one({"_id": ObjectId(user["id"])})
    if not doc or not authlib.verify_password(body.current_password, doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Your current password is incorrect.")
    new_email = body.new_email.lower().strip()
    if new_email == (doc.get("email") or "").lower():
        raise HTTPException(status_code=400, detail="That is already your email address.")
    if await db.users.find_one({"email": new_email}):
        raise HTTPException(status_code=409, detail="That email is already in use by another account.")
    code = f"{secrets.randbelow(1000000):06d}"
    await db.email_changes.update_one({"user_id": user["id"]}, {"$set": {
        "user_id": user["id"], "new_email": new_email,
        "code_hash": authlib.hash_password(code),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "attempts": 0, "created_at": now_iso(),
    }}, upsert=True)
    lang = "en"
    if doc.get("patient_id"):
        pat = await db.patients.find_one({"id": doc["patient_id"]}, {"preferred_language": 1})
        lang = email_service.norm_lang((pat or {}).get("preferred_language"))
    try:
        await email_service.send_email(to=new_email, subject=email_service.subject("reset_code", lang),
                                       html=email_service.reset_code_html(doc.get("name"), code, lang=lang))
    except Exception:
        raise HTTPException(status_code=502, detail="We couldn't send the code right now. Please try again shortly.")
    await audit("email_change_requested", "user", user["id"], user)
    return {"ok": True, "pending_email": new_email}


@api.post("/portal/account/email/verify")
async def portal_email_change_verify(body: EmailChangeVerifyBody, user: dict = Depends(get_current_user)):
    rec = await db.email_changes.find_one({"user_id": user["id"]})
    if not rec:
        raise HTTPException(status_code=400, detail="No pending email change. Please start again.")
    if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
        await db.email_changes.delete_one({"user_id": user["id"]})
        raise HTTPException(status_code=400, detail="Your code has expired. Please request a new one.")
    if rec.get("attempts", 0) >= 5:
        await db.email_changes.delete_one({"user_id": user["id"]})
        raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code.")
    if not authlib.verify_password(body.code.strip(), rec["code_hash"]):
        await db.email_changes.update_one({"user_id": user["id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    new_email = rec["new_email"]
    if await db.users.find_one({"email": new_email, "_id": {"$ne": ObjectId(user["id"])}}):
        await db.email_changes.delete_one({"user_id": user["id"]})
        raise HTTPException(status_code=409, detail="That email is already in use by another account.")
    doc = await db.users.find_one({"_id": ObjectId(user["id"])})
    old_email = doc.get("email")
    await db.users.update_one({"_id": ObjectId(user["id"])},
                              {"$set": {"email": new_email, "email_verified": True, "updated_at": now_iso()}})
    if doc.get("patient_id"):
        await db.patients.update_one({"id": doc["patient_id"]}, {"$set": {"email": new_email, "updated_at": now_iso()}})
    await db.email_changes.delete_one({"user_id": user["id"]})
    await audit("email_changed", "user", user["id"], user, meta={"old_email": old_email, "new_email": new_email})
    return {"ok": True, "email": new_email}


@api.post("/portal/account/request-pin")
async def portal_request_pin(user: dict = Depends(get_current_user)):
    """Patient asks the clinic to share their Visita PIN (sent out-of-band by staff)."""
    if user.get("role") != "patient" or not user.get("patient_id"):
        raise HTTPException(status_code=400, detail="Only patients can request their PIN.")
    p = await db.patients.find_one({"id": user["patient_id"]})
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    now = now_iso()
    ref = await next_ref("PIN")
    await db.pin_requests.insert_one({
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}", "practice_id": p.get("practice_id"),
        "status": "PENDING", "requested_at": now, "created_at": now,
    })
    await audit("pin_requested", "patient", p["id"], user, meta={"ref": ref})
    await notify_patient(p["id"], "PIN request received",
                         "We've asked the clinic to share your Visita PIN with you. They'll follow up shortly.")
    return {"ok": True, "ref_number": ref}

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
async def create_appointment(body: AppointmentBody, ctx: PortalCtx = Depends(portal_access(delegates_mod.APPOINTMENTS))):
    p = ctx.patient
    if await _has_outstanding_fee(p["id"]):
        raise HTTPException(status_code=403, detail=OUTSTANDING_FEE_MSG)
    options = [o for o in (body.options or []) if o.get("date") and o.get("time")]
    if not options:
        raise HTTPException(status_code=400, detail="Please choose an appointment time.")
    opt = options[0]
    ds, t24 = opt["date"], avail_mod._norm_time(opt["time"])
    avail = await get_availability_doc()
    _validate_bookable(avail, ds, t24)
    existing = await _upcoming_for_patient(p["id"])
    if existing and not body.acknowledge_existing:
        raise HTTPException(status_code=409, detail={
            "code": "EXISTING_UPCOMING",
            "message": "You already have an upcoming appointment or appointment request."})
    appt_id = str(uuid.uuid4())
    actor = "delegate" if ctx.is_delegate else "patient"
    # Legacy portal patients may have no practice_id: resolve the default practice so the
    # appointment is always practice-scoped (visible in internal queues/calendar).
    practice_id = p.get("practice_id") or ((await resolve_practice()) or {}).get("id")
    # Physician-configured patient-facing booking types (backend-enforced; internal calendar unaffected).
    allowed_types = await bt_mod.allowed_types(practice_id)
    requested_type = body.appointment_type or ("IN_CLINIC" if "IN_CLINIC" in allowed_types else (allowed_types[0] if allowed_types else None))
    if not allowed_types:
        raise HTTPException(status_code=403, detail="Online booking is not available for this physician right now. Please call the clinic.")
    if requested_type not in allowed_types:
        raise HTTPException(status_code=403, detail=f"{bt_mod.LABELS.get(requested_type, requested_type)} appointments cannot be booked online with this physician right now.")
    body.appointment_type = requested_type
    # portal_access() guarantees a VERIFIED patient (or an authorized caregiver acting for a
    # verified patient) — so verified bookings are CONFIRMED directly (approved by Dr. Aguayo).
    # Any non-verified path is already rejected upstream; the legacy HELD/requested branch is
    # kept only for defensive safety and is never reached for verified patients.
    auto_confirm = PORTAL_AUTO_CONFIRM and p.get("verification_status") == "verified"
    lock_state = slots_mod.CONFIRMED if auto_confirm else slots_mod.HELD
    ident = await guard_mod.identity(db, patient_id=p["id"])
    await _guard_new_booking(practice_id, ident, ds, appt_id, ctx.audit_actor(), "portal")
    try:
        await _reserve_or_409(practice_id, ds, t24, appt_id, lock_state, actor)
    except HTTPException:
        await guard_mod.release_day_lock(db, appt_id)
        raise
    ref = await next_ref("APT")
    appt_type = body.appointment_type if body.appointment_type in ("IN_CLINIC", "TELEPHONE") else None
    label = opt.get("label") or avail_mod._label(avail_mod._to_min(t24))
    status = "confirmed" if auto_confirm else "requested"
    doc = {
        "id": appt_id, "ref_number": ref, "patient_id": p["id"],
        "practice_id": practice_id,
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        "reason": body.reason, "patient_note": body.patient_note,
        "appointment_type": appt_type,
        **slots_mod.canonical_fields(ds, t24),
        "requested_display": opt.get("display") or f"{fmt_date_display(ds)} · {label}",
        "preferred_options": [{"date": ds, "time": t24, "label": label, "display": opt.get("display")}],
        "preferred_date": ds, "preferred_time": label,
        "status": status, "slot_state": lock_state, "staff_note": None,
        "submitted_by_delegate": ctx.is_delegate,
        "acted_by_user_id": ctx.user["id"] if ctx.is_delegate else None,
        "on_behalf_of_patient_id": p["id"] if ctx.is_delegate else None,
        "acknowledged_existing": bool(existing),
        "offered_slots": [], "selected_slot": None,
        "confirmed_date": None, "confirmed_time": None, "confirmed_display": None,
        "approved_by": None, "approved_at": None, "assigned_to": None,
        "booked_from": {"source_type": "portal_self_booking" if auto_confirm else "portal_request", "source_id": None},
        "internal_notes": [], "history": [{"status": status, "at": now_iso(), "by": actor,
                                           "note": ("Self-booked (verified patient) — slot confirmed " if auto_confirm else "Slot held ") + f"{ds} {t24}"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    if auto_confirm:
        doc.update({**_confirmed_fields(ds, t24, label, opt.get("display")),
                    "approved_by": "Patient self-booking (verified)", "approved_at": now_iso(), "completed_at": now_iso()})
    await db.appointment_requests.insert_one({**doc})
    await audit("create", "appointment", doc["id"], ctx.audit_actor(), new_status=status,
                meta=ctx.audit_meta({"slot": f"{ds} {t24}", "auto_confirmed": auto_confirm}))
    await guard_mod.refresh_week_flags(db, practice_id, ident, [ds], ctx.audit_actor())
    doc.pop("_id", None)
    try:
        if auto_confirm:
            await notify_svc.appointment_confirmed(db, doc)
        else:
            await notify_svc.appointment_requested(db, doc)
    except Exception as e:
        logger.warning(f"[appt] booking notification failed: {e}")
    return doc


@api.post("/portal/appointments/{item_id}/select")
async def select_slot(item_id: str, body: SelectSlotBody, ctx: PortalCtx = Depends(portal_access("APPOINTMENTS"))):
    p = ctx.patient
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
    sd, st = slot.get("date"), avail_mod._norm_time(slot.get("time") or "")
    if not avail_mod.is_within(avail, sd, st) or avail_mod.is_past_slot(avail, sd, st):
        raise HTTPException(status_code=409, detail="That time is no longer available. Please contact the clinic.")
    try:
        await slots_mod.move(db, doc.get("practice_id"), item_id, sd, st, slots_mod.CONFIRMED, "patient-selection")
    except slots_mod.SlotTaken:
        raise HTTPException(status_code=409, detail=slots_mod.SLOT_TAKEN_MSG)
    updates = {
        "status": "confirmed", "selected_slot": slot, "slot_state": slots_mod.CONFIRMED,
        **_confirmed_fields(sd, st, slot.get("label"), slot.get("display")),
        "approved_by": "Patient selection",
        "approved_at": now_iso(), "completed_at": now_iso(), "updated_at": now_iso(),
    }
    await db.appointment_requests.update_one({"id": item_id}, {
        "$set": updates,
        "$push": {"history": {"status": "confirmed", "at": now_iso(), "by": "patient-selection"}},
    })
    confirmed = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    await audit("patient_selected_slot", "appointment", item_id, ctx.audit_actor(), new_status="confirmed", meta=ctx.audit_meta())
    await notify_svc.appointment_confirmed(db, confirmed)
    return confirmed


class PatientRescheduleBody(BaseModel):
    date: str
    time: str
    label: Optional[str] = None
    display: Optional[str] = None


@api.post("/portal/appointments/{item_id}/cancel")
async def patient_cancel_appointment(item_id: str, ctx: PortalCtx = Depends(portal_access("APPOINTMENTS"))):
    p = ctx.patient
    appt = await db.appointment_requests.find_one({"id": item_id, "patient_id": p["id"]})
    if not appt:
        raise HTTPException(status_code=404, detail="Not found")
    st = appt.get("status")
    if st not in ("requested", "confirmed", "rescheduled"):
        raise HTTPException(status_code=400, detail="This appointment can't be cancelled online.")
    # >24h rule applies ONLY to confirmed appointments; a held request may be withdrawn any time.
    if st != "requested":
        hrs = _hours_until(appt)
        if hrs is None or hrs < SELF_SERVICE_CUTOFF_HOURS:
            raise HTTPException(status_code=403, detail=WITHIN_24H_MSG)
    actor = "delegate" if ctx.is_delegate else "patient"
    await slots_mod.release(db, item_id)
    await guard_mod.release_day_lock(db, item_id)
    await db.appointment_requests.update_one({"id": item_id}, {
        "$set": {"status": "cancelled", "cancelled_by": actor, "cancelled_at": now_iso(),
                 "slot_state": None,
                 "cancellation": {"reason": "Patient requested cancellation" if st != "requested" else "Request withdrawn by patient",
                                  "free_slot": True, "by": actor, "at": now_iso(), "previous_status": st},
                 "completed_at": now_iso(), "updated_at": now_iso()},
        "$push": {"history": {"status": "cancelled", "at": now_iso(), "by": actor, "note": "Slot released"}}})
    await audit("patient_cancel", "appointment", item_id,
                ctx.audit_actor(), old_status=st, new_status="cancelled", meta=ctx.audit_meta({"slot_freed": True}))
    fresh = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    await guard_mod.refresh_for_appointment(db, fresh, actor=ctx.audit_actor())
    await notify_svc.appointment_cancelled(db, fresh)
    return {"ok": True}


@api.post("/portal/appointments/{item_id}/ack-cancellation")
async def ack_cancellation(item_id: str, ctx: PortalCtx = Depends(portal_access("APPOINTMENTS"))):
    """Patient/caregiver dismisses the Home clinic-cancellation alert. Record untouched otherwise."""
    r = await db.appointment_requests.update_one(
        {"id": item_id, "patient_id": ctx.patient["id"], "status": {"$in": ["cancelled", "declined"]}},
        {"$set": {"cancellation.acknowledged_at": now_iso()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@api.post("/portal/appointments/{item_id}/reschedule")
async def patient_reschedule_appointment(item_id: str, body: PatientRescheduleBody,
                                         ctx: PortalCtx = Depends(portal_access("APPOINTMENTS"))):
    p = ctx.patient
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
    _validate_bookable(avail, body.date, time24)
    actor = "delegate" if ctx.is_delegate else "patient"
    ident = await guard_mod.identity(db, patient_id=p["id"])
    await _guard_move(appt.get("practice_id"), ident, item_id, body.date, ctx.audit_actor(), "portal")
    old_ds, old_t = _appt_when(appt)
    try:
        await slots_mod.move(db, appt.get("practice_id"), item_id, body.date, time24, slots_mod.CONFIRMED, actor,
                             duration=int(avail.get("appointment_duration") or 30))
    except slots_mod.SlotTaken:
        await guard_mod.move_day_lock(db, appt.get("practice_id"), ident["key"], item_id, old_ds)
        raise HTTPException(status_code=409, detail=slots_mod.SLOT_TAKEN_MSG)
    await db.appointment_requests.update_one({"id": item_id}, {
        "$set": {"status": "confirmed", **_confirmed_fields(body.date, time24, body.label, body.display),
                 "slot_state": slots_mod.CONFIRMED, "rescheduled_by": actor,
                 "rescheduled_at": now_iso(), "updated_at": now_iso()},
        "$push": {"history": {"status": "rescheduled", "at": now_iso(), "by": actor,
                              "note": f"Moved from {old_ds} {old_t} to {body.date} {time24}"}}})
    await audit("patient_reschedule", "appointment", item_id,
                ctx.audit_actor(), new_status="confirmed", meta=ctx.audit_meta())
    fresh = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    await guard_mod.refresh_week_flags(db, appt.get("practice_id"), ident, [old_ds, body.date], ctx.audit_actor())
    await notify_svc.appointment_rescheduled(db, fresh)
    return {"ok": True}


async def get_busy_slots(practice_id=None):
    """Shared availability engine input: active slot locks (HELD/CONFIRMED/BLOCKED)
    plus legacy appointment records. Completing/no-show never reopens a slot."""
    return await slots_mod.busy_set(db, practice_id)


@api.get("/availability/slots")
async def availability_slots(days: int = 28, user: dict = Depends(get_current_user)):
    avail = await get_availability_doc()
    busy = await get_busy_slots()
    practice_id = user.get("practice_id")
    if not practice_id and user.get("patient_id"):
        pat = await db.patients.find_one({"id": user["patient_id"]}, {"_id": 0, "practice_id": 1})
        practice_id = (pat or {}).get("practice_id")
    cfg = await bt_mod.config_for(await bt_mod.physician_for_practice(practice_id or ((await resolve_practice()) or {}).get("id")))
    return {"timezone": avail.get("timezone"), "duration": avail.get("appointment_duration"),
            "booking_types": cfg["patient_booking_types"],
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


class BookingTypesBody(BaseModel):
    patient_booking_types: list[str]


@api.get("/admin/booking-types")
async def get_booking_types(user: dict = Depends(require_roles("admin", "physician"))):
    """Per-physician patient-facing booking types for the caller's practice."""
    out = []
    async for ph in db.users.find({"role": "physician", "practice_id": user.get("practice_id")}, {"_id": 1, "name": 1}):
        pid = str(ph["_id"])
        out.append({"physician_user_id": pid, "physician_name": ph.get("name"), **(await bt_mod.config_for(pid))})
    return {"physicians": out, "patient_types": [{"key": k, "label": bt_mod.LABELS[k]} for k in bt_mod.PATIENT_TYPES]}


@api.put("/admin/booking-types/{physician_user_id}")
async def put_booking_types(physician_user_id: str, body: BookingTypesBody, user: dict = Depends(require_roles("admin", "physician"))):
    ph = None
    if ObjectId.is_valid(physician_user_id):
        ph = await db.users.find_one({"_id": ObjectId(physician_user_id), "role": "physician", "practice_id": user.get("practice_id")}, {"_id": 1})
    if not ph:
        raise HTTPException(status_code=404, detail="Physician not found in your practice.")
    before = await bt_mod.config_for(physician_user_id)
    try:
        doc = await bt_mod.save(physician_user_id, user.get("practice_id"), body.patient_booking_types, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Unknown booking type: {e}")
    await audit("update_booking_types", "physician_booking_config", physician_user_id, user,
                meta={"before": before, "after": {"patient_booking_types": doc["patient_booking_types"]}})
    return doc


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
        "$or": [{"confirmed_date": {"$gte": start, "$lte": end}}, {"slot_date": {"$gte": start, "$lte": end}}],
        "status": {"$in": ["requested", "confirmed", "rescheduled", "completed", "no_show", "cancelled"]},
    }, {"_id": 0}).to_list(1000)
    lock_map = {}
    async for lk in db[slots_mod.COLL].find({"date": {"$gte": start, "$lte": end}}, {"_id": 0}):
        lock_map[lk["appointment_id"]] = lk
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
        ds, t = _appt_when(a)
        if not ds:
            continue
        by_day.setdefault(ds, []).append({
            "id": a["id"], "ref_number": a.get("ref_number"),
            "time": t,
            "label": a.get("confirmed_time") or (avail_mod._label(avail_mod._to_min(t)) if t else None),
            "patient_name": a.get("patient_name"),
            "visita_patient_id": pin_map.get(a.get("patient_id")) or pin_map.get(a.get("directory_id")),
            "status": a.get("status"), "reason": a.get("reason"),
            "appointment_type": a.get("appointment_type"),
            "is_private": bool(a.get("is_private")),
            "source": (a.get("booked_from") or {}).get("source_type") or "appointment",
            "slot_blocked": a["id"] in lock_map,
            "cancellation": a.get("cancellation"),
            "cancelled_by": a.get("cancelled_by"), "cancelled_at": a.get("cancelled_at"),
            "completed_by": a.get("completed_by"), "marked_by": a.get("marked_by"), "completed_at": a.get("completed_at"),
            "internal_notes": a.get("internal_notes") or [],
        })
    rem_by_day = {}
    if user.get("role") in ("physician", "admin"):
        async for r in db.calendar_reminders.find({"practice_id": user.get("practice_id"), "date": {"$gte": start, "$lte": end}}, {"_id": 0}):
            rem_by_day.setdefault(r["date"], []).append(r)
    for row in day_rows:
        row["appointments"] = sorted(by_day.get(row["date"], []), key=lambda x: x["time"] or "")
        row["reminders"] = sorted(rem_by_day.get(row["date"], []), key=lambda x: x["time"])
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




class ReminderBody(BaseModel):
    date: str
    time: str
    title: str
    note: Optional[str] = None


@api.post("/internal/calendar/reminders")
async def calendar_reminder_create(body: ReminderBody, user: dict = Depends(require_roles("physician", "admin"))):
    """Personal (non-patient) calendar item for physician/admin. Never touches patients, portal or availability."""
    title = (body.title or "").strip()
    if not title or len(title) > 120:
        raise HTTPException(status_code=400, detail="Please enter a short title.")
    try:
        t24 = avail_mod._norm_time(body.time)
        datetime.strptime(f"{body.date} {t24}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Please enter a valid date and time.")
    doc = {"id": str(uuid.uuid4()), "practice_id": user.get("practice_id"), "date": body.date, "time": t24,
           "label": avail_mod._label(avail_mod._to_min(t24)), "title": title, "note": (body.note or "").strip()[:500] or None,
           "created_by": {"id": user["id"], "name": user.get("name")}, "created_at": now_iso()}
    await db.calendar_reminders.insert_one({**doc})
    await audit("calendar_reminder_created", "calendar_reminder", doc["id"], user, meta={"date": body.date, "time": t24})
    return doc


@api.delete("/internal/calendar/reminders/{rid}")
async def calendar_reminder_delete(rid: str, user: dict = Depends(require_roles("physician", "admin"))):
    r = await db.calendar_reminders.find_one_and_delete({"id": rid, "practice_id": user.get("practice_id")})
    if not r:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    await audit("calendar_reminder_deleted", "calendar_reminder", rid, user, meta={"date": r.get("date"), "time": r.get("time")})
    return {"ok": True}


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
    override_same_day: bool = False
    override_reason: Optional[str] = None
    manual: bool = False  # physician/admin any-time override (outside configured clinic hours)


@api.post("/internal/calendar/book")
async def calendar_book(body: CalendarBookBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    if body.manual and user.get("role") not in ("physician", "admin"):
        raise HTTPException(status_code=403, detail="Only a physician or admin can schedule outside clinic hours.")
    # Resolve the patient identity from either a directory record or a verified portal account.
    if body.directory_id:
        d = await db.patient_directory.find_one({"id": body.directory_id})
        if not d:
            raise HTTPException(status_code=404, detail="Patient not found in directory.")
        appt_patient_id = d.get("linked_patient_id") or d["id"]
        appt_directory_id = d["id"]
        patient_name = f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", ")
        ident = await guard_mod.identity(db, directory_id=d["id"])
    elif body.patient_id:
        p = await db.patients.find_one({"id": body.patient_id})
        if not p:
            raise HTTPException(status_code=404, detail="Patient not found.")
        if p.get("verification_status") != "verified":
            raise HTTPException(status_code=400, detail="Only verified patients can be booked.")
        appt_patient_id = p["id"]
        appt_directory_id = p.get("matched_directory_id")
        patient_name = f"{p.get('last_name','')}, {p.get('first_name','')}".strip(", ")
        ident = await guard_mod.identity(db, patient_id=p["id"])
    else:
        raise HTTPException(status_code=400, detail="A patient must be selected.")
    avail = await get_availability_doc()
    if body.manual:
        try:
            time24 = avail_mod._norm_time(body.time)
            datetime.strptime(f"{body.date} {time24}", "%Y-%m-%d %H:%M")
        except ValueError:
            raise HTTPException(status_code=400, detail="Please enter a valid date and time.")
        if avail_mod.is_past_slot(avail, body.date, time24):
            raise HTTPException(status_code=400, detail="That time is in the past. Please choose an upcoming time.")
    else:
        time24 = avail_mod._norm_time(body.time)
        _validate_bookable(avail, body.date, time24)
    appt_id = str(uuid.uuid4())
    override = await _guard_new_booking(user.get("practice_id"), ident, body.date, appt_id, user, "calendar",
                                        body.override_same_day, body.override_reason)
    try:
        await _reserve_or_409(user.get("practice_id"), body.date, time24, appt_id, slots_mod.CONFIRMED, user["name"])
    except HTTPException:
        await guard_mod.release_day_lock(db, appt_id)
        raise
    ref = await next_ref("APT")
    appt = {
        "id": appt_id, "ref_number": ref, "patient_id": appt_patient_id,
        "practice_id": user.get("practice_id"),
        "directory_id": appt_directory_id, "patient_name": patient_name,
        "reason": body.reason or "Office visit", "appointment_type": body.appointment_type,
        "same_day_override": override,
        "duration": avail.get("appointment_duration"), "preferred_options": [],
        "status": "confirmed", "slot_state": slots_mod.CONFIRMED,
        **_confirmed_fields(body.date, time24, body.label),
        "approved_by": user["name"], "approved_at": now_iso(), "booked_by": user["name"],
        "booked_from": {"source_type": "calendar_manual" if body.manual else "calendar", "source_id": None},
        "assigned_to": None, "internal_notes": [],
        "history": [{"status": "confirmed", "at": now_iso(), "by": user["name"],
                     "note": "Manually scheduled by physician/admin (any-time override)" if body.manual else "Booked directly from calendar"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.appointment_requests.insert_one({**appt})
    await audit("calendar_book", "appointment", appt["id"], user, new_status="confirmed",
                meta={"slot": f"{body.date} {time24}", "direct_booking": True, "same_day_override": bool(override),
                      "manual_any_time": bool(body.manual), "outside_clinic_hours": bool(body.manual and not avail_mod.is_within(avail, body.date, time24))})
    await guard_mod.refresh_week_flags(db, user.get("practice_id"), ident, [body.date], user)
    try:
        await notify_svc.appointment_confirmed(db, appt)
    except Exception as e:
        logger.warning(f"[appt] direct booking notification failed: {e}")
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
        "practice_id": pr.get("practice_id"),
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
    appt_id = str(uuid.uuid4())
    await _reserve_or_409(pr.get("practice_id"), ds, time24, appt_id, slots_mod.CONFIRMED, actor_name)
    ref = await next_ref("APT")
    appt = {
        "id": appt_id, "ref_number": ref, "patient_id": pr["patient_id"],
        "practice_id": pr.get("practice_id"),
        "directory_id": pr.get("directory_id"), "patient_name": pr.get("patient_name"),
        "reason": pr.get("reason_label") or "Private consultation",
        "appointment_type": "PRIVATE", "is_private": True,
        "duration": avail.get("appointment_duration"), "preferred_options": [],
        "status": "confirmed", "slot_state": slots_mod.CONFIRMED, **slots_mod.canonical_fields(ds, time24),
        "confirmed_date": ds,
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
        "practice_id": pr.get("practice_id"),
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
            await slots_mod.release(db, appt_id)
            await db.appointment_requests.update_one({"id": appt_id}, {"$set": {
                "status": "cancelled", "slot_state": None, "cancelled_by": actor, "cancelled_at": now_iso(),
                "cancellation": {"reason": reason or "Private request cancelled", "free_slot": True, "by": actor, "at": now_iso()},
                "updated_at": now_iso()}})
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
        "practice_id": inv.get("practice_id"),
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
    await block_synthetic(patient["id"], patient.get("matched_directory_id"), what="invoice", user=user)
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
async def create_rx(body: PrescriptionBody, ctx: PortalCtx = Depends(portal_access(delegates_mod.RX_REQUESTS))):
    p = ctx.patient
    await prof_mod.require_complete(p)
    ref = await next_ref("RX")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        "practice_id": p.get("practice_id"),
        **body.model_dump(), "internal_status": "waiting_physician", "assigned_to": None,
        "internal_notes": [], "history": [{"status": "waiting_physician", "at": now_iso(), "by": "patient", "note": "Patient portal request — routed directly to physician"}],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.prescription_requests.insert_one({**doc})
    await audit("create", "prescription", doc["id"], ctx.audit_actor(), new_status="waiting_physician",
                meta=ctx.audit_meta())
    doc.pop("_id", None)
    return doc


@api.get("/portal/medications")
async def portal_medications(ctx: PortalCtx = Depends(portal_access(delegates_mod.RX_REQUESTS))):
    """Patient-facing READ-ONLY medication list: active, physician-confirmed meds only.
    Sourced from the authoritative `patient_medications` (populated only when a
    physician sends a prescription). Patients can never add/edit/delete here."""
    pid = ctx.patient["id"]
    docs = await db.patient_medications.find(
        {"patient_id": pid, "active": True}, {"_id": 0}
    ).sort("last_prescribed_at", -1).to_list(100)
    meds = [{
        "id": d.get("id"), "regimen_key": d.get("regimen_key"),
        "drug": d.get("drug"), "strength": _med_strength_display(d),
        "form": d.get("form"), "directions": d.get("sig"),
        "status": "Active",
    } for d in docs]
    return {"pharmacy_label": await _refill_pharmacy_label(ctx.patient), "medications": meds}


@api.post("/portal/refill-requests")
async def create_refill_requests(body: RefillRequestBody,
                                 ctx: PortalCtx = Depends(portal_access(delegates_mod.RX_REQUESTS))):
    """Refill from the official list. One prescription_request per selected medicine,
    grouped by a shared batch_id, with authoritative medication fields copied from
    `patient_medications` (never patient free-text). Longer supply stays a REQUEST
    (received) for physician review and is never auto-approved."""
    p = ctx.patient
    await prof_mod.require_complete(p)
    ids = [i for i in (body.medication_ids or []) if i]
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one medication to refill.")
    meds = await db.patient_medications.find(
        {"id": {"$in": ids}, "patient_id": p["id"], "active": True}, {"_id": 0}).to_list(100)
    if not meds:
        raise HTTPException(status_code=404, detail="We couldn't find those medications on your list.")

    longer = body.supply_type == "longer"
    months = body.requested_months if isinstance(body.requested_months, int) else None
    if longer:
        if months not in (4, 5, 6):
            months = months if (isinstance(months, int) and months > 0) else None
        supply_text = (body.requested_supply_text or "").strip() or (f"{months} months" if months else "Longer supply")
    else:
        months = months if months in (1, 2, 3) else 1
        supply_text = f"{months} month(s)"

    pharmacy_label = await _refill_pharmacy_label(p)
    batch_id = str(uuid.uuid4())
    now = now_iso()
    created = []
    for m in meds:
        ref = await next_ref("RX")
        doc = {
            "id": str(uuid.uuid4()), "ref_number": ref, "batch_id": batch_id,
            "patient_id": p["id"], "patient_name": f"{p['last_name']}, {p['first_name']}",
            "practice_id": p.get("practice_id"),
            "source": "patient_refill",
            "patient_medication_id": m.get("id"), "regimen_key": m.get("regimen_key"),
            "medication_name": m.get("drug"), "strength": _med_strength_display(m),
            "directions": m.get("sig"),
            "requested_months": months, "supply_type": body.supply_type,
            "requested_supply_text": supply_text,
            "travel_note": ((body.travel_note or "").strip() or None) if longer else None,
            "delivery_method": "pharmacy", "destination_pharmacy_label": pharmacy_label,
            "patient_note": (body.patient_note or "").strip() or None,
            "internal_status": "waiting_physician", "assigned_to": None, "internal_notes": [],
            "history": [{"status": "waiting_physician", "at": now, "by": "patient", "note": "Patient portal request — routed directly to physician"}],
            "created_at": now, "updated_at": now, "completed_at": None,
        }
        await db.prescription_requests.insert_one({**doc})
        await audit("create", "prescription", doc["id"], ctx.audit_actor(), new_status="waiting_physician",
                    meta=ctx.audit_meta({"batch_id": batch_id, "source": "patient_refill",
                                         "supply_type": body.supply_type}))
        doc.pop("_id", None)
        created.append(doc)
    return {"batch_id": batch_id, "count": len(created), "requests": created}


@api.post("/portal/prescriptions/photo")
async def create_rx_photo(
    file: UploadFile = File(...),
    medication_name: str = Form(""),
    patient_note: str = Form(""),
    ctx: PortalCtx = Depends(portal_access(delegates_mod.RX_REQUESTS)),
):
    """'I don't see my medicine' — photo-first, review-only submission. Stored in
    object storage for staff/physician review. NEVER updates the official
    `patient_medications` list; only a physician-sent prescription can do that."""
    p = ctx.patient
    await prof_mod.require_complete(p)
    attachment = await _store_pharmacy_upload(file, "patient_rx")
    ref = await next_ref("RX")
    now = now_iso()
    name = (medication_name or "").strip() or "Medication (photo submitted)"
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "patient_id": p["id"], "patient_name": f"{p['last_name']}, {p['first_name']}",
        "practice_id": p.get("practice_id"),
        "source": "patient_photo", "review_required": True,
        "medication_name": name, "strength": None, "directions": None,
        "requested_months": None, "delivery_method": "pharmacy",
        "destination_pharmacy_label": await _refill_pharmacy_label(p),
        "patient_note": (patient_note or "").strip() or None,
        "attachment": attachment,
        "internal_status": "waiting_physician", "assigned_to": None, "internal_notes": [],
        "history": [{"status": "waiting_physician", "at": now, "by": "patient", "note": "Patient portal request — routed directly to physician"}],
        "created_at": now, "updated_at": now, "completed_at": None,
    }
    await db.prescription_requests.insert_one({**doc})
    await audit("create", "prescription", doc["id"], ctx.audit_actor(), new_status="waiting_physician",
                meta=ctx.audit_meta({"source": "patient_photo", "has_attachment": True}))
    doc.pop("_id", None)
    return doc


@api.get("/portal/medication-search")
async def portal_medication_search(q: str = "", ctx: PortalCtx = Depends(portal_access(delegates_mod.RX_REQUESTS))):
    """Smart medication typeahead for the Prescription Request flow. Searches the
    effective patient's physician-confirmed meds first, then the shared catalog
    (generic + brand + aliases). HARD max of 5 results, enforced server-side.
    Patient-specific results come ONLY from the effective (own/managed) patient."""
    term = (q or "").strip()
    if not term:
        return []
    rx = re.compile(re.escape(term), re.I)
    tl = term.lower()
    results, seen = [], set()

    def add(label, drug, brand, source, pmid=None):
        key = (label or "").lower()
        if not label or key in seen:
            return
        seen.add(key)
        results.append({"label": label, "drug": drug, "brand": brand, "source": source, "patient_medication_id": pmid})

    # 1) Effective patient's physician-confirmed medications (prefix matches first).
    p = ctx.patient
    pmeds = await db.patient_medications.find({"patient_id": p["id"], "active": True}, {"_id": 0}).to_list(200)
    pm_hits = [m for m in pmeds if m.get("drug") and rx.search(m["drug"])]
    pm_hits.sort(key=lambda m: (0 if m["drug"].lower().startswith(tl) else 1, m["drug"].lower()))
    for m in pm_hits:
        add(m.get("drug"), m.get("drug"), None, "patient", m.get("id"))
        if len(results) >= 5:
            return results[:5]

    # 2) Shared catalog (generic / brand / aliases), prefix matches first.
    cats = await db.medication_catalog.find(
        {"$or": [{"drug": rx}, {"brand": rx}, {"search_terms": rx}]}, {"_id": 0}).to_list(300)

    def cat_prefix(d):
        return (d.get("drug") or "").lower().startswith(tl) or (d.get("brand") or "").lower().startswith(tl)
    cats.sort(key=lambda d: (0 if cat_prefix(d) else 1, (d.get("drug") or "").lower()))
    for d in cats:
        label = f"{d.get('drug')} ({d.get('brand')})" if d.get("brand") else d.get("drug")
        add(label, d.get("drug"), d.get("brand"), "catalog")
        if len(results) >= 5:
            return results[:5]
    return results[:5]


@api.post("/portal/prescription-requests")
async def create_prescription_request(body: PrescriptionRequestBody,
                                      ctx: PortalCtx = Depends(portal_access(delegates_mod.RX_REQUESTS))):
    """A medication-identified Prescription Request (catalog pick or manual free-text).
    Feeds the EXISTING prescription_requests queue (status 'received'). Manual entries
    are flagged for physician review and NEVER touch patient_medications/medication_catalog."""
    p = ctx.patient
    await prof_mod.require_complete(p)
    name = (body.medication_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Enter the medication you're requesting.")
    manual = (body.medication_entry_source or "").upper() == "MANUAL"
    ref = await next_ref("RX")
    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "patient_id": p["id"], "patient_name": f"{p['last_name']}, {p['first_name']}",
        "practice_id": p.get("practice_id"),
        "source": "patient_request",
        "medication_name": name,  # preserved EXACTLY as selected/typed
        "medication_entry_source": "MANUAL" if manual else "CATALOG",
        "requires_medication_review": bool(manual),
        "review_required": bool(manual),
        "catalog_drug": None if manual else (body.drug or name),
        "catalog_brand": None if manual else (body.brand or None),
        "strength": None, "directions": None,
        "requested_months": None, "delivery_method": "pharmacy",
        "destination_pharmacy_label": await _refill_pharmacy_label(p),
        "patient_note": (body.patient_note or "").strip() or None,
        "internal_status": "waiting_physician", "assigned_to": None, "internal_notes": [],
        "history": [{"status": "waiting_physician", "at": now, "by": ("delegate" if ctx.is_delegate else "patient"), "note": "Patient portal request — routed directly to physician"}],
        "created_at": now, "updated_at": now, "completed_at": None,
    }
    await db.prescription_requests.insert_one({**doc})
    await audit("create", "prescription", doc["id"], ctx.audit_actor(), new_status="waiting_physician",
                meta=ctx.audit_meta({"source": "patient_request", "entry_source": doc["medication_entry_source"]}))
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
async def portal_overview(ctx: PortalCtx = Depends(portal_access())):
    p = ctx.patient
    pid = p["id"]
    is_del = ctx.is_delegate
    perms = set(ctx.grant.get("permissions", [])) if is_del else set()
    def allow(perm):
        return (not is_del) or (perm in perms)
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

    requests = []
    if allow("APPOINTMENTS"):
        requests += pa(appts, "Appointment", APPT_PATIENT_STATUS)
    if allow("RX_REQUESTS"):
        requests += pa(rxs, "Prescription", RX_PATIENT_STATUS)
    if allow("REQUEST_STATUS"):
        requests += (pa(imgs, "Imaging", IMG_PATIENT_STATUS) + pa(blds, "Bloodwork", BLD_PATIENT_STATUS))
    if not is_del:
        requests += pa(msgs, "Message", MSG_PATIENT_STATUS)
    requests.sort(key=lambda x: x["created_at"], reverse=True)
    referrals = [{"id": r["id"], "specialty": r.get("specialty"),
                  "status": r.get("patient_visible_status"), "last_updated": r.get("updated_at")} for r in refs]
    def appt_view(a):
        st = a.get("status")
        hrs = _hours_until(a) if st in ("confirmed", "rescheduled") else None
        ds, t = _appt_when(a)
        return {
            "id": a["id"], "ref_number": a["ref_number"], "reason": a["reason"],
            "status": APPT_PATIENT_STATUS.get(st), "raw_status": st,
            "appointment_type": a.get("appointment_type"),
            "preferred_options": a.get("preferred_options", []),
            "offered_slots": a.get("offered_slots", []),
            "slot_date": ds, "slot_time": t, "appointment_at": a.get("appointment_at"),
            "requested_display": a.get("requested_display") or (f"{fmt_date_display(ds)} · {avail_mod._label(avail_mod._to_min(t))}" if ds and t else None),
            "confirmed_date": a.get("confirmed_date"), "confirmed_time": a.get("confirmed_time"),
            "confirmed_slot_time": a.get("confirmed_slot_time"),
            "confirmed_display": a.get("confirmed_display"),
            "late_fee": a.get("late_fee"),
            "hours_until": hrs,
            "can_self_modify": bool(hrs is not None and hrs >= SELF_SERVICE_CUTOFF_HOURS),
            "can_self_cancel": st == "requested" or bool(hrs is not None and hrs >= SELF_SERVICE_CUTOFF_HOURS),
            "cancellation": ({"reason": (a.get("cancellation") or {}).get("reason"), "at": (a.get("cancellation") or {}).get("at")}
                             if a.get("cancellation") else None),
            "staff_note": a.get("staff_note"), "created_at": a["created_at"],
        }
    today_iso = date.today().isoformat()
    has_upcoming = any(a.get("status") == "requested" or
                       (a.get("status") in ("confirmed", "rescheduled") and (_appt_when(a)[0] or "") >= today_iso)
                       for a in appts)
    # Clinic-originated cancellation alert for Home: newest admin/physician cancel that is
    # not acknowledged and not superseded by a later request/booking.
    clinic_cancel_alert = None
    cancelled = [a for a in appts if (a.get("status") == "cancelled" and a.get("cancelled_by") not in (None, "patient", "delegate"))
                 or (a.get("status") == "declined" and a.get("declined_by"))]
    cancelled = [a for a in cancelled if not (a.get("cancellation") or {}).get("acknowledged_at")]
    if cancelled:
        latest = max(cancelled, key=lambda a: a.get("cancelled_at") or a.get("declined_at") or "")
        latest_at = latest.get("cancelled_at") or latest.get("declined_at") or ""
        later_active = [a for a in appts if a.get("status") in ("requested", "confirmed", "rescheduled")
                        and (a.get("created_at") or "") > latest_at]
        if not later_active:
            clinic_cancel_alert = {"id": latest["id"], "ref_number": latest.get("ref_number"),
                                   "display": latest.get("confirmed_display") or latest.get("requested_display"),
                                   "reason": (latest.get("cancellation") or {}).get("reason"),
                                   "was_request": latest.get("status") == "declined",
                                   "cancelled_at": latest_at}
    has_fee = any((a.get("late_fee") or {}).get("status") == "outstanding" for a in appts)
    pending_hc = p.get("pending_health_card")
    eff = prof_mod.effective(p, await prof_mod.canonical_for(p))  # canonical first, then registration
    inv_open = 0 if is_del else await db.invoices.count_documents({"patient_id": pid, "status": {"$in": ["ISSUED", "PAYMENT_SUBMITTED"]}})
    inv_total = 0 if is_del else await db.invoices.count_documents({"patient_id": pid, "status": {"$ne": "DRAFT"}})
    return {
        "delegate": {
            "is_delegate": is_del,
            "patient_name": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            "relationship": ctx.grant.get("relationship") if is_del else None,
            "permissions": sorted(perms) if is_del else None,
        },
        "patient": {"first_name": p["first_name"], "last_name": p["last_name"],
                    "date_of_birth": p.get("date_of_birth"),
                    "patient_type": p["patient_type"], "verification_status": p["verification_status"],
                    "visita_patient_id": p.get("visita_patient_id"),
                    "phone": p.get("phone"), "email": p.get("email"),
                    "sex": eff.get("sex"),
                    "address": p.get("address"), "unit": p.get("unit"),
                    "city": p.get("city"), "province": p.get("province"),
                    "postal_code": p.get("postal_code"),
                    "health_card_display": identity_mod.format_health_card(eff.get("health_card_number"), eff.get("health_card_version_code")),
                    "health_card_issue_date": eff.get("health_card_issue_date"),
                    "health_card_expiry_date": eff.get("health_card_expiry_date"),
                    "health_card_status": identity_mod.health_card_status(eff.get("health_card_expiry_date")),
                    "health_card_update_pending": bool(pending_hc),
                    "pending_health_card": pending_hc,
                    "has_outstanding_fee": (False if is_del else has_fee),
                    "has_upcoming_appointment": has_upcoming,
                    "booking_mode": "confirm" if PORTAL_AUTO_CONFIRM else "request",
                    "clinic_cancellation_alert": clinic_cancel_alert if allow("APPOINTMENTS") else None},
        "requests": requests,
        "appointments": [appt_view(a) for a in appts] if allow("APPOINTMENTS") else [],
        "prescriptions": ([{"id": r["id"], "ref_number": r["ref_number"], "medication_name": r["medication_name"],
                           "strength": r.get("strength"), "status": RX_PATIENT_STATUS.get(r["internal_status"]),
                           "batch_id": r.get("batch_id"), "source": r.get("source"),
                           "supply_type": r.get("supply_type"), "requested_months": r.get("requested_months"),
                           "requested_supply_text": r.get("requested_supply_text"),
                           "destination_pharmacy_label": r.get("destination_pharmacy_label"),
                           "created_at": r["created_at"]} for r in rxs] if allow("RX_REQUESTS") else []),
        "imaging": ([{"id": i["id"], "ref_number": i["ref_number"], "imaging_type": i["imaging_type"],
                     "body_part": i["body_part"], "status": IMG_PATIENT_STATUS.get(i["internal_status"]),
                     "created_at": i["created_at"]} for i in imgs] if allow("REQUEST_STATUS") else []),
        "bloodwork": ([{"id": b["id"], "ref_number": b["ref_number"], "reason": b.get("reason"),
                       "status": BLD_PATIENT_STATUS.get(b["internal_status"]),
                       "created_at": b["created_at"]} for b in blds] if allow("REQUEST_STATUS") else []),
        "messages": ([{"id": m["id"], "ref_number": m["ref_number"], "category": m["category"], "subject": m.get("subject"),
                      "thread": m.get("thread", []), "status": MSG_PATIENT_STATUS.get(m["status"]),
                      "created_at": m["created_at"]} for m in msgs] if not is_del else []),
        "referrals": referrals if allow("REQUEST_STATUS") else [],
        "notifications": notes,
        "updates": await db.patient_updates.find(
            {"patient_id": pid, "read": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(50),
        "documents": (await attach_mod.list_shared_for_patient(db, pid)) if allow("DOCUMENTS") else [],
        "pending_results": ([
            {"id": r["id"], "type_label": r.get("subtype") or r.get("category_label") or "Result",
             "category_label": r.get("category_label"), "subtype": r.get("subtype"),
             "reviewed_at": r.get("reviewed_at"), "reviewed_by": r.get("reviewed_by"),
             "access_requested": bool(r.get("access_requested"))}
            for r in await db.exam_results.find(
                {"patient_id": pid, "status": "REVIEWED", "shared_with_patient": {"$ne": True}},
                {"_id": 0}).sort("reviewed_at", -1).to_list(100)
        ] if allow("DOCUMENTS") else []),
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
async def portal_submit_health_card(body: HealthCardUpdateBody, ctx: PortalCtx = Depends(portal_access("HEALTH_CARD_UPDATE"))):
    """Patient's OWN update is applied INSTANTLY. A DELEGATE (caregiver with
    HEALTH_CARD_UPDATE) submission does NOT overwrite the authoritative record —
    it is queued as a pending update for staff review/approval."""
    p = ctx.patient
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
    display = identity_mod.format_health_card(num, ver)
    if ctx.is_delegate:
        pending = {
            **new_fields, "display": display,
            "previous_display": identity_mod.format_health_card(previous["health_card_number"], previous["health_card_version"]),
            "submitted_by_user_id": ctx.user["id"], "submitted_by_name": ctx.user.get("name"),
            "on_behalf_of_patient_id": p["id"], "relationship": ctx.grant.get("relationship"),
            "submitted_at": now_iso(),
        }
        await db.patients.update_one({"id": p["id"]}, {"$set": {"pending_health_card": pending, "updated_at": now_iso()}})
        await audit("health_card_update_submitted", "patient", p["id"], ctx.audit_actor(),
                    meta=ctx.audit_meta({"previous": previous, "submitted": new_fields}))
        return {"ok": True, "pending": True, "health_card_display": display}
    await db.patients.update_one({"id": p["id"]}, {"$set": {**new_fields, "pending_health_card": None, "updated_at": now_iso()}})
    await audit("patient_health_card_update", "patient", p["id"],
                {"id": p["id"], "name": p["first_name"], "role": "patient"},
                meta={"previous": previous, "new": new_fields})
    return {"ok": True, "health_card_display": display}


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
    ps = pscope(user)
    # Registered portal patients (verified, active) — informational total shown in the sidebar.
    registered = await db.patients.count_documents({**ps, "verification_status": "verified", "active_status": {"$ne": False}})
    if user["role"] == "physician":
        rx = await db.prescription_requests.count_documents({**ps, "internal_status": "waiting_physician"})
        img = await db.imaging_requests.count_documents({**ps, "internal_status": "waiting_physician"})
        pmsg = await db.patient_messages.count_documents({**ps, "status": "waiting_physician"})
        dmsg = await db.internal_messages.count_documents({**ps, "recipient_role": "physician", "status": {"$ne": "completed"}})
        bld = await db.bloodwork_requests.count_documents({**ps, "internal_status": "waiting_physician"})
        apps = await db.patient_applications.count_documents({**ps, "internal_status": {"$in": APP_ACTIVE}})
        par = await db.portal_access_requests.count_documents({**ps, "status": "PENDING"})
        results_review = await db.exam_results.count_documents({**ps, "status": "READY_FOR_PHYSICIAN"})
        result_access = await db.exam_results.count_documents({**ps, "status": "REVIEWED", "shared_with_patient": False, "access_requested": True})
        work = await work_mod.actionable_count(user)
        return {"role": "physician", "registered_patients": registered, "counters": {"rx": rx, "imaging": img, "bloodwork": bld, "messages": pmsg, "doctor_tasks": dmsg, "work_hub": work, "applications": apps, "portal_access": par, "results_review": results_review, "result_access": result_access}}
    rx = await db.prescription_requests.count_documents({**ps, "internal_status": {"$in": RX_ACTIVE}})
    referrals = await db.referrals.count_documents({**ps, "ready_to_fax": True, "faxed": False})
    img = await db.imaging_requests.count_documents({**ps, "internal_status": {"$in": IMG_ACTIVE}})
    bld = await db.bloodwork_requests.count_documents({**ps, "internal_status": {"$in": BLD_ACTIVE}})
    msgs = await db.patient_messages.count_documents({**ps, "status": {"$in": MSG_ACTIVE}})
    appts = await db.appointment_requests.count_documents({**ps, "status": "requested"})
    tasks = await db.internal_messages.count_documents({**ps, "recipient_role": "staff", "status": {"$ne": "completed"}})
    pending_verif = await db.patients.count_documents({**ps, "verification_status": "pending", "active_status": True})
    apps = await db.patient_applications.count_documents({**ps, "internal_status": {"$in": APP_ACTIVE}})
    par = await db.portal_access_requests.count_documents({**ps, "status": "PENDING"})
    exams = await db.exam_results.count_documents({**ps, "status": {"$in": ["NEEDS_PATIENT_MATCH", "RECEIVED"]}})
    return {"role": user["role"], "registered_patients": registered, "counters": {
        "rx": rx, "referrals": referrals, "imaging": img, "bloodwork": bld, "messages": msgs,
        "appointments": appts, "doctor_tasks": tasks, "work_hub": await work_mod.actionable_count(user), "verifications": pending_verif, "applications": apps,
        "portal_access": par, "exams": exams,
    }}


def pscope(user: dict) -> dict:
    """Mongo filter fragment that limits a query to the caller's practice."""
    return {"practice_id": user.get("practice_id")}


def assert_practice(doc, user):
    """Block cross-practice access on a fetched record. Uses 404 so record
    existence is not leaked across practices."""
    if doc is not None and doc.get("practice_id") != user.get("practice_id"):
        raise HTTPException(status_code=404, detail="Not found.")


def _search_filter(q: Optional[str], fields):
    if not q:
        return {}
    return {"$or": [{f: {"$regex": re.escape(q), "$options": "i"}} for f in fields]}


# ----------------------------- Generic request updater -----------------------------
async def _update_request(coll, entity, item_id, body: UpdateBody, user, status_field, notify_title):
    doc = await coll.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    assert_practice(doc, user)
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
        new_status = updates.get(status_field, old)
        kind = f"{entity}_{new_status}"
        if entity == "prescription" and new_status == "approved_process_visita":
            await notify_svc.generic_update(db, doc["patient_id"], "Prescription approved",
                                            "Your prescription request was approved by the clinic and is being processed. "
                                            "Sign in to the Patient Portal for details.", kind, ref=doc.get("ref_number"))
        else:
            await notify_svc.generic_update(db, doc["patient_id"], notify_title,
                                            f"{notify_title} Please log in to your Patient Portal.", kind, ref=doc.get("ref_number"))
    return await coll.find_one({"id": item_id}, {"_id": 0})


# ----------------------------- Prescriptions -----------------------------
async def _attach_pins(rows: list) -> list:
    """Backfill each queue row's patient PIN (visita_patient_id) from portal patient or directory so staff/physician can see it."""
    pids = {r.get("patient_id") for r in rows if r.get("patient_id")}
    dids = {r.get("directory_id") for r in rows if r.get("directory_id")}
    pin_map, phone_map = {}, {}
    if pids:
        async for p in db.patients.find({"id": {"$in": list(pids)}}, {"_id": 0, "id": 1, "visita_patient_id": 1, "matched_directory_id": 1, "phone": 1}):
            if p.get("phone"):
                phone_map[p["id"]] = p["phone"]
            if p.get("visita_patient_id"):
                pin_map[p["id"]] = p["visita_patient_id"]
            elif p.get("matched_directory_id"):
                dids.add(p["matched_directory_id"]); pin_map.setdefault(("via", p["id"]), p["matched_directory_id"])
    if dids:
        async for d in db.patient_directory.find({"id": {"$in": list(dids)}}, {"_id": 0, "id": 1, "visita_patient_id": 1, "cell_phone": 1, "home_phone": 1}):
            if d.get("visita_patient_id"):
                pin_map[d["id"]] = d["visita_patient_id"]
            if d.get("cell_phone") or d.get("home_phone"):
                phone_map[d["id"]] = d.get("cell_phone") or d.get("home_phone")
    for r in rows:
        via = pin_map.get(("via", r.get("patient_id")))
        if not r.get("visita_patient_id"):
            r["visita_patient_id"] = pin_map.get(r.get("patient_id")) or pin_map.get(r.get("directory_id")) or (pin_map.get(via) if via else None) \
                or (r.get("patient_snapshot") or {}).get("visita_patient_id")
        snap = r.get("patient_snapshot") or {}
        r["patient_phone"] = phone_map.get(r.get("patient_id")) or phone_map.get(r.get("directory_id")) or (phone_map.get(via) if via else None) \
            or snap.get("cell_phone") or snap.get("home_phone")
    return rows


@api.get("/internal/prescriptions")
async def rx_queue(q: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = dict(pscope(user))
    if user["role"] == "physician":
        query["internal_status"] = "waiting_physician"
    elif status:
        query["internal_status"] = status
    else:
        # Hide voided/archived requests from the normal active queue.
        query["internal_status"] = {"$nin": ["voided"]}
    query.update(_search_filter(q, ["patient_name", "medication_name", "ref_number"]))
    rows = await db.prescription_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return await _attach_pins(rows)


@api.get("/internal/prescriptions/history")
async def rx_history(directory_id: Optional[str] = None, patient_id: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Past Rx requests for one patient (read-only) so staff can review history and repeat a request from the intake form."""
    ors = [c for c in ([{"directory_id": directory_id}] if directory_id else []) + ([{"patient_id": patient_id}] if patient_id else [])]
    if not ors:
        return []
    query = {**pscope(user), "$or": ors, "internal_status": {"$ne": "voided"}}
    fields = {"_id": 0, "id": 1, "ref_number": 1, "source": 1, "received_via": 1, "pharmacy": 1, "medications": 1, "medications_structured": 1,
              "medication_name": 1, "strength": 1, "duration_qty": 1, "delivery_method": 1, "internal_status": 1, "created_at": 1, "completed_at": 1,
              "linked_transmission_ref": 1, "prescription_sent_at": 1, "physician_note": 1}
    return await db.prescription_requests.find(query, fields).sort("created_at", -1).to_list(25)


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
    medications_structured: Optional[List[dict]] = None
    selected_active_meds: Optional[List[str]] = []
    duration_qty: Optional[str] = None
    pharmacy_note: Optional[str] = None
    received_via: str  # fax | phone | call | email | message | other
    delivery_method: Optional[str] = None  # pharmacy (delivery) | pickup
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
            "is_synthetic": bool(d.get("is_synthetic")),
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
    await block_synthetic((d or p)["id"], (d or {}).get("linked_patient_id"), what="pharmacy_rx", user=user)
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
        "practice_id": user.get("practice_id"),
        "patient_id": rx_patient_id,
        "directory_id": rx_directory_id, "visita_patient_id": rx_vid,
        "patient_name": patient_name,
        "medication_name": "; ".join(meds), "strength": None,
        "medications": meds, "medications_structured": body.medications_structured or [],
        "selected_active_meds": body.selected_active_meds or [],
        "pharmacy": body.pharmacy, "duration_qty": body.duration_qty,
        "pharmacy_note": body.pharmacy_note, "received_via": body.received_via,
        "requested_months": None, "delivery_method": body.delivery_method if body.delivery_method in ("pharmacy", "pickup") else "pharmacy",
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
    query = dict(pscope(user))
    if user["role"] == "physician":
        query["internal_status"] = "waiting_physician"
    elif status:
        query["internal_status"] = status
    query.update(_search_filter(q, ["patient_name", "body_part", "ref_number"]))
    return await _attach_pins(await db.imaging_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500))


@api.patch("/internal/imaging/{item_id}")
async def img_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await _update_request(db.imaging_requests, "imaging", item_id, body, user,
                                 "internal_status", "Your imaging request has been updated.")


# ----------------------------- Bloodwork -----------------------------
@api.get("/internal/bloodwork")
async def bld_queue(q: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = dict(pscope(user))
    if user["role"] == "physician":
        query["internal_status"] = "waiting_physician"
    elif status:
        query["internal_status"] = status
    query.update(_search_filter(q, ["patient_name", "reason", "ref_number"]))
    return await _attach_pins(await db.bloodwork_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500))


@api.patch("/internal/bloodwork/{item_id}")
async def bld_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return await _update_request(db.bloodwork_requests, "bloodwork", item_id, body, user,
                                 "internal_status", "Your bloodwork request has been updated.")


# ============================================================================
# CENTRALIZED EXAMS & RESULTS
#   ONE module for all diagnostic exams/results (lab, imaging, cardiac, etc.).
#   - Requests tab aggregates existing imaging_requests + bloodwork_requests
#     (auto-classified) read-only — NO destructive migration.
#   - exam_results = lightweight record for incoming results (reuses attachments
#     / object storage / taxonomy / secure patient download).
#   Workflow status: RECEIVED -> READY_FOR_PHYSICIAN -> REVIEWED (+ NEEDS_PATIENT_MATCH).
#   Sharing (shared_with_patient) and notification (patient_notified) are SEPARATE
#   flags — release is never a linear workflow step and defaults OFF.
# ============================================================================
EXAM_CATEGORIES = {
    "LABORATORY": "Laboratory",
    "DIAGNOSTIC_IMAGING": "Diagnostic Imaging",
    "CARDIAC_TESTS": "Cardiac Tests",
    "PULMONARY_SLEEP": "Pulmonary / Sleep",
    "PATHOLOGY_CYTOLOGY": "Pathology / Cytology",
    "SCREENING": "Screening",
    "OTHER_REPORTS": "Other Reports",
}
EXAM_RESULT_ROLES = ("admin", "physician")  # review / sign / release


def _classify_imaging(doc: dict):
    it = (doc.get("imaging_type") or "").lower().replace("-", " ").strip()
    if "ultra" in it:
        sub = "Ultrasound"
    elif "x" in it and "ray" in it or it == "xray":
        sub = "X-Ray"
    elif it:
        sub = (doc.get("imaging_type") or "").strip().title()
    else:
        sub = "Imaging"
    return "DIAGNOSTIC_IMAGING", sub


def _classify_bloodwork(doc: dict):
    return "LABORATORY", "Bloodwork"


@api.get("/internal/exams/requests")
async def exams_requests(q: Optional[str] = None, category: Optional[str] = None,
                         user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Centralized, read-only view of existing patient-originated imaging/bloodwork
    requests (history preserved). Auto-classified; no redundant taxonomy prompts."""
    ps = pscope(user)
    rows = []
    if category in (None, "", "DIAGNOSTIC_IMAGING"):
        imf = {**ps, **_search_filter(q, ["patient_name", "body_part", "ref_number", "imaging_type"])}
        for d in await db.imaging_requests.find(imf, {"_id": 0}).sort("created_at", -1).to_list(500):
            cat, sub = _classify_imaging(d)
            rows.append({"id": d["id"], "source_type": "imaging", "ref_number": d.get("ref_number"),
                         "patient_id": d.get("patient_id"), "patient_name": d.get("patient_name"),
                         "category": cat, "category_label": EXAM_CATEGORIES[cat], "subtype": sub,
                         "detail": d.get("body_part") or d.get("imaging_type"), "reason": d.get("reason"),
                         "status": d.get("internal_status"), "created_at": d.get("created_at")})
    if category in (None, "", "LABORATORY"):
        blf = {**ps, **_search_filter(q, ["patient_name", "reason", "ref_number"])}
        for d in await db.bloodwork_requests.find(blf, {"_id": 0}).sort("created_at", -1).to_list(500):
            cat, sub = _classify_bloodwork(d)
            rows.append({"id": d["id"], "source_type": "bloodwork", "ref_number": d.get("ref_number"),
                         "patient_id": d.get("patient_id"), "patient_name": d.get("patient_name"),
                         "category": cat, "category_label": EXAM_CATEGORIES[cat], "subtype": sub,
                         "detail": d.get("reason"), "reason": d.get("reason"),
                         "status": d.get("internal_status"), "created_at": d.get("created_at")})
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


async def _exam_result_public(r: dict) -> dict:
    r = {k: v for k, v in r.items() if k != "_id"}
    if r.get("attachment_id"):
        att = await db.attachments.find_one({"id": r["attachment_id"]}, {"original_filename": 1, "content_type": 1})
        r["attachment_filename"] = (att or {}).get("original_filename")
    r["type_label"] = r.get("subtype") or r.get("category_label") or "Result"
    return r


class ExamResultCreate(BaseModel):
    patient_id: Optional[str] = None
    category: Optional[str] = None
    subtype: Optional[str] = None
    source_type: Optional[str] = None
    source_request_id: Optional[str] = None
    body_part: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None


@api.post("/internal/exams/results")
async def create_exam_result(body: ExamResultCreate, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Staff/Admin records an incoming result. If linked to an existing request,
    patient + category/subtype are inherited (no redundant questions). With no
    confident patient, it lands in NEEDS_PATIENT_MATCH."""
    now = now_iso()
    await block_synthetic(body.patient_id, what="exam_result", user=user)
    category, subtype = body.category, body.subtype
    source_ref, body_part, reason = None, body.body_part, body.reason
    patient_id = body.patient_id
    if body.source_request_id and body.source_type in ("imaging", "bloodwork"):
        coll = db.imaging_requests if body.source_type == "imaging" else db.bloodwork_requests
        src = await coll.find_one({"id": body.source_request_id})
        if src:
            assert_practice(src, user)
            patient_id = patient_id or src.get("patient_id")
            source_ref = src.get("ref_number")
            if body.source_type == "imaging":
                category, subtype = _classify_imaging(src)
                body_part = body_part or src.get("body_part")
            else:
                category, subtype = _classify_bloodwork(src)
            reason = reason or src.get("reason")
    practice_id = user.get("practice_id")
    patient_name = None
    if patient_id:
        patient = await db.patients.find_one({"id": patient_id})
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        assert_practice(patient, user)
        patient_name = f"{patient['last_name']}, {patient['first_name']}"
        practice_id = patient.get("practice_id")
    status = "RECEIVED" if patient_id else "NEEDS_PATIENT_MATCH"
    doc = {
        "id": str(uuid.uuid4()), "ref_number": await next_ref("EXR"), "practice_id": practice_id,
        "patient_id": patient_id, "patient_name": patient_name,
        "category": category, "category_label": EXAM_CATEGORIES.get(category, category), "subtype": subtype,
        "source_type": body.source_type or "manual", "source_request_id": body.source_request_id,
        "source_ref": source_ref, "body_part": body_part, "reason": reason, "note": body.note,
        "status": status, "attachment_id": None,
        "reviewed_by": None, "reviewed_by_id": None, "reviewed_at": None, "signed_at": None,
        "patient_notified": False, "shared_with_patient": False,
        "access_requested": False, "access_requested_at": None,
        "created_by": user.get("name"), "created_by_id": user.get("id"),
        "created_at": now, "updated_at": now,
    }
    await db.exam_results.insert_one({**doc})
    await audit("create", "exam_result", doc["id"], user, new_status=status,
                meta={"category": category, "subtype": subtype, "source": body.source_type})
    return await _exam_result_public(doc)


@api.post("/internal/exams/results/{rid}/attachment")
async def upload_exam_result_attachment(rid: str, file: UploadFile = File(...),
                                        user: dict = Depends(require_roles(*CLINIC_ROLES))):
    r = await db.exam_results.find_one({"id": rid})
    if not r:
        raise HTTPException(status_code=404, detail="Result not found.")
    assert_practice(r, user)
    att = await attach_mod.store_attachment(db, file, "exam_result", rid, user)
    await db.exam_results.update_one({"id": rid}, {"$set": {"attachment_id": att["id"], "updated_at": now_iso()}})
    return att


@api.get("/internal/exams/results")
async def list_exam_results(status: Optional[str] = None, category: Optional[str] = None,
                            q: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = dict(pscope(user))
    if status:
        query["status"] = status
    if category:
        query["category"] = category
    query.update(_search_filter(q, ["patient_name", "ref_number", "subtype", "category_label", "source_ref"]))
    rows = await db.exam_results.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [await _exam_result_public(r) for r in rows]


class ExamMatchBody(BaseModel):
    patient_id: str


@api.post("/internal/exams/results/{rid}/match")
async def match_exam_result(rid: str, body: ExamMatchBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    r = await db.exam_results.find_one({"id": rid})
    if not r:
        raise HTTPException(status_code=404, detail="Result not found.")
    assert_practice(r, user)
    patient = await db.patients.find_one({"id": body.patient_id})
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    assert_practice(patient, user)
    await db.exam_results.update_one({"id": rid}, {"$set": {
        "patient_id": patient["id"], "patient_name": f"{patient['last_name']}, {patient['first_name']}",
        "practice_id": patient.get("practice_id"), "status": "RECEIVED", "updated_at": now_iso()}})
    await audit("match_patient", "exam_result", rid, user, meta={"patient_id": patient["id"]})
    return await _exam_result_public(await db.exam_results.find_one({"id": rid}))


@api.post("/internal/exams/results/{rid}/send-to-physician")
async def send_exam_result_to_physician(rid: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    r = await db.exam_results.find_one({"id": rid})
    if not r:
        raise HTTPException(status_code=404, detail="Result not found.")
    assert_practice(r, user)
    if not r.get("patient_id"):
        raise HTTPException(status_code=400, detail="Match a patient before sending to the physician.")
    if not r.get("attachment_id"):
        raise HTTPException(status_code=400, detail="Attach the result PDF before sending to the physician.")
    await db.exam_results.update_one({"id": rid}, {"$set": {"status": "READY_FOR_PHYSICIAN", "updated_at": now_iso()}})
    await audit("send_to_physician", "exam_result", rid, user, new_status="READY_FOR_PHYSICIAN")
    return await _exam_result_public(await db.exam_results.find_one({"id": rid}))


@api.get("/internal/exams/results/{rid}/pdf")
async def view_exam_result_pdf(rid: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    r = await db.exam_results.find_one({"id": rid})
    if not r:
        raise HTTPException(status_code=404, detail="Result not found.")
    assert_practice(r, user)
    if not r.get("attachment_id"):
        raise HTTPException(status_code=404, detail="No file attached.")
    return await attach_mod.serve_attachment(db, r["attachment_id"])


class ExamReviewBody(BaseModel):
    notify: bool = True
    release: bool = False


async def _notify_result_reviewed(patient_id: str):
    msg = "Your results have been reviewed by your physician. If you would like to discuss them, you can request an appointment."
    await db.patient_updates.insert_one({
        "id": str(uuid.uuid4()), "patient_id": patient_id, "type": "result_reviewed",
        "title": "Your results have been reviewed", "body": msg, "read": False, "created_at": now_iso()})
    await notify_patient(patient_id, "Your results have been reviewed", msg)
    p = await db.patients.find_one({"id": patient_id}, {"_id": 0})
    if p and p.get("email"):
        lang = email_service.norm_lang(p.get("preferred_language"))
        html = email_service.document_available_html(p.get("first_name") or "", notify_svc.PORTAL_URL, lang=lang)
        await notify_svc._send_email(db, patient_id, p["email"],
                                     email_service.subject("document_available", lang), html, kind="document_available")


@api.post("/internal/exams/results/{rid}/review")
async def review_exam_result(rid: str, body: ExamReviewBody, user: dict = Depends(require_roles(*EXAM_RESULT_ROLES))):
    """Physician SIGN & COMPLETE. Records the signature and sets REVIEWED. Notify
    and PDF release are independent toggles; release defaults OFF."""
    r = await db.exam_results.find_one({"id": rid})
    if not r:
        raise HTTPException(status_code=404, detail="Result not found.")
    assert_practice(r, user)
    if not r.get("patient_id"):
        raise HTTPException(status_code=400, detail="This result is not linked to a patient.")
    now = now_iso()
    updates = {"status": "REVIEWED", "reviewed_by": user.get("name"), "reviewed_by_id": user.get("id"),
               "reviewed_at": now, "signed_at": now, "patient_notified": bool(body.notify), "updated_at": now}
    if body.release and r.get("attachment_id"):
        await attach_mod.mark_shared(db, r["attachment_id"], user,
                                     result_category=r.get("category_label"),
                                     result_subtype=r.get("subtype"), reviewed_by=user.get("name"))
        updates["shared_with_patient"] = True
    await db.exam_results.update_one({"id": rid}, {"$set": updates})
    if body.notify:
        await _notify_result_reviewed(r["patient_id"])
    await audit("sign_and_complete", "exam_result", rid, user, new_status="REVIEWED",
                meta={"notified": bool(body.notify), "released": bool(updates.get("shared_with_patient"))})
    return await _exam_result_public(await db.exam_results.find_one({"id": rid}))


@api.post("/internal/exams/results/{rid}/release")
async def release_exam_result(rid: str, user: dict = Depends(require_roles(*EXAM_RESULT_ROLES))):
    r = await db.exam_results.find_one({"id": rid})
    if not r:
        raise HTTPException(status_code=404, detail="Result not found.")
    assert_practice(r, user)
    if r.get("status") != "REVIEWED":
        raise HTTPException(status_code=400, detail="Only a reviewed result can be released.")
    if not r.get("attachment_id"):
        raise HTTPException(status_code=400, detail="No file to release.")
    await attach_mod.mark_shared(db, r["attachment_id"], user, result_category=r.get("category_label"),
                                 result_subtype=r.get("subtype"), reviewed_by=r.get("reviewed_by") or user.get("name"))
    await db.exam_results.update_one({"id": rid}, {"$set": {
        "shared_with_patient": True, "access_requested": False, "updated_at": now_iso()}})
    await _notify_result_reviewed(r["patient_id"])
    await audit("release", "exam_result", rid, user, meta={"from_access_request": bool(r.get("access_requested"))})
    return await _exam_result_public(await db.exam_results.find_one({"id": rid}))


@api.post("/internal/exams/results/{rid}/keep-internal")
async def keep_exam_result_internal(rid: str, user: dict = Depends(require_roles(*EXAM_RESULT_ROLES))):
    r = await db.exam_results.find_one({"id": rid})
    if not r:
        raise HTTPException(status_code=404, detail="Result not found.")
    assert_practice(r, user)
    await db.exam_results.update_one({"id": rid}, {"$set": {"access_requested": False, "updated_at": now_iso()}})
    await audit("keep_internal", "exam_result", rid, user)
    return await _exam_result_public(await db.exam_results.find_one({"id": rid}))


@api.post("/portal/results/{rid}/request-access")
async def patient_request_result_access(rid: str, ctx: PortalCtx = Depends(portal_access(delegates_mod.DOCUMENTS))):
    """Patient requests the physician to RELEASE an existing reviewed PDF. This NEVER
    creates a new exam/imaging/bloodwork request."""
    pid = ctx.patient["id"]
    r = await db.exam_results.find_one({"id": rid, "patient_id": pid})
    if not r:
        raise HTTPException(status_code=404, detail="Result not found.")
    if r.get("status") != "REVIEWED" or r.get("shared_with_patient"):
        raise HTTPException(status_code=400, detail="This result is not available to request.")
    await db.exam_results.update_one({"id": rid}, {"$set": {
        "access_requested": True, "access_requested_at": now_iso(), "updated_at": now_iso()}})
    await db.internal_messages.insert_one({
        "id": str(uuid.uuid4()), "ref_number": await next_ref("TSK"), "practice_id": r.get("practice_id"),
        "recipient_role": "physician", "status": "open", "type": "result_access_request",
        "subject": f"Patient requests access to {r.get('subtype') or r.get('category_label') or 'a result'}",
        "body": f"{r.get('patient_name') or 'A patient'} has requested access to their reviewed result ({r.get('ref_number')}).",
        "patient_id": pid, "source_type": "exam_result", "source_id": rid,
        "created_at": now_iso(), "updated_at": now_iso()})
    await audit("request_access", "exam_result", rid, ctx.audit_actor(), meta=ctx.audit_meta({}))
    return {"ok": True, "access_requested": True}




# ----------------------------- Book appointment from a request -----------------------------
_BOOK_SOURCES = {
    "prescription": (lambda: db.prescription_requests, "internal_status"),
    "imaging": (lambda: db.imaging_requests, "internal_status"),
    "bloodwork": (lambda: db.bloodwork_requests, "internal_status"),
    "message": (lambda: db.patient_messages, "status"),
}


async def _slot_taken(date_str: str, time24: str, exclude_id: Optional[str] = None, practice_id=None) -> bool:
    return not await slots_mod.is_free(db, practice_id, date_str, time24, exclude_appointment_id=exclude_id)


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
    _validate_bookable(avail, body.date, time24)
    appt_id = str(uuid.uuid4())
    practice_id = source.get("practice_id") or user.get("practice_id")
    ident = await guard_mod.identity(db, patient_id=source["patient_id"])
    override = await _guard_new_booking(practice_id, ident, body.date, appt_id, user, "request_booking",
                                        body.override_same_day, body.override_reason)
    try:
        await _reserve_or_409(user.get("practice_id"), body.date, time24, appt_id, slots_mod.CONFIRMED, user["name"])
    except HTTPException:
        await guard_mod.release_day_lock(db, appt_id)
        raise

    ref = await next_ref("APT")
    display = body.display or f"{fmt_date_display(body.date)} · {body.label or body.time}"
    appt = {
        "id": appt_id, "ref_number": ref, "patient_id": source["patient_id"],
        "practice_id": practice_id,
        "patient_name": source.get("patient_name"),
        "same_day_override": override,
        "reason": body.reason or f"Follow-up for {body.source_type} request {source.get('ref_number')}",
        "patient_note": None, "preferred_options": [],
        "preferred_date": body.date, "preferred_time": body.label or body.time,
        "status": "confirmed", "slot_state": slots_mod.CONFIRMED, "staff_note": None,
        "offered_slots": [], "selected_slot": None,
        **_confirmed_fields(body.date, time24, body.label, display),
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
                meta={"source_type": body.source_type, "source_id": body.source_id, "same_day_override": bool(override)})
    await guard_mod.refresh_week_flags(db, practice_id, ident, [body.date], user)
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
    query = dict(pscope(user))
    if user["role"] == "physician":
        query["status"] = "waiting_physician"
    elif status:
        query["status"] = status
    query.update(_search_filter(q, ["patient_name", "subject", "ref_number", "body"]))
    return await _attach_pins(await db.patient_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(500))


@api.patch("/internal/messages/{item_id}")
async def msg_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.patient_messages.find_one({"id": item_id})
    assert_practice(doc, user)
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
    # Appointments: include legacy/portal records with no practice_id so a patient can never
    # hold a request the clinic cannot see.
    default_pr = await resolve_practice()
    pids = [user.get("practice_id")]
    if default_pr and user.get("practice_id") == default_pr.get("id"):
        pids.append(None)  # unstamped legacy records belong to the default practice only
    query = {"practice_id": {"$in": pids}}
    if status:
        query["status"] = status
    query.update(_search_filter(q, ["patient_name", "reason", "ref_number"]))
    items = await db.appointment_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Batch-resolve PIN / DOB / phone so the request popup can show them (no per-row lookups).
    pids = {a.get("patient_id") for a in items if a.get("patient_id")}
    pmap = {}
    if pids:
        async for p in db.patients.find({"id": {"$in": list(pids)}},
                                        {"_id": 0, "id": 1, "visita_patient_id": 1, "date_of_birth": 1, "phone": 1}):
            pmap[p["id"]] = p
    for a in items:
        p = pmap.get(a.get("patient_id")) or {}
        a["patient_pin"] = p.get("visita_patient_id")
        a["patient_dob"] = p.get("date_of_birth")
        a["patient_phone"] = p.get("phone")
        a["booked_at"] = a.get("created_at")
        a["booked_by_label"] = ("Caregiver (on behalf)" if a.get("submitted_by_delegate")
                                else "Patient (portal)" if (a.get("booked_from") or {}).get("source_type", "").startswith("portal")
                                else a.get("booked_by") or a.get("approved_by") or "Clinic")
        ds, t = _appt_when(a)
        a["slot_date"], a["slot_time"] = a.get("slot_date") or ds, a.get("slot_time") or t
    return items


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


@api.get("/internal/appointments/reviews")
async def appointment_reviews(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Staff review surface: OPEN weekly multiple-appointment flags + existing same-day
    active duplicates (read-only; nothing is auto-cancelled or moved)."""
    pid = user.get("practice_id")
    return {"week_flags": await guard_mod.open_flags(db, pid),
            "same_day_duplicates": await guard_mod.same_day_duplicates(db, pid)}


@api.get("/internal/appointments/followups")
async def appt_followups(user: dict = Depends(require_roles("staff", "admin"))):
    """Follow-up lists: patients flagged no-show, and patients the clinic asked
    to reschedule (offered alternate times, or actively rescheduled by staff)."""
    ns = await db.appointment_requests.find({**pscope(user), "status": "no_show"}, {"_id": 0}).sort("completed_at", -1).to_list(500)
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

    rs = await db.appointment_requests.find({**pscope(user), "$or": [
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
    assert_practice(a, user)
    if a.get("status") != "no_show":
        raise HTTPException(status_code=400, detail="This appointment is not marked as a no-show.")
    if not a.get("patient_id"):
        raise HTTPException(status_code=400, detail="Link a portal patient to this appointment before billing the no-show fee.")
    await block_synthetic(a.get("patient_id"), a.get("directory_id"), what="no_show_invoice", user=user)
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


# Fail-safe: approval mode unless PORTAL_AUTO_CONFIRM=true is explicitly configured.
PORTAL_AUTO_CONFIRM = os.environ.get("PORTAL_AUTO_CONFIRM", "false").strip().lower() in ("1", "true", "yes")

ADMIN_CANCEL_REASONS = {"Physician unavailable", "Clinic schedule change", "Unexpected closure",
                        "Patient requested cancellation", "Other"}


@api.patch("/internal/appointments/{item_id}")
async def appt_update(item_id: str, body: UpdateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    doc = await db.appointment_requests.find_one({"id": item_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    old = doc.get("status")
    pid_scope = doc.get("practice_id") or user.get("practice_id")
    updates = {"updated_at": now_iso()}
    history_note = None
    notify = None  # confirmed | time_changed | cancelled | declined
    cur_ds, cur_t = _appt_when(doc)
    ident = await guard_mod.identity(db, patient_id=doc.get("patient_id"), directory_id=doc.get("directory_id")) \
        if (doc.get("patient_id") or doc.get("directory_id")) else None

    if body.action == "approve":
        if old != "requested":
            raise HTTPException(status_code=400, detail="Only a requested appointment can be approved.")
        ds = body.confirmed_date or cur_ds
        t24 = avail_mod._norm_time(body.confirmed_time or cur_t or "")
        if not ds or not t24:
            raise HTTPException(status_code=400, detail="This request has no held time. Use Change Time to pick one.")
        avail = await get_availability_doc()
        _validate_bookable(avail, ds, t24, allow_past=True)
        if ident:
            await _guard_move(pid_scope, ident, item_id, ds, user, "staff")
        try:
            # Same slot as the hold -> state flips HELD->CONFIRMED; a different slot is reserved first.
            await slots_mod.move(db, pid_scope, item_id, ds, t24, slots_mod.CONFIRMED, user["name"],
                                 duration=int(avail.get("appointment_duration") or 30))
        except slots_mod.SlotTaken:
            if ident and cur_ds:
                await guard_mod.move_day_lock(db, pid_scope, ident["key"], item_id, cur_ds)
            raise HTTPException(status_code=409, detail=slots_mod.SLOT_TAKEN_MSG)
        updates.update({"status": "confirmed", "slot_state": slots_mod.CONFIRMED,
                        **_confirmed_fields(ds, t24, None, body.confirmed_display),
                        "approved_by": user["name"], "approved_at": now_iso(), "completed_at": now_iso()})
        history_note = f"Approved for {ds} {t24}"
        notify = "confirmed"
    elif body.action in ("change_time", "reschedule"):
        if old not in ("requested", "confirmed", "rescheduled"):
            raise HTTPException(status_code=400, detail="Only a requested or confirmed appointment can be moved.")
        ds, t24 = body.confirmed_date, avail_mod._norm_time(body.confirmed_time or "")
        if not ds or not t24:
            raise HTTPException(status_code=400, detail="Select a new time.")
        avail = await get_availability_doc()
        _validate_bookable(avail, ds, t24)
        if ident:
            await _guard_move(pid_scope, ident, item_id, ds, user, "staff")
        try:
            await slots_mod.move(db, pid_scope, item_id, ds, t24, slots_mod.CONFIRMED, user["name"],
                                 duration=int(avail.get("appointment_duration") or 30))
        except slots_mod.SlotTaken:
            if ident and cur_ds:
                await guard_mod.move_day_lock(db, pid_scope, ident["key"], item_id, cur_ds)
            raise HTTPException(status_code=409, detail=slots_mod.SLOT_TAKEN_MSG)
        updates.update({"status": "confirmed", "slot_state": slots_mod.CONFIRMED,
                        **_confirmed_fields(ds, t24, None, body.confirmed_display),
                        "rescheduled_by": user["name"], "rescheduled_at": now_iso(),
                        "original_requested_slot": doc.get("original_requested_slot") or
                        ({"date": cur_ds, "time": cur_t} if cur_ds else None)})
        if old == "requested":
            updates.update({"approved_by": user["name"], "approved_at": now_iso(), "completed_at": now_iso()})
        history_note = f"Time changed from {cur_ds} {cur_t} to {ds} {t24}"
        notify = "time_changed"
    elif body.action == "cancel":
        if old not in ("requested", "confirmed", "rescheduled"):
            raise HTTPException(status_code=400, detail="This appointment cannot be cancelled.")
        reason = (body.cancel_reason or body.staff_note or "").strip()
        if not reason:
            raise HTTPException(status_code=400, detail="A cancellation reason is required.")
        free_slot = True if body.free_slot is None else bool(body.free_slot)
        await guard_mod.release_day_lock(db, item_id)
        if free_slot:
            await slots_mod.release(db, item_id)
        else:
            lk = await slots_mod.lock_for(db, item_id)
            if lk:
                await slots_mod.set_state(db, item_id, slots_mod.BLOCKED)
            elif cur_ds and cur_t:
                try:
                    await slots_mod.reserve(db, pid_scope, cur_ds, cur_t, item_id, slots_mod.BLOCKED, user["name"])
                except slots_mod.SlotTaken:
                    pass
        updates.update({"status": "cancelled", "staff_note": body.staff_note or reason,
                        "slot_state": None if free_slot else slots_mod.BLOCKED,
                        "cancelled_by": user["name"], "cancelled_at": now_iso(), "completed_at": now_iso(),
                        "cancellation": {"reason": reason, "free_slot": free_slot, "by": user["name"],
                                         "at": now_iso(), "previous_status": old}})
        history_note = f"Cancelled — {reason} — slot {'freed' if free_slot else 'kept blocked'}"
        notify = "cancelled"
    elif body.action == "decline":
        if old != "requested":
            raise HTTPException(status_code=400, detail="Only a requested appointment can be declined.")
        reason = (body.cancel_reason or body.staff_note or "").strip()
        await slots_mod.release(db, item_id)
        await guard_mod.release_day_lock(db, item_id)
        updates.update({"status": "declined", "staff_note": body.staff_note or reason or None, "slot_state": None,
                        "declined_by": user["name"], "declined_at": now_iso(), "completed_at": now_iso(),
                        "cancellation": {"reason": reason or "Declined by clinic", "free_slot": True,
                                         "by": user["name"], "at": now_iso(), "previous_status": old}})
        history_note = f"Declined — slot released{(' — ' + reason) if reason else ''}"
        notify = "declined"
    elif body.action == "note":
        if not (body.internal_note or "").strip():
            raise HTTPException(status_code=400, detail="Note text is required.")
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
        raise HTTPException(status_code=400, detail="Offering alternative times is no longer supported. Use Change Time.")
    elif body.action == "more_info":
        updates.update({"status": "more_info_required", "staff_note": body.staff_note})
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

    mongo_update = {"$set": updates, "$push": {}}
    if body.action != "note":
        hist = {"status": updates.get("status", old), "at": now_iso(), "by": user["name"]}
        if history_note:
            hist["note"] = history_note
        mongo_update["$push"]["history"] = hist
    if body.internal_note:
        mongo_update["$push"]["internal_notes"] = {"by": user["name"], "note": body.internal_note.strip(), "at": now_iso()}
    if not mongo_update["$push"]:
        mongo_update.pop("$push")
    await db.appointment_requests.update_one({"id": item_id}, mongo_update)
    await audit("update", "appointment", item_id, user, old_status=old, new_status=updates.get("status", old),
                meta={"action": body.action, "note": history_note} if body.action else None)

    fresh = await db.appointment_requests.find_one({"id": item_id}, {"_id": 0})
    if ident and body.action in ("approve", "change_time", "reschedule", "cancel", "decline", "complete", "no_show", "undo_status"):
        new_ds = _appt_when(fresh)[0]
        if body.action == "undo_status" and new_ds:
            try:
                await guard_mod.acquire_day_lock(db, pid_scope, ident["key"], new_ds, item_id)
            except guard_mod.SameDayExists:
                pass
        elif body.action in ("complete", "no_show"):
            await guard_mod.release_day_lock(db, item_id)
        await guard_mod.refresh_week_flags(db, pid_scope, ident, [cur_ds, new_ds], user)
    if not fresh.get("patient_id"):
        return fresh
    if notify == "confirmed":
        await notify_svc.appointment_confirmed(db, fresh)
    elif notify == "time_changed":
        await notify_svc.appointment_rescheduled(db, fresh)
    elif notify == "cancelled":
        await notify_svc.appointment_cancelled(db, fresh, reason=(fresh.get("cancellation") or {}).get("reason"))
    elif notify == "declined":
        await notify_svc.appointment_declined(db, fresh, reason=body.staff_note or None)
    elif body.action == "more_info":
        await notify_patient(doc["patient_id"], "Appointment update",
                             "We need a little more information about your appointment request. Please log in to your Patient Portal.")
    if body.action in ("complete", "no_show"):
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
    query = {**pscope(user), "recipient_role": "physician"} if user["role"] == "physician" else {**pscope(user), "recipient_role": "staff"}
    return await db.internal_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.post("/internal/tasks")
async def create_task(body: TaskBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    ref = await next_ref("TSK")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": body.patient_id, "patient_name": body.patient_name,
        "practice_id": user.get("practice_id"),
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
    return await db.referrals.find({**pscope(user), "ready_to_fax": True, "faxed": False}, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.get("/internal/referrals/history")
async def referrals_history(q: Optional[str] = None, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    query = {**pscope(user), "faxed": True}
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
    await block_synthetic(patient_id or None, what="referral", user=user)
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


class ShareAttachmentBody(BaseModel):
    complete: bool = True
    result_category: Optional[str] = None
    result_subtype: Optional[str] = None
    reviewed_by: Optional[str] = None
    notify: bool = True


@api.post("/internal/attachments/{att_id}/share")
async def share_attachment(att_id: str, body: ShareAttachmentBody,
                           user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Explicitly release ONE internal attachment to the patient and (optionally)
    complete the source request. Records the physician-reviewed result
    classification + reviewing physician, creates a patient update event, and
    (if notify) an in-portal notification and a GENERIC (no-PHI, no normal/abnormal)
    email. Never emails the file."""
    att, parent = await attach_mod.mark_shared(
        db, att_id, user,
        result_category=body.result_category,
        result_subtype=body.result_subtype,
        reviewed_by=body.reviewed_by)
    patient_id = att["patient_id"]
    entity_type = att["entity_type"]
    type_label = att.get("result_subtype") or att.get("result_category") or "result"
    update_id = str(uuid.uuid4())
    await db.patient_updates.insert_one({
        "id": update_id, "patient_id": patient_id, "type": "document_shared",
        "source_type": entity_type, "source_id": att["entity_id"], "attachment_id": att_id,
        "title": "Your results have been reviewed",
        "body": "Your results have been reviewed by your physician. If you would like to discuss the results, you can request an appointment.",
        "read": False, "created_at": now_iso(),
    })
    if body.notify:
        await notify_patient(patient_id, "Your results have been reviewed",
                             "Your results have been reviewed by your physician. If you would like to discuss the results, you can request an appointment.")
        p = await db.patients.find_one({"id": patient_id}, {"_id": 0})
        if p and p.get("email"):
            lang = email_service.norm_lang(p.get("preferred_language"))
            html = email_service.document_available_html(p.get("first_name") or "", notify_svc.PORTAL_URL, lang=lang)
            await notify_svc._send_email(db, patient_id, p["email"],
                                         email_service.subject("document_available", lang), html, kind="document_available")
    if body.complete and entity_type == "imaging":
        await db.imaging_requests.update_one({"id": att["entity_id"]}, {"$set": {
            "internal_status": "completed", "completed_at": now_iso(), "updated_at": now_iso()}})
        await audit("complete", "imaging", att["entity_id"], user, new_status="completed",
                    meta={"via": "share_with_patient", "attachment_id": att_id})
    return {"ok": True, "shared": True, "update_id": update_id, "type_label": type_label}


# ----------------------------- Patient documents & updates (portal) -----------------------------
@api.get("/portal/my-delegations")
async def my_delegations(user: dict = Depends(get_current_user)):
    """'People I help manage' — patients the authenticated user has active access to."""
    grants = await delegates_mod.grants_for_delegate(db, user["id"])
    out = []
    for g in grants:
        p = await db.patients.find_one({"id": g["patient_id"]},
                                       {"_id": 0, "first_name": 1, "last_name": 1})
        if not p:
            continue
        out.append({
            "patient_id": g["patient_id"],
            "patient_name": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            "relationship": g.get("relationship"),
            "permissions": g.get("permissions", []),
            "granted_at": g.get("granted_at"),
        })
    return {"has_own_patient": bool(user.get("patient_id")), "managing": out}


@api.get("/portal/managed/{patient_id}/summary")
async def managed_summary(patient_id: str, ctx: PortalCtx = Depends(portal_access())):
    """Permission-filtered read of a managed patient's portal. Only sections the delegate
    is permitted to see are populated. No internal notes/attachments ever leak."""
    if not ctx.is_delegate or ctx.patient["id"] != patient_id:
        raise HTTPException(status_code=404, detail="Not found")
    p = ctx.patient
    perms = set(ctx.grant.get("permissions", []))
    data = {
        "patient_id": p["id"],
        "patient_name": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
        "relationship": ctx.grant.get("relationship"),
        "permissions": sorted(perms),
        "appointments": None, "documents": None, "requests": None,
    }
    if delegates_mod.APPOINTMENTS in perms:
        appts = await db.appointment_requests.find(
            {"patient_id": p["id"], "status": {"$in": ["requested", "alternatives_offered",
             "more_info_required", "confirmed"]}}, {"_id": 0}).sort("created_at", -1).to_list(50)
        data["appointments"] = [{
            "ref_number": a.get("ref_number"), "reason": a.get("reason"),
            "status": APPT_PATIENT_STATUS.get(a.get("status"), a.get("status")),
            "confirmed_display": a.get("confirmed_display"),
            "preferred_date": a.get("preferred_date"), "preferred_time": a.get("preferred_time"),
            "created_at": a.get("created_at"),
        } for a in appts]
    if delegates_mod.DOCUMENTS in perms:
        data["documents"] = await attach_mod.list_shared_for_patient(db, p["id"])
    if delegates_mod.REQUEST_STATUS in perms:
        reqs = []
        for coll, label, smap in [
            ("prescription_requests", "Prescription", RX_PATIENT_STATUS),
            ("imaging_requests", "Imaging", IMG_PATIENT_STATUS),
            ("bloodwork_requests", "Bloodwork", BLD_PATIENT_STATUS),
        ]:
            for r in await db[coll].find({"patient_id": p["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50):
                reqs.append({"type": label, "ref_number": r.get("ref_number"),
                             "status": smap.get(r.get("internal_status"), r.get("internal_status")),
                             "created_at": r.get("created_at")})
        for rf in await db.referrals.find({"patient_id": p["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50):
            reqs.append({"type": "Referral", "ref_number": rf.get("ref_number"),
                         "status": "Sent" if rf.get("faxed") else "In progress",
                         "created_at": rf.get("created_at")})
        data["requests"] = sorted(reqs, key=lambda x: x.get("created_at") or "", reverse=True)
    return data


@api.get("/portal/documents")
async def portal_documents(ctx: PortalCtx = Depends(portal_access(delegates_mod.DOCUMENTS))):
    return await attach_mod.list_shared_for_patient(db, ctx.patient["id"])



@api.get("/portal/documents/{att_id}/download")
async def portal_document_download(att_id: str, ctx: PortalCtx = Depends(portal_access(delegates_mod.DOCUMENTS))):
    return await attach_mod.serve_shared_for_patient(db, att_id, ctx.patient["id"])


@api.post("/portal/updates/{update_id}/read")
async def portal_update_read(update_id: str, p: dict = Depends(require_verified_patient)):
    r = await db.patient_updates.update_one(
        {"id": update_id, "patient_id": p["id"]},
        {"$set": {"read": True, "read_at": now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Update not found.")
    return {"ok": True}


RESULT_DOC_PURPOSES = {
    "copy_result": "Copy of a result",
    "copy_imaging": "Copy of an imaging report",
    "copy_other": "Copy of another available document",
}


class DocumentRequestBody(BaseModel):
    purpose: str


@api.post("/portal/document-requests")
async def create_document_request(body: DocumentRequestBody, p: dict = Depends(require_verified_patient)):
    """Structured 'Results / Document Request'. No free text — the patient picks a
    fixed purpose. Flows into the existing staff message queue."""
    label = RESULT_DOC_PURPOSES.get(body.purpose)
    if not label:
        raise HTTPException(status_code=400, detail="Invalid request purpose.")
    ref = await next_ref("MSG")
    text = f"Results / Document Request: {label}"
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref, "patient_id": p["id"],
        "patient_name": f"{p['last_name']}, {p['first_name']}",
        "category": "Document Request", "subject": f"Results / Document Request — {label}", "body": text,
        "sender": "patient", "status": "new", "assigned_to": None,
        "thread": [{"from": "patient", "body": text, "at": now_iso()}],
        "internal_notes": [], "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None,
    }
    await db.patient_messages.insert_one({**doc})
    await audit("create", "message", doc["id"], {"id": p["id"], "name": p["first_name"], "role": "patient"},
                new_status="new", meta={"document_request": body.purpose})
    return {"ok": True, "ref_number": ref}


# ----------------------------- Patient verification -----------------------------
@api.get("/internal/verifications")
async def verifications(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    pending = await db.patients.find({**pscope(user), "verification_status": "pending", "active_status": True}).sort("created_at", -1).to_list(500)
    out = []
    for p in pending:
        strength, cands = (None, [])
        if not p.get("matched_directory_id"):
            strength, cands = await directory_mod.live_candidates(db, p)
        out.append({
            "id": p["id"], "first_name": p["first_name"], "last_name": p["last_name"],
            "middle_name": p.get("middle_name"), "second_last_name": p.get("second_last_name"), "full_name": names_mod.full_display_name(p),
            "date_of_birth": p["date_of_birth"], "phone": p.get("phone"), "email": p.get("email"),
            "patient_type": p["patient_type"], "province": p.get("province"), "country": p.get("country"),
            "extra_info": p.get("extra_info"), "created_at": p["created_at"],
            "health_card_masked": mask_hcn(p.get("health_card_number")),
            "review_queue": p.get("review_queue"),
            "directory_match": p.get("directory_match"),
            "matched_directory_id": p.get("matched_directory_id"),
            "identity_state": "LINK_PENDING" if p.get("matched_directory_id") else ("IDENTITY_REVIEW_REQUIRED" if cands else "NEW_PATIENT_CANDIDATE"),
            "live_candidates": cands, "live_strength": strength,
            "relationship": await _rel_summary_for_patient(p, user),
        })
    return out


@api.get("/internal/verifications/history")
async def verifications_history(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Recently verified/rejected patient registrations — read-only history."""
    docs = await db.patients.find(
        {**pscope(user), "verification_status": {"$in": ["verified", "rejected"]}, "verified_at": {"$exists": True, "$ne": None}}
    ).sort("verified_at", -1).limit(100).to_list(100)
    out = []
    for p in docs:
        linked = bool(p.get("matched_directory_id"))
        canon = await db.patient_directory.find_one({"id": p["matched_directory_id"]}, {"_id": 0, "first_name": 1, "last_name": 1, "visita_patient_id": 1}) if linked else None
        if linked:
            state = "LINKED_EXISTING"
        elif p.get("verification_status") == "verified" and ((p.get("directory_match") or {}).get("candidates")):
            state = "IDENTITY_REVIEW"
        elif p.get("verification_status") == "verified":
            state = p.get("identity_outcome") or "NEW_PATIENT"
        else:
            state = None
        out.append({
            "id": p["id"], "first_name": p["first_name"], "last_name": p["last_name"],
            "middle_name": p.get("middle_name"), "second_last_name": p.get("second_last_name"), "full_name": names_mod.full_display_name(p),
            "canonical_full_name": names_mod.full_display_name(canon) if canon else None,
            "patient_type": p["patient_type"],
            "verification_status": p.get("verification_status"),
            "visita_patient_id": (canon or {}).get("visita_patient_id") or p.get("visita_patient_id"),
            "linked": linked,
            "identity_state": state,
            "verified_by": p.get("verified_by"),
            "verified_at": p.get("verified_at"),
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
        "is_synthetic": bool(d.get("is_synthetic")),
        "full_name": names_mod.full_display_name(d),
        "visita_patient_id": d.get("visita_patient_id"),
        "date_of_birth": d.get("date_of_birth"), "age": _age_from_dob(d.get("date_of_birth")),
        "home_phone": d.get("home_phone"), "cell_phone": d.get("cell_phone"),
        "email": d.get("email"), "sex": d.get("sex") or SEX_FROM_CODE.get((d.get("sex_code") or "").strip().upper()),
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
        "middle_name": p.get("middle_name"), "second_last_name": p.get("second_last_name"),
        "full_name": names_mod.full_display_name(p),
        "visita_patient_id": p.get("visita_patient_id"),  # None -> UI shows "Not assigned"
        "date_of_birth": p.get("date_of_birth"), "age": _age_from_dob(p.get("date_of_birth")),
        "home_phone": p.get("home_phone"), "cell_phone": p.get("phone"),
        "email": p.get("email"), "sex": p.get("sex"),
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
        {"middle_name": {"$regex": re.escape(qn), "$options": "i"}},
        {"second_last_name": {"$regex": re.escape(qn), "$options": "i"}},
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


async def _search_patients_merged(qn: str, limit: int = 40, include_pin: bool = True, practice_id: Optional[str] = None):
    """Unified internal patient search: VERIFIED portal patient accounts PLUS
    existing patient_directory records. Verified portal patients are surfaced
    first (so they're never crowded out by many directory matches). Deduped so a
    portal account linked to a directory record appears only once.
    practice_id (optional) restricts portal accounts to that practice."""
    results, seen_dir, seen_pid = [], set(), set()

    # 1) Verified portal patients first.
    pq = {"verification_status": "verified", "active_status": True, "$or": _portal_search_ors(qn, include_pin)}
    if practice_id:
        pq["practice_id"] = practice_id
    portal = await db.patients.find(pq).limit(limit).to_list(limit)
    for p in portal:
        mdir = p.get("matched_directory_id")
        if mdir:
            if mdir in seen_dir:
                continue
            seen_dir.add(mdir)
            # CONFIRMED link ⇒ ONE clinical row using the CANONICAL directory identity
            # (full name, PIN, DOB, directory id). Portal account only decorates it.
            d = await db.patient_directory.find_one({"id": mdir})
            if d:
                snap = _directory_snapshot(d)
                snap["patient_id"] = p["id"]
                snap["portal_linked"] = True
                snap["portal_patient_name"] = names_mod.full_display_name(p)
                snap["health_card_update_pending"] = bool(p.get("pending_health_card"))
                snap["email"] = snap.get("email") or p.get("email")
                snap["cell_phone"] = snap.get("cell_phone") or p.get("phone")
            else:
                snap = _portal_patient_snapshot(p)
            results.append(snap)
            seen_pid.add(p["id"])
            continue
        if p["id"] in seen_pid:
            continue
        snap = _portal_patient_snapshot(p)
        # Unlinked portal record with credible existing-patient evidence ⇒ IDENTITY REVIEW, not an ordinary clinical row.
        if (p.get("directory_match") or {}).get("candidates"):
            snap["identity_review"] = True
            snap["identity_review_strength"] = (p.get("directory_match") or {}).get("strength")
            snap["patient_status"] = "PORTAL_IDENTITY_REVIEW"
        results.append(snap); seen_pid.add(p["id"])

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


async def _attach_portal_access(results: list) -> list:
    """Annotate each merged search result with a practice-safe `portal_access`
    flag derived from EXISTING patient/user linkage — informational only:
      "active" = an active, claimed patient portal login exists
      "none"   = directory-only, or an unclaimed/minimal portal record with no login
    No blocking, no side effects."""
    pids = {r.get("patient_id") for r in results if r.get("patient_id")}
    claimed, unclaimed = set(), set()
    if pids:
        async for p in db.patients.find(
                {"id": {"$in": list(pids)}}, {"_id": 0, "id": 1, "is_unclaimed": 1}):
            if p.get("is_unclaimed"):
                unclaimed.add(p["id"])
        async for u in db.users.find(
                {"patient_id": {"$in": list(pids)}, "role": "patient", "active": True},
                {"_id": 0, "patient_id": 1}):
            if u.get("patient_id"):
                claimed.add(u["patient_id"])
    for r in results:
        pid = r.get("patient_id")
        r["portal_access"] = "active" if (pid and pid in claimed and pid not in unclaimed) else "none"
    return results


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
    return await _attach_portal_access(await _search_patients_merged(qn, limit=40, include_pin=include_pin))


@api.get("/internal/patient-lookup/by-ref")
async def internal_patient_lookup_by_ref(patient_ref: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Resolve one patient snapshot from a canonical patient_ref (used to reselect after Exit Encounter)."""
    ident = await visits_mod.resolve_identity(db, patient_ref, None, None)
    if not ident:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return (await _attach_portal_access([_visit_snapshot(ident)]))[0]


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
    return await _attach_portal_access(results)


SEX_FROM_CODE = {"M": "Male", "F": "Female", "X": "Other", "O": "Other", "U": "Unknown", "1": "Male", "2": "Female", "9": "Unknown"}  # legacy numeric codes (ISO 5218) kept as-is
SEX_TO_CODE = {"Male": "M", "Female": "F", "Other": "X", "Unknown": "U"}
# Verified registration → canonical refresh. CURRENT fields follow the patient (overwrite when different);
# FILL fields only populate an empty canonical value; IDENTITY fields are never overwritten (reviewable conflict).
_MERGE_CURRENT = (("health_card_version", "health_card_version_code"), ("health_card_issue_date", "health_card_issue_date"),
                  ("health_card_expiry_date", "health_card_expiry_date"), ("email", "email"), ("phone", "cell_phone"), ("home_phone", "home_phone"))
_MERGE_ADDRESS = (("address", "address"), ("unit", "unit"), ("city", "city"), ("province", "province"), ("postal_code", "postal_code"), ("country", "country"))
_MERGE_IDENTITY = (("first_name", "first_name"), ("last_name", "last_name"), ("date_of_birth", "date_of_birth"), ("health_card_number", "health_card_number"))


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


async def _refresh_canonical_from_registration(p: dict, d: dict, user: dict, source: str) -> dict:
    """MISSING ≠ CONFLICT. Fill/refresh the canonical directory record from a human-verified portal
    registration without ever erasing canonical data or silently changing strong identity fields."""
    changes, conflicts = {}, {}
    if d.get("practice_id") and p.get("practice_id") and d["practice_id"] != p["practice_id"]:
        await audit("canonical_refresh_skipped", "patient_directory", d["id"], user,
                    meta={"reason": "cross_practice", "patient_id": p["id"], "link_source": source})
        return {"changes": {}, "conflicts": {"practice_id": {"canonical": d["practice_id"], "submitted": p["practice_id"]}}}
    for pk, dk in _MERGE_CURRENT:
        pv = p.get(pk)
        if _blank(pv):
            continue
        if isinstance(pv, str):
            pv = pv.strip()
        if (d.get(dk) or None) != pv:
            changes[dk] = {"from": d.get(dk), "to": pv}
    # Address is updated as a block only when the registration supplies a street address.
    if not _blank(p.get("address")):
        for pk, dk in _MERGE_ADDRESS:
            pv = p.get(pk)
            if _blank(pv):
                continue  # never erase canonical data with a blank submitted field
            pv = pv.strip() if isinstance(pv, str) else pv
            if (d.get(dk) or None) != pv:
                changes[dk] = {"from": d.get(dk), "to": pv}
    # Sex: fill when canonical empty; conflict when both present and different.
    psex = (p.get("sex") or "").strip() or None
    dsex = d.get("sex") or SEX_FROM_CODE.get((d.get("sex_code") or "").strip().upper())
    if psex and not dsex:
        changes["sex"] = {"from": None, "to": psex}
        changes["sex_code"] = {"from": d.get("sex_code"), "to": SEX_TO_CODE.get(psex, d.get("sex_code"))}
    elif psex and dsex and psex.lower() != dsex.lower():
        conflicts["sex"] = {"canonical": dsex, "submitted": psex}
    for pk, dk in _MERGE_IDENTITY:
        pv, dv = p.get(pk), d.get(dk)
        if _blank(pv) or _blank(dv):
            continue
        norm = (lambda x: "".join(ch for ch in str(x).lower() if ch.isalnum()))
        if norm(pv) != norm(dv):
            conflicts[dk] = {"canonical": dv, "submitted": pv}
    if changes:
        await db.patient_directory.update_one({"id": d["id"]}, {"$set": {**{k: v["to"] for k, v in changes.items()}, "updated_at": now_iso()}})
    if changes or conflicts:
        await audit("canonical_refreshed_from_registration", "patient_directory", d["id"], user,
                    meta={"source": "VERIFIED_PORTAL_REGISTRATION", "link_source": source, "patient_id": p["id"],
                          "changes": changes, "conflicts": conflicts})
    return {"changes": changes, "conflicts": conflicts}


async def _link_portal_to_directory(p: dict, d: dict, user: dict, source: str) -> Optional[str]:
    """Hardened two-way link portal account ⇄ canonical directory record.
    Guards: PORTAL_ALREADY_LINKED, DIRECTORY_ALREADY_LINKED (incl. any other active
    portal account pointing at this directory). Conditional writes + rollback so a
    half-link is never left behind. Preserves the canonical PIN; never merges
    clinical history or overwrites demographics. Returns the canonical PIN."""
    pid, did = p["id"], d["id"]
    if p.get("matched_directory_id") and p["matched_directory_id"] != did:
        raise HTTPException(status_code=409, detail={
            "code": "PORTAL_ALREADY_LINKED", "current_directory_id": p["matched_directory_id"],
            "message": "This portal account is already linked to a different VISITA record. Explicit reconciliation is required."})
    existing = d.get("linked_patient_id")
    other = await db.patients.find_one({"id": {"$ne": pid}, "matched_directory_id": did, "active_status": True}, {"_id": 0, "id": 1})
    if (existing and existing != pid) or other:
        raise HTTPException(status_code=409, detail={
            "code": "DIRECTORY_ALREADY_LINKED", "linked_patient_id": existing or other["id"],
            "message": "This VISITA record is already linked to another portal account. Identity review is required."})
    pin = d.get("visita_patient_id")
    ts = now_iso()
    r1 = await db.patient_directory.update_one(
        {"id": did, "$or": [{"linked_patient_id": None}, {"linked_patient_id": {"$exists": False}}, {"linked_patient_id": pid}]},
        {"$set": {"linked_patient_id": pid, "updated_at": ts}})
    if r1.matched_count != 1:
        raise HTTPException(status_code=409, detail={"code": "DIRECTORY_ALREADY_LINKED", "message": "Concurrent link detected; no change made."})
    updates = {"matched_directory_id": did, "canonical_directory_id": did,
               "identity_linked": True, "identity_linked_by": user["name"], "identity_linked_at": ts, "updated_at": ts}
    if pin:
        updates["visita_patient_id"] = pin
        if p.get("visita_patient_id") and p["visita_patient_id"] != pin:
            # historical duplicate PIN issued by the old Verify flow: retained for reference, never recycled
            updates["historical_visita_patient_id"] = p["visita_patient_id"]
    r2 = await db.patients.update_one(
        {"id": pid, "$or": [{"matched_directory_id": None}, {"matched_directory_id": {"$exists": False}}, {"matched_directory_id": did}]},
        {"$set": updates})
    if r2.matched_count != 1:
        # rollback directory side to its prior state so no half-link remains
        await db.patient_directory.update_one({"id": did, "linked_patient_id": pid},
                                              {"$set": {"linked_patient_id": existing, "updated_at": now_iso()}})
        await audit("identity_link_rolled_back", "patient", pid, user, meta={"directory_id": did, "reason": "portal_conditional_write_failed"})
        raise HTTPException(status_code=409, detail={"code": "PORTAL_ALREADY_LINKED", "message": "Concurrent link detected; rolled back."})
    merge = await _refresh_canonical_from_registration(p, d, user, source)
    await audit("identity_linked", "patient", pid, user,
                meta={"directory_id": did, "visita_patient_id": pin, "preserved_pin": bool(pin), "source": source,
                      "historical_portal_pin": updates.get("historical_visita_patient_id"),
                      "resulting_identity_state": "LINKED_EXISTING",
                      "canonical_fields_refreshed": sorted(merge["changes"].keys()), "identity_conflicts": sorted(merge["conflicts"].keys())})
    return pin


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
    # Link to a directory record (stable VISITA-id relationship) — hardened two-way link.
    link_dir_id = body.matched_patient_id or p.get("matched_directory_id")
    identity_outcome = None
    if body.decision == "verified" and link_dir_id:
        await block_synthetic(link_dir_id, what="portal_link_verification", user=user)
        d = await db.patient_directory.find_one({"id": link_dir_id})
        if not d:
            raise HTTPException(status_code=404, detail="VISITA directory record not found.")
        pin = await _link_portal_to_directory(p, d, user, source="verification")
        updates["visita_patient_id"] = pin or updates.get("visita_patient_id")
        updates["matched_directory_id"] = link_dir_id
        identity_outcome = "LINKED_EXISTING"
        # Stage C — verified + linked ⇒ active relationship anchored to canonical identity.
        if p.get("practice_id"):
            await rel_mod.upsert_relationship(
                db, practice_id=p["practice_id"], status=rel_mod.ACTIVE,
                directory_id=link_dir_id, patient_id=patient_id,
                visita_patient_id=pin, by=user["name"], source="verification")
    # Unlinked verification: identity review must come first; new-patient must be explicit.
    final_pin = updates.get("visita_patient_id") or p.get("visita_patient_id")
    if body.decision == "verified" and not link_dir_id:
        strength, cands = await directory_mod.live_candidates(db, p)
        if cands:
            await audit("identity_link_required", "patient", patient_id, user,
                        meta={"strength": strength, "candidate_directory_ids": [c["id"] for c in cands]})
            raise HTTPException(status_code=409, detail={
                "code": "IDENTITY_LINK_REQUIRED", "strength": strength,
                "message": "An existing VISITA patient may match this registration. Review / link in Identity Link Review before verifying.",
                "candidates": cands})
        if not body.confirm_new_patient:
            raise HTTPException(status_code=409, detail={
                "code": "NEW_PATIENT_CONFIRMATION_REQUIRED",
                "message": "No existing patient match requiring review was identified. Confirm 'Verify as New Patient' to create a new VIen identity / PIN."})
        identity_outcome = "NEW_PATIENT"
        updates["identity_outcome"] = identity_outcome
        # Auto-assign a unique 4-digit VISITA PIN ONLY here — explicit NEW PATIENT decision.
        if not final_pin:
            new_pin = await identity_mod.assign_visita_pin(db, patient_id)
            if new_pin is None:
                raise HTTPException(status_code=507,
                                    detail="No 4-digit VISITA PINs remain (1000-9999 exhausted). Please contact an administrator.")
            updates["visita_patient_id"] = new_pin
            await audit("visita_pin_assigned", "patient", patient_id, user, meta={"visita_patient_id": new_pin})
        await audit("patient_verified_new", "patient", patient_id, user,
                    meta={"visita_patient_id": updates.get("visita_patient_id"), "match_strength": strength, "resulting_identity_state": "NEW_PATIENT"})
    if identity_outcome:
        updates["identity_outcome"] = identity_outcome
    await db.patients.update_one({"id": patient_id}, {"$set": updates})
    await audit("verify_patient", "patient", patient_id, user, new_status=body.decision,
                meta={"identity_outcome": identity_outcome} if identity_outcome else None)
    # Stage C — a verified portal account is an ACTIVE patient at its practice (covers
    # the portal-only case with no directory link; link case handled above). A rejected
    # account's practice relationship is marked inactive.
    if p.get("practice_id"):
        if body.decision == "verified":
            await rel_mod.upsert_relationship(
                db, practice_id=p["practice_id"], status=rel_mod.ACTIVE,
                directory_id=updates.get("matched_directory_id") or p.get("matched_directory_id"),
                patient_id=patient_id, visita_patient_id=updates.get("visita_patient_id") or p.get("visita_patient_id"),
                by=user["name"], source="verification")
        elif body.decision == "rejected":
            await rel_mod.upsert_relationship(
                db, practice_id=p["practice_id"], status=rel_mod.INACTIVE,
                directory_id=p.get("matched_directory_id"), patient_id=patient_id,
                by=user["name"], source="verification_rejected")
    if body.decision == "verified" and not was_verified:
        fresh = await db.patients.find_one({"id": patient_id}, {"_id": 0})
        await notify_svc.account_verified(db, fresh)
    else:
        await notify_patient(patient_id, "Account update",
                             "Your portal account has been reviewed. Please log in to your Patient Portal.")
    return {"ok": True}


# ----------------------------- Identity Link Review -----------------------------
@api.get("/internal/identity-links")
async def identity_links(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Portal accounts that have directory candidates but are not yet linked to a
    canonical VISITA record — the manual Identity Link Review queue. Ambiguous
    matches live here too; nothing is linked automatically."""
    pend = await db.patients.find({
        **pscope(user),
        "active_status": True,
        "identity_linked": {"$ne": True},
        "verification_status": {"$in": ["pending", "verified"]},
    }, {"_id": 0}).sort("created_at", -1).to_list(300)
    out = []
    for p in pend:
        link_id = p.get("matched_directory_id")
        # Skip rows already linked both ways (defensive — identity_linked covers most).
        if link_id:
            d = await db.patient_directory.find_one({"id": link_id}, {"_id": 0, "linked_patient_id": 1})
            if d and d.get("linked_patient_id") == p["id"]:
                continue
        stored = (p.get("directory_match") or {}).get("candidates", [])
        strength = (p.get("directory_match") or {}).get("strength")
        if not stored and not link_id:
            strength, stored = await directory_mod.live_candidates(db, p)
        if not stored:
            continue
        out.append({
            "id": p["id"], "first_name": p["first_name"], "last_name": p["last_name"],
            "middle_name": p.get("middle_name"), "second_last_name": p.get("second_last_name"), "full_name": names_mod.full_display_name(p),
            "date_of_birth": p.get("date_of_birth"), "phone": p.get("phone"), "email": p.get("email"),
            "patient_type": p.get("patient_type"),
            "verification_status": p.get("verification_status"),
            "visita_patient_id": p.get("visita_patient_id"),
            "health_card_masked": mask_hcn(p.get("health_card_number")),
            "strength": strength,
            "candidates": stored,
            "relationship": await _rel_summary_for_patient(p, user),
        })
    return out


class LinkDirectoryBody(BaseModel):
    directory_id: str


@api.post("/internal/patients/{patient_id}/link-directory")
async def link_patient_directory(patient_id: str, body: LinkDirectoryBody,
                                  user: dict = Depends(require_roles("staff", "admin"))):
    """Explicitly link a portal account to an existing canonical directory record.
    Preserves the canonical PIN, writes an audit event, and NEVER merges clinical
    history or silently overwrites demographics. Ambiguity is resolved by the
    caller choosing an explicit directory_id."""
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Portal patient not found.")
    d = await db.patient_directory.find_one({"id": body.directory_id})
    if not d:
        raise HTTPException(status_code=404, detail="VISITA directory record not found.")
    pin = await _link_portal_to_directory(p, d, user, source="identity_link_review")
    await db.patients.update_one({"id": patient_id}, {"$set": {"identity_outcome": "LINKED_EXISTING"}})
    # Stage C — canonical linking re-anchors this practice's relationship to the
    # canonical identity. Preserve an existing status if present, else mark active.
    if p.get("practice_id"):
        prior = await rel_mod.relationship_for_patient(db, p["practice_id"], patient_id=patient_id,
                                                        directory_id=d["id"])
        await rel_mod.upsert_relationship(
            db, practice_id=p["practice_id"],
            status=(prior.get("status") if prior else rel_mod.ACTIVE),
            directory_id=d["id"], patient_id=patient_id, visita_patient_id=pin,
            by=user["name"], source="identity_link")
    return {"ok": True, "visita_patient_id": pin, "directory_id": d["id"]}


_REL_LABEL = {"active": "Active patient", "applicant": "Applicant",
              "former": "Former patient", "inactive": "Inactive"}


# ----------------------------- Identity Cleanup (historical reconciliation) -----------------------------
class CleanupLinkBody(BaseModel):
    directory_id: str


class CleanupApplyBody(BaseModel):
    directory_id: str
    selections: list
    confirm_identity_critical: bool = False


class CleanupCompleteBody(BaseModel):
    outcome: str = "completed"  # completed | conflict_noted
    note: Optional[str] = None


async def _cleanup_pair(patient_id: str, directory_id: str, user: dict):
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Portal patient not found.")
    assert_practice(p, user)
    d = await db.patient_directory.find_one({"id": directory_id})
    if not d:
        raise HTTPException(status_code=404, detail="VISITA directory record not found.")
    return p, d


@api.get("/internal/identity-cleanup")
async def identity_cleanup_queue(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Read-only queue of historical identity cases for the caller's practice. No mutations."""
    return await cleanup_mod.queue(db, user.get("practice_id"))


@api.get("/internal/identity-cleanup/{patient_id}")
async def identity_cleanup_case(patient_id: str, directory_id: Optional[str] = None,
                                user: dict = Depends(require_roles(*CLINIC_ROLES))):
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found.")
    assert_practice(p, user)
    return await cleanup_mod.case(db, p, directory_id)


@api.post("/internal/identity-cleanup/{patient_id}/link")
async def identity_cleanup_link(patient_id: str, body: CleanupLinkBody, user: dict = Depends(require_roles("staff", "admin", "physician"))):
    p, d = await _cleanup_pair(patient_id, body.directory_id, user)
    await block_synthetic(patient_id, body.directory_id, what="identity_cleanup_link", user=user)
    c = await cleanup_mod.case(db, p, body.directory_id)
    if not c["can_link"]:
        await audit("identity_cleanup_conflict", "patient", patient_id, user,
                    meta={"directory_id": d["id"], "class": c["class"], "blocked_reason": c["blocked_reason"], "evidence": c["evidence"]})
        raise HTTPException(status_code=409, detail={"code": c["blocked_reason"] or c["class"],
                                                     "message": "This case cannot be linked routinely. Additional review is required."})
    pin = await _link_portal_to_directory(p, d, user, source="identity_cleanup")
    await db.patients.update_one({"id": patient_id}, {"$set": {
        "identity_outcome": "LINKED_EXISTING",
        "identity_cleanup": {"status": "linked", "linked_at": now_iso(), "by": user["name"], "via": "identity_cleanup"}}})
    await audit("identity_cleanup_linked", "patient", patient_id, user,
                meta={"directory_id": d["id"], "visita_patient_id": pin, "strength": c["strength"], "evidence": c["evidence"],
                      "resulting_identity_state": "LINKED_EXISTING"})
    if p.get("practice_id"):
        prior = await rel_mod.relationship_for_patient(db, p["practice_id"], patient_id=patient_id, directory_id=d["id"])
        await rel_mod.upsert_relationship(db, practice_id=p["practice_id"], status=(prior.get("status") if prior else rel_mod.ACTIVE),
                                          directory_id=d["id"], patient_id=patient_id, visita_patient_id=pin,
                                          by=user["name"], source="identity_cleanup")
    return {"ok": True, "visita_patient_id": pin, "directory_id": d["id"]}


@api.post("/internal/identity-cleanup/{patient_id}/repair-half-link")
async def identity_cleanup_repair(patient_id: str, body: CleanupLinkBody, user: dict = Depends(require_roles("staff", "admin", "physician"))):
    p, d = await _cleanup_pair(patient_id, body.directory_id, user)
    try:
        return await cleanup_mod.repair_half_link(db, p, d, user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "HALF_LINK_REPAIR_BLOCKED", "message": str(e)})


@api.post("/internal/identity-cleanup/{patient_id}/apply-fields")
async def identity_cleanup_apply(patient_id: str, body: CleanupApplyBody, user: dict = Depends(require_roles("staff", "admin", "physician"))):
    p, d = await _cleanup_pair(patient_id, body.directory_id, user)
    if not (p.get("matched_directory_id") == d["id"] and d.get("linked_patient_id") == patient_id):
        raise HTTPException(status_code=409, detail={"code": "NOT_LINKED", "message": "Demographic reconciliation requires a confirmed two-way link first."})
    return await cleanup_mod.apply_fields(db, p, d, body.selections, body.confirm_identity_critical, user)


@api.post("/internal/identity-cleanup/{patient_id}/complete")
async def identity_cleanup_complete(patient_id: str, body: CleanupCompleteBody, user: dict = Depends(require_roles("staff", "admin", "physician"))):
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found.")
    assert_practice(p, user)
    status = "completed" if body.outcome == "completed" else "conflict_noted"
    await db.patients.update_one({"id": patient_id}, {"$set": {
        "identity_cleanup": {**(p.get("identity_cleanup") or {}), "status": status, "reviewed_at": now_iso(), "reviewed_by": user["name"], "note": body.note}}})
    await audit("identity_cleanup_reviewed" if status == "completed" else "identity_cleanup_conflict", "patient", patient_id, user,
                meta={"directory_id": p.get("matched_directory_id"), "outcome": status})
    return {"ok": True, "status": status}


async def _practice_name(practice_id):
    if not practice_id:
        return None
    p = await db.practices.find_one({"id": practice_id}, {"_id": 0, "physician_name": 1, "clinic_name": 1, "slug": 1})
    if not p:
        return practice_id
    return p.get("clinic_name") or p.get("physician_name") or p.get("slug") or practice_id


@api.get("/internal/patients/{patient_id}/relationship")
async def patient_relationship(patient_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """The caller-practice relationship for a portal patient's canonical identity.
    Scoped: a staff member only sees their own practice's relationship record."""
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    assert_practice(p, user)
    rel = await rel_mod.relationship_for_patient(
        db, user.get("practice_id"), patient_id=patient_id, directory_id=p.get("matched_directory_id"))
    out = rel_mod.serialize(rel)
    if out:
        out["label"] = _REL_LABEL.get(out.get("status"), out.get("status"))
    return {"relationship": out}


@api.get("/internal/canonical/{directory_id}/relationships")
async def canonical_relationships(directory_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Cross-practice view of ONE canonical patient identity. The caller sees their
    own practice's relationship in full; other practices are summarised to
    {practice, status} ONLY (no PHI, no records) so the global identity is visible
    without breaching practice data isolation."""
    rels = await rel_mod.relationships_for_directory(db, directory_id)
    own, others = None, []
    for r in rels:
        if r.get("practice_id") == user.get("practice_id"):
            own = rel_mod.serialize(r)
            if own:
                own["label"] = _REL_LABEL.get(own.get("status"), own.get("status"))
        else:
            others.append({
                "practice_id": r.get("practice_id"),
                "practice_name": await _practice_name(r.get("practice_id")),
                "status": r.get("status"),
                "label": _REL_LABEL.get(r.get("status"), r.get("status")),
                "updated_at": r.get("updated_at"),
            })
    return {"directory_id": directory_id, "own": own, "others": others}


async def _rel_summary_for_patient(p, user):
    """Compact relationship summary for a portal patient: own-practice status +
    other-practice statuses (status only, no PHI). Used to annotate review queues."""
    pid = user.get("practice_id")
    own = await rel_mod.relationship_for_patient(
        db, pid, patient_id=p["id"], directory_id=p.get("matched_directory_id"))
    summary = {"own": None, "others": []}
    if own:
        summary["own"] = {"status": own.get("status"),
                          "label": _REL_LABEL.get(own.get("status"), own.get("status"))}
    if p.get("matched_directory_id"):
        for r in await rel_mod.relationships_for_directory(db, p["matched_directory_id"]):
            if r.get("practice_id") == pid:
                continue
            summary["others"].append({
                "practice_name": await _practice_name(r.get("practice_id")),
                "status": r.get("status"),
                "label": _REL_LABEL.get(r.get("status"), r.get("status")),
            })
    return summary


# ----------------------------- Family / Caregiver delegated access -----------------------------
class CaregiverCreateBody(BaseModel):
    name: str
    email: str


class DelegateCreateBody(BaseModel):
    delegate_user_id: Optional[str] = None          # existing VIen user
    new_caregiver: Optional[CaregiverCreateBody] = None  # or create a caregiver-only user
    relationship: str
    relationship_other: Optional[str] = None
    permissions: List[str] = []
    consent_type: str
    consent_note: Optional[str] = None


class DelegateEditBody(BaseModel):
    relationship: Optional[str] = None
    relationship_other: Optional[str] = None
    permissions: Optional[List[str]] = None


@api.get("/internal/user-search")
async def internal_user_search(q: str = "", user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Find existing patient/caregiver VIen users to grant delegate access to.
    Excludes staff/physician/admin/pharmacy/partner accounts."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    rx = {"$regex": re.escape(q), "$options": "i"}
    docs = await db.users.find(
        {"role": {"$in": ["patient", "caregiver"]},
         "$or": [{"name": rx}, {"email": rx}, {"username": rx}]},
        {"_id": 1, "name": 1, "email": 1, "role": 1}).limit(15).to_list(15)
    return [{"id": str(d["_id"]), "name": d.get("name"), "email": d.get("email"),
             "role": d.get("role")} for d in docs]


@api.post("/internal/caregivers")
async def create_caregiver(body: CaregiverCreateBody, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Create a caregiver-only user (no patient record, no chart, no PIN). Reuses the
    existing JWT login + bcrypt + must_change_password flow. Returns a one-time temp
    password. If the email already belongs to a VIen user, that user is reused."""
    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    existing = await db.users.find_one({"email": email})
    if existing:
        return {"reused": True, "user_id": str(existing["_id"]), "name": existing.get("name"),
                "email": email, "role": existing.get("role")}
    temp = _gen_temp_password()
    uid = (await db.users.insert_one({
        "email": email, "password_hash": authlib.hash_password(temp),
        "name": (body.name or "").strip() or email, "role": "caregiver",
        "active": True, "must_change_password": True, "patient_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    })).inserted_id
    await audit("create_caregiver_account", "user", str(uid), user, meta={"email": email})
    return {"reused": False, "user_id": str(uid), "name": body.name, "email": email,
            "role": "caregiver", "temp_password": temp, "must_change_password": True}


async def _enrich_delegate(g: dict) -> dict:
    u = None
    try:
        u = await db.users.find_one({"_id": ObjectId(g["delegate_user_id"])},
                                    {"_id": 0, "name": 1, "email": 1, "role": 1})
    except Exception:
        u = None
    d = delegates_mod.serialize(g)
    d["delegate_name"] = (u or {}).get("name")
    d["delegate_email"] = (u or {}).get("email")
    d["delegate_role"] = (u or {}).get("role")
    return d


@api.get("/internal/patients/{patient_id}/delegates")
async def list_patient_delegates(patient_id: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    assert_practice(p, user)
    grants = await delegates_mod.grants_for_patient(db, patient_id)
    return [await _enrich_delegate(g) for g in grants]


@api.post("/internal/patients/{patient_id}/delegates")
async def add_patient_delegate(patient_id: str, body: DelegateCreateBody,
                               user: dict = Depends(require_roles(*CLINIC_ROLES))):
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    assert_practice(p, user)
    if body.relationship not in delegates_mod.RELATIONSHIPS:
        raise HTTPException(status_code=400, detail="Invalid relationship.")
    if body.consent_type not in delegates_mod.CONSENT_TYPES:
        raise HTTPException(status_code=400, detail="An authorization basis is required.")
    perms = delegates_mod.clean_permissions(body.permissions)
    if not perms:
        raise HTTPException(status_code=400, detail="Select at least one permission.")

    # Resolve the delegate user: existing id, or create/reuse a caregiver by email.
    delegate_user_id = body.delegate_user_id
    if not delegate_user_id and body.new_caregiver:
        created = await create_caregiver(body.new_caregiver, user)
        delegate_user_id = created["user_id"]
        temp_pw = created.get("temp_password")
    else:
        temp_pw = None
    if not delegate_user_id:
        raise HTTPException(status_code=400, detail="Select an existing user or create a caregiver account.")
    try:
        du = await db.users.find_one({"_id": ObjectId(delegate_user_id)})
    except Exception:
        du = None
    if not du:
        raise HTTPException(status_code=404, detail="Delegate user not found.")
    if du.get("role") in ("staff", "physician", "admin", "pharmacy", "partner", "developer_ops"):
        raise HTTPException(status_code=400, detail="Clinic/partner accounts cannot be delegates.")
    # A delegate cannot be granted access to their OWN patient record.
    if du.get("patient_id") == patient_id:
        raise HTTPException(status_code=400, detail="This is the patient's own account.")

    existing = await db[delegates_mod.COLL].find_one(
        {"patient_id": patient_id, "delegate_user_id": delegate_user_id, "active": True})
    if existing:
        raise HTTPException(status_code=409, detail="This person already has active access to this patient.")

    now = now_iso()
    g = {
        "id": "del_" + uuid.uuid4().hex,
        "patient_id": patient_id,
        "delegate_user_id": delegate_user_id,
        "practice_id": p.get("practice_id"),
        "relationship": body.relationship,
        "relationship_other": (body.relationship_other or "").strip() if body.relationship == "Other" else None,
        "permissions": perms,
        "active": True,
        "granted_at": now,
        "granted_by": user["id"],
        "consent_type": body.consent_type,
        "consent_note": (body.consent_note or "").strip() or None,
        "revoked_at": None, "revoked_by": None,
        "created_at": now, "updated_at": now,
    }
    await db[delegates_mod.COLL].insert_one({**g})
    await audit("delegate_access_granted", "patient", patient_id, user,
                meta={"delegate_user_id": delegate_user_id, "relationship": body.relationship,
                      "permissions": perms, "consent_type": body.consent_type})
    out = await _enrich_delegate(g)
    if temp_pw:
        out["temp_password"] = temp_pw  # one-time display for a freshly created caregiver
    return out


@api.patch("/internal/patients/{patient_id}/delegates/{grant_id}")
async def edit_patient_delegate(patient_id: str, grant_id: str, body: DelegateEditBody,
                                user: dict = Depends(require_roles(*CLINIC_ROLES))):
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    assert_practice(p, user)
    g = await db[delegates_mod.COLL].find_one({"id": grant_id, "patient_id": patient_id})
    if not g:
        raise HTTPException(status_code=404, detail="Access grant not found.")
    updates = {"updated_at": now_iso()}
    if body.relationship is not None:
        if body.relationship not in delegates_mod.RELATIONSHIPS:
            raise HTTPException(status_code=400, detail="Invalid relationship.")
        updates["relationship"] = body.relationship
        updates["relationship_other"] = (body.relationship_other or "").strip() if body.relationship == "Other" else None
    if body.permissions is not None:
        perms = delegates_mod.clean_permissions(body.permissions)
        if not perms:
            raise HTTPException(status_code=400, detail="Select at least one permission.")
        updates["permissions"] = perms
    await db[delegates_mod.COLL].update_one({"id": grant_id}, {"$set": updates})
    await audit("delegate_access_updated", "patient", patient_id, user,
                meta={"grant_id": grant_id, **{k: v for k, v in updates.items() if k != "updated_at"}})
    return await _enrich_delegate(await db[delegates_mod.COLL].find_one({"id": grant_id}))


@api.post("/internal/patients/{patient_id}/delegates/{grant_id}/revoke")
async def revoke_patient_delegate(patient_id: str, grant_id: str,
                                  user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Soft-revoke (active=false) — access stops immediately; history is preserved."""
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    assert_practice(p, user)
    g = await db[delegates_mod.COLL].find_one({"id": grant_id, "patient_id": patient_id})
    if not g:
        raise HTTPException(status_code=404, detail="Access grant not found.")
    if g.get("active"):
        await db[delegates_mod.COLL].update_one({"id": grant_id}, {"$set": {
            "active": False, "revoked_at": now_iso(), "revoked_by": user["id"], "updated_at": now_iso()}})
        await audit("delegate_access_revoked", "patient", patient_id, user,
                    meta={"grant_id": grant_id, "delegate_user_id": g.get("delegate_user_id")})
    return await _enrich_delegate(await db[delegates_mod.COLL].find_one({"id": grant_id}))


@api.get("/internal/delegate-options")
async def delegate_options(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return {"relationships": delegates_mod.RELATIONSHIPS,
            "consent_types": delegates_mod.CONSENT_TYPES,
            "permissions": sorted(delegates_mod.PERMISSIONS)}


# ---------------- Public caregiver / on-behalf-of access requests ----------------
# INTAKE ONLY. A public submission is an UNAPPROVED request — it never creates a
# patient_portal_delegates grant, never auto-links a patient by name/DOB/OHIP, and
# never shares credentials. Staff review and APPROVE to create/activate the real
# delegate grant in the existing architecture; DECLINE leaves no authorization.
ACCESS_REQ_COLL = "portal_access_requests"


class PortalAccessRequestBody(BaseModel):
    practice_slug: Optional[str] = None
    practice_id: Optional[str] = None
    # Person being helped (claimed identifiers — staff confirm the real patient)
    patient_first_name: str
    patient_last_name: str
    patient_date_of_birth: str
    patient_health_card_number: str
    patient_health_card_version: Optional[str] = None
    patient_health_card_issue_date: Optional[str] = None
    patient_health_card_expiry_date: Optional[str] = None
    # Requester (the caregiver — uses their OWN account + chosen password)
    first_name: str
    last_name: str
    email: str
    phone: str
    password: str
    relationship: str
    authorization_basis: str
    note: Optional[str] = None


class ApproveAccessRequestBody(BaseModel):
    patient_id: str
    permissions: Optional[List[str]] = None
    relationship: Optional[str] = None
    review_note: Optional[str] = None


class DeclineAccessRequestBody(BaseModel):
    review_note: Optional[str] = None


async def _resolve_access_practice(body: PortalAccessRequestBody):
    pr = None
    if body.practice_slug:
        pr = await db.practices.find_one({"slug": body.practice_slug})
    if not pr and body.practice_id:
        pr = await db.practices.find_one({"id": body.practice_id})
    return pr


@api.post("/portal-access-requests")
async def create_portal_access_request(body: PortalAccessRequestBody):
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if not (body.patient_health_card_number or "").strip():
        raise HTTPException(status_code=400, detail="The health card (OHIP) number of the person you are helping is required.")
    if len(body.password or "") < 6:
        raise HTTPException(status_code=400, detail="Your password must be at least 6 characters.")
    if body.relationship not in delegates_mod.RELATIONSHIPS:
        raise HTTPException(status_code=400, detail="Please select a relationship.")
    if body.authorization_basis not in delegates_mod.CONSENT_TYPES:
        raise HTTPException(status_code=400, detail="Please select how you are authorized to help.")
    practice = await _resolve_access_practice(body)
    if not practice:
        raise HTTPException(status_code=400, detail="We couldn't identify the clinic. Please use your clinic's link.")
    # Note an existing VIen user (reuse later) WITHOUT creating anything now.
    existing_user = await db.users.find_one({"email": email}, {"_id": 1, "name": 1, "role": 1})
    now = now_iso()
    ref = await next_ref("PAR")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "practice_id": practice["id"], "practice_slug": practice.get("slug"),
        "patient_first_name": body.patient_first_name.strip(),
        "patient_last_name": body.patient_last_name.strip(),
        "patient_date_of_birth": body.patient_date_of_birth,
        "patient_health_card_number": (body.patient_health_card_number or "").strip() or None,
        "patient_health_card_version": (body.patient_health_card_version or "").strip().upper() or None,
        "patient_health_card_issue_date": body.patient_health_card_issue_date or None,
        "patient_health_card_expiry_date": body.patient_health_card_expiry_date or None,
        "requester_user_id": str(existing_user["_id"]) if existing_user else None,
        "requester_name": f"{body.first_name.strip()} {body.last_name.strip()}".strip(),
        "requester_first_name": body.first_name.strip(), "requester_last_name": body.last_name.strip(),
        "requester_email": email, "requester_phone": identity_mod.normalize_phone(body.phone),
        # Caregiver's OWN chosen password — stored hashed only, cleared once the account is created.
        "requester_password_hash": None if existing_user else authlib.hash_password(body.password),
        "relationship": body.relationship,
        "authorization_basis": body.authorization_basis,
        "note": (body.note or "").strip() or None,
        "status": "PENDING",
        "linked_patient_id": None, "resulting_delegate_id": None,
        "reviewed_by": None, "reviewed_at": None, "review_note": None,
        "submitted_at": now, "created_at": now, "updated_at": now,
        "history": [{"status": "PENDING", "at": now, "by": "public"}],
    }
    await db[ACCESS_REQ_COLL].insert_one({**doc})
    await audit("portal_access_requested", "portal_access_request", doc["id"],
                {"id": doc["requester_user_id"], "name": doc["requester_name"], "role": "caregiver"},
                new_status="PENDING",
                meta={"practice_id": practice["id"], "relationship": body.relationship,
                      "existing_user": bool(existing_user)})
    return {"ok": True, "ref_number": ref,
            "message": "Request received. The clinic will review and approve your access before you can see this patient's information."}


@api.get("/internal/portal-access-requests")
async def list_portal_access_requests(status: Optional[str] = None,
                                      user: dict = Depends(require_roles(*CLINIC_ROLES))):
    q = {**pscope(user)}
    if status:
        q["status"] = status.upper()
    reqs = await db[ACCESS_REQ_COLL].find(q, {"_id": 0, "requester_password_hash": 0}).sort("created_at", -1).to_list(200)
    return reqs


def _norm_hcn(v: str) -> str:
    return re.sub(r"\D", "", v or "")


def _mask_hcn_display(v: str) -> str:
    d = _norm_hcn(v)
    if not d:
        return None
    return ("•••• ••• " + d[-3:]) if len(d) >= 3 else d


def _match_fields_payload(sub: dict, can: dict) -> dict:
    """Shared patient-match comparison used by Portal Access AND Verifications.
    Inputs carry: name, dob, hcn, version, issue, expiry. OHIP compared on digits
    and returned MASKED only (full canonical number never leaves the server)."""
    def eq(a, b):
        return bool(a) and bool(b) and str(a).strip().lower() == str(b).strip().lower()
    submitted = {
        "name": sub.get("name"), "dob": sub.get("dob"),
        "ohip_display": _mask_hcn_display(sub.get("hcn")),
        "version": (sub.get("version") or "").upper() or None,
        "issue": sub.get("issue"), "expiry": sub.get("expiry"),
    }
    canonical = {
        "name": can.get("name"), "dob": can.get("dob"),
        "ohip_display": _mask_hcn_display(can.get("hcn")),
        "version": (can.get("version") or "").upper() or None,
        "issue": can.get("issue"), "expiry": can.get("expiry"),
    }
    sub_num, can_num = _norm_hcn(sub.get("hcn")), _norm_hcn(can.get("hcn"))
    match = {
        "name": eq(submitted["name"], canonical["name"]),
        "dob": eq(submitted["dob"], canonical["dob"]),
        "ohip": bool(sub_num) and sub_num == can_num,
        "version": eq(submitted["version"], canonical["version"]),
        "issue": eq(submitted["issue"], canonical["issue"]),
        "expiry": eq(submitted["expiry"], canonical["expiry"]),
    }
    return {"submitted": submitted, "canonical": canonical, "match": match}


@api.get("/internal/portal-access-requests/candidates")
async def portal_access_candidates(q: str, user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Candidate patients for the Portal Access approval dialog: the same merged
    search as the Patients module (verified portal accounts, scoped to the caller's
    practice, PLUS active directory records incl. patients with no portal account).
    An all-digit query is treated as an exact VISITA PIN first. Search only — no link."""
    qn = (q or "").strip()
    if len(qn) < 2:
        return []
    out = []
    if qn.isdigit():
        out = await internal_patient_lookup_pin(qn, user)
    seen = {r["id"] for r in out}
    for r in await _search_patients_merged(qn, limit=40, include_pin=True, practice_id=user.get("practice_id")):
        if r["id"] not in seen:
            out.append(r); seen.add(r["id"])
    return out[:40]


@api.get("/internal/portal-access-requests/{req_id}/compare")
async def compare_portal_access_request(req_id: str, patient_id: str,
                                         user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Side-by-side match helper for the Portal Access review: caregiver-submitted
    patient info vs a candidate canonical patient (portal account OR directory
    record). Does NOT link or approve."""
    req = await db[ACCESS_REQ_COLL].find_one({"id": req_id})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")
    assert_practice(req, user)
    p = await db.patients.find_one({"id": patient_id})
    if p:
        assert_practice(p, user)
        can = {"name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
               "dob": p.get("date_of_birth"), "hcn": p.get("health_card_number"),
               "version": p.get("health_card_version"),
               "issue": p.get("health_card_issue_date"), "expiry": p.get("health_card_expiry_date")}
    else:
        d = await db.patient_directory.find_one({"id": patient_id})
        if not d:
            raise HTTPException(status_code=404, detail="Patient not found.")
        can = {"name": f"{d.get('first_name', '')} {d.get('last_name', '')}".strip(),
               "dob": d.get("date_of_birth"), "hcn": d.get("health_card_number"),
               "version": d.get("health_card_version_code") or d.get("health_card_version"),
               "issue": d.get("health_card_issue_date"), "expiry": d.get("health_card_expiry_date")}
    return _match_fields_payload(
        {"name": f"{req.get('patient_first_name', '')} {req.get('patient_last_name', '')}".strip(),
         "dob": req.get("patient_date_of_birth"), "hcn": req.get("patient_health_card_number"),
         "version": req.get("patient_health_card_version"),
         "issue": req.get("patient_health_card_issue_date"), "expiry": req.get("patient_health_card_expiry_date")},
        can)


@api.get("/internal/verifications/{patient_id}/compare")
async def compare_verification_candidate(patient_id: str, candidate_id: str,
                                          user: dict = Depends(require_roles(*CLINIC_ROLES))):
    """Side-by-side match for the Verifications queue: the pending portal registration
    vs a canonical candidate (directory record or existing patient). Does NOT verify/link."""
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    assert_practice(p, user)
    can = await db.patient_directory.find_one({"id": candidate_id})
    if can:
        can_fields = {"name": f"{can.get('first_name', '')} {can.get('last_name', '')}".strip(),
                      "dob": can.get("date_of_birth"), "hcn": can.get("health_card_number"),
                      "version": can.get("health_card_version_code") or can.get("health_card_version"),
                      "issue": can.get("health_card_issue_date"), "expiry": can.get("health_card_expiry_date")}
    else:
        cp = await db.patients.find_one({"id": candidate_id})
        if not cp:
            raise HTTPException(status_code=404, detail="Candidate not found.")
        assert_practice(cp, user)
        can_fields = {"name": f"{cp.get('first_name', '')} {cp.get('last_name', '')}".strip(),
                      "dob": cp.get("date_of_birth"), "hcn": cp.get("health_card_number"),
                      "version": cp.get("health_card_version"),
                      "issue": cp.get("health_card_issue_date"), "expiry": cp.get("health_card_expiry_date")}
    return _match_fields_payload(
        {"name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
         "dob": p.get("date_of_birth"), "hcn": p.get("health_card_number"),
         "version": p.get("health_card_version"),
         "issue": p.get("health_card_issue_date"), "expiry": p.get("health_card_expiry_date")},
        can_fields)


async def _ensure_portal_patient_for_directory(d: dict, req: dict, user: dict) -> dict:
    """Safe bridge for caregiver approval on a directory-only ACTIVE patient.
    Returns an existing linked portal patient if present, otherwise creates a
    minimal UNCLAIMED portal patient record anchored to the canonical directory
    identity (existing VISITA PIN + canonical demographics, NO login email,
    NO password, NO user account, no fabricated data). The patient never
    receives credentials and is never required to log in. If that patient later
    registers for their own portal, this record is claimed/linked (PIN, history
    and delegate grants preserved) rather than duplicated."""
    # 1) Reuse an existing portal patient already linked to this identity.
    if d.get("linked_patient_id"):
        p = await db.patients.find_one({"id": d["linked_patient_id"]})
        if p:
            return p
    existing = await db.patients.find_one({"matched_directory_id": d["id"], "active_status": True})
    if existing:
        await db.patient_directory.update_one(
            {"id": d["id"], "linked_patient_id": {"$in": [None, ""]}},
            {"$set": {"linked_patient_id": existing["id"], "updated_at": now_iso()}})
        return existing

    # 2) Only bridge a confirmed ACTIVE clinic patient.
    if str(d.get("patient_status") or "").upper() != directory_mod.ACTIVE:
        raise HTTPException(status_code=409,
                            detail="Caregiver access can only be bridged for an active clinic patient.")

    patient_id = str(uuid.uuid4())
    pin = d.get("visita_patient_id")
    practice_id = d.get("practice_id") or req.get("practice_id") or user.get("practice_id")
    now = now_iso()
    patient = {
        "id": patient_id, "visita_patient_id": pin,
        "first_name": d.get("first_name"), "last_name": d.get("last_name"),
        "date_of_birth": d.get("date_of_birth"),
        "health_card_number": d.get("health_card_number"),
        "health_card_version": d.get("health_card_version_code") or d.get("health_card_version"),
        "health_card_issue_date": d.get("health_card_issue_date"),
        "health_card_expiry_date": d.get("health_card_expiry_date"),
        "phone": d.get("cell_phone") or d.get("home_phone"),
        "home_phone": d.get("home_phone"),
        "email": None,  # UNCLAIMED — no login email, no credentials
        "address": d.get("address"), "unit": d.get("unit"),
        "city": d.get("city"), "province": d.get("province"),
        "postal_code": d.get("postal_code"), "country": d.get("country"),
        "patient_type": d.get("patient_type"),
        "verification_status": "verified", "portal_status": "UNCLAIMED",
        "matched_directory_id": d["id"], "canonical_directory_id": d["id"],
        "identity_linked": True, "identity_linked_by": user.get("name"), "identity_linked_at": now,
        "practice_id": practice_id,
        "is_unclaimed": True, "has_login": False,
        "active_status": True, "is_demo": False,
        "created_via": "caregiver_access_bridge",
        "created_at": now, "updated_at": now,
    }
    await db.patients.insert_one({**patient})
    await db.patient_directory.update_one({"id": d["id"]}, {"$set": {
        "linked_patient_id": patient_id, "updated_at": now}})
    if pin:
        await db.visita_pins.update_one({"_id": pin}, {"$set": {
            "patient_id": patient_id, "created_at": now}}, upsert=True)
    await audit("unclaimed_portal_patient_created", "patient", patient_id, user,
                meta={"directory_id": d["id"], "visita_patient_id": pin, "via": "caregiver_access_bridge"})
    # Stage C — anchor the practice relationship to the canonical identity.
    if practice_id:
        await rel_mod.upsert_relationship(
            db, practice_id=practice_id, status=rel_mod.ACTIVE,
            directory_id=d["id"], patient_id=patient_id,
            visita_patient_id=pin, by=user.get("name"), source="caregiver_access_bridge")
    return await db.patients.find_one({"id": patient_id})


@api.post("/internal/portal-access-requests/{req_id}/approve")
async def approve_portal_access_request(req_id: str, body: ApproveAccessRequestBody,
                                        user: dict = Depends(require_roles(*CLINIC_ROLES))):
    req = await db[ACCESS_REQ_COLL].find_one({"id": req_id})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")
    assert_practice(req, user)
    if req.get("status") != "PENDING":
        raise HTTPException(status_code=409, detail="This request has already been reviewed.")

    patient = await db.patients.find_one({"id": body.patient_id})
    if not patient:
        d = await db.patient_directory.find_one({"id": body.patient_id})
        if not d:
            raise HTTPException(status_code=404, detail="Select a valid patient to link.")
        # Safe bridge: an ACTIVE directory-only patient (no portal account yet) gets
        # a minimal UNCLAIMED portal record so caregiver access can be granted without
        # forcing the patient to register or receive any login.
        patient = await _ensure_portal_patient_for_directory(d, req, user)
        body.patient_id = patient["id"]
    assert_practice(patient, user)

    relationship = body.relationship or req.get("relationship")
    if relationship not in delegates_mod.RELATIONSHIPS:
        raise HTTPException(status_code=400, detail="Invalid relationship.")
    consent_type = req.get("authorization_basis")
    if consent_type not in delegates_mod.CONSENT_TYPES:
        raise HTTPException(status_code=400, detail="Missing authorization basis on the request.")
    perms = delegates_mod.clean_permissions(body.permissions) or sorted(delegates_mod.PERMISSIONS)

    # Resolve the caregiver user: reuse existing by email, else create a caregiver-only account.
    temp_pw = None
    du = None
    if req.get("requester_user_id"):
        try:
            du = await db.users.find_one({"_id": ObjectId(req["requester_user_id"])})
        except Exception:
            du = None
    if not du:
        du = await db.users.find_one({"email": req["requester_email"]})
    if not du:
        if req.get("requester_password_hash"):
            # Caregiver chose their OWN password at signup — create the account with it.
            uid = (await db.users.insert_one({
                "email": req["requester_email"], "password_hash": req["requester_password_hash"],
                "name": req["requester_name"], "role": "caregiver",
                "active": True, "must_change_password": False, "email_verified": False,
                "patient_id": None, "created_at": now_iso(), "updated_at": now_iso(),
            })).inserted_id
            await audit("create_caregiver_account", "user", str(uid), user,
                        meta={"email": req["requester_email"], "self_set_password": True})
            du = await db.users.find_one({"_id": uid})
        else:
            created = await create_caregiver(
                CaregiverCreateBody(name=req["requester_name"], email=req["requester_email"]), user)
            temp_pw = created.get("temp_password")
            du = await db.users.find_one({"_id": ObjectId(created["user_id"])})
    if not du:
        raise HTTPException(status_code=500, detail="Could not resolve the caregiver account.")
    delegate_user_id = str(du["_id"])
    if du.get("role") in ("staff", "physician", "admin", "pharmacy", "partner", "developer_ops"):
        raise HTTPException(status_code=400, detail="Clinic/partner accounts cannot be delegates.")
    if du.get("patient_id") == body.patient_id:
        raise HTTPException(status_code=400, detail="This is the patient's own account.")

    existing_grant = await db[delegates_mod.COLL].find_one(
        {"patient_id": body.patient_id, "delegate_user_id": delegate_user_id, "active": True})
    now = now_iso()
    if existing_grant:
        grant_id = existing_grant["id"]
    else:
        grant_id = "del_" + uuid.uuid4().hex
        g = {
            "id": grant_id, "patient_id": body.patient_id, "delegate_user_id": delegate_user_id,
            "practice_id": patient.get("practice_id"),
            "relationship": relationship, "relationship_other": None,
            "permissions": perms, "active": True,
            "granted_at": now, "granted_by": user["id"],
            "consent_type": consent_type,
            "consent_note": req.get("note"),
            "source_request_id": req_id,
            "revoked_at": None, "revoked_by": None, "created_at": now, "updated_at": now,
        }
        await db[delegates_mod.COLL].insert_one({**g})
        await audit("delegate_access_granted", "patient", body.patient_id, user,
                    meta={"delegate_user_id": delegate_user_id, "relationship": relationship,
                          "permissions": perms, "consent_type": consent_type, "via": "access_request"})

    await db[ACCESS_REQ_COLL].update_one({"id": req_id}, {"$set": {
        "status": "APPROVED", "linked_patient_id": body.patient_id, "resulting_delegate_id": grant_id,
        "reviewed_by": user["id"], "reviewed_at": now, "review_note": (body.review_note or "").strip() or None,
        "updated_at": now,
    }, "$unset": {"requester_password_hash": ""},
        "$push": {"history": {"status": "APPROVED", "at": now, "by": user.get("name")}}})
    await audit("portal_access_approved", "portal_access_request", req_id, user,
                new_status="APPROVED", meta={"patient_id": body.patient_id, "grant_id": grant_id})

    out = {"ok": True, "grant_id": grant_id, "patient_id": body.patient_id,
           "delegate_user_id": delegate_user_id}
    if temp_pw:
        out["temp_password"] = temp_pw  # one-time display for a freshly created caregiver
    return out


@api.post("/internal/portal-access-requests/{req_id}/decline")
async def decline_portal_access_request(req_id: str, body: DeclineAccessRequestBody,
                                        user: dict = Depends(require_roles(*CLINIC_ROLES))):
    req = await db[ACCESS_REQ_COLL].find_one({"id": req_id})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")
    assert_practice(req, user)
    if req.get("status") != "PENDING":
        raise HTTPException(status_code=409, detail="This request has already been reviewed.")
    now = now_iso()
    await db[ACCESS_REQ_COLL].update_one({"id": req_id}, {"$set": {
        "status": "DECLINED", "reviewed_by": user["id"], "reviewed_at": now,
        "review_note": (body.review_note or "").strip() or None, "updated_at": now,
    }, "$unset": {"requester_password_hash": ""},
        "$push": {"history": {"status": "DECLINED", "at": now, "by": user.get("name")}}})
    await audit("portal_access_declined", "portal_access_request", req_id, user, new_status="DECLINED")
    return {"ok": True}




# ----------------------------- Patient Applications (new / former return) -----------------------------
def _serialize_application(a: dict) -> dict:
    return {
        "id": a["id"], "ref_number": a.get("ref_number"), "application_type": a.get("application_type"),
        "first_name": a.get("first_name"), "last_name": a.get("last_name"),
        "date_of_birth": a.get("date_of_birth"), "phone": a.get("phone"), "email": a.get("email"),
        "address": a.get("address"), "unit": a.get("unit"), "city": a.get("city"), "province": a.get("province"),
        "postal_code": a.get("postal_code"), "country": a.get("country"),
        "coverage": a.get("coverage"), "had_family_doctor": a.get("had_family_doctor"),
        "join_reason": a.get("join_reason"), "reason_other": a.get("reason_other"),
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
    query.update(pscope(user))
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
    # Stage C — acceptance transitions the applicant into an ACTIVE patient at this
    # practice, now anchored to the freshly-created canonical identity (dir_id).
    if doc.get("practice_id"):
        await rel_mod.upsert_relationship(
            db, practice_id=doc["practice_id"], status=rel_mod.ACTIVE,
            directory_id=dir_id, patient_id=patient_id, application_id=doc["id"],
            visita_patient_id=pin, by=actor.get("name", "physician"), source="application_accepted",
            note="New-patient application accepted")
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
                    if doc.get("practice_id"):
                        await rel_mod.upsert_relationship(
                            db, practice_id=doc["practice_id"], status=rel_mod.ACTIVE,
                            directory_id=d["id"], application_id=item_id,
                            visita_patient_id=d.get("visita_patient_id"),
                            by=user["name"], source="former_return_accepted")
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
        "full_name": names_mod.full_display_name(d),
        "visita_patient_id": d.get("visita_patient_id"),
        "date_of_birth": d.get("date_of_birth"),
        "home_phone": d.get("home_phone"), "cell_phone": d.get("cell_phone"),
        "address": d.get("address"), "unit": d.get("unit"),
        "city": d.get("city"), "province": d.get("province"), "postal_code": d.get("postal_code"),
        "address_full": address_full,
        "health_card_number": d.get("health_card_number"),
        "health_card_version_code": d.get("health_card_version_code") or d.get("health_card_version"),
        "health_card_version": d.get("health_card_version") or d.get("health_card_version_code"),
        "health_card_expiry_date": d.get("health_card_expiry_date"),
        "patient_type": d.get("patient_type"),
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
        {"date_of_birth": {"$regex": re.escape(qn), "$options": "i"}},
    ]}
    docs = await db.patient_directory.find(query).limit(25).to_list(25)
    seen = {d["id"] for d in docs}
    # VISITA PIN search: a verified patient's PIN can live on the portal `patients`
    # record while the directory PIN is blank (same mapping the physician PIN lookup
    # uses). Resolve numeric PINs through the linked patient -> directory record.
    if qn.isdigit():
        portal = await db.patients.find({
            "verification_status": "verified", "active_status": True, "visita_patient_id": qn,
        }).limit(25).to_list(25)
        for p in portal:
            mdir = p.get("matched_directory_id")
            if not mdir or mdir in seen:
                continue
            d = await db.patient_directory.find_one({"id": mdir})
            if d and d.get("patient_status") != "FORMER_CLOSED":
                docs.append(d); seen.add(mdir)
    return [_pharmacy_patient_identity(d) for d in docs]


@api.get("/pharmacy/patients/{directory_id}")
async def pharmacy_patient(directory_id: str, user: dict = Depends(require_roles("pharmacy"))):
    _pharmacy_of(user)
    d = await db.patient_directory.find_one({"id": directory_id})
    if not d or d.get("patient_status") == "FORMER_CLOSED":
        raise HTTPException(status_code=404, detail="Patient not found in directory.")
    return _pharmacy_patient_identity(d)


async def _practice_for_directory(d: dict) -> Optional[str]:
    """Resolve the clinic/practice a directory patient belongs to, so a
    pharmacy-origin Rx request lands in the right practice's shared queue.
    Pharmacies are global (no practice), so the practice comes from the patient."""
    if d.get("practice_id"):
        return d["practice_id"]
    if d.get("linked_patient_id"):
        p = await db.patients.find_one({"id": d["linked_patient_id"]}, {"_id": 0, "practice_id": 1})
        if p and p.get("practice_id"):
            return p["practice_id"]
    for r in await rel_mod.relationships_for_directory(db, d["id"]):
        if r.get("status") == rel_mod.ACTIVE and r.get("practice_id"):
            return r["practice_id"]
    if await db.practices.count_documents({}) == 1:
        one = await db.practices.find_one({}, {"_id": 0, "id": 1})
        return one["id"] if one else None
    return None


@api.post("/pharmacy/rx")
async def pharmacy_create_rx(
    directory_id: str = Form(...),
    medications: str = Form(""),
    medication_name: str = Form(""),
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

    # Structured multi-medication payload from the smart builder. Falls back to
    # the legacy single-medication form fields for backward compatibility.
    meds_struct = []
    if medications.strip():
        try:
            raw = json.loads(medications)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid medications payload.")
        if isinstance(raw, list):
            for m in raw:
                if isinstance(m, dict) and (m.get("drug") or "").strip():
                    meds_struct.append(m)

    attachment = await _store_pharmacy_upload(file, "rx") if file is not None else None

    display_list = []
    if meds_struct:
        for m in meds_struct:
            display_list.append(" ".join(
                [str(m.get(k) or "").strip() for k in ("drug", "strength", "form") if str(m.get(k) or "").strip()]))
        primary = meds_struct[0]
        med = (primary.get("drug") or "").strip()
        strength_val = (primary.get("strength") or "").strip()
    else:
        med = medication_name.strip()
        strength_val = strength.strip()
        if med:
            display_list = [f"{med}{(' ' + strength_val) if strength_val else ''}"]

    if not meds_struct and not med and not attachment:
        raise HTTPException(status_code=400, detail="Add at least one medication or attach a document.")

    # Immutable prescription-time patient identity (mirrors PHYSICIAN->PHARMACY snapshot).
    snapshot = await _build_patient_snapshot(directory_id)
    ref = await next_ref("RX")
    patient_name = f"{d.get('last_name','')}, {d.get('first_name','')}".strip(", ")
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref,
        "source": "pharmacy",
        "provenance": "PHARMACY_REQUEST",
        "practice_id": await _practice_for_directory(d),
        "patient_id": d.get("linked_patient_id") or d["id"],
        "directory_id": d["id"], "visita_patient_id": d.get("visita_patient_id"),
        "patient_name": patient_name,
        "patient_snapshot": snapshot,
        "medication_name": med or None, "strength": strength_val or None,
        "medications": display_list, "medications_structured": meds_struct, "selected_active_meds": [],
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
    # 'Enter once -> VIen remembers', pharmacy-scoped, source=PHARMACY_REQUEST.
    # Learns ONLY from a request actually sent; never touches physician_rx_memory
    # and never becomes a physician-confirmed patient regimen.
    await _remember_pharmacy_rx(pid, meds_struct)
    await audit("pharmacy_portal_rx", "prescription", doc["id"],
                {"id": user["id"], "name": pname, "role": "pharmacy"}, new_status="waiting_physician",
                meta={"pharmacy_id": pid, "directory_id": d["id"], "attachment": bool(attachment),
                      "medications": len(meds_struct)})
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


async def _remember_pharmacy_rx(pharmacy_id: str, meds: list):
    """Pharmacy-scoped workflow memory (source=PHARMACY_REQUEST). Learns ONLY from
    requests actually SENT by THIS pharmacy. Kept strictly separate from
    physician_rx_memory: it never promotes pharmacy-entered data to a
    physician-confirmed patient regimen and never crosses pharmacies."""
    now = now_iso()
    for m in (meds or []):
        drug = (m.get("drug") or "").strip()
        if not drug:
            continue
        dk = drug.lower()
        add = {}
        for field, memk in [("strength", "strengths"), ("form", "forms"), ("sig", "sigs"),
                            ("quantity_unit", "quantity_units"), ("manufacturer", "manufacturers"),
                            ("days_supply", "days_supplies")]:
            v = str(m.get(field) or "").strip()
            if v:
                add[memk] = v
        attrs = [str(a).strip() for a in (m.get("attributes") or []) if str(a).strip()]
        update = {"$set": {"pharmacy_id": pharmacy_id, "drug_key": dk, "drug": drug,
                           "source": "PHARMACY_REQUEST", "updated_at": now},
                  "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}}
        addto = dict(add)
        if attrs:
            addto["attributes"] = {"$each": attrs}
        if addto:
            update["$addToSet"] = addto
        await db.pharmacy_rx_memory.update_one(
            {"pharmacy_id": pharmacy_id, "drug_key": dk}, update, upsert=True)


class PharmacyRxParseBody(BaseModel):
    text: str


@api.post("/pharmacy/rx/parse")
async def pharmacy_rx_parse(body: PharmacyRxParseBody, user: dict = Depends(require_roles("pharmacy"))):
    """Reuse the shared Access-EMR parser (ONE med = ONE card). Pharmacy-scoped;
    no separate/duplicate parser. Conservative: uncertain data is left blank and the
    original text preserved. Never fabricates."""
    _pharmacy_of(user)
    return rx_parser.parse_access_rx(body.text)


@api.get("/pharmacy/rx/suggest")
async def pharmacy_rx_suggest(patient_ref: Optional[str] = None, drug: Optional[str] = None,
                              user: dict = Depends(require_roles("pharmacy"))):
    """Ranked DATA-ENTRY suggestions for the pharmacy builder (NOT clinical decision
    support). Sources: this patient's previous confirmed meds -> THIS pharmacy's
    remembered values -> neutral catalog. Pharmacy memory is scoped to the
    authenticated pharmacy and never leaks across pharmacies."""
    pid, _ = _pharmacy_of(user)
    patient_id = None
    if patient_ref:
        snap = await _resolve_rx_patient(patient_ref)
        if snap:
            patient_id = snap["patient_id"]

    seen, drugs = set(), []
    def _add(v, src):
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            drugs.append({"value": v, "source": src})

    if patient_id:
        for d in await db.patient_medications.find(
                {"patient_id": patient_id, "active": True}, {"_id": 0, "drug": 1, "last_prescribed_at": 1}
        ).sort("last_prescribed_at", -1).to_list(100):
            _add(d.get("drug"), "patient")
    for d in await db.pharmacy_rx_memory.find(
            {"pharmacy_id": pid}, {"_id": 0, "drug": 1, "updated_at": 1}
    ).sort("updated_at", -1).to_list(300):
        _add(d.get("drug"), "pharmacy")
    for d in await db.medication_catalog.find({}, {"_id": 0, "drug": 1}).sort("updated_at", -1).to_list(400):
        _add(d.get("drug"), "catalog")

    result = {"drugs": drugs[:120]}

    if drug:
        dl = drug.lower().strip()
        fields = {"strengths": [], "forms": [], "attributes": [], "sigs": [], "quantity_units": [], "manufacturers": []}
        fseen = {k: set() for k in fields}

        def _addf(fk, v, src):
            v = str(v or "").strip()
            if v and v.lower() not in fseen[fk]:
                fseen[fk].add(v.lower())
                fields[fk].append({"value": v, "source": src})

        if patient_id:
            for doc in await db.patient_medications.find(
                    {"patient_id": patient_id, "active": True}, {"_id": 0}).to_list(100):
                if (doc.get("drug") or "").lower().strip() == dl:
                    for f, fk in [("strength", "strengths"), ("form", "forms"), ("sig", "sigs"),
                                  ("quantity_unit", "quantity_units"), ("manufacturer", "manufacturers")]:
                        _addf(fk, doc.get(f), "patient")
                    for a in (doc.get("attributes") or []):
                        _addf("attributes", a, "patient")
        pm = await db.pharmacy_rx_memory.find_one({"pharmacy_id": pid, "drug_key": dl}, {"_id": 0})
        if pm:
            for fk, memk in [("strengths", "strengths"), ("forms", "forms"), ("sigs", "sigs"),
                            ("quantity_units", "quantity_units"), ("manufacturers", "manufacturers"),
                            ("attributes", "attributes")]:
                for v in (pm.get(memk) or []):
                    _addf(fk, v, "pharmacy")
        for doc in await db.medication_catalog.find({}, {"_id": 0}).to_list(500):
            if (doc.get("drug") or "").lower().strip() == dl:
                for f, fk in [("strength", "strengths"), ("form", "forms")]:
                    _addf(fk, doc.get(f), "catalog")
                for a in (doc.get("attributes") or []):
                    _addf("attributes", a, "catalog")
        result["fields"] = fields

    return result


@api.get("/pharmacy/patients/{directory_id}/prior-requests")
async def pharmacy_prior_requests(directory_id: str, user: dict = Depends(require_roles("pharmacy"))):
    """THIS pharmacy's previous portal requests for THIS patient (for 'repeat').
    Scoped by pharmacy_id; never exposes another pharmacy's requests."""
    pid, _ = _pharmacy_of(user)
    docs = await db.prescription_requests.find(
        {"pharmacy_id": pid, "received_via": "pharmacy_portal", "directory_id": directory_id},
        {"_id": 0}).sort("created_at", -1).to_list(50)
    out = []
    for x in docs:
        out.append({
            "id": x.get("id"), "ref_number": x.get("ref_number"), "created_at": x.get("created_at"),
            "medications_structured": x.get("medications_structured") or [],
            "medications": x.get("medications") or [],
            "status_label": ("Waiting for Physician to review" if x.get("internal_status") == "waiting_physician"
                             else RX_PATIENT_STATUS.get(x.get("internal_status"), "Received")),
        })
    return out



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
        "health_card_version": g("health_card_version") or g("health_card_version_code"),
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
    refs = list({r for r in (pid, snap.get("directory_id")) if r})  # same canonical identity: linked patient id and/or directory id
    docs = await db.rx_transmissions.find(
        {"direction": "PHYSICIAN_TO_PHARMACY", "$or": [{"patient_id": {"$in": refs}}, {"patient_directory_id": {"$in": refs}}]}
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


# ============================================================================
# PHASE B — Staff/Admin Patient Portal Account Management
#   Manage a patient's PORTAL LOGIN only (users doc). Never touches the clinical
#   patient record, PIN, directory, or history. Practice-scoped and audited.
#   Current passwords are never shown; temp passwords are one-time + expiring.
# ============================================================================
ACCOUNT_MGMT_ROLES = ("admin", "staff")
TEMP_PASSWORD_TTL_HOURS = 72


async def _get_scoped_patient(patient_id: str, user: dict) -> dict:
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    assert_practice(p, user)
    return p


async def _portal_user_for_patient(patient_id: str):
    return await db.users.find_one({"patient_id": patient_id})


def _portal_account_status(u: dict) -> str:
    if not u.get("active", True):
        return "Disabled"
    if u.get("pending_activation"):
        return "Pending activation"
    if u.get("must_change_password"):
        return "Must change password"
    return "Active"


def _portal_account_public(u: dict) -> dict:
    return {
        "has_account": True,
        "user_id": str(u["_id"]),
        "login_email": u.get("email"),
        "name": u.get("name"),
        "role": u.get("role"),
        "status": _portal_account_status(u),
        "email_verified": bool(u.get("email_verified")),
        "active": u.get("active", True),
        "disabled": not u.get("active", True),
        "must_change_password": bool(u.get("must_change_password")),
        "pending_activation": bool(u.get("pending_activation")),
        "locked": bool(u.get("locked", False)),
        "last_login_at": u.get("last_login_at"),
        "temp_password_expires_at": u.get("temp_password_expires_at"),
    }


async def _issue_activation_email(uid: str, email: str, first_name: str, lang: str = "en"):
    """(Re)issue a single-use 72h set-password activation link and email it."""
    token = secrets.token_urlsafe(32)
    await db.account_activations.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "token_hash": authlib.hash_password(token),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(),
        "used": False, "created_at": now_iso(),
    }}, upsert=True)
    portal_url = (os.environ.get("APP_BASE_URL") or notify_svc.PORTAL_URL or "").strip().rstrip("/")
    if email and portal_url and portal_url.startswith("https://"):
        activate_url = f"{portal_url}/activate?uid={uid}&token={token}"
        await email_service.send_email(
            to=email,
            subject=email_service.subject("account_activation", lang),
            html=email_service.account_activation_html(first_name or "there", activate_url, lang=lang))
        return True
    return False


async def _patient_lang(u: dict) -> str:
    if u.get("patient_id"):
        pat = await db.patients.find_one({"id": u["patient_id"]}, {"preferred_language": 1})
        return email_service.norm_lang((pat or {}).get("preferred_language"))
    return "en"


@api.get("/internal/patients/{patient_id}/portal-account")
async def get_portal_account(patient_id: str, user: dict = Depends(require_roles(*ACCOUNT_MGMT_ROLES))):
    await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u:
        prior = await db.portal_account_archive.find_one({"patient_id": patient_id}, {"_id": 0}, sort=[("detached_at", -1)])
        return {"has_account": False, "patient_id": patient_id, "prior_account": prior}
    return _portal_account_public(u)


class PortalResetBody(BaseModel):
    reason: str
    confirm_text: str


PORTAL_RESET_CONFIRM = "RESET PORTAL"


async def _portal_reset_conflicts(patient_id: str, p: dict, u: dict) -> list:
    """Identity/link conflicts that make detaching unsafe. Empty list == safe."""
    issues = []
    if u.get("role") != "patient":
        issues.append(f"Login identity role is '{u.get('role')}', not a patient portal account.")
    if await db.users.count_documents({"patient_id": patient_id}) > 1:
        issues.append("More than one login identity is attached to this patient.")
    dirs = [d async for d in db.patient_directory.find({"linked_patient_id": patient_id}, {"id": 1, "visita_patient_id": 1, "patient_status": 1})]
    if len(dirs) > 1:
        issues.append("More than one directory record is linked to this patient.")
    if not dirs:
        issues.append("No directory record is linked to this patient, so a future re-registration could not be linked back to the same record.")
    elif p.get("matched_directory_id") and p["matched_directory_id"] != dirs[0]["id"]:
        issues.append("Patient's matched directory record differs from the directory record linked to it (half-link).")
    return issues


@api.post("/internal/patients/{patient_id}/portal-account/reset")
async def portal_account_reset(patient_id: str, body: PortalResetBody, user: dict = Depends(require_roles("admin"))):
    """Detach/archive the portal LOGIN identity only. Patient record, PIN, directory link,
    appointments, visits, Rx, results, referrals, delegates and audit history are untouched.
    The patient can re-register later and claim the SAME record (has_login=False claim path)."""
    p = await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u:
        raise HTTPException(status_code=404, detail="This patient has no portal account.")
    reason = (body.reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(status_code=422, detail="A reason (at least 5 characters) is required.")
    if body.confirm_text.strip() != PORTAL_RESET_CONFIRM:
        raise HTTPException(status_code=422, detail=f'Type "{PORTAL_RESET_CONFIRM}" to confirm.')
    conflicts = await _portal_reset_conflicts(patient_id, p, u)
    if conflicts:
        raise HTTPException(status_code=409, detail={"code": "REVIEW_REQUIRED", "issues": conflicts,
                                                     "message": "Reset not performed — identity/link review required."})
    uid = str(u["_id"])
    ts = now_iso()
    actor = {"id": user.get("id"), "name": user.get("name"), "role": user.get("role")}
    archive = {
        "id": str(uuid.uuid4()), "user_id": uid, "patient_id": patient_id,
        "visita_patient_id": p.get("visita_patient_id"), "login_email": u.get("email"), "name": u.get("name"),
        "email_verified": bool(u.get("email_verified")), "account_created_at": u.get("created_at"),
        "last_login_at": u.get("last_login_at"), "was_active": u.get("active", True),
        "detached_at": ts, "detached_by": actor, "reason": reason,
    }
    await db.portal_account_archive.insert_one(archive)
    # Detach credentials & linkage; release the login email; revoke sessions (active=False → 403 on every token).
    await db.users.update_one({"_id": u["_id"]}, {
        "$set": {"email": f"detached+{uid}@archived.vien.invalid", "password_hash": None, "active": False,
                 "patient_id": None, "detached_patient_id": patient_id, "portal_detached": True,
                 "detached_at": ts, "detached_by": actor, "detach_reason": reason, "archive_id": archive["id"],
                 "email_verified": False, "must_change_password": False, "updated_at": ts},
        "$unset": {"temp_password_expires_at": "", "pending_activation": ""},
    })
    await db.password_resets.delete_many({"user_id": uid})
    await db.account_activations.delete_many({"user_id": uid})
    await db.patients.update_one({"id": patient_id}, {"$set": {
        "has_login": False, "portal_status": "DETACHED", "portal_detached_at": ts, "updated_at": ts}})
    await audit("staff_reset_portal_account", "user", uid, user, meta={
        "patient_id": patient_id, "archive_id": archive["id"], "prior_login_email": archive["login_email"], "reason": reason})
    return {"ok": True, "has_account": False, "archive_id": archive["id"], "released_email": archive["login_email"]}


@api.post("/internal/patients/{patient_id}/portal-account/send-reset")
async def portal_account_send_reset(patient_id: str, user: dict = Depends(require_roles(*ACCOUNT_MGMT_ROLES))):
    await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u or not u.get("email"):
        raise HTTPException(status_code=400, detail="This patient has no portal login email.")
    code = f"{secrets.randbelow(1000000):06d}"
    lang = await _patient_lang(u)
    await db.password_resets.update_one({"user_id": str(u["_id"])}, {"$set": {
        "user_id": str(u["_id"]), "code_hash": authlib.hash_password(code),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "attempts": 0, "created_at": now_iso(),
    }}, upsert=True)
    try:
        await email_service.send_email(to=u["email"], subject=email_service.subject("reset_code", lang),
                                       html=email_service.reset_code_html(u.get("name"), code, lang=lang))
    except Exception:
        raise HTTPException(status_code=502, detail="We couldn't send the email right now. Please try again shortly.")
    await audit("staff_send_password_reset", "user", str(u["_id"]), user, meta={"patient_id": patient_id})
    return {"ok": True, "sent_to": u["email"]}


@api.post("/internal/patients/{patient_id}/portal-account/resend-verification")
async def portal_account_resend_verification(patient_id: str, user: dict = Depends(require_roles(*ACCOUNT_MGMT_ROLES))):
    await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u or not u.get("email"):
        raise HTTPException(status_code=400, detail="This patient has no portal login email.")
    if not u.get("pending_activation"):
        raise HTTPException(status_code=400, detail="This account is already activated. No verification link is needed.")
    lang = await _patient_lang(u)
    first = (u.get("name") or "").split(" ")[0]
    try:
        sent = await _issue_activation_email(str(u["_id"]), u["email"], first, lang)
    except Exception:
        raise HTTPException(status_code=502, detail="We couldn't send the email right now. Please try again shortly.")
    if not sent:
        raise HTTPException(status_code=502, detail="Activation link could not be generated (email not configured).")
    await audit("staff_resend_activation", "user", str(u["_id"]), user, meta={"patient_id": patient_id})
    return {"ok": True, "sent_to": u["email"]}


@api.post("/internal/patients/{patient_id}/portal-account/temp-password")
async def portal_account_temp_password(patient_id: str, user: dict = Depends(require_roles(*ACCOUNT_MGMT_ROLES))):
    await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u:
        raise HTTPException(status_code=404, detail="This patient has no portal account.")
    temp = _gen_temp_password()
    expires = (datetime.now(timezone.utc) + timedelta(hours=TEMP_PASSWORD_TTL_HOURS)).isoformat()
    await db.users.update_one({"_id": u["_id"]}, {"$set": {
        "password_hash": authlib.hash_password(temp),
        "must_change_password": True,
        "temp_password_expires_at": expires,
        "pending_activation": False,
        "password_rotated_at": now_iso(),
    }})
    await audit("staff_generate_temp_password", "user", str(u["_id"]), user, meta={"patient_id": patient_id})
    return {"ok": True, "temp_password": temp, "expires_at": expires,
            "must_change_password": True, "login_email": u.get("email")}


@api.post("/internal/patients/{patient_id}/portal-account/force-password-change")
async def portal_account_force_change(patient_id: str, user: dict = Depends(require_roles(*ACCOUNT_MGMT_ROLES))):
    await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u:
        raise HTTPException(status_code=404, detail="This patient has no portal account.")
    await db.users.update_one({"_id": u["_id"]}, {"$set": {"must_change_password": True, "updated_at": now_iso()}})
    await audit("staff_force_password_change", "user", str(u["_id"]), user, meta={"patient_id": patient_id})
    return {"ok": True, "must_change_password": True}


class StaffEmailChangeBody(BaseModel):
    new_email: EmailStr


@api.post("/internal/patients/{patient_id}/portal-account/email")
async def portal_account_change_email(patient_id: str, body: StaffEmailChangeBody,
                                      user: dict = Depends(require_roles(*ACCOUNT_MGMT_ROLES))):
    p = await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u:
        raise HTTPException(status_code=404, detail="This patient has no portal account.")
    new_email = body.new_email.lower().strip()
    old_email = u.get("email")
    if new_email == (old_email or "").lower():
        raise HTTPException(status_code=400, detail="That is already this patient's login email.")
    clash_u = await db.users.find_one({"email": new_email, "_id": {"$ne": u["_id"]}})
    clash_p = await db.patients.find_one({"email": new_email, "id": {"$ne": patient_id}})
    if clash_u or clash_p:
        raise HTTPException(status_code=409, detail="Another account already uses that email address.")
    await db.users.update_one({"_id": u["_id"]}, {"$set": {
        "email": new_email, "email_verified": False, "updated_at": now_iso()}})
    await db.patients.update_one({"id": patient_id}, {"$set": {"email": new_email, "updated_at": now_iso()}})
    await audit("staff_change_login_email", "user", str(u["_id"]), user,
                meta={"patient_id": patient_id, "old_email": old_email, "new_email": new_email})
    return {"ok": True, "login_email": new_email, "email_verified": False}


@api.post("/internal/patients/{patient_id}/portal-account/disable")
async def portal_account_disable(patient_id: str, user: dict = Depends(require_roles(*ACCOUNT_MGMT_ROLES))):
    await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u:
        raise HTTPException(status_code=404, detail="This patient has no portal account.")
    # Disable LOGIN only — patient record, PIN, directory link and history are untouched.
    await db.users.update_one({"_id": u["_id"]}, {"$set": {"active": False, "updated_at": now_iso()}})
    await audit("staff_disable_portal_access", "user", str(u["_id"]), user, meta={"patient_id": patient_id})
    return {"ok": True, "active": False}


@api.post("/internal/patients/{patient_id}/portal-account/enable")
async def portal_account_enable(patient_id: str, user: dict = Depends(require_roles(*ACCOUNT_MGMT_ROLES))):
    await _get_scoped_patient(patient_id, user)
    u = await _portal_user_for_patient(patient_id)
    if not u:
        raise HTTPException(status_code=404, detail="This patient has no portal account.")
    await db.users.update_one({"_id": u["_id"]}, {"$set": {"active": True, "updated_at": now_iso()}})
    await audit("staff_enable_portal_access", "user", str(u["_id"]), user, meta={"patient_id": patient_id})
    return {"ok": True, "active": True}


# ============================================================================
# PHYSICIAN — Patient Medical Record (read) + Medication Management (write)
#   Physician-only, practice-scoped. Reads only data that already exists in VIen.
#   Medication writes reuse the authoritative patient_medications / medication_catalog
#   / physician_rx_memory architecture. Discontinue != delete; history is preserved.
# ============================================================================
# ============= VISITS (UI: Encounter) — canonical clinical record, Phase 2A1 =============
VISIT_WRITE_ROLES = ("physician",)
VISIT_READ_ROLES = ("physician", "admin")


class VisitCreateBody(BaseModel):
    patient_ref: Optional[str] = None
    patient_id: Optional[str] = None
    directory_id: Optional[str] = None
    encounter_type: str
    appointment_id: Optional[str] = None
    reason: Optional[str] = None
    source: Optional[str] = "patients"


class VisitSoapBody(BaseModel):
    subjective: Optional[str] = None
    objective: Optional[str] = None
    assessment: Optional[str] = None
    plan: Optional[str] = None


async def _visit_identity_or_400(body_ref, patient_id, directory_id):
    ident = await visits_mod.resolve_identity(db, body_ref, patient_id, directory_id)
    if not ident:
        raise HTTPException(status_code=400, detail="Patient identity could not be resolved.")
    return ident


def _visit_snapshot(ident) -> dict:
    return _portal_patient_snapshot(ident["portal"]) if ident["portal"] else _directory_snapshot(ident["directory"])


async def _get_visit_scoped(visit_id: str, user: dict) -> dict:
    v = await db[visits_mod.COLL].find_one({"id": visit_id}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Not found.")
    assert_practice(v, user)
    if user["role"] == "physician" and v.get("physician_user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Not found.")
    return v


async def _get_visit_for_write(visit_id: str, user: dict) -> dict:
    """Scoped visit whose documentation is still open (IN_PROGRESS or STOPPED_UNSIGNED). SIGNED rejects every mutation (409 VISIT_SIGNED)."""
    v = await _get_visit_scoped(visit_id, user)
    if v.get("status") not in visits_mod.EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail=visits_mod.lock_error(v))
    return v


async def _get_visit_for_timer(visit_id: str, user: dict) -> dict:
    """Timer/lifecycle changes only while IN_PROGRESS. Stopped (409 VISIT_STOPPED) or signed (409 VISIT_SIGNED) never resume."""
    v = await _get_visit_scoped(visit_id, user)
    if v.get("status") != visits_mod.IN_PROGRESS:
        raise HTTPException(status_code=409, detail=visits_mod.lock_error(v))
    return v


def _lifecycle_meta(v: dict, user: dict, **extra) -> dict:
    return {"visit_id": v["id"], "ref_number": v.get("ref_number"), "patient_ref": v.get("patient_ref"), "practice_id": v.get("practice_id"),
            "actor_id": user["id"], "actor_name": user.get("name"), "actor_role": user.get("role"), "server_time": now_iso(), **extra}


async def _visit_context(ident) -> dict:
    pid, did = ident.get("patient_id"), ident.get("directory_id")
    ids = [x for x in (pid, did) if x]
    meds = await db.patient_medications.find({"patient_id": pid, "active": True}, {"_id": 0}).sort(
        "last_prescribed_at", -1).to_list(100) if pid else []
    appts = await db.appointment_requests.find(
        {"$or": [{"patient_id": {"$in": ids}}, {"directory_id": {"$in": ids}}],
         "status": {"$in": ["confirmed", "rescheduled", "completed", "no_show"]}},
        {"_id": 0, "ref_number": 1, "status": 1, "reason": 1, "appointment_type": 1,
         "slot_date": 1, "confirmed_date": 1, "slot_time": 1, "confirmed_slot_time": 1}).sort("created_at", -1).to_list(10)
    try:
        docs = await attach_mod.list_shared_for_patient(db, pid) if pid else []
    except Exception:
        docs = []
    return {"medications_active": [_med_public(m) for m in meds],
            "recent_appointments": [{**a, "date": a.get("slot_date") or a.get("confirmed_date"),
                                     "time": a.get("slot_time") or a.get("confirmed_slot_time")} for a in appts],
            "documents": docs,
            "diagnoses": None, "pmhx": None, "allergies": None}


@api.get("/internal/visits/active")
async def visit_active(patient_ref: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    ident = await _visit_identity_or_400(patient_ref, None, None)
    v = await visits_mod.find_active(db, user.get("practice_id"), ident["patient_ref"], user["id"])
    return {"active": visits_mod.history_row(v) if v else None, "patient_ref": ident["patient_ref"]}


@api.get("/internal/visits/ready")
async def visit_ready(patient_ref: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    """Enter-Encounter workspace shell: identity + context + this physician's open visit (if any). Creates nothing."""
    ident = await _visit_identity_or_400(patient_ref, None, None)
    v = await visits_mod.find_active(db, user.get("practice_id"), ident["patient_ref"], user["id"])
    snap = _visit_snapshot(ident)
    return {"patient_ref": ident["patient_ref"], "patient_id": ident["patient_id"], "directory_id": ident["directory_id"],
            "patient_snapshot": {k: snap.get(k) for k in visits_mod.SNAPSHOT_FIELDS}, "visita_patient_id": snap.get("visita_patient_id"),
            "physician_name": user.get("name"), "context": await _visit_context(ident),
            "active": {"id": v["id"], "ref_number": v.get("ref_number"), **visits_mod.timer_of(v)} if v else None,
            "server_time": now_iso()}


@api.post("/internal/visits")
async def visit_create(body: VisitCreateBody, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    if body.encounter_type not in visits_mod.ENCOUNTER_TYPES:
        raise HTTPException(status_code=400, detail="Invalid encounter type.")
    ident = await _visit_identity_or_400(body.patient_ref, body.patient_id, body.directory_id)
    practice_id = user.get("practice_id")
    appointment = None
    if body.appointment_id:
        appointment = await db.appointment_requests.find_one({"id": body.appointment_id}, {"_id": 0, "id": 1, "ref_number": 1, "practice_id": 1})
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found.")
        assert_practice(appointment, user)
    existing = await visits_mod.find_active(db, practice_id, ident["patient_ref"], user["id"])
    if existing:
        await audit("visit_start_blocked_active_exists", "visit", existing["id"], user,
                    meta={"patient_ref": ident["patient_ref"], "ref_number": existing.get("ref_number")})
        raise HTTPException(status_code=409, detail={"message": "An encounter is already in progress for this patient.",
                                                     "visit_id": existing["id"], "ref_number": existing.get("ref_number")})
    snap = _visit_snapshot(ident)
    prof = await db.professionals.find_one({"linked_user_id": user["id"]}, {"_id": 0, "id": 1})
    try:
        v = await visits_mod.create(
            db, practice_id=practice_id, identity=ident, snapshot=snap, visita_patient_id=snap.get("visita_patient_id"),
            user=user, professional_id=(prof or {}).get("id"), encounter_type=body.encounter_type,
            reason=(body.reason or "").strip() or None, appointment=appointment,
            source="calendar" if body.source == "calendar" else "patients", ref_number=await next_ref("VIS"))
    except visits_mod.ActiveVisitExists as e:
        ex = e.visit or {}
        await audit("visit_start_blocked_active_exists", "visit", ex.get("id"), user, meta={"patient_ref": ident["patient_ref"]})
        raise HTTPException(status_code=409, detail={"message": "An encounter is already in progress for this patient.",
                                                     "visit_id": ex.get("id"), "ref_number": ex.get("ref_number")})
    await audit("visit_created", "visit", v["id"], user, new_status=v["status"],
                meta={"ref_number": v["ref_number"], "patient_ref": v["patient_ref"], "encounter_type": v["encounter_type"],
                      "appointment_id": v["appointment_id"], "source": v["source"]})
    await audit("visit_started", "visit", v["id"], user, new_status=v["status"],
                meta=_lifecycle_meta(v, user, started_at=v["started_at"], encounter_type=v["encounter_type"], resulting_status=v["status"]))
    return v


@api.get("/internal/visits/{visit_id}")
async def visit_get(visit_id: str, user: dict = Depends(require_visit_access(*VISIT_READ_ROLES))):
    v = await _get_visit_scoped(visit_id, user)
    ident = await visits_mod.resolve_identity(db, v["patient_ref"], v.get("patient_id"), v.get("directory_id"))
    ctx = await _visit_context(ident) if ident else {}
    await audit("visit_read", "visit", v["id"], user, meta={"patient_ref": v["patient_ref"], "ref_number": v.get("ref_number")})
    return {**v, "vitals": {**visits_mod.EMPTY_VITALS, **(v.get("vitals") or {})}, **visits_mod.timer_of(v), "context": ctx, "server_time": now_iso()}


@api.get("/internal/visits/{visit_id}/record")
async def visit_record(visit_id: str, user: dict = Depends(require_visit_access(*VISIT_READ_ROLES))):
    """Visit Hx read-only record. GET only — there are no historical mutation endpoints."""
    v = await _get_visit_scoped(visit_id, user)
    await audit("visit_read", "visit", v["id"], user, meta={"patient_ref": v["patient_ref"], "ref_number": v.get("ref_number"), "via": "visit_hx"})
    return visits_mod.read_only_record(v)


@api.patch("/internal/visits/{visit_id}/soap")
async def visit_save_soap(visit_id: str, body: VisitSoapBody, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    v = await _get_visit_for_write(visit_id, user)
    changed, v2 = await visits_mod.save_soap(db, v, body.model_dump(), user)
    if changed:
        await audit("visit_soap_saved", "visit", v["id"], user,
                    meta={"fields_changed": changed, "save_count": v2.get("save_count"), "saved_at": v2.get("last_saved_at")})
    return {"id": v2["id"], "last_saved_at": v2.get("last_saved_at"), "save_count": v2.get("save_count"),
            "changed": changed, "noop": not changed}


@api.patch("/internal/visits/{visit_id}/vitals")
async def visit_save_vitals(visit_id: str, body: dict, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    v = await _get_visit_for_write(visit_id, user)
    unknown = set(body) - set(visits_mod.VITAL_FIELDS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown vitals field(s): {', '.join(sorted(unknown))}")
    try:
        changed, v2 = await visits_mod.save_vitals(db, v, body, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if changed:
        await audit("visit_vitals_saved", "visit", v["id"], user,
                    meta={"fields_changed": changed, "updated_at": v2["vitals"]["updated_at"]})
    return {"id": v2["id"], "vitals": {**visits_mod.EMPTY_VITALS, **(v2.get("vitals") or {})}, "changed": changed, "noop": not changed}


@api.post("/internal/visits/{visit_id}/exit")
async def visit_exit(visit_id: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    v = await _get_visit_scoped(visit_id, user)
    now = now_iso()
    await db[visits_mod.COLL].update_one({"id": visit_id}, {"$set": {
        "exited_at": now, "updated_at": now, "updated_by": {"id": user["id"], "name": user.get("name")}}})
    await audit("visit_exited", "visit", visit_id, user, meta={"ref_number": v.get("ref_number"), "started_at": v.get("started_at")})
    return {"id": visit_id, "status": v["status"], "exited_at": now}


@api.post("/internal/visits/{visit_id}/stop")
async def visit_stop(visit_id: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    """FINAL stop of the encounter: freezes time, status STOPPED_UNSIGNED. Irreversible (no resume). Documentation stays editable. Does NOT sign."""
    v = await _get_visit_for_timer(visit_id, user)
    before = visits_mod.timer_of(v)["timer_state"]
    sets = await visits_mod.stop_final(db, v, user)
    if not sets:
        raise HTTPException(status_code=409, detail=visits_mod.lock_error(await _get_visit_scoped(visit_id, user)))
    await audit("visit_stopped", "visit", visit_id, user, old_status=v["status"], new_status=sets["status"],
                meta=_lifecycle_meta(v, user, stopped_at=sets["stopped_at"], elapsed_seconds=sets["elapsed_seconds"], timer_before=before, resulting_status=sets["status"]))
    return {"id": visit_id, "status": sets["status"], "stopped_at": sets["stopped_at"], **{k: sets[k] for k in visits_mod.TIMER_FIELDS}, "server_time": now_iso()}


@api.post("/internal/visits/{visit_id}/resume")
async def visit_resume(visit_id: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    """Compatibility only for legacy PAUSED visits that are still IN_PROGRESS. Stopped/signed visits can never be resumed."""
    v = await _get_visit_for_timer(visit_id, user)
    before = visits_mod.timer_of(v)["timer_state"]
    t = await visits_mod.timer_resume(db, v, user)
    if before != t["timer_state"]:
        await audit("visit_timer_resumed", "visit", visit_id, user, old_status=before, new_status=t["timer_state"],
                    meta={"ref_number": v.get("ref_number"), "elapsed_seconds": t["elapsed_seconds"]})
    return {"id": visit_id, "status": v["status"], **t, "resumed_at": now_iso(), "server_time": now_iso()}


@api.post("/internal/visits/{visit_id}/sign")
async def visit_sign(visit_id: str, user: dict = Depends(require_visit_access("physician"))):
    """Physician-only. STOPPED_UNSIGNED -> SIGNED using the authenticated identity; snapshot = exact reviewed state at this moment."""
    v = await _get_visit_scoped(visit_id, user)
    if v.get("status") == visits_mod.SIGNED:
        raise HTTPException(status_code=409, detail=visits_mod.lock_error(v))
    if v.get("status") not in visits_mod.UNSIGNED_STOPPED:
        raise HTTPException(status_code=409, detail={"code": "VISIT_NOT_STOPPED", "status": v.get("status"), "message": "Stop the visit before signing."})
    if v.get("physician_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Only the encounter physician can sign this visit.")
    prof = await db.professionals.find_one({"linked_user_id": user["id"]}, {"_id": 0, "id": 1})
    sets = await visits_mod.sign(db, v, user, (prof or {}).get("id"))
    if not sets:
        raise HTTPException(status_code=409, detail=visits_mod.lock_error(await _get_visit_scoped(visit_id, user)))
    await audit("visit_signed", "visit", visit_id, user, old_status=v["status"], new_status=sets["status"],
                meta=_lifecycle_meta(v, user, signed_at=sets["signed_at"], signed_by=sets["signed_by"], signed_snapshot_version=sets["signed_snapshot_version"],
                                     signed_snapshot_hash=sets["signed_snapshot_hash"], resulting_status=sets["status"]))
    return {"id": visit_id, "status": sets["status"], "signed_at": sets["signed_at"], "signed_by": sets["signed_by"],
            "signed_snapshot_version": sets["signed_snapshot_version"], "signed_snapshot_hash": sets["signed_snapshot_hash"], "server_time": now_iso()}


@api.get("/internal/patients/{patient_ref}/visits")
async def visit_history(patient_ref: str, exclude_visit_id: Optional[str] = None, user: dict = Depends(require_visit_access(*VISIT_READ_ROLES))):
    ident = await _visit_identity_or_400(patient_ref, None, None)
    q = {"practice_id": user.get("practice_id"), "patient_ref": {"$in": visits_mod.all_refs(ident)}}
    if exclude_visit_id:
        q["id"] = {"$ne": exclude_visit_id}
    if user["role"] == "physician":
        q["physician_user_id"] = user["id"]
    rows = await db[visits_mod.COLL].find(q, {"_id": 0}).sort("started_at", -1).to_list(200)
    return {"patient_ref": ident["patient_ref"], "visits": [visits_mod.history_row(v) for v in rows]}


@api.get("/internal/patients/{patient_ref}/issue-plan-history")
async def visit_issue_plan_history(patient_ref: str, search: str = "", exclude: Optional[str] = None,
                                   user: dict = Depends(require_visit_access(*VISIT_READ_ROLES))):
    """Read-only Issue (Assessment) / Plan history across the patient's canonical identity, most recent first."""
    ident = await _visit_identity_or_400(patient_ref, None, None)
    q = {"practice_id": user.get("practice_id"), "patient_ref": {"$in": visits_mod.all_refs(ident)}}
    if user["role"] == "physician":
        q["physician_user_id"] = user["id"]
    if exclude:
        q["id"] = {"$ne": exclude}
    q["$or"] = [{"soap.assessment": {"$nin": [None, ""]}}, {"soap.plan": {"$nin": [None, ""]}}]
    if search.strip():
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        q = {"$and": [q, {"$or": [{"soap.assessment": rx}, {"soap.plan": rx}, {"started_at": rx}, {"ref_number": rx}]}]}
    rows = await db[visits_mod.COLL].find(q, {"_id": 0, "id": 1, "ref_number": 1, "started_at": 1, "status": 1,
                                             "encounter_type": 1, "physician_name": 1, "soap.assessment": 1, "soap.plan": 1}).sort("started_at", -1).to_list(100)
    return {"patient_ref": ident["patient_ref"], "entries": [
        {"visit_id": r["id"], "ref_number": r.get("ref_number"), "date": (r.get("started_at") or "")[:10], "status": r.get("status"),
         "encounter_type": r.get("encounter_type"), "physician_name": r.get("physician_name"),
         "issue": (r.get("soap") or {}).get("assessment") or "", "plan": (r.get("soap") or {}).get("plan") or ""} for r in rows]}


@api.get("/internal/patients/{patient_ref}/metrics-summary")
async def patient_metrics_summary(patient_ref: str, user: dict = Depends(require_visit_access(*VISIT_READ_ROLES))):
    """Longitudinal METRICS (Recent / 3 mo / 12 mo / global means) from canonical visit vitals; daily-deduplicated."""
    ident = await _visit_identity_or_400(patient_ref, None, None)
    q = {"practice_id": user.get("practice_id"), "patient_ref": {"$in": visits_mod.all_refs(ident)},
         "$or": [{f"vitals.{k}": {"$ne": None}} for k in visits_mod.VITAL_FIELDS]}
    rows = await db[visits_mod.COLL].find(q, {"_id": 0, "id": 1, "started_at": 1, "vitals": 1}).to_list(2000)
    return {"patient_ref": ident["patient_ref"], **metrics_mod.summarize(rows)}


@api.get("/internal/patients/{patient_ref}/recent-vitals")
async def visit_recent_vitals(patient_ref: str, limit: int = 3, exclude: Optional[str] = None,
                              user: dict = Depends(require_visit_access(*VISIT_READ_ROLES))):
    """Compact read-only vitals of the most recent historical visits that contain vitals (newest first)."""
    ident = await _visit_identity_or_400(patient_ref, None, None)
    limit = max(1, min(limit, 10))
    q = {"practice_id": user.get("practice_id"), "patient_ref": {"$in": visits_mod.all_refs(ident)},
         "$or": [{f"vitals.{k}": {"$ne": None}} for k in visits_mod.VITAL_FIELDS]}
    if user["role"] == "physician":
        q["physician_user_id"] = user["id"]
    if exclude:
        q["id"] = {"$ne": exclude}
    proj = {"_id": 0, "id": 1, "ref_number": 1, "started_at": 1, **{f"vitals.{k}": 1 for k in (*visits_mod.VITAL_FIELDS, "bmi")}}
    rows = await db[visits_mod.COLL].find(q, proj).sort("started_at", -1).to_list(limit)
    return {"patient_ref": ident["patient_ref"], "visits": [
        {"visit_id": r["id"], "ref_number": r.get("ref_number"), "started_at": r.get("started_at"),
         **{k: (r.get("vitals") or {}).get(k) for k in (*visits_mod.VITAL_FIELDS, "bmi")}} for r in rows]}


MED_RECORD_ROLES = ("admin", "physician")


# ============= CLINICAL HISTORY (PMHx / PSHx / Allergies) — Phase 2A4A =============
HISTORY_READ_ROLES = CLINIC_ROLES  # staff/admin read-only; physicians write


async def _history_list(domain, patient_ref, user):
    ident = await _visit_identity_or_400(patient_ref, None, None)
    rows = await history_mod.list_records(db, domain, user.get("practice_id"), visits_mod.all_refs(ident))
    return {"patient_ref": ident["patient_ref"], "items": rows}


async def _history_create(domain, patient_ref, body, user):
    ident = await _visit_identity_or_400(patient_ref, None, None)
    snap = _visit_snapshot(ident)
    try:
        doc = await history_mod.create(db, domain, practice_id=user.get("practice_id"), identity=ident,
                                       visita_patient_id=snap.get("visita_patient_id"), body=body, user=user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ent = history_mod.DOMAINS[domain]["entity"]
    await audit(f"{ent}_created", ent, doc["id"], user, new_status=doc["status"], meta={"patient_ref": doc["patient_ref"]})
    return doc


async def _history_patch(domain, patient_ref, record_id, body, user):
    ident = await _visit_identity_or_400(patient_ref, None, None)
    d = history_mod.DOMAINS[domain]
    rec = await db[d["coll"]].find_one({"id": record_id, "patient_ref": {"$in": visits_mod.all_refs(ident)}}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found.")
    assert_practice(rec, user)
    try:
        changed, old_s, new_s, doc = await history_mod.patch(db, domain, rec, body, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ent = d["entity"]
    if changed:
        meta = {"patient_ref": doc["patient_ref"], "fields_changed": changed}
        if old_s != new_s:
            ev = f"{ent}_archived" if new_s == "ARCHIVED" else f"{ent}_status_changed"
            await audit(ev, ent, doc["id"], user, old_status=old_s, new_status=new_s, meta=meta)
        if [c for c in changed if c != "status"]:
            await audit(f"{ent}_updated", ent, doc["id"], user, meta=meta)
    return {**doc, "changed": changed}


@api.get("/internal/patients/{patient_ref}/conditions")
async def conditions_list(patient_ref: str, user: dict = Depends(require_roles(*HISTORY_READ_ROLES))):
    return await _history_list("conditions", patient_ref, user)


# ============= ANNUAL EXAM MONTH (Visit New) — canonical on patient_directory; never auto-set from visit date =============
ANNUAL_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def _annual_out(ident):
    d = ident.get("directory") or {}
    return {"patient_ref": ident["patient_ref"], "annual_exam_month": d.get("annual_exam_month"), "editable": bool(ident.get("directory_id")),
            "source": (d.get("annual_exam_month_source") or {}).get("source_type"), "updated_at": d.get("annual_exam_month_updated_at")}


@api.get("/internal/patients/{patient_ref}/annual-exam-month")
async def annual_exam_month_get(patient_ref: str, user: dict = Depends(require_roles(*HISTORY_READ_ROLES))):
    ident = await _visit_identity_or_400(patient_ref, None, None)
    return _annual_out(ident)


class AnnualMonthBody(BaseModel):
    annual_exam_month: Optional[str] = None


@api.put("/internal/patients/{patient_ref}/annual-exam-month")
async def annual_exam_month_set(patient_ref: str, body: AnnualMonthBody, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    ident = await _visit_identity_or_400(patient_ref, None, None)
    if not ident.get("directory_id"):
        raise HTTPException(status_code=409, detail="Patient has no canonical directory record yet; Annual month cannot be stored.")
    if body.annual_exam_month is not None and body.annual_exam_month not in ANNUAL_MONTHS:
        raise HTTPException(status_code=422, detail="Invalid month.")
    before = (ident.get("directory") or {}).get("annual_exam_month")
    now = datetime.now(timezone.utc).isoformat()
    actor = {"id": user["id"], "name": user.get("name")}
    await db.patient_directory.update_one({"id": ident["directory_id"]}, {"$set": {
        "annual_exam_month": body.annual_exam_month, "annual_exam_month_updated_at": now, "annual_exam_month_updated_by": actor,
        "annual_exam_month_source": {"source_type": "PHYSICIAN_EDIT", "at": now, "by": actor}, "updated_at": now}})
    await audit("annual_exam_month_set", "patient_directory", ident["directory_id"], user, meta={"from": before, "to": body.annual_exam_month, "patient_ref": ident["patient_ref"]})
    ident["directory"] = await db.patient_directory.find_one({"id": ident["directory_id"]}, {"_id": 0})
    return _annual_out(ident)


@api.post("/internal/patients/{patient_ref}/conditions")
async def conditions_create(patient_ref: str, body: dict, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    return await _history_create("conditions", patient_ref, body, user)


@api.patch("/internal/patients/{patient_ref}/conditions/{record_id}")
async def conditions_patch(patient_ref: str, record_id: str, body: dict, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    return await _history_patch("conditions", patient_ref, record_id, body, user)


@api.get("/internal/patients/{patient_ref}/surgeries")
async def surgeries_list(patient_ref: str, user: dict = Depends(require_roles(*HISTORY_READ_ROLES))):
    return await _history_list("surgeries", patient_ref, user)


@api.post("/internal/patients/{patient_ref}/surgeries")
async def surgeries_create(patient_ref: str, body: dict, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    return await _history_create("surgeries", patient_ref, body, user)


@api.patch("/internal/patients/{patient_ref}/surgeries/{record_id}")
async def surgeries_patch(patient_ref: str, record_id: str, body: dict, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    return await _history_patch("surgeries", patient_ref, record_id, body, user)


@api.get("/internal/patients/{patient_ref}/allergies")
async def allergies_list(patient_ref: str, user: dict = Depends(require_roles(*HISTORY_READ_ROLES))):
    return await _history_list("allergies", patient_ref, user)


@api.post("/internal/patients/{patient_ref}/allergies")
async def allergies_create(patient_ref: str, body: dict, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    return await _history_create("allergies", patient_ref, body, user)


@api.patch("/internal/patients/{patient_ref}/allergies/{record_id}")
async def allergies_patch(patient_ref: str, record_id: str, body: dict, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    return await _history_patch("allergies", patient_ref, record_id, body, user)


# ============= SOAP HELPERS (read/search for Encounter use) — Phase 2A3 =============
@api.get("/internal/soap-helpers")
async def soap_helpers_search(search: str = "", patient_ref: Optional[str] = None, visit_id: Optional[str] = None,
                              user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    """Templates filtered by patient sex AND the canonical Visit's encounter_type (visit_id) — suggestions only."""
    sex = None
    if patient_ref:
        ident = await visits_mod.resolve_identity(db, patient_ref, None, None)
        sex = helpers_mod.patient_sex(ident)
    encounter_type = None
    if visit_id:
        v = await _get_visit_scoped(visit_id, user)
        encounter_type = v.get("encounter_type")
    prof = helpers_mod.profile_for(encounter_type)
    res = await helpers_mod.search(db, user, search, sex, encounter_type=encounter_type)
    return {"helpers": res["items"], "sex_hidden_count": res["sex_hidden_count"], "patient_sex": sex,
            "encounter_type": encounter_type, "template_profile": {"key": prof["key"], "label": prof["label"], "show": list(prof["show"])}}


# ============= DIAGNOSIS (tabDiagCode catalog + structured per-Visit diagnosis) — explicit selection only =============
@api.get("/internal/diagnosis-catalog/search")
async def diagnosis_catalog_search(q: str = "", user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return {"items": await dx_mod.search(db, q)}


@api.get("/internal/visits/{visit_id}/diagnoses/previous")
async def visit_previous_diagnoses(visit_id: str, user: dict = Depends(require_visit_access(*VISIT_READ_ROLES))):
    v = await _get_visit_scoped(visit_id, user)
    ident = await visits_mod.resolve_identity(db, v["patient_ref"], v.get("patient_id"), v.get("directory_id"))
    refs = visits_mod.all_refs(ident) if ident else [v["patient_ref"]]
    return {"items": await dx_mod.previous_for_patient(db, v["practice_id"], refs, exclude_visit_id=v["id"])}


class DiagnosisSelectBody(BaseModel):
    catalog_id: str
    source: str = "CATALOG"


@api.put("/internal/visits/{visit_id}/diagnoses/primary")
async def visit_set_primary_diagnosis(visit_id: str, body: DiagnosisSelectBody, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    v = await _get_visit_for_write(visit_id, user)
    if body.source not in ("CATALOG", "PATIENT_HISTORY"):
        raise HTTPException(status_code=422, detail="Invalid source.")
    dx = await dx_mod.set_primary(db, v, body.catalog_id, body.source, user)
    if dx is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found in catalog.")
    await audit("visit_diagnosis_set", "visit", v["id"], user, meta={"catalog_id": body.catalog_id, "source": body.source})
    return {"diagnoses": dx}


@api.delete("/internal/visits/{visit_id}/diagnoses/primary")
async def visit_clear_primary_diagnosis(visit_id: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    v = await _get_visit_for_write(visit_id, user)
    await dx_mod.clear(db, v, user)
    await audit("visit_diagnosis_cleared", "visit", v["id"], user)
    return {"diagnoses": []}


# ============= SERVICE / CODING (tabBillCode catalog → visits.service) — explicit selection only, no fees =============
# ============= AUDIT & COMPLIANCE — READ ONLY (admin + physician, practice-scoped). No mutation endpoints exist. =============
AUDIT_ROLES = ("admin", "physician")


@api.get("/internal/audit")
async def audit_list(date_from: Optional[str] = None, date_to: Optional[str] = None, patient_ref: Optional[str] = None, visit_ref: Optional[str] = None,
                     actor: Optional[str] = None, action: Optional[str] = None, module: Optional[str] = None, visit_status: Optional[str] = None,
                     page: int = 1, page_size: int = 50, user: dict = Depends(require_roles(*AUDIT_ROLES))):
    return await audit_mod.list_events(db, user, date_from=date_from, date_to=date_to, patient_ref=patient_ref, visit_ref=visit_ref, actor=actor,
                                       action=action, module=module, visit_status=visit_status, page=page, page_size=page_size)


@api.get("/internal/audit/visit/{visit_id}")
async def audit_visit_timeline(visit_id: str, user: dict = Depends(require_roles(*AUDIT_ROLES))):
    out = await audit_mod.visit_timeline(db, user, visit_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return out


@api.get("/internal/audit/{audit_id}")
async def audit_get(audit_id: str, user: dict = Depends(require_roles(*AUDIT_ROLES))):
    out = await audit_mod.get_event(db, user, audit_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return out


@api.get("/internal/service-catalog")
async def service_catalog_list(user: dict = Depends(require_roles(*CLINIC_ROLES))):
    return {"items": await svc_mod.list_active(db)}


class ServiceSelectBody(BaseModel):
    catalog_id: str


@api.post("/internal/visits/{visit_id}/service/select")
async def visit_service_select(visit_id: str, body: ServiceSelectBody, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    v = await _get_visit_for_write(visit_id, user)
    svc = await svc_mod.select(db, v, body.catalog_id, user)
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found in catalog.")
    await audit("visit_service_select", "visit", v["id"], user, meta={"catalog_id": body.catalog_id})
    return {"service": svc}


@api.delete("/internal/visits/{visit_id}/service/primary")
async def visit_service_clear_primary(visit_id: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    v = await _get_visit_for_write(visit_id, user)
    svc = await svc_mod.remove(db, v, None, user)
    await audit("visit_service_clear_primary", "visit", v["id"], user)
    return {"service": svc}


@api.delete("/internal/visits/{visit_id}/service/additional/{catalog_id}")
async def visit_service_remove_additional(visit_id: str, catalog_id: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    v = await _get_visit_for_write(visit_id, user)
    svc = await svc_mod.remove(db, v, catalog_id, user)
    await audit("visit_service_remove_additional", "visit", v["id"], user, meta={"catalog_id": catalog_id})
    return {"service": svc}


@api.get("/internal/soap-helpers/{helper_id}")
async def soap_helper_get(helper_id: str, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    h = await helpers_mod.get(db, user, helper_id)
    if not h:
        raise HTTPException(status_code=404, detail="Not found.")
    return h


class HelperUsedBody(BaseModel):
    helper_id: str
    sections_inserted: List[str]


@api.post("/internal/visits/{visit_id}/helper-used")
async def visit_helper_used(visit_id: str, body: HelperUsedBody, user: dict = Depends(require_visit_access(*VISIT_WRITE_ROLES))):
    """Audit-only: records that a helper's text was explicitly inserted. Note text itself flows through PATCH /soap."""
    v = await _get_visit_for_write(visit_id, user)
    h = await helpers_mod.get(db, user, body.helper_id)
    if not h:
        raise HTTPException(status_code=404, detail="Helper not found.")
    sections = [s for s in body.sections_inserted if s in visits_mod.SOAP_FIELDS]
    await audit("soap_helper_used", "visit", v["id"], user,
                meta={"helper_id": h["id"], "helper_key": h.get("key"), "sections_inserted": sections, "visit_id": v["id"]})
    return {"ok": True}


def _med_public(d: dict) -> dict:
    d = {k: v for k, v in d.items() if k != "_id"}
    d["strength_display"] = _med_strength_display(d)
    return d


@api.get("/internal/patients/{patient_id}/medical-record")
async def patient_medical_record(patient_id: str, user: dict = Depends(require_roles(*MED_RECORD_ROLES))):
    p = await _get_scoped_patient(patient_id, user)
    summary = _portal_patient_snapshot(p)
    appts = await db.appointment_requests.find(
        {"patient_id": patient_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    encounters = [{
        "id": a.get("id"), "ref_number": a.get("ref_number"),
        "status": a.get("status"), "reason": a.get("reason"),
        "label": a.get("label") or a.get("display"),
        "date": a.get("confirmed_date") or a.get("requested_date") or a.get("date"),
        "time": a.get("confirmed_time") or a.get("requested_time") or a.get("time"),
        "source_type": a.get("source_type"), "created_at": a.get("created_at"),
    } for a in appts]
    meds_active = await db.patient_medications.find(
        {"patient_id": patient_id, "active": True}, {"_id": 0}).sort("last_prescribed_at", -1).to_list(200)
    meds_discontinued = await db.patient_medications.find(
        {"patient_id": patient_id, "active": False}, {"_id": 0}).sort("updated_at", -1).to_list(200)
    try:
        documents = await attach_mod.list_shared_for_patient(db, patient_id)
    except Exception:
        documents = []
    return {
        "patient_id": patient_id,
        "summary": summary,
        "encounters": encounters,
        "medications": {
            "active": [_med_public(m) for m in meds_active],
            "discontinued": [_med_public(m) for m in meds_discontinued],
        },
        "documents": documents,
    }


_MED_FIELDS = ("drug", "action", "strength", "unit", "form", "attributes", "sig", "quantity",
               "quantity_unit", "route", "duration_value", "duration_unit", "concentration",
               "prn_reason", "eye", "ear", "interval", "site", "device", "brand", "generic",
               "din", "manufacturer", "additional_instructions", "note", "months", "refills")


class MedWriteBody(BaseModel):
    drug: Optional[str] = None
    action: Optional[str] = None
    strength: Optional[str] = None
    unit: Optional[str] = None
    form: Optional[str] = None
    attributes: Optional[List[str]] = None
    sig: Optional[str] = None
    quantity: Optional[str] = None
    quantity_unit: Optional[str] = None
    route: Optional[str] = None
    duration_value: Optional[str] = None
    duration_unit: Optional[str] = None
    concentration: Optional[str] = None
    prn_reason: Optional[str] = None
    eye: Optional[str] = None
    ear: Optional[str] = None
    interval: Optional[str] = None
    site: Optional[str] = None
    device: Optional[str] = None
    brand: Optional[str] = None
    generic: Optional[str] = None
    din: Optional[str] = None
    manufacturer: Optional[str] = None
    additional_instructions: Optional[str] = None
    note: Optional[str] = None
    months: Optional[int] = None
    refills: Optional[int] = None


class MedActionBody(MedWriteBody):
    action_type: str  # continue | edit | discontinue


async def _remember_med_catalog(m: dict):
    now = now_iso()
    ckey = "|".join([(m.get("drug") or "").lower().strip(), (m.get("strength") or "").lower().strip(),
                     (m.get("form") or "").lower().strip()])
    await db.medication_catalog.update_one({"catalog_key": ckey}, {
        "$setOnInsert": {"id": str(uuid.uuid4()), "catalog_key": ckey, "drug": m.get("drug"),
                         "strength": m.get("strength"), "unit": m.get("unit"),
                         "form": m.get("form"), "attributes": m.get("attributes") or [],
                         "created_at": now},
        "$set": {"updated_at": now}}, upsert=True)


@api.post("/internal/patients/{patient_id}/medications")
async def physician_add_medication(patient_id: str, body: MedWriteBody,
                                   user: dict = Depends(require_roles(*MED_RECORD_ROLES))):
    """Physician adds an authoritative medication to the patient's active list."""
    await _get_scoped_patient(patient_id, user)
    if not (body.drug or "").strip():
        raise HTTPException(status_code=400, detail="A medication name is required.")
    now = now_iso()
    m = {k: getattr(body, k) for k in _MED_FIELDS}
    m["attributes"] = m.get("attributes") or []
    key = _regimen_key(patient_id, m)
    event = {"action": "added", "at": now, "by": user["name"], "by_role": user["role"]}
    existing = await db.patient_medications.find_one({"regimen_key": key})
    if existing:
        await db.patient_medications.update_one({"regimen_key": key}, {
            "$set": {**{k: m[k] for k in _MED_FIELDS}, "active": True, "source": "physician_manual",
                     "last_prescribed_at": now, "discontinued_at": None, "updated_at": now},
            "$push": {"history": event}})
        med_id = existing["id"]
    else:
        med_id = str(uuid.uuid4())
        await db.patient_medications.insert_one({
            "id": med_id, "regimen_key": key, "patient_id": patient_id,
            **{k: m[k] for k in _MED_FIELDS},
            "source": "physician_manual", "active": True,
            "last_prescribed_at": now, "last_tx_id": None,
            "history": [event], "created_at": now, "updated_at": now})
    await _remember_med_catalog(m)
    await _remember_physician_rx(user["id"], [m])
    await audit("medication_added", "patient_medication", med_id, user,
                meta={"patient_id": patient_id, "drug": m.get("drug")})
    fresh = await db.patient_medications.find_one({"id": med_id}, {"_id": 0})
    return _med_public(fresh)


@api.patch("/internal/patients/{patient_id}/medications/{med_id}")
async def physician_update_medication(patient_id: str, med_id: str, body: MedActionBody,
                                      user: dict = Depends(require_roles(*MED_RECORD_ROLES))):
    """Continue / Edit / Discontinue an existing medication. History is preserved;
    discontinue sets active=False (never deletes)."""
    await _get_scoped_patient(patient_id, user)
    med = await db.patient_medications.find_one({"id": med_id, "patient_id": patient_id})
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found for this patient.")
    now = now_iso()
    act = (body.action_type or "").strip()
    if act == "discontinue":
        event = {"action": "discontinued", "at": now, "by": user["name"], "by_role": user["role"],
                 "note": (body.note or None)}
        await db.patient_medications.update_one({"id": med_id}, {
            "$set": {"active": False, "discontinued_at": now, "discontinued_by": user["name"], "updated_at": now},
            "$push": {"history": event}})
        await audit("medication_discontinued", "patient_medication", med_id, user,
                    meta={"patient_id": patient_id, "drug": med.get("drug")})
    elif act == "continue":
        event = {"action": "continued", "at": now, "by": user["name"], "by_role": user["role"]}
        await db.patient_medications.update_one({"id": med_id}, {
            "$set": {"active": True, "discontinued_at": None, "last_prescribed_at": now, "updated_at": now},
            "$push": {"history": event}})
        await audit("medication_continued", "patient_medication", med_id, user,
                    meta={"patient_id": patient_id, "drug": med.get("drug")})
    elif act == "edit":
        provided = {k: getattr(body, k) for k in _MED_FIELDS if getattr(body, k) is not None}
        if not provided:
            raise HTTPException(status_code=400, detail="No changes were provided.")
        previous = {k: med.get(k) for k in provided}
        event = {"action": "edited", "at": now, "by": user["name"], "by_role": user["role"],
                 "previous": previous, "new": provided}
        await db.patient_medications.update_one({"id": med_id}, {
            "$set": {**provided, "active": True, "updated_at": now},
            "$push": {"history": event}})
        merged = {**med, **provided}
        await _remember_med_catalog(merged)
        await _remember_physician_rx(user["id"], [merged])
        await audit("medication_edited", "patient_medication", med_id, user,
                    meta={"patient_id": patient_id, "drug": merged.get("drug"), "changed": list(provided.keys())})
    else:
        raise HTTPException(status_code=400, detail="Unknown medication action.")
    fresh = await db.patient_medications.find_one({"id": med_id}, {"_id": 0})
    return _med_public(fresh)



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
    source_request_id: str = Form(""),
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
    await block_synthetic(snap["patient_id"], snap.get("directory_id"), what="send_rx", user=user)

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
        "source": "PHYSICIAN_PRESCRIPTION",
        "source_request_id": source_request_id.strip() or None,
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

    # If this prescription was CONVERTED from a pharmacy request, link the two
    # records and advance the originating request to PRESCRIPTION SENT. The
    # pharmacy request itself is preserved unchanged as historical evidence
    # (we only add the link + a status/history entry; never overwrite it).
    if source_request_id.strip():
        src = await db.prescription_requests.find_one({"id": source_request_id.strip()})
        if src and src.get("internal_status") != "prescription_sent":
            await db.prescription_requests.update_one(
                {"id": src["id"]},
                {"$set": {"internal_status": "prescription_sent",
                          "linked_transmission_id": tx["id"], "linked_transmission_ref": tx["ref_number"],
                          "prescription_sent_at": now, "updated_at": now},
                 "$push": {"history": {"status": "prescription_sent", "at": now, "by": user.get("name"),
                                       "note": f"Prescription {tx['ref_number']} sent"}}})
            await audit("rx_request_converted", "prescription", src["id"], user, new_status="prescription_sent",
                        meta={"transmission_id": tx["id"], "pharmacy_id": pharmacy_id})
            # Patient-originated requests get a no-PHI 'sent to your pharmacy' update.
            if src.get("source") in ("patient_refill", "patient_photo"):
                await _notify_patient_rx_sent(src)

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
    new_password: Optional[str] = None


def _gen_temp_password(length: int = 16) -> str:
    """Strong random temp password, unambiguous chars, guaranteed mixed classes."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    specials = "!@#$%^&*-_"
    rng = secrets.SystemRandom()
    while True:
        chars = [secrets.choice(alphabet) for _ in range(length - 3)] + [secrets.choice(specials) for _ in range(3)]
        rng.shuffle(chars)
        pw = "".join(chars)
        if (any(c.isupper() for c in pw) and any(c.islower() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in specials for c in pw)):
            return pw


@api.get("/admin/pharmacy-accounts")
async def admin_list_pharmacy_accounts(user: dict = Depends(require_roles("admin"))):
    """Admin-only list of pharmacy LOGIN accounts (role=pharmacy). No password material."""
    return await db.users.find({"role": "pharmacy"}, {
        "_id": 0, "username": 1, "pharmacy_name": 1, "pharmacy_id": 1,
        "active": 1, "must_change_password": 1, "created_at": 1, "password_rotated_at": 1,
    }).sort("pharmacy_name", 1).to_list(200)


@api.post("/admin/pharmacy/reset-temp-password")
async def admin_reset_pharmacy_temp_password(body: ResetPharmacyPwBody, user: dict = Depends(require_roles("admin"))):
    """Admin-only rotation of a PHARMACY account's temporary password. Scoped to
    role='pharmacy' targets ONLY — it can never affect admin/physician/staff/patient
    accounts. Server-generates a strong temp password (returned ONCE for one-time
    display) unless an explicit new_password is supplied (back-compat). Stores only the
    bcrypt hash, sets must_change_password=True, preserves every other field, and
    audits the event WITHOUT recording the password."""
    target = await db.users.find_one({
        "username": {"$regex": f"^{re.escape((body.identifier or '').strip())}$", "$options": "i"},
        "role": "pharmacy",
    })
    if not target:
        raise HTTPException(status_code=404, detail="Pharmacy user not found.")
    supplied = (body.new_password or "").strip()
    if supplied and len(supplied) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    temp = supplied or _gen_temp_password()
    await db.users.update_one({"_id": target["_id"]}, {"$set": {
        "password_hash": authlib.hash_password(temp),
        "must_change_password": True,
        "password_rotated_at": now_iso(),
    }})
    await audit("reset_pharmacy_temp_password", "user", str(target["_id"]), user,
                meta={"username": target.get("username")})
    return {"ok": True, "username": target.get("username"),
            "pharmacy_name": target.get("pharmacy_name"),
            "must_change_password": True, "temp_password": temp}


class DataHygieneBody(BaseModel):
    token: str
    operation: str  # stamp_practice_id | backfill_slot_locks
    appointment_ids: List[str]
    dry_run: bool = True


RELEASE_INFO = {"commit": os.environ.get("RELEASE_COMMIT") or None, "started_at": now_iso()}
try:
    _head = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".git", "HEAD")).read().strip()
    if _head.startswith("ref:"):
        _ref = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".git", _head.split(" ", 1)[1])
        _head = open(_ref).read().strip() if os.path.exists(_ref) else None
    RELEASE_INFO["commit"] = RELEASE_INFO["commit"] or (_head[:12] if _head else None)
except Exception:
    pass


def _flag_on(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


@api.get("/system/banner")
async def system_banner():
    """Public, read-only: active announcement + maintenance flag for the client shell."""
    return sys_mod.public_view(await sys_mod.get_state())


@api.get("/developer/status")
async def developer_status(user: dict = Depends(require_roles(*OPS_ROLES))):
    """Simple installation status for the Developer portal (no secrets, no PHI)."""
    try:
        await asyncio.wait_for(db.command("ping"), timeout=3)
        database = "CONNECTED"
    except Exception:
        database = "DEGRADED"
    storage_state = "CONNECTED" if BOOTSTRAP["steps"].get("storage") == "ok" else ("DEGRADED" if "storage" in BOOTSTRAP["steps"] else "PENDING")
    base = os.environ.get("APP_BASE_URL", "")
    state = await sys_mod.get_state(fresh=True)
    return {
        "api": "ONLINE", "database": database, "storage": storage_state,
        "readiness": "READY" if BOOTSTRAP["ready"] else "NOT READY",
        "bootstrap": BOOTSTRAP["status"], "steps": {k: ("ok" if v == "ok" else "failed") for k, v in BOOTSTRAP["steps"].items()},
        "environment": "production" if "visitaemr.com" in base.lower() else "preview",
        "release": RELEASE_INFO, "time": now_iso(),
        "announcement": state["announcement"], "maintenance": state["maintenance"],
        "operator": pc_mod.operator_profile((await pc_mod.published())["config"], user),
    }


class AnnouncementBody(BaseModel):
    message: str
    type: str = "INFO"


@api.put("/developer/announcement")
async def developer_set_announcement(body: AnnouncementBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    if body.type not in sys_mod.ANNOUNCEMENT_TYPES:
        raise HTTPException(status_code=400, detail="type must be INFO, WARNING or CRITICAL.")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message is required.")
    prev = (await sys_mod.get_state(fresh=True))["announcement"]
    a = await sys_mod.set_announcement(body.message, body.type, user)
    await audit("announcement_updated" if prev.get("active") else "announcement_published", "system_state", "global", user,
                meta={"type": a["type"], "message": a["message"]})
    return a


@api.delete("/developer/announcement")
async def developer_clear_announcement(user: dict = Depends(require_roles(*OPS_ROLES))):
    a = await sys_mod.clear_announcement(user)
    await audit("announcement_removed", "system_state", "global", user, meta={"message": a.get("message")})
    return a


class MaintenanceModeBody(BaseModel):
    on: bool
    message: Optional[str] = None
    confirm: str


@api.post("/developer/maintenance-mode")
async def developer_maintenance_mode(body: MaintenanceModeBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    """Soft maintenance mode: the server stays alive; non-operator API/app use is blocked (503)."""
    expected = "ENTER" if body.on else "EXIT"
    if body.confirm != expected:
        raise HTTPException(status_code=400, detail=f'Type {expected} to confirm.')
    prev = (await sys_mod.get_state(fresh=True))["maintenance"]
    m = await sys_mod.set_maintenance(body.on, body.message, user)
    await audit("maintenance_mode_entered" if body.on else "maintenance_mode_exited", "system_state", "global", user,
                old_status="ON" if prev.get("on") else "OFF", new_status="ON" if body.on else "OFF", meta={"message": m["message"]})
    return m


class ThemeBody(BaseModel):
    theme: str


@api.put("/me/theme")
async def set_my_theme(body: ThemeBody, user: dict = Depends(get_current_user)):
    """USER-LEVEL appearance preference (VIen Light default / VIen Dark). Affects only this user."""
    if body.theme not in ("light", "dark"):
        raise HTTPException(status_code=400, detail="theme must be light or dark")
    await db.users.update_one({"_id": ObjectId(user["id"])}, {"$set": {"theme": body.theme}})
    return {"theme": body.theme}


@api.get("/system/config")
async def system_config(preview: bool = False, user_role: Optional[str] = None):
    """Public, read-only published platform config (branding/features/navigation/public copy).
    ?preview=1 is honoured only for developer_ops (draft preview)."""
    return pc_mod.public_view(await pc_mod.published())


@api.get("/developer/platform-config")
async def developer_platform_config(user: dict = Depends(require_roles(*OPS_ROLES))):
    return {"published": await pc_mod.published(), "draft": await pc_mod.draft(), "history": await pc_mod.history(),
            "registry": {"features": pc_mod.FEATURES, "states": pc_mod.FEATURE_STATES, "audiences": pc_mod.AUDIENCES,
                         "public_site_fields": pc_mod.PUBLIC_SITE_FIELDS, "sections": pc_mod.SECTIONS}}


class DraftBody(BaseModel):
    section: str
    data: dict


@api.put("/developer/platform-config/draft")
async def developer_save_draft(body: DraftBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    try:
        d = await pc_mod.save_draft(body.section, body.data, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit("platform_config_draft_saved", "platform_config", "draft", user, meta={"section": body.section})
    return d


@api.delete("/developer/platform-config/draft")
async def developer_discard_draft(user: dict = Depends(require_roles(*OPS_ROLES))):
    await pc_mod.discard_draft()
    await audit("platform_config_draft_discarded", "platform_config", "draft", user)
    return {"ok": True}


class ConfirmBody(BaseModel):
    confirm: str
    version: Optional[int] = None


@api.post("/developer/platform-config/publish")
async def developer_publish(body: ConfirmBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    if body.confirm != "PUBLISH":
        raise HTTPException(status_code=400, detail="Type PUBLISH to confirm.")
    try:
        prev, new, changed = await pc_mod.publish_draft(user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit("platform_config_published", "platform_config", f"v{new}", user, old_status=f"v{prev}", new_status=f"v{new}",
                meta={"sections": changed, "previous_version": prev, "new_version": new})
    return {"previous_version": prev, "version": new, "sections": changed}


@api.post("/developer/platform-config/rollback")
async def developer_rollback(body: ConfirmBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    if body.confirm != "ROLLBACK" or body.version is None:
        raise HTTPException(status_code=400, detail="Type ROLLBACK and choose a version.")
    try:
        prev, new = await pc_mod.rollback(body.version, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit("platform_config_rolled_back", "platform_config", f"v{new}", user, old_status=f"v{prev}", new_status=f"v{new}",
                meta={"restored_version": body.version, "previous_version": prev, "new_version": new})
    return {"previous_version": prev, "version": new, "restored_version": body.version}


class SyntheticPatientsBody(BaseModel):
    token: str


# ---------------- VIen Network — Phase 1 (feature "network"; PILOT = internal roles incl. `network` persons) ----------------
NETWORK_ROLES = ("physician", "admin", "staff", "network", "developer_ops")


class InviteBody(BaseModel):
    user_id: str
    role_title: str = "Secretary"


class AccessBody(BaseModel):
    modules: list[str]


class NetProfileBody(BaseModel):
    headline: Optional[str] = None
    summary: Optional[str] = None
    city: Optional[str] = None
    languages: Optional[list[str]] = None
    availability: Optional[str] = None


async def _owned_org(user: dict, org_id: str) -> dict:
    org = await net_mod.org_doc(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if not await net_mod.is_org_owner(user, org_id):
        raise HTTPException(status_code=403, detail="Only the organization owner can manage its team.")
    return org


@api.get("/network/home")
async def network_home(user: dict = Depends(require_roles(*NETWORK_ROLES))):
    uid = str(user["id"])
    me = await net_mod.profile_for(uid)
    invitations = await db.org_memberships.find({"user_id": uid, "status": "INVITED"}, {"_id": 0}).to_list(20)
    memberships = await db.org_memberships.find({"user_id": uid, "status": {"$in": ["ACTIVE", "SUSPENDED"]}}, {"_id": 0}).to_list(20)
    owned = [await net_mod.org_doc(p["id"]) for p in await db.practices.find({"physician_user_id": uid}, {"_id": 0, "id": 1}).to_list(10)]
    return {"me": me, "invitations": invitations, "memberships": memberships, "owned_organizations": owned, "modules": net_mod.MODULES}


@api.put("/network/me/profile")
async def network_update_profile(body: NetProfileBody, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    await db.network_profiles.update_one({"user_id": str(user["id"])}, {"$set": {**data, "updated_at": now_iso()}}, upsert=True)
    return await net_mod.profile_for(str(user["id"]))


@api.get("/network/people/{user_id}")
async def network_person(user_id: str, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    p = await net_mod.profile_for(user_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return p


@api.get("/network/orgs/{org_id}")
async def network_org(org_id: str, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    org = await net_mod.org_doc(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return {**org, "team": await net_mod.team(org_id), "connections": await net_mod.connections_for("organization", org_id),
            "can_manage": await net_mod.is_org_owner(user, org_id), "modules": net_mod.MODULES}


@api.get("/network/search")
async def network_search(q: str = "", user: dict = Depends(require_roles(*NETWORK_ROLES))):
    q = q.strip()
    if len(q) < 2:
        return {"results": []}
    rx = {"$regex": re.escape(q), "$options": "i"}
    rows = await db.users.find({"role": {"$nin": ["patient", "caregiver", "developer_ops"]}, "active": {"$ne": False},
                                "$or": [{"name": rx}, {"email": rx}, {"username": rx}]}, {"name": 1, "email": 1, "role": 1, "username": 1}).limit(10).to_list(10)
    return {"results": [{"id": str(u["_id"]), "name": u.get("name"), "email": u.get("email"), "username": u.get("username"), "role": u.get("role")} for u in rows]}


@api.post("/network/orgs/{org_id}/invite")
async def network_invite(org_id: str, body: InviteBody, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    org = await _owned_org(user, org_id)
    try:
        invitee = await db.users.find_one({"_id": ObjectId(body.user_id)})
    except Exception:
        invitee = None
    if not invitee or invitee.get("role") in ("patient", "caregiver"):
        raise HTTPException(status_code=404, detail="VIen identity not found.")
    try:
        m = await net_mod.invite(org, invitee, body.role_title.strip() or "Secretary", user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await audit("network_invitation_sent", "org_membership", m["id"], user, meta={"org_id": org_id, "invitee_id": m["user_id"], "role_title": m["role_title"]})
    return m


async def _my_invitation(mid: str, user: dict) -> dict:
    m = await db.org_memberships.find_one({"id": mid, "user_id": str(user["id"]), "status": "INVITED"}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    return m


@api.post("/network/invitations/{mid}/accept")
async def network_accept(mid: str, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    m = await net_mod.respond(await _my_invitation(mid, user), True, user)
    await audit("network_invitation_accepted", "org_membership", mid, user, old_status="INVITED", new_status="ACTIVE", meta={"org_id": m["org_id"], "role_title": m["role_title"]})
    return m


@api.post("/network/invitations/{mid}/decline")
async def network_decline(mid: str, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    m = await net_mod.respond(await _my_invitation(mid, user), False, user)
    await audit("network_invitation_declined", "org_membership", mid, user, old_status="INVITED", new_status="DECLINED", meta={"org_id": m["org_id"]})
    return m


async def _org_member(user: dict, org_id: str, mid: str) -> dict:
    await _owned_org(user, org_id)
    m = await db.org_memberships.find_one({"id": mid, "org_id": org_id, "status": {"$in": ["ACTIVE", "SUSPENDED"]}}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Membership not found.")
    return m


@api.put("/network/orgs/{org_id}/members/{mid}/access")
async def network_set_access(org_id: str, mid: str, body: AccessBody, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    m = await _org_member(user, org_id, mid)
    mods = await net_mod.set_access(m, body.modules)
    await audit("network_access_granted", "org_membership", mid, user, meta={"org_id": org_id, "member_id": m["user_id"], "modules_before": m.get("modules", []), "modules_after": mods})
    return {"ok": True, "modules": mods}


@api.post("/network/orgs/{org_id}/members/{mid}/{action}")
async def network_member_action(org_id: str, mid: str, action: str, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    m = await _org_member(user, org_id, mid)
    new = {"suspend": "SUSPENDED", "reactivate": "ACTIVE", "remove": "REMOVED"}.get(action)
    if not new:
        raise HTTPException(status_code=400, detail="Unknown action.")
    await net_mod.set_status(m, new)
    await audit(f"network_member_{action}", "org_membership", mid, user, old_status=m["status"], new_status=new, meta={"org_id": org_id, "member_id": m["user_id"]})
    return {"ok": True, "status": new}


@api.post("/network/workspace/{mid}/enter")
async def network_workspace_enter(mid: str, user: dict = Depends(require_roles(*NETWORK_ROLES))):
    m = await db.org_memberships.find_one({"id": mid, "user_id": str(user["id"])}, {"_id": 0})
    if not m or m["status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="Your membership is not active.")
    if not m.get("modules"):
        raise HTTPException(status_code=403, detail="The organization has not granted you workspace access yet.")
    token = authlib.create_access_token(str(user["id"]), user.get("email") or "", "staff", extra={"ws": mid})
    await audit("network_workspace_entered", "org_membership", mid, user, meta={"org_id": m["org_id"], "modules": m["modules"]})
    return {"token": token, "workspace": {"org_id": m["org_id"], "org_name": m["org_name"], "role_title": m["role_title"], "modules": m["modules"]}}


@api.post("/network/workspace/exit")
async def network_workspace_exit(user: dict = Depends(get_current_user)):
    u = await db.users.find_one({"_id": ObjectId(user["id"])})
    return {"token": authlib.create_access_token(str(u["_id"]), u.get("email") or "", u["role"])}


# ---------------- Developer Data Operations (developer_ops only, fail-closed outside PRELAUNCH_TEST) ----------------
import data_ops as dops  # noqa: E402
import network as net_mod  # noqa: E402


async def _require_prelaunch_mode():
    live = await pc_mod.published()
    mode = pc_mod.live_data_mode(live["config"])
    if mode != "PRELAUNCH_TEST":
        raise HTTPException(status_code=403, detail={"code": "DATA_MODE_LIVE", "message": "Platform data mode is LIVE_CLINICAL — test-data tools are permanently disabled."})
    return mode


class DataOpsResetBody(BaseModel):
    reason: str
    confirm_text: str
    include_directory: bool = False


class DataOpsDeleteUserBody(BaseModel):
    reason: str
    confirm_text: str


def _ops_reason(reason: str):
    if len((reason or "").strip()) < 5:
        raise HTTPException(status_code=422, detail="A reason (at least 5 characters) is required.")
    return reason.strip()


@api.get("/developer/data-ops/status")
async def developer_data_ops_status(user: dict = Depends(require_roles(*OPS_ROLES))):
    live = await pc_mod.published()
    return {"data_mode": pc_mod.live_data_mode(live["config"]), "version": live["version"], "modes": pc_mod.DATA_MODES,
            "confirm": {"reset": dops.RESET_CONFIRM, "delete_user": dops.DELETE_USER_CONFIRM, "purge": dops.PURGE_CONFIRM}}


@api.get("/developer/data-ops/search")
async def developer_data_ops_search(q: str = "", user: dict = Depends(require_roles(*OPS_ROLES))):
    await _require_prelaunch_mode()
    return {"results": await dops.search(q)}


@api.get("/developer/data-ops/patient/{patient_id}/preview")
async def developer_data_ops_patient_preview(patient_id: str, user: dict = Depends(require_roles(*OPS_ROLES))):
    await _require_prelaunch_mode()
    pv = await dops.patient_preview(patient_id)
    if not pv:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return pv


@api.post("/developer/data-ops/patient/{patient_id}/reset")
async def developer_data_ops_patient_reset(patient_id: str, body: DataOpsResetBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    await _require_prelaunch_mode()
    reason = _ops_reason(body.reason)
    if body.confirm_text.strip() != dops.RESET_CONFIRM:
        raise HTTPException(status_code=422, detail=f'Type "{dops.RESET_CONFIRM}" to confirm.')
    res = await dops.reset_patient(patient_id, body.include_directory)
    if not res:
        raise HTTPException(status_code=404, detail="Patient not found.")
    pv = res["preview"]
    await audit("devops_test_patient_reset", "patient", patient_id, user, meta={
        "pin": pv["patient"].get("pin"), "name": pv["patient"].get("name"), "login_emails": [l.get("email") for l in pv["logins"]],
        "directory_ids": [d["id"] for d in pv["directory"]], "include_directory": body.include_directory,
        "deleted": res["deleted"], "total_deleted": res["total"], "reason": reason, "data_mode": "PRELAUNCH_TEST"})
    return {"ok": True, "deleted": res["deleted"], "total": res["total"], "released_emails": [l.get("email") for l in pv["logins"]]}


@api.get("/developer/data-ops/user/{user_id}/preview")
async def developer_data_ops_user_preview(user_id: str, user: dict = Depends(require_roles(*OPS_ROLES))):
    await _require_prelaunch_mode()
    pv = await dops.user_preview(user_id)
    if not pv:
        raise HTTPException(status_code=404, detail="User not found.")
    pv.pop("_raw_id", None)
    return pv


@api.post("/developer/data-ops/user/{user_id}/delete")
async def developer_data_ops_user_delete(user_id: str, body: DataOpsDeleteUserBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    await _require_prelaunch_mode()
    reason = _ops_reason(body.reason)
    if body.confirm_text.strip() != dops.DELETE_USER_CONFIRM:
        raise HTTPException(status_code=422, detail=f'Type "{dops.DELETE_USER_CONFIRM}" to confirm.')
    pv = await dops.user_preview(user_id)
    if not pv:
        raise HTTPException(status_code=404, detail="User not found.")
    if pv["protected"] or pv["id"] == str(user.get("id")) or (pv.get("email") or "").lower() == OWNER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Operator, owner and your own identity cannot be deleted here.")
    if pv.get("patient_id") and await db.patients.find_one({"id": pv["patient_id"]}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="This login is attached to a patient record — use RESET TEST PATIENT instead.")
    res = await dops.delete_user(user_id)
    await audit("devops_test_user_deleted", "user", user_id, user, meta={
        "email": pv.get("email"), "role": pv.get("role"), "name": pv.get("name"), "deleted": res["deleted"], "reason": reason, "data_mode": "PRELAUNCH_TEST"})
    return {"ok": True, "deleted": res["deleted"], "released_email": pv.get("email")}


@api.get("/developer/data-ops/purge-preview")
async def developer_data_ops_purge_preview(user: dict = Depends(require_roles(*OPS_ROLES))):
    await _require_prelaunch_mode()
    return await dops.purge_preview()


@api.post("/developer/data-ops/purge-all")
async def developer_data_ops_purge_all(user: dict = Depends(require_roles(*OPS_ROLES))):
    await _require_prelaunch_mode()
    await audit("devops_purge_all_attempt_blocked", "platform", "purge-all", user, meta={"reason": "purge not wired in this release"})
    raise HTTPException(status_code=501, detail={"code": "PURGE_NOT_WIRED", "message": "PURGE ALL TEST DATA is architecturally prepared but intentionally not enabled in this release."})


SYNTHETIC_PATIENTS = [
    {"visita_patient_id": "TEST-F-001", "first_name": "Testfemale", "last_name": "SYNTHETIC-ZZ", "date_of_birth": "1985-03-15",
     "sex": "Female", "sex_code": None, "health_card_number": "0000000001", "health_card_version_code": "ZZ",
     "address": "1 Test Lane", "city": "Testville", "province": "ON", "postal_code": "A0A 0A0", "cell_phone": "000-000-0001"},
    {"visita_patient_id": "TEST-M-001", "first_name": "Testmale", "last_name": "SYNTHETIC-ZZ", "date_of_birth": "1978-09-22",
     "sex": "Male", "sex_code": None, "health_card_number": "0000000002", "health_card_version_code": "ZZ",
     "address": "2 Test Lane", "city": "Testville", "province": "ON", "postal_code": "A0A 0A0", "cell_phone": "000-000-0002"},
]


@api.post("/internal/admin/synthetic-test-patients")
async def admin_create_synthetic_patients(body: SyntheticPatientsBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    """Admin + MAINTENANCE_TOKEN gated. Creates EXACTLY two directory-only synthetic test patients
    (create-if-missing by TEST PIN). No portal account, no email. Never touches real records."""
    expected = os.environ.get("MAINTENANCE_TOKEN", "")
    if not expected or not secrets.compare_digest(body.token, expected):
        raise HTTPException(status_code=403, detail="Invalid maintenance token.")
    out = []
    for sp in SYNTHETIC_PATIENTS:
        existing = await db.patient_directory.find_one({"visita_patient_id": sp["visita_patient_id"]}, {"_id": 0})
        if existing:
            out.append({"id": existing["id"], "visita_patient_id": sp["visita_patient_id"], "created": False})
            continue
        doc = {
            "id": str(uuid.uuid4()), **sp, "email": None, "home_phone": None, "unit": None,
            "patient_status": directory_mod.ACTIVE, "linked_patient_id": None, "practice_id": user.get("practice_id"),
            "is_synthetic": True, "synthetic_marker": SYNTHETIC_MARKER, "notes": SYNTHETIC_MARKER,
            "norm_first": directory_mod.norm_name(sp["first_name"]), "norm_last": directory_mod.norm_name(sp["last_name"]),
            "norm_dob": directory_mod.norm_dob(sp["date_of_birth"]), "norm_hcn": directory_mod.norm_hcn(sp["health_card_number"]),
            "import_source": "synthetic_test", "imported_at": now_iso(), "updated_at": now_iso(),
        }
        await db.patient_directory.insert_one({**doc})
        await audit("synthetic_test_patient_created", "patient_directory", doc["id"], user,
                    meta={"visita_patient_id": sp["visita_patient_id"], "marker": SYNTHETIC_MARKER})
        out.append({"id": doc["id"], "visita_patient_id": sp["visita_patient_id"], "created": True})
    return {"patients": out, "marker": SYNTHETIC_MARKER}


class CatalogImportBody(BaseModel):
    token: str
    apply: bool = False


@api.post("/internal/admin/maintenance/catalog-import")
async def admin_catalog_import(body: CatalogImportBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    """Admin + MAINTENANCE_TOKEN gated. One-time, insert-missing-only import of the three reference
    catalogs (soap_helpers / diagnosis_catalog / service_catalog) from the approved packages.
    Dry-run (default) performs zero writes. Existing rows are never updated/deleted. Audited."""
    expected = os.environ.get("MAINTENANCE_TOKEN", "")
    if not expected or not secrets.compare_digest(body.token, expected):
        raise HTTPException(status_code=403, detail="Invalid maintenance token.")
    results = await catalog_import_mod.run(db, apply=body.apply)
    await audit("catalog_import_maintenance", "reference_catalogs", "soap_helpers+diagnosis_catalog+service_catalog", user,
                meta={"mode": "apply" if body.apply else "dry_run",
                      "results": {k: {f: v[f] for f in ("SOURCE", "EXISTS", "MISSING", "INSERTED", "FAILED")} for k, v in results.items()}})
    return {"mode": "apply" if body.apply else "dry_run", "results": results}


class AuditIndexMaintenanceBody(BaseModel):
    token: str
    apply: bool = False


@api.post("/internal/admin/maintenance/audit-indexes")
async def admin_audit_index_maintenance(body: AuditIndexMaintenanceBody, user: dict = Depends(require_roles(*OPS_ROLES))):
    """Admin + MAINTENANCE_TOKEN gated. Builds ONLY the predefined approved audit_logs performance
    indexes (index_bootstrap.AUDIT_INDEXES). dry-run (default) lists EXISTS/MISSING; apply creates
    missing ones only (EXISTS/CREATED/FAILED). Never drops/alters existing indexes; no generic commands."""
    expected = os.environ.get("MAINTENANCE_TOKEN", "")
    if not expected or not secrets.compare_digest(body.token, expected):
        raise HTTPException(status_code=403, detail="Invalid maintenance token.")
    if body.apply:
        results = await ib_mod.ensure_missing(db, "audit_logs", ib_mod.AUDIT_INDEXES, timeout=120)
    else:
        results = await ib_mod.plan(db, "audit_logs", ib_mod.AUDIT_INDEXES)
    await audit("audit_index_maintenance", "audit_logs", "indexes", user,
                meta={"mode": "apply" if body.apply else "dry_run", "results": results})
    return {"mode": "apply" if body.apply else "dry_run", "collection": "audit_logs", "results": results}


OWNER_ADMIN_EMAIL = "kevinrodriguez9528@gmail.com"
PLACEHOLDER_OPS_EMAIL = "devops@visita.demo"


TEST_PATIENT_DEP_COLLECTIONS = [
    "appointment_requests", "visits", "prescription_requests", "rx_transmissions", "patient_medications",
    "exam_results", "bloodwork_requests", "imaging_requests", "referrals", "patient_referrals", "invoices",
    "payment_proofs", "attachments", "private_requests", "patient_messages", "portal_access_requests",
    "patient_provider_relationships", "practice_patient_relationships", "appointment_day_locks",
    "appointment_review_flags", "patient_portal_delegates",
]


class VoidTestPatientBody(BaseModel):
    token: str
    patient_id: str
    pin: str
    portal_email: str
    confirm: bool = False


@api.post("/internal/admin/maintenance/void-test-patient")
async def admin_void_test_patient(body: VoidTestPatientBody, user: dict = Depends(require_roles("admin"))):
    """ONE-TIME, owner-admin + OPS_PROVISION_TOKEN gated archive of a single owner-confirmed TEST patient
    with ZERO clinical dependencies. Soft-voids the patient, detaches its login identity (releasing the
    email), never hard-deletes. Refuses on any dependency or identity mismatch."""
    if (user.get("email") or "").lower() != OWNER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Not authorized")
    expected = os.environ.get("OPS_PROVISION_TOKEN", "")
    if not expected or not secrets.compare_digest(body.token, expected):
        raise HTTPException(status_code=403, detail="Invalid token.")
    p = await db.patients.find_one({"id": body.patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    email = body.portal_email.strip().lower()
    if str(p.get("visita_patient_id")) != body.pin.strip():
        raise HTTPException(status_code=409, detail="PIN does not match this patient record.")
    if p.get("record_status") == "VOIDED_TEST":
        raise HTTPException(status_code=409, detail="This record is already archived as TEST.")
    logins = [u async for u in db.users.find({"patient_id": p["id"]})]
    if len(logins) != 1 or (logins[0].get("email") or "").lower() != email:
        raise HTTPException(status_code=409, detail="Portal login identity does not match (expected exactly one login with the given email).")
    u = logins[0]
    deps = {c: await db[c].count_documents({"patient_id": p["id"]}) for c in TEST_PATIENT_DEP_COLLECTIONS}
    deps["patient_directory_linked"] = await db.patient_directory.count_documents({"linked_patient_id": p["id"]})
    deps["patient_directory_matched"] = await db.patient_directory.count_documents({"id": p.get("matched_directory_id")}) if p.get("matched_directory_id") else 0
    deps["delegate_grants_as_caregiver"] = await db.patient_portal_delegates.count_documents({"delegate_user_id": str(u["_id"])})
    # Owner-confirmed exception: this test patient's OWN per-practice relationship-state record(s) may be removed
    # with it (keyed strictly to this patient_id; practices/providers themselves are never touched).
    own_rels = [r async for r in db.patient_provider_relationships.find({"patient_id": p["id"]}, {"_id": 0})]
    rels_ok = len(own_rels) == deps["patient_provider_relationships"] and all(
        r.get("patient_id") == p["id"] and not (r.get("directory_id") and r["directory_id"] != p.get("matched_directory_id")) for r in own_rels)
    blocking = {k: v for k, v in deps.items() if v and not (k == "patient_provider_relationships" and rels_ok)}
    summary = {"patient_id": p["id"], "pin": p.get("visita_patient_id"), "name": f"{p.get('first_name')} {p.get('last_name')}",
               "portal_email": u.get("email"), "login_active": u.get("active", True), "dependencies": deps,
               "removable_relationships": [{"id": r.get("id"), "practice_id": r.get("practice_id"), "status": r.get("status"), "created_at": r.get("created_at")} for r in own_rels] if rels_ok else []}
    if blocking:
        return {"mode": "blocked", "blocking": blocking, **summary}
    if not body.confirm:
        return {"mode": "dry_run", "would_archive": summary}
    ts = now_iso()
    actor = {"id": user.get("id"), "name": user.get("name"), "role": user.get("role")}
    reason = "Confirmed test patient cleanup — owner-created test record"
    uid = str(u["_id"])
    archive = {"id": str(uuid.uuid4()), "user_id": uid, "patient_id": p["id"], "visita_patient_id": p.get("visita_patient_id"),
               "login_email": u.get("email"), "name": u.get("name"), "email_verified": bool(u.get("email_verified")),
               "account_created_at": u.get("created_at"), "last_login_at": u.get("last_login_at"), "was_active": u.get("active", True),
               "detached_at": ts, "detached_by": actor, "reason": reason, "kind": "TEST_RECORD_VOID", "dependency_check": deps}
    await db.portal_account_archive.insert_one(archive)
    rel_ids = [r["id"] for r in summary["removable_relationships"] if r.get("id")]
    rels_deleted = (await db.patient_provider_relationships.delete_many({"patient_id": p["id"]})).deleted_count if rel_ids else 0
    await db.users.update_one({"_id": u["_id"]}, {
        "$set": {"email": f"detached+{uid}@archived.vien.invalid", "password_hash": None, "active": False, "patient_id": None,
                 "detached_patient_id": p["id"], "portal_detached": True, "detached_at": ts, "detached_by": actor,
                 "detach_reason": reason, "archive_id": archive["id"], "email_verified": False, "must_change_password": False,
                 "is_test_identity": True, "updated_at": ts},
        "$unset": {"temp_password_expires_at": "", "pending_activation": ""}})
    await db.password_resets.delete_many({"user_id": uid})
    await db.account_activations.delete_many({"user_id": uid})
    await db.patients.update_one({"id": p["id"]}, {"$set": {
        "record_status": "VOIDED_TEST", "is_test_record": True, "active_status": False, "has_login": False,
        "portal_status": "DETACHED", "portal_detached_at": ts, "voided_at": ts, "voided_by": actor, "void_reason": reason,
        "prior_portal_email": u.get("email"), "updated_at": ts}})
    # PIN stays attached to this voided record so it is never reissued to another patient.
    await db.visita_pins.update_one({"_id": p.get("visita_patient_id")}, {"$set": {"voided_test": True, "voided_at": ts}})
    await audit("test_patient_voided", "patient", p["id"], user, meta={
        "pin": p.get("visita_patient_id"), "prior_portal_email": u.get("email"), "reason": reason,
        "dependency_check": deps, "archive_id": archive["id"],
        "removed_relationship_ids": rel_ids, "relationships_deleted": rels_deleted})
    return {"mode": "apply", "archived": summary, "released_email": u.get("email"), "archive_id": archive["id"], "relationships_deleted": rels_deleted}


class OpsProvisionBody(BaseModel):
    token: str
    email: str
    username: str
    name: str
    confirm: bool = False


@api.post("/internal/admin/maintenance/provision-developer-ops")
async def admin_provision_developer_ops(body: OpsProvisionBody, user: dict = Depends(require_roles("admin"))):
    """ONE-TIME, owner-admin + OPS_PROVISION_TOKEN gated creation of a single installation-level
    developer_ops account. Refuses if any non-placeholder developer_ops already exists or the action
    already ran. Temp password is returned ONCE and never logged/audited."""
    if (user.get("email") or "").lower() != OWNER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Not authorized")
    expected = os.environ.get("OPS_PROVISION_TOKEN", "")
    if not expected or not secrets.compare_digest(body.token, expected):
        raise HTTPException(status_code=403, detail="Invalid provisioning token.")
    email = body.email.strip().lower()
    username = body.username.strip().upper()
    name = body.name.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or not re.fullmatch(r"[A-Z0-9]{3,32}", username) or not name:
        raise HTTPException(status_code=422, detail="Invalid email, username (A-Z/0-9, 3-32) or name.")
    if await db.app_meta.find_one({"id": "developer_ops_provisioned"}):
        raise HTTPException(status_code=409, detail="developer_ops provisioning already performed.")
    if await db.users.find_one({"role": "developer_ops", "email": {"$ne": PLACEHOLDER_OPS_EMAIL}}):
        raise HTTPException(status_code=409, detail="A developer_ops account already exists.")
    if await db.users.find_one({"$or": [{"email": email}, {"username": {"$regex": f"^{re.escape(username)}$", "$options": "i"}}]}):
        raise HTTPException(status_code=409, detail="Email or username already in use.")
    plan = {"email": email, "username": username, "name": name, "role": "developer_ops", "must_change_password": True}
    if not body.confirm:
        return {"mode": "dry_run", "would_create": plan}
    temp = _gen_temp_password()
    await db.users.insert_one({
        **plan, "password_hash": authlib.hash_password(temp), "mfa_enabled": False, "patient_id": None,
        "active": True, "created_at": now_iso(), "provisioned_by": user.get("email"),
    })
    await db.app_meta.insert_one({"id": "developer_ops_provisioned", "at": now_iso(), "email": email, "by": user.get("email")})
    await audit("developer_ops_provisioned", "user", email, user, meta={"username": username, "name": name})
    return {"mode": "apply", "created": plan, "temp_password": temp}


@api.post("/internal/admin/data-hygiene")
async def admin_data_hygiene(body: DataHygieneBody, user: dict = Depends(require_roles("admin"))):
    """TEMPORARY maintenance endpoint: admin + MAINTENANCE_TOKEN gated, scoped to an explicit
    appointment id list, idempotent, audited. No delete/reset, conflicts never auto-resolved."""
    expected = os.environ.get("MAINTENANCE_TOKEN", "")
    if not expected or not secrets.compare_digest(body.token, expected):
        raise HTTPException(status_code=403, detail="Invalid maintenance token.")
    ids = list(dict.fromkeys(i.strip() for i in body.appointment_ids if i and i.strip()))
    if not ids or len(ids) > hygiene_mod.MAX_IDS:
        raise HTTPException(status_code=400, detail=f"Provide 1-{hygiene_mod.MAX_IDS} explicit appointment ids.")
    ops = {"stamp_practice_id": hygiene_mod.stamp_practice_id, "backfill_slot_locks": hygiene_mod.backfill_slot_locks,
           "close_stale_request": hygiene_mod.close_stale_request}
    if body.operation not in ops:
        raise HTTPException(status_code=400, detail="Unknown operation.")
    result = await ops[body.operation](db, ids, not body.dry_run, user)
    await audit("data_hygiene", "appointment_requests", body.operation, user,
                meta={"mode": result.get("mode"), "ids": ids, "summary": result.get("summary"),
                      "changed_ids": [r["id"] for r in result.get("stamped", []) + result.get("created", []) + result.get("closed", [])]})
    return result


# ============= PROFESSIONALS — Dr. Aguayo's Professional Construct (Phase 1) =============
# ONE shared Professional Profile model + Directory (search/view). System ACCESS stays
# SEPARATE from professional identity (optional users.professional_id link, added later).
#
# ARCHITECTURE BOUNDARY (do not violate):
#   * CORE VIen (users -> practices -> patients -> patient-provider relationships ->
#     patient-care workflows) is INDEPENDENT of Professional Profiles. A physician can
#     use every patient-care workflow with NO professional profile. Nothing here gates
#     login, practice access, patient visibility, applications, verifications, appointments,
#     Rx, imaging, bloodwork, referrals, patient updates/documents, registration QR, or
#     practice isolation. Those are controlled by practice/RBAC ONLY.
#   * The modern `vien_professional_*` taxonomy is OPTIONAL enrichment metadata. Core VIen
#     must never depend on it being populated/available.
#   * LEGACY ACCESS professional tables are REFERENCE / FUTURE REFERRAL DIRECTORY ONLY.
#     They must NOT control physician authentication, physician onboarding, practice
#     ownership, patient ownership, patient permissions, or modern Professional Profile
#     identity. Do NOT attempt Access-ID reconciliation into the modern profile system.
#
# Only `surname` is required to save a profile; every other field is optional.
# New collections only; existing providers / organizations / users are never modified.
PROF_VIEW_ROLES = ("admin", "physician", "staff", "pharmacy")
PROF_EDIT_ROLES = ("admin",)  # architected so physician/staff can be enabled later w/o rework


def _prof_public(p: dict) -> dict:
    p = {k: v for k, v in p.items() if k != "_id"}
    p["has_vien_access"] = bool(p.get("linked_user_id"))
    p["record_type"] = "user" if p.get("linked_user_id") else "contact"
    names = " ".join([n for n in [p.get("first_name"), p.get("second_name")] if n]).strip()
    p["display_name"] = ", ".join([x for x in [p.get("surname"), names] if x])
    return p


class ProfessionalBody(BaseModel):
    surname: str
    first_name: Optional[str] = ""
    second_name: Optional[str] = ""
    sphere_id: Optional[str] = None
    area_id: Optional[str] = None
    specialty_id: Optional[str] = None
    credential_ids: Optional[list] = None
    language_ids: Optional[list] = None
    accepting_patients: Optional[bool] = None
    waiting_list: Optional[bool] = None
    sex: Optional[str] = None
    areas_of_practice_ids: Optional[list] = None   # cumulative (VIen AOP ids, scoped by specialty)
    practice_type_ids: Optional[list] = None        # cumulative (VIen practice-type ids)
    primary_care_model_ids: Optional[list] = None   # Ontario models (array; kept separate)
    registration_number: Optional[str] = None
    professorship: Optional[str] = None
    organization_ids: Optional[list] = None
    visibility: Optional[str] = "authenticated"
    # PUBLIC professional contact (separate from login/account contact; never auto-copied)
    public_phone: Optional[str] = None
    public_fax: Optional[str] = None
    public_email: Optional[str] = None
    public_address: Optional["PublicAddress"] = None


class PublicAddress(BaseModel):
    street: Optional[str] = ""
    unit: Optional[str] = ""
    city: Optional[str] = ""
    province: Optional[str] = "Ontario"
    postal_code: Optional[str] = ""
    country: Optional[str] = "Canada"


ProfessionalBody.model_rebuild()

_PHONE_RX = re.compile(r"^[0-9+()\-.\s]{7,25}$")
_POSTAL_RX = re.compile(r"^[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d$")


def _validate_public_contact(body: ProfessionalBody):
    """Format checks ONLY when a value is entered; blanks never block saving."""
    for label, val in (("phone", body.public_phone), ("fax", body.public_fax)):
        if val and val.strip() and not _PHONE_RX.match(val.strip()):
            raise HTTPException(status_code=400, detail=f"Public {label} must be 7–25 characters using digits, spaces, +, (, ), - or .")
    if body.public_email and body.public_email.strip() and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", body.public_email.strip()):
        raise HTTPException(status_code=400, detail="Public email is not a valid email address.")
    a = body.public_address
    if a and a.postal_code and a.postal_code.strip() and (a.country or "Canada").strip().lower() == "canada" \
            and not _POSTAL_RX.match(a.postal_code.strip()):
        raise HTTPException(status_code=400, detail="Postal code must look like A1A 1A1.")


class EditorGrantBody(BaseModel):
    user_id: str
    organization_id: Optional[str] = None
    permission_level: Optional[str] = "EDIT_PROFILE"


class LinkUserBody(BaseModel):
    user_id: Optional[str] = None  # None to unlink


class AffiliationBody(BaseModel):
    organization_id: str
    affiliation_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


async def _active_edit_auth(user_id: str, prof_id: str):
    return await db.professional_profile_editors.find_one({
        "professional_id": prof_id, "user_id": user_id,
        "permission_level": "EDIT_PROFILE", "active": True})


async def _edit_source(user: dict, profile: dict) -> Optional[str]:
    """Server-side authorization: who (if anyone) the current user edits this profile as."""
    if user.get("role") == "admin":
        return "ADMIN"
    if profile.get("linked_user_id") and user.get("id") == profile["linked_user_id"]:
        return "SELF"
    if await _active_edit_auth(user["id"], profile["id"]):
        return "AUTHORIZED_ORGANIZATION_EDITOR"
    return None


def _management_label(profile: dict, has_editors: bool) -> str:
    if profile.get("linked_user_id"):
        return "Self-managed"
    if has_editors:
        return "Organization-managed"
    return "Admin-managed"


# High-risk fields never mutated via the shared profile editor (defensive; not in ProfessionalBody).
_HIGH_RISK_FIELDS = ("linked_user_id", "id", "source_professional_id", "created_by", "created_at", "role")


@api.get("/professionals/taxonomy")
async def professionals_taxonomy(user: dict = Depends(require_roles(*PROF_VIEW_ROLES))):
    """Modern VIen-native taxonomy (vien_professional_* ONLY; seed_vien_professional_taxonomy.py).
    Legacy Access-origin professional_* collections are never read here."""
    async def _all(coll):
        return await db[coll].find({"active": {"$ne": False}}, {"_id": 0}).sort("sort_order", 1).to_list(2000)
    out = {
        "spheres": await _all("vien_professional_spheres"),
        "areas": await _all("vien_professional_areas"),
        "specialties": await _all("vien_professional_specialties"),
        "credentials": await _all("vien_professional_credentials"),
        "languages": await _all("vien_professional_languages"),
        "practice_types": await _all("vien_professional_practice_types"),
        "primary_care_models": await _all("vien_professional_primary_care_models"),
    }
    out["available"] = bool(out["areas"] and out["specialties"])
    return out


@api.get("/professionals/areas-of-practice")
async def professionals_areas_of_practice(specialty_id: Optional[str] = None,
                                          user: dict = Depends(require_roles(*PROF_VIEW_ROLES))):
    """Controlled Areas of Practice for a given Specialty (currently only Family
    Medicine is configured). Empty list when the specialty has no configured list."""
    query = {"active": True}
    if specialty_id:
        query["specialty_id"] = specialty_id
    docs = await db.vien_professional_areas_of_practice.find(query, {"_id": 0}).sort("sort_order", 1).to_list(500)
    return docs


@api.get("/professionals")
async def professionals_list(q: Optional[str] = None, sphere_id: Optional[str] = None,
                             area_id: Optional[str] = None, specialty_id: Optional[str] = None,
                             accepting_patients: Optional[bool] = None,
                             user: dict = Depends(require_roles(*PROF_VIEW_ROLES))):
    """Directory search across Professional Profiles regardless of VIen login status."""
    query = {}
    if sphere_id: query["sphere_id"] = sphere_id
    if area_id: query["area_id"] = area_id
    if specialty_id: query["specialty_id"] = specialty_id
    if accepting_patients is not None: query["accepting_patients"] = accepting_patients
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"surname": rx}, {"first_name": rx}, {"second_name": rx}, {"registration_number": rx}]
    docs = await db.professional_profiles.find(query).sort([("surname", 1), ("first_name", 1)]).limit(200).to_list(200)
    my_auth = set()
    if user.get("role") != "admin":
        async for a in db.professional_profile_editors.find(
                {"user_id": user["id"], "active": True, "permission_level": "EDIT_PROFILE"}, {"professional_id": 1}):
            my_auth.add(a["professional_id"])
    out = []
    for d in docs:
        pub = _prof_public(d)
        pub["can_edit"] = True if user.get("role") == "admin" else (
            (d.get("linked_user_id") == user["id"]) or (d["id"] in my_auth))
        out.append(pub)
    return out


PROF_SELF_ROLES = ("admin", "physician")  # may manage their OWN professional profile


@api.get("/professionals/me")
async def professionals_get_me(user: dict = Depends(require_roles(*PROF_SELF_ROLES))):
    """The professional profile linked to the current user (None if not yet created)."""
    d = await db.professional_profiles.find_one({"linked_user_id": user["id"]})
    return {"profile": _prof_public(d) if d else None}


@api.put("/professionals/me")
async def professionals_upsert_me(body: ProfessionalBody, user: dict = Depends(require_roles(*PROF_SELF_ROLES))):
    """A physician (or admin) creates/updates their OWN professional profile only.
    Cannot touch other profiles; linkage to the user is enforced server-side."""
    if not (body.surname or "").strip():
        raise HTTPException(status_code=400, detail="Surname is required.")
    _validate_public_contact(body)
    now = now_iso()
    body_dict = body.model_dump()
    for hk in _HIGH_RISK_FIELDS:  # never accept linked_user_id/id/role/etc from the browser
        body_dict.pop(hk, None)
    existing = await db.professional_profiles.find_one({"linked_user_id": user["id"]})
    if existing:
        upd = {k: v for k, v in body_dict.items() if v is not None}
        diff = {k: {"before": existing.get(k), "after": v} for k, v in upd.items() if existing.get(k) != v}
        upd["updated_at"] = now
        await db.professional_profiles.update_one({"id": existing["id"]}, {"$set": upd})
        await audit("professional_self_update", "professional", existing["id"], user,
                    meta={"edit_source": "SELF", "fields_changed": list(diff.keys()), "diff": diff})
        return _prof_public({**existing, **upd})
    doc = {"id": str(uuid.uuid4()), **body_dict,
           "credential_ids": body.credential_ids or [], "language_ids": body.language_ids or [],
           "areas_of_practice_ids": body.areas_of_practice_ids or [],
           "practice_type_ids": body.practice_type_ids or [],
           "primary_care_model_ids": body.primary_care_model_ids or [],
           "organization_ids": body.organization_ids or [],
           "linked_user_id": user["id"], "created_by": user.get("name"), "created_at": now, "updated_at": now}
    try:
        await db.professional_profiles.insert_one({**doc})
    except DuplicateKeyError:
        # Race / double-submit: a profile for this user was created concurrently — return it.
        again = await db.professional_profiles.find_one({"linked_user_id": user["id"]})
        if again:
            return _prof_public(again)
        raise
    await audit("professional_profile_created", "professional", doc["id"], user, meta={"edit_source": "SELF"})
    return _prof_public(doc)


@api.get("/professionals/authz/user-search")
async def professionals_user_search(q: Optional[str] = None, user: dict = Depends(require_roles("admin"))):
    """Admin picker for granting authorized editors — searches EXISTING VIen users
    (never creates users, never grants by free-text email alone)."""
    query = {"role": {"$ne": "patient"}}
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"name": rx}, {"email": rx}, {"username": rx}]
    users = await db.users.find(query).sort("name", 1).limit(25).to_list(25)
    org_ids = list({u.get("organization_id") for u in users if u.get("organization_id")})
    org_names = {}
    if org_ids:
        async for o in db.organizations.find({"id": {"$in": org_ids}}, {"_id": 0, "id": 1, "organization_name": 1}):
            org_names[o["id"]] = o.get("organization_name")
    return [{
        "id": str(u["_id"]), "name": u.get("name"), "email": u.get("email"),
        "role": u.get("role"), "organization_id": u.get("organization_id"),
        "organization_name": org_names.get(u.get("organization_id")),
    } for u in users]


@api.get("/professionals/{prof_id}")
async def professionals_get(prof_id: str, user: dict = Depends(require_roles(*PROF_VIEW_ROLES))):
    d = await db.professional_profiles.find_one({"id": prof_id})
    if not d:
        raise HTTPException(status_code=404, detail="Professional not found.")
    pub = _prof_public(d)
    editors_count = await db.professional_profile_editors.count_documents(
        {"professional_id": prof_id, "active": True, "permission_level": "EDIT_PROFILE"})
    src = await _edit_source(user, d)
    pub["can_edit"] = bool(src)
    pub["edit_source"] = src
    pub["management_label"] = _management_label(d, editors_count > 0)
    pub["can_manage_editors"] = user.get("role") == "admin"
    return pub


@api.post("/professionals")
async def professionals_create(body: ProfessionalBody, user: dict = Depends(require_roles(*PROF_EDIT_ROLES))):
    """Create a Professional Profile (Directory Contact by default; VIen User linkage is a
    later flow). Duplicate-warning is advisory only — never auto-merges."""
    if not (body.surname or "").strip():
        raise HTTPException(status_code=400, detail="Surname is required.")
    _validate_public_contact(body)
    now = now_iso()
    doc = {"id": str(uuid.uuid4()), **body.model_dump(),
           "credential_ids": body.credential_ids or [], "language_ids": body.language_ids or [],
           "areas_of_practice_ids": body.areas_of_practice_ids or [],
           "practice_type_ids": body.practice_type_ids or [],
           "primary_care_model_ids": body.primary_care_model_ids or [],
           "organization_ids": body.organization_ids or [],
           "linked_user_id": None, "created_by": user.get("name"), "created_at": now, "updated_at": now}
    await db.professional_profiles.insert_one({**doc})
    await audit("professional_create", "professional", doc["id"], user)
    return _prof_public(doc)


@api.patch("/professionals/{prof_id}")
async def professionals_update(prof_id: str, body: ProfessionalBody, user: dict = Depends(require_roles(*PROF_VIEW_ROLES))):
    """Edit a Professional Profile. Server-side authorization: Admin, the linked
    professional (SELF), or a user with an active EDIT_PROFILE authorization."""
    d = await db.professional_profiles.find_one({"id": prof_id})
    if not d:
        raise HTTPException(status_code=404, detail="Professional not found.")
    source = await _edit_source(user, d)
    if not source:
        raise HTTPException(status_code=403, detail="You are not authorized to edit this professional profile.")
    _validate_public_contact(body)
    body_dict = body.model_dump()
    for hk in _HIGH_RISK_FIELDS:
        body_dict.pop(hk, None)
    upd = {k: v for k, v in body_dict.items() if v is not None}
    diff = {k: {"before": d.get(k), "after": v} for k, v in upd.items() if d.get(k) != v}
    upd["updated_at"] = now_iso()
    await db.professional_profiles.update_one({"id": prof_id}, {"$set": upd})
    await audit("professional_update", "professional", prof_id, user,
                meta={"edit_source": source, "actor_organization_id": user.get("organization_id"),
                      "fields_changed": list(diff.keys()), "diff": diff})
    return _prof_public({**d, **upd})


# ---------- Ownership: Admin links a VIen user to a Professional Profile (explicit, audited) ----------
@api.put("/professionals/{prof_id}/link-user")
async def professionals_link_user(prof_id: str, body: LinkUserBody, user: dict = Depends(require_roles("admin"))):
    d = await db.professional_profiles.find_one({"id": prof_id})
    if not d:
        raise HTTPException(status_code=404, detail="Professional not found.")
    new_uid = None
    if body.user_id:
        try:
            u = await db.users.find_one({"_id": ObjectId(body.user_id)})
        except Exception:
            u = None
        if not u or u.get("role") == "patient":
            raise HTTPException(status_code=400, detail="Select an existing non-patient VIen user.")
        clash = await db.professional_profiles.find_one({"linked_user_id": body.user_id, "id": {"$ne": prof_id}})
        if clash:
            raise HTTPException(status_code=409, detail="That user is already linked to another professional profile.")
        new_uid = body.user_id
    await db.professional_profiles.update_one({"id": prof_id}, {"$set": {"linked_user_id": new_uid, "updated_at": now_iso()}})
    await audit("professional_link_user", "professional", prof_id, user,
                old_status=d.get("linked_user_id"), new_status=new_uid, meta={"edit_source": "ADMIN"})
    return _prof_public({**d, "linked_user_id": new_uid})


# ---------- Authorized editors (Admin-managed) ----------
@api.get("/professionals/{prof_id}/editors")
async def professionals_list_editors(prof_id: str, user: dict = Depends(require_roles("admin"))):
    rows = await db.professional_profile_editors.find(
        {"professional_id": prof_id, "active": True}, {"_id": 0}).sort("granted_at", -1).to_list(200)
    for r in rows:
        try:
            u = await db.users.find_one({"_id": ObjectId(r["user_id"])})
            r["user_name"] = u.get("name") if u else None
            r["user_email"] = u.get("email") if u else None
            r["user_role"] = u.get("role") if u else None
        except Exception:
            r["user_name"] = None
        if r.get("organization_id"):
            o = await db.organizations.find_one({"id": r["organization_id"]}, {"_id": 0, "organization_name": 1})
            r["organization_name"] = (o or {}).get("organization_name")
    return rows


@api.post("/professionals/{prof_id}/editors")
async def professionals_grant_editor(prof_id: str, body: EditorGrantBody, user: dict = Depends(require_roles("admin"))):
    d = await db.professional_profiles.find_one({"id": prof_id})
    if not d:
        raise HTTPException(status_code=404, detail="Professional not found.")
    try:
        u = await db.users.find_one({"_id": ObjectId(body.user_id)})
    except Exception:
        u = None
    if not u or u.get("role") == "patient":
        raise HTTPException(status_code=400, detail="Select an existing non-patient VIen user.")
    level = body.permission_level if body.permission_level in ("VIEW", "EDIT_PROFILE") else "EDIT_PROFILE"
    existing = await db.professional_profile_editors.find_one(
        {"professional_id": prof_id, "user_id": body.user_id, "permission_level": level, "active": True})
    if existing:
        return {k: v for k, v in existing.items() if k != "_id"}
    doc = {"id": str(uuid.uuid4()), "professional_id": prof_id, "user_id": body.user_id,
           "organization_id": body.organization_id or u.get("organization_id"),
           "permission_level": level, "active": True,
           "granted_by": user.get("name"), "granted_at": now_iso(), "revoked_at": None}
    await db.professional_profile_editors.insert_one({**doc})
    await audit("professional_editor_grant", "professional", prof_id, user,
                meta={"edit_source": "ADMIN", "grantee_user_id": body.user_id, "permission_level": level})
    return doc


@api.delete("/professionals/{prof_id}/editors/{authorization_id}")
async def professionals_revoke_editor(prof_id: str, authorization_id: str, user: dict = Depends(require_roles("admin"))):
    r = await db.professional_profile_editors.find_one({"id": authorization_id, "professional_id": prof_id})
    if not r:
        raise HTTPException(status_code=404, detail="Authorization not found.")
    await db.professional_profile_editors.update_one(
        {"id": authorization_id}, {"$set": {"active": False, "revoked_at": now_iso()}})
    await audit("professional_editor_revoke", "professional", prof_id, user,
                meta={"edit_source": "ADMIN", "grantee_user_id": r.get("user_id")})
    return {"ok": True}


# ---------- Organization affiliations (Admin-managed; references only) ----------
@api.get("/professionals/{prof_id}/affiliations")
async def professionals_list_affiliations(prof_id: str, user: dict = Depends(require_roles(*PROF_VIEW_ROLES))):
    rows = await db.professional_organization_affiliations.find(
        {"professional_id": prof_id, "active": True}, {"_id": 0}).sort("created_at", -1).to_list(200)
    for r in rows:
        o = await db.organizations.find_one({"id": r["organization_id"]}, {"_id": 0, "organization_name": 1})
        r["organization_name"] = (o or {}).get("organization_name")
    return rows


@api.post("/professionals/{prof_id}/affiliations")
async def professionals_add_affiliation(prof_id: str, body: AffiliationBody, user: dict = Depends(require_roles("admin"))):
    d = await db.professional_profiles.find_one({"id": prof_id})
    if not d:
        raise HTTPException(status_code=404, detail="Professional not found.")
    o = await db.organizations.find_one({"id": body.organization_id})
    if not o:
        raise HTTPException(status_code=400, detail="Organization not found.")
    doc = {"id": str(uuid.uuid4()), "professional_id": prof_id, "organization_id": body.organization_id,
           "affiliation_type": body.affiliation_type, "active": True,
           "start_date": body.start_date, "end_date": body.end_date,
           "created_at": now_iso(), "created_by": user.get("name")}
    await db.professional_organization_affiliations.insert_one({**doc})
    await audit("professional_affiliation_add", "professional", prof_id, user,
                meta={"edit_source": "ADMIN", "organization_id": body.organization_id})
    return doc


@api.delete("/professionals/{prof_id}/affiliations/{affiliation_id}")
async def professionals_remove_affiliation(prof_id: str, affiliation_id: str, user: dict = Depends(require_roles("admin"))):
    r = await db.professional_organization_affiliations.find_one({"id": affiliation_id, "professional_id": prof_id})
    if not r:
        raise HTTPException(status_code=404, detail="Affiliation not found.")
    await db.professional_organization_affiliations.update_one(
        {"id": affiliation_id}, {"$set": {"active": False, "end_date": now_iso()}})
    await audit("professional_affiliation_remove", "professional", prof_id, user, meta={"edit_source": "ADMIN"})
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
    sex: Optional[str] = None  # "Male" | "Female" | "X" | "" (clear)


def _sex_value(body) -> tuple[bool, Optional[str]]:
    """Staff-entered sex. Returns (provided, value|None). Only canonical portal values accepted."""
    if body.sex is None:
        return False, None
    v = body.sex.strip()
    if v and v not in ("Male", "Female", "X"):
        raise HTTPException(status_code=400, detail="Sex must be Male, Female or X.")
    return True, (v or None)


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
    provided, sex_val = _sex_value(body)
    if provided:
        track("sex", sex_val)
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
    provided, sex_val = _sex_value(body)
    if provided:
        track("sex", sex_val)  # explicit canonical sex on the directory record (raw legacy sex_code untouched)
    hc_num_in = re.sub(r"\D", "", body.health_card_number or "") if body.health_card_number is not None else None
    hc_ver_in = re.sub(r"[^A-Za-z]", "", body.health_card_version or "").upper() if body.health_card_version is not None else None
    hc_unchanged = ((hc_num_in is None or hc_num_in == re.sub(r"\D", "", d.get("health_card_number") or ""))
                    and (hc_ver_in is None or hc_ver_in == (d.get("health_card_version_code") or "").upper()))
    # Legacy directory rows may lack a version code; only validate when the health card is actually being changed.
    if (body.health_card_number is not None or body.health_card_version is not None) and not hc_unchanged:
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



@api.get("/internal/health-card-updates")
async def internal_list_health_card_updates(user: dict = Depends(require_roles("staff", "admin", "physician"))):
    """Pending caregiver-submitted Health Card updates awaiting staff review (practice-scoped)."""
    docs = await db.patients.find(
        {**pscope(user), "pending_health_card": {"$ne": None}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "visita_patient_id": 1,
         "date_of_birth": 1, "pending_health_card": 1,
         "health_card_number": 1, "health_card_version": 1,
         "health_card_issue_date": 1, "health_card_expiry_date": 1}).to_list(200)
    out = []
    for p in docs:
        pend = p.get("pending_health_card") or {}
        out.append({
            "patient_id": p["id"],
            "patient_name": f"{p.get('last_name','')}, {p.get('first_name','')}".strip(", "),
            "visita_patient_id": p.get("visita_patient_id"),
            "date_of_birth": p.get("date_of_birth"),
            "current": {
                "display": identity_mod.format_health_card(p.get("health_card_number"), p.get("health_card_version")),
                "issue_date": p.get("health_card_issue_date"), "expiry_date": p.get("health_card_expiry_date"),
            },
            "submitted": {
                "display": pend.get("display"), "issue_date": pend.get("health_card_issue_date"),
                "expiry_date": pend.get("health_card_expiry_date"),
                "submitted_by_name": pend.get("submitted_by_name"),
                "relationship": pend.get("relationship"), "submitted_at": pend.get("submitted_at"),
            },
        })
    return out


@api.post("/internal/patients/{patient_id}/health-card/{action}")
async def internal_health_card_review(patient_id: str, action: str,
                                      user: dict = Depends(require_roles("staff", "admin", "physician"))):
    """Approve or reject a caregiver-submitted HEALTH CARD UPDATE pending proposal."""
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Invalid action.")
    p = await db.patients.find_one({"id": patient_id})
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    assert_practice(p, user)
    pending = p.get("pending_health_card")
    if not pending:
        raise HTTPException(status_code=400, detail="No pending Health Card update.")
    audit_meta = {
        "patient_id": patient_id,
        "acted_by": pending.get("submitted_by_name"),
        "acted_by_user_id": pending.get("submitted_by_user_id"),
        "on_behalf_of_patient_id": patient_id,
        "submitted_values": pending.get("display"),
        "submitted_at": pending.get("submitted_at"),
        "reviewed_by": user.get("name"), "reviewed_at": now_iso(),
    }
    if action == "reject":
        await db.patients.update_one({"id": patient_id}, {"$unset": {"pending_health_card": ""}, "$set": {"updated_at": now_iso()}})
        await audit("health_card_update_rejected", "patient", patient_id, user,
                    meta={**audit_meta, "decision": "declined",
                          "old_values": identity_mod.format_health_card(p.get("health_card_number"), p.get("health_card_version"))})
        await notify_patient(patient_id, "Health Card update not approved",
                             "Your Health Card update was reviewed and not approved. Your existing record remains active. Please contact the clinic.")
        return {"ok": True, "status": "rejected"}
    change = {"field": "health_card", "previous": identity_mod.format_health_card(p.get("health_card_number"), p.get("health_card_version")),
              "new": pending.get("display"), "changed_by": user["name"], "changed_at": now_iso(),
              "submitted_by": pending.get("submitted_by_name")}
    await db.patients.update_one({"id": patient_id}, {
        "$set": {"health_card_number": pending["health_card_number"], "health_card_version": pending["health_card_version"],
                 "health_card_issue_date": pending.get("health_card_issue_date"),
                 "health_card_expiry_date": pending.get("health_card_expiry_date"), "updated_at": now_iso()},
        "$unset": {"pending_health_card": ""},
        "$push": {"identity_history": change},
    })
    await audit("health_card_update_approved", "patient", patient_id, user,
                meta={**audit_meta, "decision": "approved", "old_values": change["previous"]})
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


@app.middleware("http")
async def maintenance_mode_gate(request: Request, call_next):
    """Maintenance mode never stops the server: infra probes, banner, login and the Developer portal keep
    working; everything else returns 503 for non-operator users."""
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api") or sys_mod.path_allowed(path):
        return await call_next(request)
    header = request.headers.get("Authorization", "")
    try:
        role = authlib.decode_token(header[7:]).get("role") if header.startswith("Bearer ") else None
    except Exception:
        role = None
    # Feature registry: OFF fails closed at the API; PILOT = internal roles only.
    ws_modules = None
    try:
        _pl = authlib.decode_token(header[7:]) if header.startswith("Bearer ") else {}
        if _pl.get("ws"):
            _m = await db.org_memberships.find_one({"id": _pl["ws"]}, {"modules": 1, "status": 1})
            ws_modules = (_m or {}).get("modules", []) if (_m or {}).get("status") == "ACTIVE" else []
    except Exception:
        ws_modules = None
    if ws_modules is not None and not net_mod.workspace_allowed(path, ws_modules):
        return JSONResponse(status_code=403, content={"detail": {"code": "WORKSPACE_MODULE_DENIED", "message": "This organization has not granted you access to this tool."}})
    feat = pc_mod.feature_for_path(path)
    if feat and role not in OPS_ROLES:
        st = pc_mod.feature_state((await pc_mod.published())["config"], feat)
        if st == "OFF" or (st == "PILOT" and role not in pc_mod.INTERNAL_ROLES):
            return JSONResponse(status_code=403, content={"detail": {"code": "FEATURE_OFF", "feature": feat,
                                                                     "message": f"{pc_mod.FEATURES[feat]} is currently unavailable."}})
    state = await sys_mod.get_state()
    if not state["maintenance"]["on"]:
        return await call_next(request)
    if role in OPS_ROLES:
        return await call_next(request)
    return JSONResponse(status_code=503, content={"detail": {"code": "MAINTENANCE_MODE", "message": state["maintenance"]["message"]}})


api.include_router(work_mod.build_router(require_roles))
api.include_router(prof_mod.build_router(get_current_user, get_patient_record, validate_hc_dates, require_roles))
app.include_router(api)

_DEFAULT_CORS = "https://visitaemr.com,https://www.visitaemr.com,https://visita-admin.preview.emergentagent.com"
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", _DEFAULT_CORS).split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


BOOTSTRAP = {"status": "pending", "ready": False, "steps": {}, "attempts": 0}


async def _bootstrap_step(name, coro_factory, timeout=120) -> bool:
    """Run one startup step with a hard deadline. Returns success; never raises."""
    try:
        await asyncio.wait_for(coro_factory(), timeout=timeout)
        BOOTSTRAP["steps"][name] = "ok"
        return True
    except Exception as e:
        BOOTSTRAP["steps"][name] = f"{type(e).__name__}: {e}"[:200]
        logger.warning(f"[bootstrap] {name} failed: {type(e).__name__}: {e}")
        return False


async def _ensure_core_indexes():
    await ib_mod.ensure_missing(db, "users", [{"keys": [("email", 1)], "unique": True}])
    await ib_mod.ensure_missing(db, "patients", [{"keys": [("id", 1)]}])
    # One canonical self-owned profile per user (null linked_user_id excluded).
    await ib_mod.ensure_missing(db, "professional_profiles", [{"keys": [("linked_user_id", 1)], "unique": True,
                                                              "partialFilterExpression": {"linked_user_id": {"$type": "string"}}}])
    await ib_mod.ensure_missing(db, "referrals", [{"keys": [("ready_to_fax", 1), ("faxed", 1)]}])


async def _mongo_ping():
    await db.command("ping")


# listIndexes-first everywhere: ensure_missing() creates ONLY absent indexes, never alters existing ones.
# CRITICAL steps gate readiness: Mongo reachable + every integrity index (incl. the unique
# double-booking / same-day / one-active-visit guards) + create-if-missing seed.
CRITICAL_STEPS = [
    ("mongo_ping", _mongo_ping), ("core_indexes", _ensure_core_indexes),
    # Slot reservation layer: unique (practice_id, slot_start) is the final double-booking guard.
    # Index only — NO data backfill at startup (see backfill_slot_locks.py).
    ("slots_indexes", lambda: slots_mod.ensure_indexes(db)), ("appt_guard_indexes", lambda: guard_mod.ensure_indexes(db)),
    ("visits_indexes", lambda: visits_mod.ensure_indexes(db)), ("history_indexes", lambda: history_mod.ensure_indexes(db)),
    ("diag_catalog_indexes", lambda: diag_mod.ensure_indexes(db)), ("diagnosis_indexes", lambda: dx_mod.ensure_indexes(db)),
    ("service_indexes", lambda: svc_mod.ensure_indexes(db)),
    ("seed", lambda: seed_all(db, authlib)),
]
# NON-CRITICAL (never gate readiness): audit_logs performance indexes, object-storage warm-up.
NON_CRITICAL_STEPS = [("audit_indexes", lambda: audit_mod.ensure_indexes(db), 150),
                      ("storage", lambda: asyncio.to_thread(storage.init_storage), 8)]


async def _bootstrap():
    """Runs in the BACKGROUND after uvicorn binds :8001 (liveness up immediately). Readiness
    (/health) stays 503 until every CRITICAL step succeeds; failed steps are retried every 15s.
    Optional services (object storage warm-up) fail-soft — storage is lazy on first use."""
    BOOTSTRAP["status"] = "running"
    while not BOOTSTRAP["ready"]:
        BOOTSTRAP["attempts"] += 1
        ok = True
        for name, factory in CRITICAL_STEPS:
            if BOOTSTRAP["steps"].get(name) == "ok":
                continue
            if not await _bootstrap_step(name, factory, timeout=120):
                ok = False
                break
        if ok:
            BOOTSTRAP["ready"] = True
            break
        await asyncio.sleep(15)
    for name, factory, timeout in NON_CRITICAL_STEPS:
        await _bootstrap_step(name, factory, timeout=timeout)
    BOOTSTRAP["status"] = "complete"
    logger.info(f"Startup complete — ready after {BOOTSTRAP['attempts']} attempt(s); bootstrap {BOOTSTRAP['steps']}")


def _health_payload():
    return {"status": "ok" if BOOTSTRAP["ready"] else "starting", "ready": BOOTSTRAP["ready"],
            "bootstrap": BOOTSTRAP["status"], "attempts": BOOTSTRAP["attempts"],
            "steps": {k: ("ok" if v == "ok" else "failed") for k, v in BOOTSTRAP["steps"].items()}, "time": now_iso()}


@app.get("/health/live")
async def health_live():
    """Liveness: process is up (always 200 once uvicorn is bound)."""
    return {"status": "alive", "time": now_iso()}


@app.get("/health")
@app.get("/api/health")
async def health(response: Response):
    """Readiness: 200 only when Mongo + critical bootstrap are complete, else 503."""
    if not BOOTSTRAP["ready"]:
        response.status_code = 503
    return _health_payload()


@app.on_event("startup")
async def startup():
    asyncio.create_task(_bootstrap())


@app.on_event("shutdown")
async def shutdown():
    pass
