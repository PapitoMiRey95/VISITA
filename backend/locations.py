"""VIen standardized professional / referral location model.
A location (address + routing context + per-location contact) belongs to an entity (professional, clinic,
hospital, department, facility, pharmacy, organization) or stands alone as a referral destination.
Additive: existing professional.public_address / organization.locations are untouched.
Postal Code Pool = assistance only (suggests City/Province); unknown postal codes never block entry."""
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import audit, db, now_iso

COLL = "locations"
POOL = "postal_pool"

ADDRESS_TYPES = [("PRACTICE", "Practice / Clinic"), ("HOSPITAL", "Hospital"), ("FACILITY", "Facility"), ("MAILING", "Mailing"), ("OTHER", "Other")]
ADDRESS_SUBTYPES = [("MAIN_OFFICE", "Main Office"), ("SPECIALIST_OFFICE", "Specialist Office"), ("DEPARTMENT", "Department"), ("REFERRAL_INTAKE", "Referral Intake"),
                    ("DIAGNOSTIC_SITE", "Diagnostic Site"), ("MAILING_BILLING", "Mailing / Billing"), ("OTHER", "Other")]
ENTITY_TYPES = ("professional", "clinic", "hospital", "department", "facility", "pharmacy", "organization", "destination")
POSTAL_RX = re.compile(r"^[A-Za-z]\d[A-Za-z]\d[A-Za-z]\d$")
PHONE_RX = re.compile(r"^[0-9+()\-.\s]{7,25}$")


def norm_postal(p: Optional[str]) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", p or "").upper()


def fmt_postal(p: str) -> str:
    n = norm_postal(p)
    return f"{n[:3]} {n[3:]}" if len(n) == 6 else (p or "").strip().upper()


class LocationBody(BaseModel):
    entity_type: str
    entity_id: Optional[str] = None          # None for standalone referral destinations
    label: Optional[str] = None              # e.g. "Cardiology Referral Service", "Downtown office"
    address: Optional[str] = None            # flexible, user-entered street line; never normalized/rewritten
    address_type: Optional[str] = None
    address_subtype: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    country: Optional[str] = "Canada"
    phone: Optional[str] = None
    fax: Optional[str] = None
    specialty: Optional[str] = None          # destination routing hint (e.g. Cardiology)
    notes: Optional[str] = None


def _label(opts, code):
    return next((l for c, l in opts if c == code), None)


async def pool_lookup(postal: str) -> Optional[dict]:
    """City/Province suggestion for a postal code. Learns from saved locations and, as a fallback,
    from existing directory/patient addresses (read-only aggregation); misses return None."""
    n = norm_postal(postal)
    if len(n) != 6:
        return None
    hit = await db[POOL].find_one({"_id": n}, {"_id": 0})
    if hit:
        return hit
    votes = {}
    for coll in ("patient_directory", "patients"):
        async for d in db[coll].find({"postal_code": {"$regex": f"^{n[:3]}\\s?{n[3:]}$", "$options": "i"}}, {"_id": 0, "city": 1, "province": 1}).limit(50):
            if d.get("city"):
                k = (d["city"].strip().title(), (d.get("province") or "").strip() or "ON")
                votes[k] = votes.get(k, 0) + 1
    if not votes:
        return None
    (city, prov), count = max(votes.items(), key=lambda kv: kv[1])
    entry = {"city": city, "province": prov, "source": "directory", "count": count}
    await db[POOL].update_one({"_id": n}, {"$setOnInsert": {**entry, "learned_at": now_iso()}}, upsert=True)
    return entry


async def pool_learn(postal: str, city: str, province: str):
    n = norm_postal(postal)
    if len(n) == 6 and city and province:
        await db[POOL].update_one({"_id": n}, {"$set": {"city": city.strip(), "province": province.strip(), "source": "location", "updated_at": now_iso()}}, upsert=True)


def validate(body: LocationBody) -> dict:
    if body.entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Unknown location type.")
    if body.entity_type != "destination" and not body.entity_id:
        raise HTTPException(status_code=400, detail="This location must belong to a record.")
    if body.entity_type == "destination" and not (body.label or "").strip():
        raise HTTPException(status_code=400, detail="Give the referral destination a name (e.g. Mount Sinai — Cardiology Referral Service).")
    addr, city, prov = (body.address or "").strip(), (body.city or "").strip(), (body.province or "").strip()
    physical = body.address_type != "MAILING"
    if physical and not addr:
        raise HTTPException(status_code=400, detail="Address is required for a physical location.")
    if addr and (not city or not prov):
        raise HTTPException(status_code=400, detail="City and Province are required.")
    pc = (body.postal_code or "").strip()
    if pc and (body.country or "Canada").strip().lower() == "canada" and not POSTAL_RX.match(norm_postal(pc)):
        raise HTTPException(status_code=400, detail="Postal code must look like A1A 1A1.")
    if body.address_type and not _label(ADDRESS_TYPES, body.address_type):
        raise HTTPException(status_code=400, detail="Please choose a valid address type.")
    if body.address_subtype and not _label(ADDRESS_SUBTYPES, body.address_subtype):
        raise HTTPException(status_code=400, detail="Please choose a valid address subtype.")
    for name, val in (("Phone", body.phone), ("Fax", body.fax)):
        if val and val.strip() and not PHONE_RX.match(val.strip()):
            raise HTTPException(status_code=400, detail=f"{name} must be 7–25 characters using digits, spaces, +, (, ), - or .")
    clean = lambda v: (v or "").strip() or None
    return {
        "entity_type": body.entity_type, "entity_id": body.entity_id, "label": clean(body.label),
        "address": addr or None, "address_type": body.address_type or None, "address_type_label": _label(ADDRESS_TYPES, body.address_type),
        "address_subtype": body.address_subtype or None, "address_subtype_label": _label(ADDRESS_SUBTYPES, body.address_subtype),
        "postal_code": fmt_postal(pc) if pc else None, "city": city or None, "province": prov or None, "country": clean(body.country) or "Canada",
        "phone": clean(body.phone), "fax": clean(body.fax), "specialty": clean(body.specialty), "notes": clean(body.notes),
    }


def display_line(loc: dict) -> str:
    return ", ".join(p for p in (loc.get("address"), loc.get("city"), loc.get("province"), loc.get("postal_code")) if p)


def build_router(require_roles) -> APIRouter:
    r = APIRouter()
    guard = Depends(require_roles("staff", "admin", "physician"))

    @r.get("/internal/address/options")
    async def options(user: dict = guard):
        return {"address_types": [{"code": c, "label": l} for c, l in ADDRESS_TYPES], "address_subtypes": [{"code": c, "label": l} for c, l in ADDRESS_SUBTYPES], "entity_types": list(ENTITY_TYPES)}

    @r.get("/internal/address/postal-lookup")
    async def postal_lookup(postal: str, user: dict = guard):
        hit = await pool_lookup(postal)
        return {"postal_code": fmt_postal(postal), "found": bool(hit), **({"city": hit["city"], "province": hit["province"]} if hit else {})}

    @r.get("/internal/locations")
    async def list_locations(entity_type: Optional[str] = None, entity_id: Optional[str] = None, q: Optional[str] = None, user: dict = guard):
        query = {"practice_id": user.get("practice_id"), "active": True}
        if entity_type:
            query["entity_type"] = entity_type
        if entity_id:
            query["entity_id"] = entity_id
        if q and q.strip():
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            query["$or"] = [{"label": rx}, {"entity_name": rx}, {"address": rx}, {"city": rx}, {"specialty": rx}, {"fax": rx}]
        rows = await db[COLL].find(query, {"_id": 0}).sort([("entity_name", 1), ("label", 1)]).to_list(300)
        for x in rows:
            x["display_line"] = display_line(x)
        return rows

    @r.post("/internal/locations")
    async def create_location(body: LocationBody, user: dict = guard):
        doc = validate(body)
        entity_name = None
        if body.entity_type == "professional" and body.entity_id:
            p = await db.professional_profiles.find_one({"id": body.entity_id}, {"_id": 0, "display_name": 1, "first_name": 1, "surname": 1, "title": 1})
            if not p:
                raise HTTPException(status_code=404, detail="Professional not found.")
            entity_name = p.get("display_name") or " ".join(x for x in (p.get("title"), p.get("first_name"), p.get("surname")) if x)
        doc.update({"id": str(uuid.uuid4()), "practice_id": user.get("practice_id"), "entity_name": entity_name, "active": True,
                    "created_by": user.get("name"), "created_at": now_iso(), "updated_at": now_iso()})
        await db[COLL].insert_one({**doc})
        await pool_learn(doc["postal_code"], doc["city"], doc["province"])
        await audit("create_location", "location", doc["id"], user, meta={"entity_type": doc["entity_type"], "entity_id": doc["entity_id"]})
        doc["display_line"] = display_line(doc)
        return doc

    @r.patch("/internal/locations/{loc_id}")
    async def update_location(loc_id: str, body: LocationBody, user: dict = guard):
        cur = await db[COLL].find_one({"id": loc_id, "practice_id": user.get("practice_id")}, {"_id": 0})
        if not cur:
            raise HTTPException(status_code=404, detail="Location not found.")
        doc = validate(body)
        doc.pop("entity_type"); doc.pop("entity_id")  # ownership never changes via edit
        doc["updated_at"] = now_iso()
        await db[COLL].update_one({"id": loc_id}, {"$set": doc})
        await pool_learn(doc["postal_code"], doc["city"], doc["province"])
        await audit("update_location", "location", loc_id, user, meta={"changed": [k for k in doc if cur.get(k) != doc[k]]})
        out = {**cur, **doc}
        out["display_line"] = display_line(out)
        return out

    @r.delete("/internal/locations/{loc_id}")
    async def remove_location(loc_id: str, user: dict = guard):
        res = await db[COLL].update_one({"id": loc_id, "practice_id": user.get("practice_id")}, {"$set": {"active": False, "removed_at": now_iso(), "removed_by": user.get("name")}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Location not found.")
        await audit("remove_location", "location", loc_id, user)
        return {"ok": True}

    return r
