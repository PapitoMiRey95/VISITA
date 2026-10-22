"""Clinic Profile — the practice's network identity (phones, emails, address, hours, services). Stored on the
`practices` document so it is the single source reused by the portal, templates and public VIen directory."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import audit, db, now_iso

PUBLIC_FIELDS = ("slug", "clinic_name", "physician_name", "clinic_phone", "clinic_fax", "clinic_email", "website",
                 "clinic_address", "address_struct", "office_hours", "hours", "services", "languages", "about",
                 "accepting_new_patients", "emergency_notice", "profile_updated_at")


class AddressStruct(BaseModel):
    street_number: Optional[str] = ""
    street_name: Optional[str] = ""
    street_type: Optional[str] = ""
    street_direction: Optional[str] = ""
    unit: Optional[str] = ""
    postal_code: Optional[str] = ""
    city: Optional[str] = ""
    province: Optional[str] = "ON"
    country: Optional[str] = "Canada"


class ClinicProfileBody(BaseModel):
    clinic_name: Optional[str] = None
    physician_name: Optional[str] = None
    clinic_phone: Optional[str] = None
    clinic_fax: Optional[str] = None
    clinic_email: Optional[str] = None
    website: Optional[str] = None
    address_struct: Optional[AddressStruct] = None
    clinic_address: Optional[str] = None          # legacy free text; kept when no structured address is given
    office_hours: Optional[str] = None            # free-text summary (legacy templates use it)
    hours: Optional[dict] = None                  # {mon: "9:00-17:00", ...}
    services: Optional[List[str]] = None
    languages: Optional[List[str]] = None
    about: Optional[str] = None
    accepting_new_patients: Optional[bool] = None
    emergency_notice: Optional[str] = None


def assemble_address(a: dict) -> str:
    core = " ".join(x for x in (a.get("street_number"), a.get("street_name"), a.get("street_type"), a.get("street_direction")) if (x or "").strip())
    if (a.get("unit") or "").strip():
        core = f"{core}, {a['unit'].strip()}" if core else a["unit"].strip()
    tail = ", ".join(x for x in (a.get("city"), a.get("province")) if (x or "").strip())
    parts = [p for p in (core, tail, (a.get("postal_code") or "").strip()) if p]
    return ", ".join(parts)


def public_view(p: dict) -> dict:
    return {k: p.get(k) for k in PUBLIC_FIELDS}


def build_router(require_roles, clinic_roles) -> APIRouter:
    r = APIRouter()

    async def _practice_for(user: dict) -> dict:
        p = await db.practices.find_one({"id": user.get("practice_id"), "active": True}, {"_id": 0}) if user.get("practice_id") else None
        if not p:
            raise HTTPException(status_code=404, detail="No active practice is associated with your account.")
        return p

    @r.get("/internal/clinic-profile")
    async def get_profile(user: dict = Depends(require_roles(*clinic_roles))):
        return public_view(await _practice_for(user))

    @r.put("/internal/clinic-profile")
    async def put_profile(body: ClinicProfileBody, user: dict = Depends(require_roles("admin", "physician"))):
        p = await _practice_for(user)
        upd = {k: v for k, v in body.model_dump(exclude_none=True).items()}
        if "address_struct" in upd:
            assembled = assemble_address(upd["address_struct"])
            if assembled:
                upd["clinic_address"] = assembled
        for k in ("clinic_name", "clinic_phone", "clinic_email", "website", "clinic_fax", "physician_name"):
            if k in upd and isinstance(upd[k], str):
                upd[k] = upd[k].strip()
        if "services" in upd:
            upd["services"] = [s.strip() for s in upd["services"] if s and s.strip()]
        if "languages" in upd:
            upd["languages"] = [s.strip() for s in upd["languages"] if s and s.strip()]
        upd["profile_updated_at"] = now_iso()
        await db.practices.update_one({"id": p["id"]}, {"$set": upd})
        # keep the legacy clinic settings (used by message templates) in step with the network profile
        sync = {k: upd[k] for k in ("clinic_name", "physician_name", "clinic_phone", "clinic_address", "office_hours") if k in upd}
        if sync:
            await db.settings.update_one({"id": "clinic"}, {"$set": {**sync, "id": "clinic"}}, upsert=True)
        await audit("clinic_profile_updated", "practice", p["id"], user, meta={"fields": sorted(upd.keys())})
        return public_view(await db.practices.find_one({"id": p["id"]}, {"_id": 0}))

    @r.get("/practices/{slug}/profile")
    async def public_profile(slug: str):
        p = await db.practices.find_one({"slug": slug, "active": True}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Practice not found.")
        return public_view(p)

    return r
