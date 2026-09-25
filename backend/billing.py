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


def invoice_internal(doc: dict) -> dict:
    """Full billing view for staff/physician/admin (no storage paths)."""
    return {
        "id": doc["id"],
        "invoice_number": doc.get("invoice_number"),
        "patient_id": doc.get("patient_id"),
        "patient_name": doc.get("patient_name"),
        "private_request_id": doc.get("private_request_id"),
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


def invoice_public(doc: dict, etransfer_email: str = None) -> dict:
    """Patient-facing view — no internal notes, includes payment instructions."""
    return {
        "id": doc["id"],
        "invoice_number": doc.get("invoice_number"),
        "private_request_id": doc.get("private_request_id"),
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
