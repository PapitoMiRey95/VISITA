"""SOAP Helpers — physician-authored reusable note text (collection `soap_helpers`).
Phase 2A3: read/search only. Helpers insert reviewable NOTE TEXT; they are never patient facts."""
import re

COLL = "soap_helpers"
SEX_FILTERS = ("ANY", "MALE", "FEMALE")
TEMPLATE_TYPES = ("ANY", "REGULAR_IN_CLINIC", "TELEPHONE", "VIDEO", "PROXY", "PHYSICAL")
# Visit encounter_type -> template profile (encounter_template_profiles.v1). Visit type is authoritative; ADMIN -> general only.
VISIT_TYPE_TO_PROFILE = {"IN_CLINIC": "REGULAR_IN_CLINIC", "REGULAR_IN_CLINIC": "REGULAR_IN_CLINIC", "TELEPHONE": "TELEPHONE",
                         "VIDEO": "VIDEO", "PROXY": "PROXY", "PHYSICAL": "PHYSICAL"}
PROFILES = {
    "REGULAR_IN_CLINIC": {"label": "Regular / In-Clinic", "show": ("ANY", "REGULAR_IN_CLINIC", "PHYSICAL")},
    "PHYSICAL": {"label": "Physical", "show": ("ANY", "PHYSICAL")},
    "TELEPHONE": {"label": "Telephone", "show": ("ANY", "TELEPHONE")},
    "VIDEO": {"label": "Video", "show": ("ANY", "VIDEO")},
    "PROXY": {"label": "Proxy", "show": ("ANY", "PROXY")},
}


def profile_for(encounter_type: str | None) -> dict:
    """Which template types to SHOW for a visit type. Unknown/none -> general (ANY) only."""
    key = VISIT_TYPE_TO_PROFILE.get(encounter_type or "")
    if not key:
        return {"key": None, "label": "General", "show": ("ANY",)}
    return {"key": key, **PROFILES[key]}


def visible_for(h: dict, show: tuple) -> bool:
    types = h.get("encounter_types") or ["ANY"]
    return any(t in show for t in types)
SEX_MAP = {"male": "MALE", "m": "MALE", "female": "FEMALE", "f": "FEMALE"}


def patient_sex(identity) -> str | None:
    """Authoritative portal `patients.sex` only ('Male'/'Female'); anything else -> None (never guessed)."""
    raw = ((identity or {}).get("portal") or {}).get("sex")
    return SEX_MAP.get(str(raw).strip().lower()) if raw else None


def scope_filter(user: dict) -> dict:
    return {"active": True, "practice_id": user.get("practice_id"),
            "$or": [{"physician_user_id": None}, {"physician_user_id": {"$exists": False}}, {"physician_user_id": user["id"]}]}


SOURCE_LEGACY, SOURCE_VIEN = "LEGACY_TABDIAGTEXT", "VIEN_SOAP_TEMPLATE"


def compact(h: dict) -> dict:
    return {"id": h["id"], "key": h.get("key"), "name": h.get("name"), "sex_filter": h.get("sex_filter") or "ANY",
            "source_type": h.get("source_type") or SOURCE_VIEN, "legacy_id": h.get("legacy_id"),
            "has_template_text": bool((h.get("template_text") or "").strip()), "pmhx_description": h.get("pmhx_description"),
            "encounter_types": h.get("encounter_types") or ["ANY"], "template_category": h.get("template_category"),
            "yes_no_mode": bool(h.get("yes_no_mode")), "has_subjective": bool((h.get("subjective_text") or "").strip()),
            "has_objective": bool((h.get("objective_text") or "").strip()), "has_plan": bool((h.get("plan_text") or "").strip()),
            "synthetic_sample": bool(h.get("synthetic_sample"))}


async def search(db, user: dict, q: str, sex: str | None, limit: int = 30, encounter_type: str | None = None) -> list:
    f = scope_filter(user)
    show = profile_for(encounter_type)["show"]
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        # Key / Text (name, template_text) / PMHxDescript
        f = {"$and": [f, {"$or": [{"name": rx}, {"key": rx}, {"template_text": rx}, {"pmhx_description": rx}]}]}
    rows = await db[COLL].find(f, {"_id": 0, "subjective_text": 0, "objective_text": 0, "plan_text": 0}).to_list(400)
    # sex filter: ANY/null always; MALE/FEMALE only when the patient's authoritative sex matches; unknown -> ANY only
    rows = [h for h in rows if (h.get("sex_filter") or "ANY") == "ANY" or (sex and h.get("sex_filter") == sex)]
    ql = (q or "").strip().lower()
    specific = tuple(t for t in show if t != "ANY")

    def rank(h):
        n, k = (h.get("name") or "").lower(), (h.get("key") or "").lower()
        text_rank = 0 if ql and (n.startswith(ql) or k.startswith(ql)) else 1 if ql and (ql in n or ql in k) else 2
        # visit-type-specific VIen templates surface first, then general VIen, then legacy tabDiagText
        src_rank = 0 if any(t in specific for t in (h.get("encounter_types") or [])) else 1 if (h.get("source_type") or SOURCE_VIEN) == SOURCE_VIEN else 2
        return (text_rank, src_rank, n)
    rows.sort(key=rank)
    # encounter-type filter: suggestions only — never touches the note
    rows = [h for h in rows if visible_for(h, show)]
    return [compact(h) for h in rows[:limit]]


async def get(db, user: dict, helper_id: str):
    return await db[COLL].find_one({"id": helper_id, **scope_filter(user)}, {"_id": 0})


async def import_tabdiagtext(db, pkg: dict, practice_id: str) -> dict:
    """tabDiagText -> soap_helpers as LEGACY_TABDIAGTEXT templates. Additive upsert by (legacy_source, legacy_id).
    No S/O/A/P destination exists in the source, so `template_text` is kept neutral; the physician picks the section."""
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    counts = {"total": 0, "imported": 0, "updated": 0, "skipped_disabled": 0, "flagged_review": 0}
    gender_map = pkg.get("gender_mapping") or {"OPN": "ANY", "FML": "FEMALE", "MAL": "MALE"}
    for r in pkg.get("records", []):
        counts["total"] += 1
        if r.get("review_reasons"):
            counts["flagged_review"] += 1
        if not r.get("import_enabled", True):
            counts["skipped_disabled"] += 1
            continue
        sg = r.get("source_gender")
        doc = {"key": r.get("key"), "name": r.get("key") or r.get("text"), "template_text": r.get("text"),
               "legacy_note": r.get("note"), "coded": bool(r.get("coded")), "source_gender": sg,
               "sex_filter": gender_map.get(sg) if sg else None, "pmhx_description": r.get("pmhx_description"),
               "source_type": SOURCE_LEGACY, "legacy_source": r["legacy_source"], "legacy_id": r["legacy_id"],
               "review_reasons": r.get("review_reasons") or [], "active": bool(r.get("active", True)), "updated_at": now}
        res = await db[COLL].update_one(
            {"legacy_source": r["legacy_source"], "legacy_id": r["legacy_id"], "practice_id": practice_id},
            {"$set": doc, "$setOnInsert": {"id": str(uuid.uuid4()), "practice_id": practice_id, "physician_user_id": None,
                                           "encounter_types": ["ANY"], "yes_no_mode": False, "subjective_text": "", "objective_text": "",
                                           "plan_text": "", "created_at": now, "created_by": {"id": "import", "name": "tabDiagText import"}}},
            upsert=True)
        counts["imported" if res.upserted_id else "updated"] += 1
    return counts
