"""Patient portal — required missing health-card / demographic completion.
Canonical = patient_directory when linked, else the portal `patients` record. Never prompts for a
value already held in either record; fills BLANK canonical fields only; conflicts and name
differences become review items + a Work Hub item for Clinic. Source = PATIENT_PORTAL_PROFILE_COMPLETION."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import identity as identity_mod
import platform_config as platform_mod
import work_hub as work_mod
from db import audit, db, next_ref, now_iso

SOURCE = "PATIENT_PORTAL_PROFILE_COMPLETION"
SEX_FROM_CODE = {"M": "Male", "F": "Female", "X": "Other", "O": "Other", "U": "Unknown", "1": "Male", "2": "Female", "9": "Unknown"}
SEX_TO_CODE = {"Male": "M", "Female": "F", "X": "X", "Other": "X", "Unknown": "U"}
SEX_OPTIONS = ("Male", "Female", "X")
OHIP_FIELDS = ("health_card_version_code", "health_card_issue_date", "health_card_expiry_date")
# canonical key -> portal registration key
REG_KEY = {"health_card_version_code": "health_card_version", "health_card_issue_date": "health_card_issue_date",
           "health_card_expiry_date": "health_card_expiry_date", "sex": "sex", "health_card_number": "health_card_number"}


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def sex_of(doc: dict) -> Optional[str]:
    return (doc.get("sex") or "").strip() or SEX_FROM_CODE.get(str(doc.get("sex_code") or "").strip().upper())


def effective(p: dict, d: Optional[dict]) -> dict:
    """Best known value per field: canonical first, then the preserved registration."""
    out = {}
    for ck, pk in REG_KEY.items():
        cv = sex_of(d) if (ck == "sex" and d) else (d.get(ck) if d else None)
        pv = sex_of(p) if ck == "sex" else p.get(pk)
        out[ck] = cv if not _blank(cv) else (pv if not _blank(pv) else None)
    return out


def missing_fields(p: dict, d: Optional[dict]) -> list:
    eff = effective(p, d)
    req = ["sex"] + (list(OHIP_FIELDS) if p.get("patient_type") == "ohip" else [])
    return [k for k in req if _blank(eff.get(k))]


async def canonical_for(p: dict) -> Optional[dict]:
    did = p.get("matched_directory_id") or p.get("canonical_directory_id")
    return await db.patient_directory.find_one({"id": did}) if did else None


async def feature_on() -> bool:
    """Operator flag (Platform Control Center → features.profile_completion). OFF = no prompt, no gate."""
    return platform_mod.feature_state((await platform_mod.published())["config"], "profile_completion") == "ON"


async def completeness(p: dict) -> dict:
    d = await canonical_for(p)
    missing = missing_fields(p, d) if await feature_on() else []
    name_src = d or p
    return {"required": bool(missing), "missing": missing, "feature_on": await feature_on(), "date_of_birth": (d or p).get("date_of_birth") or p.get("date_of_birth"),
            "health_card_number_on_file": not _blank(effective(p, d).get("health_card_number")),
            "name_on_file": {"first_name": name_src.get("first_name"), "middle_name": p.get("middle_name"),
                             "last_name": name_src.get("last_name"), "second_last_name": p.get("second_last_name")}}


async def require_complete(p: dict):
    """428 gate for lower-urgency transactional actions (Rx requests, non-urgent admin submissions)."""
    c = await completeness(p)
    if c["required"]:
        raise HTTPException(status_code=428, detail={"code": "PROFILE_COMPLETION_REQUIRED", "missing": c["missing"],
                                                     "message": "Please complete your health card information before sending this request."})


class CompletionBody(BaseModel):
    health_card_version_code: Optional[str] = None
    health_card_issue_date: Optional[str] = None
    health_card_expiry_date: Optional[str] = None
    sex: Optional[str] = None
    hc_first_name: Optional[str] = None
    hc_middle_name: Optional[str] = None
    hc_last_name: Optional[str] = None
    hc_second_last_name: Optional[str] = None


def _norm(x) -> str:
    return "".join(ch for ch in str(x or "").lower() if ch.isalnum())


async def _clinic_review_item(p: dict, d: Optional[dict], review: dict):
    """Surface conflicts / name differences to Clinic via the existing Work Hub (Admin, Routine)."""
    practice_id = p.get("practice_id") or (d or {}).get("practice_id")
    target = await work_mod.resolve_target(practice_id, "CLINIC", None)
    actor = {"id": p["id"], "name": "Patient portal", "role": "patient", "practice_id": practice_id}
    lines = [f"{k.replace('_', ' ')}: on file differs from patient submission" for k in review.get("conflicts", {})]
    if review.get("name_difference"):
        lines.append("Name as shown on health card differs from the name on file")
    msg = "Review patient-submitted health card information. " + "; ".join(lines) + "."
    doc = {
        "id": str(uuid.uuid4()), "ref_number": await next_ref("WRK"), "practice_id": practice_id,
        "patient_id": p["id"], "directory_id": (d or {}).get("id"),
        "patient_name": f"{(d or p).get('last_name', '')}, {(d or p).get('first_name', '')}".strip(", "),
        "category": "ADMIN_OTHER", "message": msg, "message_auto": False,
        "created_by": p["id"], "created_by_name": "Patient portal", "created_by_role": "patient",
        **target, "status": "NEW", "priority": "NORMAL", "due_at": None, "waiting_until": None,
        "signed": False, "appointment_id": None, "source_type": "IDENTITY_REVIEW", "source_id": review["id"],
        "created_at": now_iso(), "updated_at": now_iso(), "completed_at": None, "completed_by": None,
        "events": [work_mod._event("created", actor, msg, to_role=target["owner_role"], to_user_id=target["owner_user_id"], to_name=target["owner_name"], to_position=target["owner_position"])],
    }
    await db.work_items.insert_one({**doc})
    return doc["ref_number"]


BACKFILL_FILL = (("health_card_version", "health_card_version_code"), ("health_card_issue_date", "health_card_issue_date"), ("health_card_expiry_date", "health_card_expiry_date"))
BACKFILL_IDENTITY = (("first_name", "first_name"), ("last_name", "last_name"), ("date_of_birth", "date_of_birth"), ("health_card_number", "health_card_number"))


def _mask(v):
    return v if _blank(v) else "*" * max(0, len(str(v)) - 4) + str(v)[-4:]


async def backfill_registration_gaps(apply: bool = False, pins: Optional[list] = None, actor: Optional[dict] = None, include_demo: bool = False) -> dict:
    """Canonical ← verified portal registration. Scope: issue/expiry, version-when-blank, sex only when no usable sex/sex_code.
    Never overwrites a non-blank canonical value; identity/contact fields are reported only. DRY-RUN unless apply=True."""
    q = {"portal_status": {"$in": ["ACTIVE", "VERIFIED"]}, "verification_status": "verified", "matched_directory_id": {"$ne": None}}
    if not include_demo:
        q["is_demo"] = {"$ne": True}
    plan, review, skipped, examined = [], [], 0, 0
    async for p in db.patients.find(q):
        examined += 1
        d = await db.patient_directory.find_one({"id": p["matched_directory_id"]})
        if not d or d.get("patient_status") not in (None, "ACTIVE"):
            skipped += 1
            continue
        pin = str(d.get("visita_patient_id"))
        if pins and pin not in pins:
            continue
        changes, conflicts = {}, {}
        for pk, dk in BACKFILL_FILL:
            pv, dv = p.get(pk), d.get(dk)
            if _blank(pv):
                continue
            pv = pv.strip() if isinstance(pv, str) else pv
            if _blank(dv):
                changes[dk] = pv
            elif _norm(pv) != _norm(dv):
                conflicts[dk] = {"canonical": dv, "registration": pv}
        psex, dsex = (p.get("sex") or "").strip() or None, sex_of(d)
        if psex and not dsex:
            changes["sex"] = psex
            if _blank(d.get("sex_code")):
                changes["sex_code"] = SEX_TO_CODE.get(psex, "X")
        elif psex and dsex and psex.lower() != dsex.lower():
            conflicts["sex"] = {"canonical": dsex, "registration": psex}
        for pk, dk in BACKFILL_IDENTITY:
            pv, dv = p.get(pk), d.get(dk)
            if not _blank(pv) and not _blank(dv) and _norm(pv) != _norm(dv):
                conflicts[dk] = {"canonical": _mask(dv) if "card" in dk else dv, "registration": _mask(pv) if "card" in dk else pv}
        if changes:
            plan.append({"pin": pin, "directory_id": d["id"], "patient_id": p["id"], "set": changes})
        if conflicts:
            review.append({"pin": pin, "directory_id": d["id"], "conflicts": conflicts})
    applied = 0
    if apply:
        for row in plan:
            d = await db.patient_directory.find_one({"id": row["directory_id"]})
            safe = {k: v for k, v in row["set"].items() if _blank(d.get(k))}  # re-check at write time
            if not safe:
                continue
            await db.patient_directory.update_one({"id": row["directory_id"]}, {"$set": {**safe, "updated_at": now_iso()}})
            await audit("canonical_refreshed_from_registration", "patient_directory", row["directory_id"],
                        actor or {"id": "system", "name": "backfill_registration_gaps", "role": "system", "practice_id": d.get("practice_id")},
                        meta={"source": "VERIFIED_PORTAL_REGISTRATION", "link_source": "historical_backfill", "patient_id": row["patient_id"],
                              "changes": {k: {"from": None, "to": v} for k, v in safe.items()}, "conflicts": {}})
            applied += 1
    return {"mode": "APPLY" if apply else "DRY_RUN", "records_examined": examined, "records_skipped_no_active_directory": skipped,
            "records_to_update": len(plan), "applied": applied,
            "field_fill_counts": {k: sum(1 for r in plan if k in r["set"]) for k in ("health_card_issue_date", "health_card_expiry_date", "health_card_version_code", "sex", "sex_code")},
            "review_required": len(review), "plan": plan, "review": review}


class BackfillBody(BaseModel):
    apply: bool = False
    pins: Optional[list] = None
    confirm: Optional[str] = None  # must equal "APPLY" when apply=True


def build_router(get_current_user, get_patient_record, validate_hc_dates, require_roles) -> APIRouter:
    r = APIRouter()

    @r.post("/internal/system/backfill-registration-gaps")
    async def run_backfill(body: BackfillBody, user: dict = Depends(require_roles("admin", "developer_ops"))):
        """Operator-only. Dry-run by default; apply requires confirm == "APPLY". Audited."""
        if body.apply and body.confirm != "APPLY":
            raise HTTPException(status_code=400, detail="To apply, send confirm: \"APPLY\".")
        actor = {"id": user["id"], "name": user.get("name"), "role": user["role"], "practice_id": user.get("practice_id")}
        res = await backfill_registration_gaps(apply=body.apply, pins=body.pins, actor=actor)
        await audit("backfill_registration_gaps_run", "system", "patient_directory", actor,
                    meta={"mode": res["mode"], "records_to_update": res["records_to_update"], "applied": res["applied"], "field_fill_counts": res["field_fill_counts"], "review_required": res["review_required"]})
        return res

    @r.get("/portal/profile-completeness")
    async def get_completeness(user: dict = Depends(get_current_user)):
        return await completeness(await get_patient_record(user))

    @r.post("/portal/profile-completion")
    async def submit_completion(body: CompletionBody, user: dict = Depends(get_current_user)):  # noqa: C901
        p = await get_patient_record(user)
        d = await canonical_for(p)
        eff = effective(p, d)
        submitted, filled_dir, filled_portal, conflicts = {}, {}, {}, {}
        ver = (body.health_card_version_code or "").strip().upper().replace(" ", "")
        if ver:
            if not (len(ver) == 2 and ver.isalpha()):
                raise HTTPException(status_code=400, detail="Version Code must be exactly 2 letters (it is separate from the 10-digit number).")
            submitted["health_card_version_code"] = ver
        for k in ("health_card_issue_date", "health_card_expiry_date"):
            v = (getattr(body, k) or "").strip()
            if v:
                if not identity_mod.valid_date(v):
                    raise HTTPException(status_code=400, detail="Please enter valid dates.")
                submitted[k] = v
        if body.sex:
            if body.sex not in SEX_OPTIONS:
                raise HTTPException(status_code=400, detail="Please select a valid sex.")
            submitted["sex"] = body.sex
        # Same authoritative HC date rules as registration (5-year issue window, expiry year range, expiry after issue).
        validate_hc_dates(submitted.get("health_card_issue_date") or eff.get("health_card_issue_date"),
                          submitted.get("health_card_expiry_date") or eff.get("health_card_expiry_date"),
                          (d or p).get("date_of_birth") or p.get("date_of_birth"))
        for k, v in submitted.items():
            cur = eff.get(k)
            if _blank(cur):
                if d is not None:
                    filled_dir[k] = v
                    if k == "sex":
                        filled_dir["sex_code"] = SEX_TO_CODE.get(v, "X")
                pk = REG_KEY[k]
                if _blank(p.get(pk)):
                    filled_portal[pk] = v
            elif _norm(cur) != _norm(v):
                conflicts[k] = {"on_file": cur, "submitted": v}  # never overwrite a non-blank canonical value
        # Name as shown on health card — identity-sensitive: stored for review only, canonical untouched.
        hc_name = {k: (getattr(body, f"hc_{k}") or "").strip() or None for k in ("first_name", "middle_name", "last_name", "second_last_name")}
        name_src = d or p
        name_difference = None
        if any(hc_name.values()):
            on_file_full = _norm((name_src.get("first_name") or "") + (p.get("middle_name") or "") + (name_src.get("last_name") or "") + (p.get("second_last_name") or ""))
            sub_full = _norm("".join(hc_name.get(k) or "" for k in ("first_name", "middle_name", "last_name", "second_last_name")))
            if on_file_full != sub_full:
                name_difference = {"on_file": {"first_name": name_src.get("first_name"), "middle_name": p.get("middle_name"),
                                               "last_name": name_src.get("last_name"), "second_last_name": p.get("second_last_name")},
                                   "submitted": hc_name}
        if filled_dir:
            await db.patient_directory.update_one({"id": d["id"]}, {"$set": {**filled_dir, "updated_at": now_iso()}})
        if filled_portal:
            await db.patients.update_one({"id": p["id"]}, {"$set": {**filled_portal, "updated_at": now_iso()}})
        review_ref = None
        if conflicts or name_difference:
            review = {"id": str(uuid.uuid4()), "patient_id": p["id"], "directory_id": (d or {}).get("id"), "practice_id": p.get("practice_id"),
                      "source": SOURCE, "conflicts": conflicts, "name_difference": name_difference, "status": "OPEN", "created_at": now_iso()}
            review_ref = await _clinic_review_item(p, d, review)
            review["work_ref"] = review_ref
            await db.identity_review_items.insert_one({**review})
        actor = {"id": user["id"], "name": p.get("first_name"), "role": "patient"}
        await audit("patient_profile_completion", "patient", p["id"], actor,
                    meta={"source": SOURCE, "directory_id": (d or {}).get("id"), "fields_submitted": sorted(submitted.keys()),
                          "fields_filled": sorted(set(filled_dir) | set(filled_portal)), "conflicts": sorted(conflicts.keys()),
                          "name_difference": bool(name_difference), "review_work_ref": review_ref})
        c = await completeness(await db.patients.find_one({"id": p["id"]}) or p)
        return {"ok": True, "filled": sorted(set(filled_dir) | set(filled_portal)), "conflicts": sorted(conflicts.keys()),
                "name_review": bool(name_difference), "review_ref": review_ref, "completeness": c}

    return r
