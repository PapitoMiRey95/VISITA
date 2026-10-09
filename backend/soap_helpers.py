"""SOAP Helpers — physician-authored reusable note text (collection `soap_helpers`).
Phase 2A3: read/search only. Helpers insert reviewable NOTE TEXT; they are never patient facts."""
import re

COLL = "soap_helpers"
SEX_FILTERS = ("ANY", "MALE", "FEMALE")
SEX_MAP = {"male": "MALE", "m": "MALE", "female": "FEMALE", "f": "FEMALE"}


def patient_sex(identity) -> str | None:
    """Authoritative portal `patients.sex` only ('Male'/'Female'); anything else -> None (never guessed)."""
    raw = ((identity or {}).get("portal") or {}).get("sex")
    return SEX_MAP.get(str(raw).strip().lower()) if raw else None


def scope_filter(user: dict) -> dict:
    return {"active": True, "practice_id": user.get("practice_id"),
            "$or": [{"physician_user_id": None}, {"physician_user_id": {"$exists": False}}, {"physician_user_id": user["id"]}]}


def compact(h: dict) -> dict:
    return {"id": h["id"], "key": h.get("key"), "name": h.get("name"), "sex_filter": h.get("sex_filter", "ANY"),
            "yes_no_mode": bool(h.get("yes_no_mode")), "has_subjective": bool((h.get("subjective_text") or "").strip()),
            "has_objective": bool((h.get("objective_text") or "").strip()), "has_plan": bool((h.get("plan_text") or "").strip()),
            "synthetic_sample": bool(h.get("synthetic_sample"))}


async def search(db, user: dict, q: str, sex: str | None, limit: int = 20) -> list:
    f = scope_filter(user)
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        f = {"$and": [f, {"$or": [{"name": rx}, {"key": rx}]}]}
    rows = await db[COLL].find(f, {"_id": 0}).sort("name", 1).to_list(200)
    # sex filter: ANY always; MALE/FEMALE only when the patient's authoritative sex matches; unknown -> ANY only
    rows = [h for h in rows if h.get("sex_filter", "ANY") == "ANY" or (sex and h.get("sex_filter") == sex)]
    return [compact(h) for h in rows[:limit]]


async def get(db, user: dict, helper_id: str):
    return await db[COLL].find_one({"id": helper_id, **scope_filter(user)}, {"_id": 0})
