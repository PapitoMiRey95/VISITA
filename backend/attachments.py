"""Shared private-file attachment service (Phase 1).

Common upload/list/download/soft-delete for internal clinical attachments,
built on the existing object-storage abstraction (storage.py). PHI-safe:
file bytes live in object storage, metadata in Mongo, and every access goes
through an authenticated backend route — never a public URL.

Supported entities (internal, staff/physician/admin only): imaging, bloodwork,
patient messages. Referral PDFs keep their existing dedicated flow untouched.
"""
import uuid

from fastapi import HTTPException, Response

import storage
from db import audit, now_iso

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024  # 15 MB

# ext -> (canonical content-type)
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

# entity_type -> Mongo collection that must own the record
ENTITY_COLLECTIONS = {
    "imaging": "imaging_requests",
    "bloodwork": "bloodwork_requests",
    "message": "patient_messages",
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


def _public(doc: dict) -> dict:
    """Metadata safe to return to internal clients (no storage_path leak)."""
    return {
        "id": doc["id"],
        "original_filename": doc.get("original_filename"),
        "content_type": doc.get("content_type"),
        "size": doc.get("size"),
        "uploaded_by": doc.get("uploaded_by"),
        "uploaded_at": doc.get("uploaded_at"),
        "entity_type": doc.get("entity_type"),
        "entity_id": doc.get("entity_id"),
    }


async def store_attachment(db, file, entity_type: str, entity_id: str, user: dict) -> dict:
    if entity_type not in ENTITY_COLLECTIONS:
        raise HTTPException(status_code=400, detail="Unsupported attachment type.")
    parent = await db[ENTITY_COLLECTIONS[entity_type]].find_one({"id": entity_id})
    if not parent:
        raise HTTPException(status_code=404, detail="The linked record was not found.")

    ext = _resolve_ext(file.content_type, file.filename)
    content_type = _ALLOWED[ext]
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The selected file is empty.")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 15 MB.")

    path = f"{storage.APP_NAME}/{entity_type}/{uuid.uuid4()}.{ext}"
    result = storage.put_object(path, data, content_type)

    doc = {
        "id": f"att_{uuid.uuid4().hex[:16]}",
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": len(data),
        "uploaded_by": user.get("name"),
        "uploaded_by_id": user.get("id"),
        "uploaded_at": now_iso(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "is_deleted": False,
    }
    await db.attachments.insert_one({**doc})
    await audit("attachment_upload", entity_type, entity_id, user,
                meta={"attachment_id": doc["id"], "filename": file.filename, "size": len(data)})
    return _public(doc)


async def list_attachments(db, entity_type: str, entity_id: str) -> list:
    if entity_type not in ENTITY_COLLECTIONS:
        raise HTTPException(status_code=400, detail="Unsupported attachment type.")
    docs = await db.attachments.find(
        {"entity_type": entity_type, "entity_id": entity_id, "is_deleted": {"$ne": True}}
    ).sort("uploaded_at", 1).to_list(500)
    return [_public(d) for d in docs]


async def serve_attachment(db, att_id: str) -> Response:
    doc = await db.attachments.find_one({"id": att_id, "is_deleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    data, ctype = storage.get_object(doc["storage_path"])
    ctype = doc.get("content_type") or ctype
    fname = doc.get("original_filename") or "attachment"
    return Response(content=data, media_type=ctype,
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


async def soft_delete_attachment(db, att_id: str, user: dict) -> dict:
    doc = await db.attachments.find_one({"id": att_id})
    if not doc or doc.get("is_deleted"):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    await db.attachments.update_one(
        {"id": att_id},
        {"$set": {"is_deleted": True, "deleted_at": now_iso(), "deleted_by": user.get("name")}})
    await audit("attachment_removed", doc.get("entity_type"), doc.get("entity_id"), user,
                meta={"attachment_id": att_id, "filename": doc.get("original_filename")})
    return {"ok": True, "id": att_id}
