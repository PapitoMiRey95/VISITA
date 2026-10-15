"""Diagnosis / PMHx terminology catalog imported from Access `tabDiagText` (collection `diagnosis_text_catalog`).
Separate from soap_helpers. Additive upsert by (legacy_source, legacy_id); terminology is never rewritten."""
import re
from datetime import datetime, timezone

COLL = "diagnosis_text_catalog"
GENDER_MAP = {"OPN": "ANY", "FML": "FEMALE", "MAL": "MALE"}
PRESERVE = ("key", "text", "note", "coded", "source_gender", "sex_filter", "pmhx_description", "legacy_id", "legacy_source", "active")


async def ensure_indexes(db):
    import index_bootstrap as ib
    await ib.ensure_missing(db, COLL, [{"keys": [("legacy_source", 1), ("legacy_id", 1)], "unique": True}, {"keys": [("key", 1)]}])


async def import_package(db, pkg: dict) -> dict:
    """Idempotent additive upsert. Skips import_enabled=false. Returns counts."""
    now = datetime.now(timezone.utc).isoformat()
    counts = {"total": 0, "imported": 0, "updated": 0, "skipped_disabled": 0, "flagged_review": 0}
    for r in pkg.get("records", []):
        counts["total"] += 1
        if r.get("needs_review") or r.get("review_reasons"):
            counts["flagged_review"] += 1
        if not r.get("import_enabled", True):
            counts["skipped_disabled"] += 1
            continue
        sg = r.get("source_gender")
        doc = {k: r.get(k) for k in PRESERVE}
        doc["sex_filter"] = r.get("sex_filter") if r.get("sex_filter") is not None else (GENDER_MAP.get(sg) if sg else None)
        doc["review_reasons"] = r.get("review_reasons") or []
        doc["updated_at"] = now
        res = await db[COLL].update_one({"legacy_source": r["legacy_source"], "legacy_id": r["legacy_id"]},
                                        {"$set": doc, "$setOnInsert": {"created_at": now, "import_schema": pkg.get("schema")}}, upsert=True)
        counts["imported" if res.upserted_id else "updated"] += 1
    return counts


def _rank(doc: dict, q: str) -> int:
    ql = q.lower()
    key, text, pm = (doc.get("key") or "").lower(), (doc.get("text") or "").lower(), (doc.get("pmhx_description") or "").lower()
    if key == ql or text == ql:
        return 0
    if key.startswith(ql) or text.startswith(ql):
        return 1
    if ql in key or ql in text:
        return 2
    return 3 if ql in pm else 4


async def search(db, q: str, sex: str | None, limit: int = 25) -> list:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    words = [re.escape(w) for w in q.split()]
    per_word = [{"$or": [{"key": {"$regex": w, "$options": "i"}}, {"text": {"$regex": w, "$options": "i"}},
                         {"pmhx_description": {"$regex": w, "$options": "i"}}]} for w in words]
    f = {"active": {"$ne": False}, "$and": per_word}
    rows = await db[COLL].find(f, {"_id": 0, "legacy_source": 1, "legacy_id": 1, "key": 1, "text": 1, "coded": 1,
                                   "sex_filter": 1, "pmhx_description": 1}).to_list(400)
    # sex_filter: ANY / null visible to all; MALE/FEMALE only when the patient's authoritative sex matches
    rows = [r for r in rows if r.get("sex_filter") in (None, "ANY") or (sex and r.get("sex_filter") == sex)]
    rows.sort(key=lambda r: (_rank(r, q), len(r.get("key") or ""), r.get("key") or ""))
    return [{**r, "id": f"{r['legacy_source']}:{r['legacy_id']}"} for r in rows[:limit]]
