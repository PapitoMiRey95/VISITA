"""Reference address pools seeded from Dr. Aguayo's legacy Access tables (backend/seed/address/*.xlsx).
Semantics (legacy names are misleading if read literally):
  tblAddress        → street NAME pool            (ref_street_names)
  tblAddressType    → street TYPE / suffix        (ref_street_types)      e.g. Avenue, Road
  tblAddressSubType → street DIRECTION suffix     (ref_street_directions) East/North/South/West
  tblPostalCode     → Postal Code Pool            (ref_postal_codes)      postal → city_id + prov_id
  tblCity / tblProv → localities / provinces      (ref_cities / ref_provinces)
Legacy IDs are preserved (legacy_*_id) and the import is idempotent (upsert on legacy id). Source XLSX is never rewritten."""
import re
from pathlib import Path
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from db import audit, db, now_iso

SEED_DIR = Path(__file__).parent / "seed" / "address"
DEFAULT_PROV_ID, DEFAULT_PROV = 9, "ON"
TORONTO_ALIASES = {"Toronto York North": "Toronto North York", "Toronto York East": "Toronto East York"}
POSTAL_RX = re.compile(r"^[A-Z]\d[A-Z]\d[A-Z]\d$")


def norm_postal(p) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(p or "")).upper()


def fmt_postal(p) -> str:
    n = norm_postal(p)
    return f"{n[:3]} {n[3:]}" if len(n) == 6 else str(p or "").strip().upper()


def _rows(name):
    ws = openpyxl.load_workbook(SEED_DIR / f"{name}.xlsx", read_only=True).active
    it = ws.iter_rows(values_only=True)
    cols = [str(c) for c in next(it)]
    return [dict(zip(cols, r)) for r in it if any(v is not None for v in r)]


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def analyze() -> dict:
    """Read-only data-quality report on the source files (nothing is 'fixed' here; findings are flagged)."""
    prov, city, pc, st, stt, sd = (_rows(n) for n in ("tblProv", "tblCity", "tblPostalCode", "tblAddress", "tblAddressType", "tblAddressSubType"))
    prov_ids = {r["ProvID"] for r in prov}
    city_ids = {r["CityID"] for r in city}
    def dups(rows, key):
        seen, out = {}, []
        for r in rows:
            k = _s(r[key]).lower()
            if k in seen: out.append(_s(r[key]))
            seen[k] = True
        return sorted(set(out))
    collapsed = {}
    for r in st:
        k = re.sub(r"[^a-z]", "", _s(r["Address"]).lower())
        collapsed.setdefault(k, set()).add(_s(r["Address"]))
    near = sorted([sorted(v) for v in collapsed.values() if len(v) > 1])
    # near-duplicates by simple edit distance 1 (typos such as Lansdowne / Landsdowne / Lansdown)
    names = sorted({_s(r["Address"]) for r in st})
    def d1(a, b):
        if abs(len(a) - len(b)) > 1: return False
        if len(a) == len(b): return sum(x != y for x, y in zip(a, b)) == 1
        s, l = (a, b) if len(a) < len(b) else (b, a)
        i = 0
        while i < len(s) and s[i] == l[i]: i += 1
        return s[i:] == l[i + 1:]
    typo_pairs = []
    low = [n.lower() for n in names]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if len(low[i]) > 4 and d1(low[i], low[j]): typo_pairs.append([names[i], names[j]])
    pc_map = {}
    conflicts = []
    malformed = []
    for r in pc:
        n = norm_postal(r["PostalCode"])
        if not POSTAL_RX.match(n): malformed.append(_s(r["PostalCode"]))
        key = (r["CityID"], r["ProvID"])
        if n in pc_map and pc_map[n] != key: conflicts.append({"postal": fmt_postal(n), "a": pc_map[n], "b": key})
        pc_map.setdefault(n, key)
    return {
        "source_rows": {"tblProv": len(prov), "tblCity": len(city), "tblPostalCode": len(pc), "tblAddress": len(st), "tblAddressType": len(stt), "tblAddressSubType": len(sd)},
        "duplicate_exact_values": {"cities": dups(city, "City"), "street_names": dups(st, "Address"), "street_types": dups(stt, "AddressType")},
        "near_duplicate_street_names": near[:50], "typo_like_street_pairs": typo_pairs[:80], "typo_like_pair_count": len(typo_pairs),
        "orphan_city_refs_in_postal": sorted({r["CityID"] for r in pc if r["CityID"] not in city_ids}),
        "orphan_prov_refs": {"cities": sorted({r["ProvID"] for r in city if r["ProvID"] not in prov_ids}), "postal": sorted({r["ProvID"] for r in pc if r["ProvID"] not in prov_ids}), "street_names": sorted({r["ProvID"] for r in st if r["ProvID"] is not None and r["ProvID"] not in prov_ids})},
        "duplicate_postal_mappings_conflicting": conflicts, "duplicate_postal_exact": len(pc) - len(pc_map),
        "malformed_postal_codes": malformed[:50], "malformed_postal_count": len(malformed),
        "toronto_alias_rows": [{"legacy": _s(r["City"]), "canonical": TORONTO_ALIASES[_s(r["City"])], "city_id": r["CityID"]} for r in city if _s(r["City"]) in TORONTO_ALIASES],
        "city_postal_mismatch": sum(1 for r in pc if r["CityID"] in city_ids and next(c["ProvID"] for c in city if c["CityID"] == r["CityID"]) != r["ProvID"]),
    }


async def seed() -> dict:
    """Idempotent: upserts by legacy id. Running twice creates no duplicates."""
    prov, city, pc, st, stt, sd = (_rows(n) for n in ("tblProv", "tblCity", "tblPostalCode", "tblAddress", "tblAddressType", "tblAddressSubType"))
    ts = now_iso()
    for r in prov:
        await db.ref_provinces.update_one({"legacy_prov_id": r["ProvID"]}, {"$set": {"code": _s(r["Prov"]), "name": _s(r["FullProv"]), "source": "tblProv"}, "$setOnInsert": {"imported_at": ts}}, upsert=True)
    for r in city:
        label = _s(r["City"]); canon = TORONTO_ALIASES.get(label, label)
        await db.ref_cities.update_one({"legacy_city_id": r["CityID"]}, {"$set": {"name": canon, "legacy_name": label, "aliases": sorted({label, canon}), "prov_id": r["ProvID"], "favourite": bool(r["Favourite"]), "favourite2": bool(r["Favourite2"]), "norm": canon.lower(), "source": "tblCity"}, "$setOnInsert": {"imported_at": ts}}, upsert=True)
    for r in pc:
        n = norm_postal(r["PostalCode"])
        if not POSTAL_RX.match(n): continue  # flagged in analyze(), not imported
        await db.ref_postal_codes.update_one({"_id": n}, {"$set": {"postal_code": fmt_postal(n), "city_id": r["CityID"], "prov_id": r["ProvID"], "favourite": bool(r["Favourite"]), "legacy_postal_code_id": r["PostalCodeID"], "source": "tblPostalCode"}, "$setOnInsert": {"imported_at": ts}}, upsert=True)
    for r in st:
        await db.ref_street_names.update_one({"legacy_address_id": r["AddressID"]}, {"$set": {"name": _s(r["Address"]), "norm": _s(r["Address"]).lower(), "prov_id": r["ProvID"], "favourite": bool(r["Favourite"]), "favourite2": bool(r["Favourite2"]), "source": "tblAddress"}, "$setOnInsert": {"imported_at": ts}}, upsert=True)
    for r in stt:
        await db.ref_street_types.update_one({"legacy_address_type_id": r["AddressTypeID"]}, {"$set": {"name": _s(r["AddressType"]), "norm": _s(r["AddressType"]).lower(), "favourite": bool(r["Favourite"]), "source": "tblAddressType"}, "$setOnInsert": {"imported_at": ts}}, upsert=True)
    for r in sd:
        await db.ref_street_directions.update_one({"legacy_address_subtype_id": r["AddressSubTypeID"]}, {"$set": {"name": _s(r["AddressSubType"]), "source": "tblAddressSubType"}, "$setOnInsert": {"imported_at": ts}}, upsert=True)
    for c, k in (("ref_cities", "norm"), ("ref_street_names", "norm"), ("ref_street_types", "norm")):
        await db[c].create_index(k)
    await db.ref_postal_candidates.create_index("postal_norm")
    return {c: await db[c].count_documents({}) for c in ("ref_provinces", "ref_cities", "ref_postal_codes", "ref_street_names", "ref_street_types", "ref_street_directions")}


async def postal_lookup(postal: str) -> Optional[dict]:
    n = norm_postal(postal)
    if len(n) != 6:
        return None
    hit = await db.ref_postal_codes.find_one({"_id": n})
    if not hit:
        return None
    city = await db.ref_cities.find_one({"legacy_city_id": hit["city_id"]}, {"_id": 0, "name": 1, "legacy_city_id": 1})
    prov = await db.ref_provinces.find_one({"legacy_prov_id": hit["prov_id"]}, {"_id": 0, "code": 1, "legacy_prov_id": 1})
    return {"postal_code": hit["postal_code"], "city": city["name"] if city else None, "city_id": hit["city_id"], "province": prov["code"] if prov else None, "prov_id": hit["prov_id"], "source": hit.get("source")}


def assemble_street(street_number, street_name, street_type, street_direction, unit=None) -> str:
    """Human-readable line, e.g. '1214 Lansdowne Avenue' / '123 Main Street West' / 'Suite 410A'."""
    core = " ".join(p for p in (_s(street_number), _s(street_name), _s(street_type), _s(street_direction)) if p)
    return f"{core}, {_s(unit)}" if _s(unit) and core else core or _s(unit)


class PostalAdd(BaseModel):
    postal_code: str
    city: str
    province: str = DEFAULT_PROV


class StreetAdd(BaseModel):
    name: str


def build_router(require_roles) -> APIRouter:
    r = APIRouter()
    internal = Depends(require_roles("staff", "admin", "physician"))

    async def _resolve_city(city: str, province: str):
        c = await db.ref_cities.find_one({"$or": [{"norm": city.strip().lower()}, {"aliases": city.strip()}]}, {"_id": 0, "legacy_city_id": 1, "name": 1})
        p = await db.ref_provinces.find_one({"code": province.strip().upper()}, {"_id": 0, "legacy_prov_id": 1})
        return c, p

    @r.get("/internal/address/postal-lookup")
    async def internal_postal(postal: str, user: dict = internal):
        hit = await postal_lookup(postal)
        return {"postal_code": fmt_postal(postal), "found": bool(hit), **(hit or {})}

    @r.get("/public/address/postal-lookup")
    async def public_postal(postal: str):
        hit = await postal_lookup(postal)
        return {"postal_code": fmt_postal(postal), "found": bool(hit), "city": hit and hit["city"], "province": hit and hit["province"]}

    @r.post("/public/address/postal-candidate")
    async def public_candidate(body: PostalAdd):
        """Unreviewed patient input never touches the master pool — queued for internal review only."""
        n = norm_postal(body.postal_code)
        if not POSTAL_RX.match(n) or await db.ref_postal_codes.find_one({"_id": n}, {"_id": 1}):
            return {"queued": False}
        await db.ref_postal_candidates.update_one({"postal_norm": n, "status": "pending"}, {"$set": {"postal_code": fmt_postal(n), "city": body.city.strip(), "province": body.province.strip().upper(), "source": "patient", "updated_at": now_iso()}, "$inc": {"count": 1}, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
        return {"queued": True}

    @r.post("/internal/address/postal-codes")
    async def add_postal(body: PostalAdd, user: dict = internal):
        """Trusted internal '+ Add Postal Code' → shared master pool."""
        n = norm_postal(body.postal_code)
        if not POSTAL_RX.match(n):
            raise HTTPException(status_code=400, detail="Postal code must look like A1A 1A1.")
        if not body.city.strip() or not body.province.strip():
            raise HTTPException(status_code=400, detail="City and Province are required.")
        c, p = await _resolve_city(body.city, body.province)
        if not p:
            raise HTTPException(status_code=400, detail="Unknown province code.")
        if not c:
            nxt = await db.ref_cities.find_one(sort=[("legacy_city_id", -1)])
            cid = (nxt["legacy_city_id"] if nxt else 0) + 1
            await db.ref_cities.insert_one({"legacy_city_id": cid, "name": body.city.strip(), "legacy_name": None, "aliases": [body.city.strip()], "prov_id": p["legacy_prov_id"], "favourite": False, "favourite2": False, "norm": body.city.strip().lower(), "source": "internal_add", "created_by": user.get("name"), "imported_at": now_iso()})
            c = {"legacy_city_id": cid, "name": body.city.strip()}
        existing = await db.ref_postal_codes.find_one({"_id": n})
        if existing and existing.get("source") == "tblPostalCode":
            raise HTTPException(status_code=409, detail="This postal code is already in the pool.")
        await db.ref_postal_codes.update_one({"_id": n}, {"$set": {"postal_code": fmt_postal(n), "city_id": c["legacy_city_id"], "prov_id": p["legacy_prov_id"], "favourite": False, "source": "internal_add", "added_by": user.get("name"), "added_at": now_iso()}}, upsert=True)
        await db.ref_postal_candidates.update_many({"postal_norm": n, "status": "pending"}, {"$set": {"status": "resolved", "resolved_by": user.get("name")}})
        await audit("add_postal_code", "ref_postal_codes", n, user, meta={"city": c["name"], "province": body.province.upper()})
        return {"ok": True, "postal_code": fmt_postal(n), "city": c["name"], "province": body.province.upper()}

    @r.get("/internal/address/provinces")
    async def provinces(user: dict = internal):
        rows = await db.ref_provinces.find({}, {"_id": 0}).sort("legacy_prov_id", 1).to_list(20)
        return {"default": DEFAULT_PROV, "provinces": rows}

    @r.get("/internal/address/cities")
    async def cities(q: str = "", province: Optional[str] = None, limit: int = Query(15, le=50), user: dict = internal):
        query = {}
        if q.strip():
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            query["$or"] = [{"name": rx}, {"aliases": rx}]
        if province:
            p = await db.ref_provinces.find_one({"code": province.upper()}, {"legacy_prov_id": 1})
            if p: query["prov_id"] = p["legacy_prov_id"]
        rows = await db.ref_cities.find(query, {"_id": 0, "name": 1, "legacy_city_id": 1, "favourite": 1, "favourite2": 1, "prov_id": 1}).sort([("favourite", -1), ("favourite2", -1), ("name", 1)]).to_list(limit)
        return rows

    @r.get("/internal/address/streets")
    async def streets(q: str = "", limit: int = Query(12, le=50), user: dict = internal):
        if len(q.strip()) < 2:
            return []
        rx = {"$regex": "^" + re.escape(q.strip()), "$options": "i"}
        return await db.ref_street_names.find({"name": rx}, {"_id": 0, "name": 1, "legacy_address_id": 1, "favourite": 1}).sort([("favourite", -1), ("name", 1)]).to_list(limit)

    @r.post("/internal/address/streets")
    async def add_street(body: StreetAdd, user: dict = internal):
        name = body.name.strip()
        if len(name) < 2:
            raise HTTPException(status_code=400, detail="Street name is too short.")
        if hit := await db.ref_street_names.find_one({"norm": name.lower()}, {"_id": 0, "name": 1, "legacy_address_id": 1}):
            return {"ok": True, "existing": True, **hit}
        nxt = await db.ref_street_names.find_one(sort=[("legacy_address_id", -1)])
        sid = (nxt["legacy_address_id"] if nxt else 0) + 1
        await db.ref_street_names.insert_one({"legacy_address_id": sid, "name": name, "norm": name.lower(), "prov_id": None, "favourite": False, "favourite2": False, "source": "internal_add", "created_by": user.get("name"), "imported_at": now_iso()})
        await audit("add_street_name", "ref_street_names", str(sid), user, meta={"name": name})
        return {"ok": True, "existing": False, "name": name, "legacy_address_id": sid}

    @r.get("/internal/address/street-types")
    async def street_types(q: str = "", limit: int = Query(15, le=130), user: dict = internal):
        query = {"name": {"$regex": "^" + re.escape(q.strip()), "$options": "i"}} if q.strip() else {}
        return await db.ref_street_types.find(query, {"_id": 0, "name": 1, "legacy_address_type_id": 1, "favourite": 1}).sort([("favourite", -1), ("name", 1)]).to_list(limit)

    @r.get("/internal/address/street-directions")
    async def street_directions(user: dict = internal):
        return await db.ref_street_directions.find({}, {"_id": 0, "name": 1, "legacy_address_subtype_id": 1}).sort("name", 1).to_list(10)

    @r.get("/internal/address/postal-candidates")
    async def candidates(user: dict = internal):
        return await db.ref_postal_candidates.find({"status": "pending"}, {"_id": 0}).sort("count", -1).to_list(100)

    @r.get("/internal/system/address-pools/report")
    async def pools_report(user: dict = Depends(require_roles("admin", "physician"))):
        return {"analysis": analyze(), "counts": {c: await db[c].count_documents({}) for c in ("ref_provinces", "ref_cities", "ref_postal_codes", "ref_street_names", "ref_street_types", "ref_street_directions")}}

    @r.post("/internal/system/address-pools/seed")
    async def pools_seed(user: dict = Depends(require_roles("admin", "physician"))):
        counts = await seed()
        await audit("seed_address_pools", "system", "address_pools", user, meta=counts)
        return {"ok": True, "counts": counts}

    return r
