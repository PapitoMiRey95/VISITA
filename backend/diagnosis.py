"""Phase 2A4.1 — Diagnosis core. Catalog from Access `tabDiagCode` (collection `diagnosis_catalog`) +
structured per-Visit diagnosis (`visits.diagnoses[]`, one primary entry for now). Never writes SOAP."""
import re
import uuid
from datetime import datetime, timezone

COLL = "diagnosis_catalog"
SOURCE_TYPE = "LEGACY_TABDIAGCODE"
NOT_IN_USE = re.compile(r"not in use", re.I)
REVIEW_META = ("import_key", "exact_duplicate_count", "same_text_multi_code", "review_flag", "review_reason")


def _now():
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db):
    import index_bootstrap as ib
    await ib.ensure_missing(db, COLL, [{"keys": [("source_type", 1), ("legacy_id_raw", 1)], "unique": True},
                                       {"keys": [("active", 1), ("diagnosis_text", 1)]}])


async def import_rows(db, rows: list) -> dict:
    """Idempotent upsert keyed on (source_type, legacy_id_raw). Text/code preserved verbatim.
    rows = dicts {legacy_id_raw, diagnosis_code, diagnosis_text, active?, review metadata?} (normalized package) or
    raw tuples (ID, Code, Diagnosis). `active` defaults to the 'Not in use' rule when not supplied."""
    now = _now()
    counts = {"total": 0, "inserted": 0, "updated": 0, "inactive": 0, "review_flagged": 0, "skipped_blank": 0}
    for r in rows:
        counts["total"] += 1
        if not isinstance(r, dict):
            r = {"legacy_id_raw": r[0], "diagnosis_code": r[1], "diagnosis_text": r[2]}
        legacy_id, code, text = r.get("legacy_id_raw"), r.get("diagnosis_code"), r.get("diagnosis_text")
        if legacy_id in (None, "") or text is None or not str(text).strip():
            counts["skipped_blank"] += 1
            continue
        text = str(text)
        active = r["active"] if isinstance(r.get("active"), bool) else not NOT_IN_USE.search(text)
        if not active:
            counts["inactive"] += 1
        if r.get("review_flag"):
            counts["review_flagged"] += 1
        code = str(code).strip() if code not in (None, "") else None
        doc = {"legacy_id_raw": int(legacy_id), "diagnosis_code": code, "diagnosis_text": text, "active": active, "updated_at": now}
        for k in REVIEW_META:
            if k in r:
                doc[k] = r[k]
        res = await db[COLL].update_one({"source_type": SOURCE_TYPE, "legacy_id_raw": int(legacy_id)},
                                        {"$set": doc, "$setOnInsert": {"id": str(uuid.uuid4()), "source_type": SOURCE_TYPE, "created_at": now}}, upsert=True)
        counts["inserted" if res.upserted_id else "updated"] += 1
    return counts


def _rank(d: dict, q: str) -> int:
    ql, t, c = q.lower(), d["diagnosis_text"].lower(), (d.get("diagnosis_code") or "")
    if c == q or t == ql:
        return 0
    if c.startswith(q) or t.startswith(ql):
        return 1
    return 2 if any(w.startswith(ql) for w in re.split(r"[\s,;/]+", t)) else 3


async def search(db, q: str, limit: int = 30) -> list:
    """Matches diagnosis text (partial words) and code. Exact (code+text) duplicates collapsed for display only."""
    q = (q or "").strip()
    if not q:
        return []
    words = [re.escape(w) for w in q.split()]
    f = {"active": True, "$and": [{"$or": [{"diagnosis_text": {"$regex": w, "$options": "i"}}, {"diagnosis_code": {"$regex": f"^{w}"}}]} for w in words]}
    rows = await db[COLL].find(f, {"_id": 0, "id": 1, "legacy_id_raw": 1, "diagnosis_code": 1, "diagnosis_text": 1}).to_list(500)
    rows.sort(key=lambda r: (_rank(r, q), r["diagnosis_text"].lower(), r["legacy_id_raw"]))
    seen, out = set(), []
    for r in rows:
        key = (r.get("diagnosis_code"), r["diagnosis_text"].strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


async def previous_for_patient(db, practice_id: str, refs: list, exclude_visit_id: str | None = None) -> list:
    """DISTINCT diagnoses previously selected on canonical Visits of this patient (all linked refs), same practice.
    Ranked: most recently used, then frequency. Clean text only — never '(idem)'."""
    f = {"practice_id": practice_id, "patient_ref": {"$in": refs}, "diagnoses.0": {"$exists": True}}
    if exclude_visit_id:
        f["id"] = {"$ne": exclude_visit_id}
    cur = db.visits.find(f, {"_id": 0, "id": 1, "started_at": 1, "diagnoses": 1})
    agg = {}
    async for v in cur:
        for d in v.get("diagnoses") or []:
            key = (d.get("diagnosis_code"), d.get("diagnosis_text"))
            e = agg.setdefault(key, {"catalog_id": d.get("catalog_id"), "diagnosis_code": d.get("diagnosis_code"),
                                     "diagnosis_text": d.get("diagnosis_text"), "count": 0, "last_used_at": None})
            e["count"] += 1
            if not e["last_used_at"] or v["started_at"] > e["last_used_at"]:
                e["last_used_at"] = v["started_at"]
    return sorted(agg.values(), key=lambda e: (e["last_used_at"], e["count"]), reverse=True)


async def set_primary(db, visit: dict, catalog_id: str, source: str, user: dict) -> list:
    """Physician-explicit selection. Replaces the single primary entry; list shape kept for future multi-dx."""
    cat = await db[COLL].find_one({"id": catalog_id, "active": True}, {"_id": 0})
    if not cat:
        return None
    entry = {"id": str(uuid.uuid4()), "catalog_id": cat["id"], "diagnosis_text": cat["diagnosis_text"], "diagnosis_code": cat.get("diagnosis_code"),
             "legacy_id_raw": cat["legacy_id_raw"], "source": source, "is_primary": True, "selected_at": _now(),
             "selected_by": {"id": user["id"], "name": user.get("name")}}
    await db.visits.update_one({"id": visit["id"]}, {"$set": {"diagnoses": [entry], "updated_at": _now(), "updated_by": entry["selected_by"]}})
    return [entry]


async def clear(db, visit: dict, user: dict):
    await db.visits.update_one({"id": visit["id"]}, {"$set": {"diagnoses": [], "updated_at": _now(), "updated_by": {"id": user["id"], "name": user.get("name")}}})
