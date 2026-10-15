"""Visit New — Service / coding (Sr, Sr Nº). Catalog from Access `tabBillCode` (collection `service_catalog`) +
structured per-Visit selection `visits.service = {primary, additional_codes[]}`. Never writes SOAP.
legacy_fee_reference is reference-only (never an operational fee). Separate from settings.direct_billing_services."""
import uuid
from datetime import datetime, timezone

COLL = "service_catalog"
SOURCE_TYPE = "LEGACY_TABBILLCODE"
BEHAVIORS = ("REPLACE_PRIMARY", "APPEND_CODE")
REVIEW_META = ("import_key", "review_flag", "review_reason")


def _now():
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db):
    import index_bootstrap as ib
    await ib.ensure_missing(db, COLL, [{"keys": [("source_type", 1), ("legacy_id_raw", 1)], "unique": True}])


async def import_rows(db, rows: list) -> dict:
    """Idempotent upsert on (source_type, legacy_id_raw). Codes/descriptions verbatim; service_code is NOT an identity."""
    now = _now()
    counts = {"total": 0, "inserted": 0, "updated": 0, "append_code": 0}
    for r in rows:
        counts["total"] += 1
        assert r["selection_behavior"] in BEHAVIORS, r
        if r["selection_behavior"] == "APPEND_CODE":
            counts["append_code"] += 1
        doc = {"legacy_id_raw": int(r["legacy_id_raw"]), "service_code": r["service_code"], "service_description": r["service_description"],
               "selection_behavior": r["selection_behavior"], "legacy_fee_reference": r.get("legacy_fee_reference"),
               "favourite": bool(r.get("favourite")), "active": bool(r.get("active", True)), "updated_at": now}
        for k in REVIEW_META:
            if k in r:
                doc[k] = r[k]
        res = await db[COLL].update_one({"source_type": SOURCE_TYPE, "legacy_id_raw": doc["legacy_id_raw"]},
                                        {"$set": doc, "$setOnInsert": {"id": str(uuid.uuid4()), "source_type": SOURCE_TYPE, "created_at": now}}, upsert=True)
        counts["inserted" if res.upserted_id else "updated"] += 1
    return counts


async def list_active(db) -> list:
    """Favourites first, then the rest alphabetically. Fee is deliberately NOT returned to the UI."""
    rows = await db[COLL].find({"active": True}, {"_id": 0, "id": 1, "legacy_id_raw": 1, "service_code": 1, "service_description": 1,
                                                  "selection_behavior": 1, "favourite": 1}).to_list(500)
    rows.sort(key=lambda r: (not r["favourite"], r["service_description"].lower(), r["legacy_id_raw"]))
    return rows


def _entry(cat: dict, user: dict) -> dict:
    return {"catalog_id": cat["id"], "legacy_id_raw": cat["legacy_id_raw"], "service_description": cat["service_description"],
            "service_code": cat["service_code"], "selected_at": _now(), "selected_by": {"id": user["id"], "name": user.get("name")}}


async def select(db, visit: dict, catalog_id: str, user: dict):
    """REPLACE_PRIMARY → replaces primary (add-ons kept). APPEND_CODE → appended once to additional_codes (no primary invented)."""
    cat = await db[COLL].find_one({"id": catalog_id, "active": True}, {"_id": 0})
    if not cat:
        return None
    svc = visit.get("service") or {"primary": None, "additional_codes": []}
    if cat["selection_behavior"] == "APPEND_CODE":
        if not any(a["catalog_id"] == cat["id"] for a in svc["additional_codes"]):
            svc["additional_codes"].append(_entry(cat, user))
    else:
        svc["primary"] = _entry(cat, user)
    await _save(db, visit, svc, user)
    return svc


async def remove(db, visit: dict, catalog_id: str | None, user: dict):
    """catalog_id None → clear primary; otherwise remove that add-on."""
    svc = visit.get("service") or {"primary": None, "additional_codes": []}
    if catalog_id is None:
        svc["primary"] = None
    else:
        svc["additional_codes"] = [a for a in svc["additional_codes"] if a["catalog_id"] != catalog_id]
    await _save(db, visit, svc, user)
    return svc


async def _save(db, visit, svc, user):
    await db.visits.update_one({"id": visit["id"]}, {"$set": {"service": svc, "updated_at": _now(), "updated_by": {"id": user["id"], "name": user.get("name")}}})


def sr_number(svc: dict | None) -> str | None:
    """Display only: primary code then add-on codes in selection order, ';'-joined (Access style). Canonical data stays structured."""
    if not svc:
        return None
    codes = ([svc["primary"]["service_code"]] if svc.get("primary") else []) + [a["service_code"] for a in svc.get("additional_codes") or []]
    return ";".join(codes) or None
