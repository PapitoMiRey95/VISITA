"""Private / Uninsured billing service (Phase 2).

Invoices + Interac e-Transfer payment-proof handling for private/uninsured
patients. PHI/PII-safe: proof file bytes live in object storage, metadata in
Mongo, and every access goes through an authenticated backend route that
enforces ownership — never a public URL. The uploaded receipt is *evidence*
submitted by the patient, not proof that payment actually cleared; only
ADMIN/STAFF may verify receipt and mark an invoice PAID.
"""
import uuid

from fastapi import HTTPException, Response

import storage
from db import now_iso

MAX_PROOF_BYTES = 15 * 1024 * 1024  # 15 MB — consistent with the attachment service

INVOICE_STATUSES = {"DRAFT", "ISSUED", "PAYMENT_SUBMITTED", "PAID", "VOID"}
PAYMENT_MODES = {"NO_PAYMENT_REQUIRED", "PREPAYMENT_REQUIRED", "INVOICE_AFTER_SERVICE"}
# Request-level payment status mirror (separate state machine from appointment status).
PAYMENT_STATUS = {"NONE", "PENDING", "PAYMENT_SUBMITTED", "PAID"}

_ALLOWED = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
_MIME_TO_EXT = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
}


def _resolve_ext(content_type: str, filename: str) -> str:
    ext = _MIME_TO_EXT.get((content_type or "").lower())
    if ext:
        return ext
    fn = (filename or "").lower()
    if fn.endswith(".pdf"):
        return "pdf"
    if fn.endswith((".jpg", ".jpeg")):
        return "jpg"
    if fn.endswith(".png"):
        return "png"
    raise HTTPException(status_code=400, detail="Only PDF, JPG, or PNG files are accepted.")


def normalize_amount(amount) -> float:
    try:
        val = round(float(amount), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Please enter a valid amount.")
    if val <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    if val > 1_000_000:
        raise HTTPException(status_code=400, detail="Amount is unreasonably large.")
    return val


# ---- Direct 3rd Party Billing --------------------------------------------
# Two billing methods: SET_SERVICE (fixed predefined service) and TIME_BASED
# (hourly rate × time). Backend is the source of truth for every calculation.
BILLING_METHODS = {"SET_SERVICE", "TIME_BASED"}
MAX_WHOLE_HOURS = 50

# Internal-guidance classification for a catalogue service. Only NO_CHARGE
# blocks invoicing; the others are advisory (still require a configured amount).
BILLING_CLASSIFICATIONS = {
    "PATIENT_THIRD_PARTY_BILLABLE", "THIRD_PARTY_EXTERNAL_FEE",
    "NO_CHARGE", "REVIEW_REQUIRED",
}

# Human minutes -> hour multiplier. Values are fixed by the billing spec (note
# 25 min = 0.416) so frontend and backend never disagree.
PARTIAL_MULTIPLIERS = {
    0: 0.0, 5: 0.08, 10: 0.17, 15: 0.25, 20: 0.33, 25: 0.416, 30: 0.50,
    35: 0.58, 40: 0.67, 45: 0.75, 50: 0.83, 55: 0.92,
}


def normalize_rate(rate) -> float:
    try:
        val = round(float(rate), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Please set a valid hourly rate.")
    if val <= 0:
        raise HTTPException(status_code=400, detail="Hourly rate must be greater than zero.")
    if val > 100_000:
        raise HTTPException(status_code=400, detail="Hourly rate is unreasonably large.")
    return val


def _validate_time(whole_hours, partial_minutes):
    try:
        wh = int(whole_hours)
        pm = int(partial_minutes)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid hours worked.")
    if wh < 0 or wh > MAX_WHOLE_HOURS:
        raise HTTPException(status_code=400, detail=f"Hours worked must be between 0 and {MAX_WHOLE_HOURS}.")
    if pm not in PARTIAL_MULTIPLIERS:
        raise HTTPException(status_code=400, detail="Invalid partial hours selection.")
    return wh, pm, PARTIAL_MULTIPLIERS[pm]


def compute_time_based(hourly_rate, whole_hours, partial_minutes, minimum_fee=None) -> dict:
    """Authoritative time-based calculation:
    total = hourly_rate × (whole_hours + partial_multiplier), then a per-service
    minimum fee is applied if the computed total is lower."""
    rate = normalize_rate(hourly_rate)
    wh, pm, mult = _validate_time(whole_hours, partial_minutes)
    total = round(rate * (wh + mult), 2)
    min_fee = normalize_amount(minimum_fee) if minimum_fee not in (None, "") else None
    min_applied = False
    if min_fee is not None and total < min_fee:
        total, min_applied = min_fee, True
    if total <= 0:
        raise HTTPException(status_code=400, detail="Total must be greater than zero — select time or configure a minimum fee.")
    return {"hourly_rate_used": rate, "whole_hours": wh, "partial_minutes": pm,
            "partial_multiplier": mult, "calculated_total": total,
            "minimum_fee": min_fee, "minimum_fee_applied": min_applied}


def resolve_set_service(services: list, code: str) -> dict:
    """Look up a SET_SERVICE by code. Rejects time-based services, inactive
    services, No-Charge services, and services with no configured amount."""
    for s in services or []:
        if str(s.get("code")) == str(code):
            if (s.get("billing_type") or "SET_SERVICE") == "TIME_BASED":
                raise HTTPException(status_code=400, detail="This is a time-based service — use Time-Based billing.")
            if not s.get("active", True):
                raise HTTPException(status_code=400, detail="That service is inactive and cannot be invoiced.")
            if s.get("billing_classification") == "NO_CHARGE":
                raise HTTPException(status_code=400, detail="This service is marked No Charge / Unremunerated and cannot generate an invoice.")
            amt = s.get("amount")
            if amt in (None, ""):
                raise HTTPException(status_code=400, detail="This service has no configured amount yet. Set it in Clinic Settings.")
            return {"service_code": s.get("code"),
                    "service_description": (s.get("description") or "").strip(),
                    "amount": normalize_amount(amt)}
    raise HTTPException(status_code=400, detail="Select a valid predefined service.")


def _proof_meta(doc: dict) -> dict:
    """Proof metadata safe for clients (no storage_path leak)."""
    if not doc:
        return None
    return {
        "attachment_id": doc.get("attachment_id"),
        "original_filename": doc.get("original_filename"),
        "content_type": doc.get("content_type"),
        "size": doc.get("size"),
        "uploaded_at": doc.get("uploaded_at"),
    }


def _billing_context(coverage) -> str:
    """Human label separating the patient's coverage from the invoice reason."""
    if coverage == "ohip":
        return "OHIP PATIENT — UNINSURED SERVICE"
    return "PRIVATE / UNINSURED SERVICE"


# ---- Patient-facing "why is there a fee?" resolver (read-only, additive) -----
# Derives a contextual explanation purely from fields already stored on the
# invoice (is_no_show, patient_coverage, service_code→category/classification).
# No DB writes, no schema/catalogue/billing-logic changes. Always returns a
# safe value; falls back to a coverage-aware generic message when unknown.
_REASON_TITLE = "Why is there a fee?"

_CATEGORY_REASONS = {
    "MEDICAL_NOTES": "Doctor's notes and medical certificates are administrative documents and are not covered by OHIP. This fee covers preparing and issuing your requested note.",
    "MEDICAL_RECORDS_ADMIN": "Copying, transferring, or summarising your medical records is an administrative service that is not covered by OHIP. This fee covers the time to prepare your records.",
    "SCHOOL_EMPLOYMENT_FITNESS": "Forms and assessments requested for school, employment, or activities are not covered by OHIP. This fee covers completing and signing your requested form.",
    "DRIVING": "Driver's medical examinations and transportation forms are not covered by OHIP. This fee covers completing your requested assessment or form.",
    "DISABILITY_BENEFITS": "Disability and benefit forms are not covered by OHIP. This fee covers reviewing your file and completing the requested form.",
    "INSURANCE_THIRD_PARTY": "This is a fee for a form or report requested by or for a third party (such as an insurer or employer), which is not insured by OHIP.",
    "PRESCRIPTION_REQUEST": "This is a fee for a prescription-related administrative request that is not covered by OHIP.",
}

_REASON_MISSED_APPT = "This is a fee for a missed or late-cancelled appointment. The time was reserved for you and could not be offered to another patient. It is not an insured medical service and is billed directly to you."
_REASON_THIRD_PARTY_EXTERNAL = "This charge follows a third-party or program fee schedule (for example an insurer, employer, or government program) rather than being billed through OHIP."
_REASON_PRIVATE_PAY = "You are registered as a private-pay patient, so this service is billed directly to you rather than through OHIP."
_REASON_GENERIC_OHIP = "This invoice is for a service that is not covered under your OHIP coverage."
_REASON_GENERIC_NONOHIP = "This invoice is for a service that is not covered by public health insurance and is billed directly to you."

_PRIVATE_COVERAGE = {"private", "uninsured", "tourist"}


def resolve_invoice_reason(doc: dict, category=None, classification=None) -> dict:
    """Return {reason_title, reason_message} from existing invoice/service fields.
    Priority: missed appointment → category → third-party fee rule → coverage →
    generic fallback. Never raises; always returns a usable message."""
    coverage = doc.get("patient_coverage")
    # 1) Missed / late-cancelled appointment — never described as OHIP-uninsured medical service.
    if doc.get("is_no_show") or category == "APPOINTMENT":
        return {"reason_title": _REASON_TITLE, "reason_message": _REASON_MISSED_APPT}
    # 2) Category-specific explanation from the existing catalogue.
    if category in _CATEGORY_REASONS:
        return {"reason_title": _REASON_TITLE, "reason_message": _CATEGORY_REASONS[category]}
    # 3) Third-party / external program fee rule.
    if classification == "THIRD_PARTY_EXTERNAL_FEE":
        return {"reason_title": _REASON_TITLE, "reason_message": _REASON_THIRD_PARTY_EXTERNAL}
    # 4) Coverage-based fallback (private/uninsured/tourist vs OHIP).
    if coverage in _PRIVATE_COVERAGE:
        return {"reason_title": _REASON_TITLE, "reason_message": _REASON_PRIVATE_PAY}
    if coverage == "ohip":
        return {"reason_title": _REASON_TITLE, "reason_message": _REASON_GENERIC_OHIP}
    # 5) Generic safe fallback (unknown coverage / MANUAL / unresolved).
    return {"reason_title": _REASON_TITLE, "reason_message": _REASON_GENERIC_NONOHIP}


def invoice_internal(doc: dict) -> dict:
    """Full billing view for staff/physician/admin (no storage paths)."""
    coverage = doc.get("patient_coverage")
    return {
        "id": doc["id"],
        "invoice_number": doc.get("invoice_number"),
        "patient_id": doc.get("patient_id"),
        "patient_name": doc.get("patient_name"),
        "patient_coverage": coverage,
        "billing_context": _billing_context(coverage),
        "private_request_id": doc.get("private_request_id"),
        "appointment_id": doc.get("appointment_id"),
        "is_no_show": doc.get("is_no_show", False),
        "billing_method": doc.get("billing_method"),
        "hourly_rate_used": doc.get("hourly_rate_used"),
        "whole_hours": doc.get("whole_hours"),
        "partial_minutes": doc.get("partial_minutes"),
        "partial_multiplier": doc.get("partial_multiplier"),
        "service_code": doc.get("service_code"),
        "service_description": doc.get("service_description"),
        "amount": doc.get("amount"),
        "currency": doc.get("currency", "CAD"),
        "status": doc.get("status"),
        "payment_mode": doc.get("payment_mode"),
        "issue_date": doc.get("issue_date"),
        "created_by": doc.get("created_by"),
        "created_at": doc.get("created_at"),
        "issued_at": doc.get("issued_at"),
        "payment_submitted_at": doc.get("payment_submitted_at"),
        "paid_at": doc.get("paid_at"),
        "voided_at": doc.get("voided_at"),
        "internal_note": doc.get("internal_note"),
        "payment_proof": _proof_meta(doc.get("payment_proof")),
        "updated_at": doc.get("updated_at"),
    }


def invoice_public(doc: dict, etransfer_email: str = None, service_category=None, service_classification=None) -> dict:
    """Patient-facing view — no internal notes, includes payment instructions."""
    coverage = doc.get("patient_coverage")
    reason = resolve_invoice_reason(doc, service_category, service_classification)
    return {
        "id": doc["id"],
        "invoice_number": doc.get("invoice_number"),
        "private_request_id": doc.get("private_request_id"),
        "billing_context": _billing_context(coverage),
        "ohip_uninsured": coverage == "ohip",
        "reason_title": reason["reason_title"],
        "reason_message": reason["reason_message"],
        "billing_method": doc.get("billing_method"),
        "hourly_rate_used": doc.get("hourly_rate_used"),
        "whole_hours": doc.get("whole_hours"),
        "partial_minutes": doc.get("partial_minutes"),
        "partial_multiplier": doc.get("partial_multiplier"),
        "service_code": doc.get("service_code"),
        "service_description": doc.get("service_description"),
        "amount": doc.get("amount"),
        "currency": doc.get("currency", "CAD"),
        "status": doc.get("status"),
        "payment_mode": doc.get("payment_mode"),
        "issue_date": doc.get("issue_date"),
        "issued_at": doc.get("issued_at"),
        "payment_submitted_at": doc.get("payment_submitted_at"),
        "paid_at": doc.get("paid_at"),
        "voided_at": doc.get("voided_at"),
        "payment_proof": _proof_meta(doc.get("payment_proof")),
        "etransfer_email": etransfer_email,
        "payment_required": doc.get("payment_mode") in {"PREPAYMENT_REQUIRED", "INVOICE_AFTER_SERVICE"},
    }


async def store_payment_proof(db, file, invoice: dict, user: dict) -> dict:
    """Validate + store a payment-proof file in object storage, record metadata,
    and mark it the current proof for the invoice. Returns proof metadata."""
    ext = _resolve_ext(file.content_type, file.filename)
    content_type = _ALLOWED[ext]
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The selected file is empty.")
    if len(data) > MAX_PROOF_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 15 MB.")

    path = f"{storage.APP_NAME}/payment-proofs/{uuid.uuid4()}.{ext}"
    result = storage.put_object(path, data, content_type)

    doc = {
        "attachment_id": f"pay_{uuid.uuid4().hex[:16]}",
        "invoice_id": invoice["id"],
        "patient_id": invoice.get("patient_id"),
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": len(data),
        "uploaded_by": user.get("name") or user.get("email"),
        "uploaded_by_id": user.get("id"),
        "uploaded_at": now_iso(),
        "is_current": True,
    }
    # Retire any previous current proof for this invoice (preserve history).
    await db.payment_proofs.update_many(
        {"invoice_id": invoice["id"], "is_current": True},
        {"$set": {"is_current": False}})
    await db.payment_proofs.insert_one({**doc})
    return {k: v for k, v in doc.items() if k not in ("_id", "storage_path")}


async def serve_payment_proof(db, invoice_id: str, att_id: str) -> Response:
    """Stream a stored proof. Caller MUST have already authorized access."""
    doc = await db.payment_proofs.find_one({"attachment_id": att_id, "invoice_id": invoice_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Payment proof not found.")
    data, ctype = storage.get_object(doc["storage_path"])
    ctype = doc.get("content_type") or ctype
    fname = doc.get("original_filename") or "payment-proof"
    return Response(content=data, media_type=ctype,
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})
