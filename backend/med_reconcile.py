"""Smart Medication reconciliation: parse pasted lists / request items, classify against patient_medications,
apply ONLY confirmed decisions. Updates the medication list only — never creates an Rx or transmission."""
import re
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import db, now_iso, audit
import rx_parser

SOURCES = ("VIEN_RX_SENT", "CLINIC_VERIFIED_EXTERNAL_RX", "MEDICATION_RECONCILIATION", "LEGACY_IMPORT")
_SIG_ALIASES = {"od": "daily", "qd": "daily", "once daily": "daily", "daily": "daily", "bid": "bid", "twice daily": "bid", "tid": "tid",
                "qid": "qid", "hs": "hs", "at bedtime": "hs", "qhs": "hs", "prn": "prn", "as needed": "prn"}


def _n(s) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _drug_key(m: dict) -> str:
    return _n(m.get("generic") or m.get("drug")).split(" (")[0]


def _strength_key(m: dict) -> str:
    st = _n(m.get("strength")).replace(" ", "")
    unit = _n(m.get("unit")).replace(" ", "")
    if st and unit and not re.search(r"[a-z%]", st):
        st += unit  # stored as strength="500" + unit="mg" → "500mg"
    return st


_FREQ = [(r"\b(bid|b\.i\.d|twice (a |per )?day|twice daily|2x daily)\b", "bid"), (r"\b(tid|t\.i\.d|three times (a |per )?day|three times daily)\b", "tid"),
         (r"\b(qid|four times (a |per )?day|four times daily)\b", "qid"), (r"\b(hs|qhs|at bedtime|bedtime|at night|nightly)\b", "hs"),
         (r"\b(od|qd|once (a |per )?day|once daily|daily|every day|q24h)\b", "daily"), (r"\b(prn|as needed|when needed)\b", "prn"),
         (r"\b(weekly|once a week|q7d)\b", "weekly")]


def _sig_key(m: dict) -> str:
    """Frequency-level comparison: 'Take 1 tablet twice daily with meals' ≡ 'BID'. Falls back to full text."""
    s = _n(m.get("sig"))
    for pat, canon in _FREQ:
        if re.search(pat, s):
            return canon
    return s


def classify(parsed: list, existing: list) -> list:
    out = []
    for m in parsed:
        if not m.get("drug"):
            continue
        dk = _drug_key(m)
        same = [e for e in existing if _drug_key(e) == dk]
        active, seen = [], set()
        for e in sorted([e for e in same if e.get("active")], key=lambda x: x.get("last_prescribed_at") or "", reverse=True):
            k = (_strength_key(e), _sig_key(e))
            if k not in seen:  # same regimen stored under linked ids (portal + directory) counts once
                seen.add(k); active.append(e)
        stopped = [e for e in same if not e.get("active")]
        # a missing SIG is editable on the card, not a reason to block reconciliation
        row = {"parsed": m, "classification": "ADD_MISSING", "match": None, "reasons": [x for x in (m.get("needs_review") or []) if x != "sig"]}
        if row["reasons"] or not dk:
            row["classification"] = "REVIEW_REQUIRED"
        elif len(active) > 1:
            row.update(classification="REVIEW_REQUIRED", reasons=["multiple active entries for this drug"], match=active[0])
        elif active:
            e = active[0]; row["match"] = e
            if _strength_key(e) != _strength_key(m) and _strength_key(m):
                row["classification"] = "POSSIBLE_DOSE_CHANGE"
            elif _sig_key(e) != _sig_key(m) and _sig_key(m):
                row["classification"] = "SIG_DIFFERENCE"
            else:
                row["classification"] = "ALREADY_ON_LIST"
        elif stopped:
            row.update(classification="POSSIBLE_RESTART", match=sorted(stopped, key=lambda x: x.get("updated_at") or "", reverse=True)[0])
        out.append(row)
    return out


def summary_line(row: dict) -> str:
    m = row["parsed"]; name = " ".join(x for x in (m.get("drug"), m.get("strength")) if x)
    c = row["classification"]
    return {"ALREADY_ON_LIST": f"✓ {name} — already on list", "ADD_MISSING": f"+ {name} — missing, will add",
            "POSSIBLE_DOSE_CHANGE": f"⚠ {name} — existing dose differs, review required",
            "SIG_DIFFERENCE": f"⚠ {name} — existing SIG differs, review required",
            "POSSIBLE_RESTART": f"⚠ {name} — previously stopped, possible restart", "REVIEW_REQUIRED": f"⚠ {name} — review required"}[c]


def _public(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "_id"}


async def organize(patient_ids: list, text: str = None, items: list = None) -> dict:
    if items is None:  # one medication per line: parse line-by-line so newlines are hard boundaries
        parsed = []
        for line in (text or "").splitlines():
            if line.strip():
                parsed.extend(rx_parser.parse_access_rx(line.strip()).get("medications", []))
    else:
        parsed = items
    existing = await db.patient_medications.find({"patient_id": {"$in": patient_ids}}, {"_id": 0}).to_list(300)
    rows = classify(parsed, existing)
    return {"items": [{**r, "summary": summary_line(r)} for r in rows], "existing_count": len(existing)}


MED_KEYS = ("drug", "strength", "unit", "form", "sig", "route", "quantity", "quantity_unit", "brand", "generic", "din",
            "additional_instructions", "original_text", "note", "attributes", "action")


async def apply(pid: str, decisions: list, source: str, user: dict, regimen_key, remember_catalog, context: dict = None, refs: list = None) -> dict:
    """Only the explicit Smart Paste decision 'add_both' may create a second active entry for a drug."""
    """decisions: [{med:{...}, classification, decision: add|skip|replace|update_sig|restart, match_id, portal_visible}]"""
    if source not in SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")
    now = now_iso()
    applied, flagged, skipped = [], [], []
    actor = {"by": user["name"], "by_role": user["role"], "by_id": user["id"]}
    scope = {"$in": list({*(refs or []), pid})}  # every match_id write is scoped to THIS patient's records (no cross-patient IDOR)
    for d in decisions:
        m = {k: (d.get("med") or {}).get(k) for k in MED_KEYS}
        m["attributes"] = m.get("attributes") or []
        label = " ".join(x for x in (m.get("drug"), m.get("strength")) if x)
        sm = re.match(r"^\s*([\d.,/]+)\s*([a-zA-Z%µ/]+)\s*$", m.get("strength") or "")
        if sm:  # store like VIen Rx does: strength="5", unit="mg"
            m["strength"], m["unit"] = sm.group(1), (m.get("unit") or sm.group(2))
        dec, cls, match_id = d.get("decision") or "skip", d.get("classification"), d.get("match_id")
        if not m.get("drug") or dec == "skip":
            skipped.append(label); continue
        if dec == "flag":
            if match_id:
                await db.patient_medications.update_one({"id": match_id, "patient_id": scope}, {"$set": {"review_flag": {"type": cls, "pasted": m, "at": now, **actor, "source": source}, "updated_at": now}})
            flagged.append(label); continue
        if dec == "replace" and match_id:
            await db.patient_medications.update_one({"id": match_id, "patient_id": scope}, {"$set": {"active": False, "discontinued_at": now, "discontinue_reason": "dose_change", "updated_at": now},
                                                                        "$push": {"history": {"action": "discontinued", "reason": "dose_change", "at": now, **actor, "source": source}}})
            dec = "add"
        if dec == "update_sig" and match_id:
            await db.patient_medications.update_one({"id": match_id, "patient_id": scope}, {"$set": {"sig": m.get("sig"), "updated_at": now, "last_verified_at": now, "source": source},
                                                                        "$push": {"history": {"action": "sig_updated", "sig": m.get("sig"), "at": now, **actor, "source": source}}})
            applied.append(f"{label} — SIG updated"); continue
        if dec == "restart" and match_id:
            await db.patient_medications.update_one({"id": match_id, "patient_id": scope}, {"$set": {**{k: m[k] for k in MED_KEYS if m.get(k) is not None}, "active": True, "discontinued_at": None, "source": source,
                                                                                 "last_verified_at": now, "updated_at": now, "portal_visible": d.get("portal_visible", True), "review_flag": None},
                                                                        "$push": {"history": {"action": "restarted", "at": now, **actor, "source": source}}})
            applied.append(f"{label} — restarted"); continue
        if dec == "add_both":
            dec = "add"
        elif dec == "add":
            # server-side guard (never trust client classification): an active row for the same drug
            # means this is a dose/SIG conflict → flag instead of adding a second active entry
            same = [e for e in await db.patient_medications.find({"patient_id": scope, "active": True}, {"_id": 0}).to_list(300) if _drug_key(e) == _drug_key(m)]
            if any(_strength_key(e) == _strength_key(m) and (_sig_key(e) == _sig_key(m) or not _sig_key(m)) for e in same):
                skipped.append(f"{label} (duplicate)"); continue  # identical regimen already active → never a second row
            if same:
                await db.patient_medications.update_one({"id": same[0]["id"]}, {"$set": {"review_flag": {"type": "POSSIBLE_DOSE_CHANGE", "pasted": m, "at": now, **actor, "source": source}, "updated_at": now}})
                flagged.append(f"{label} (conflicts with active {same[0].get('drug')} — flagged, not added)"); continue
        if dec == "add":
            key = regimen_key(pid, m)
            if await db.patient_medications.find_one({"regimen_key": key, "active": True}):
                skipped.append(f"{label} (duplicate)"); continue
            await db.patient_medications.insert_one({"id": str(uuid.uuid4()), "regimen_key": key, "patient_id": pid, **m, "source": source, "active": True,
                                                     "portal_visible": d.get("portal_visible", True), "last_prescribed_at": now, "last_verified_at": now, "last_tx_id": None,
                                                     "context": context, "history": [{"action": "added", "at": now, **actor, "source": source}], "created_at": now, "updated_at": now})
            await remember_catalog(m)
            applied.append(f"{label} — added")
    result = {"applied": applied, "flagged": flagged, "skipped": skipped, "at": now, "source": source}
    await audit("medication_reconciliation_applied", "patient", pid, user, meta={**result, "context": context})
    return result


class OrganizeBody(BaseModel):
    text: str


class Decision(BaseModel):
    med: dict
    classification: str
    decision: str
    match_id: Optional[str] = None
    portal_visible: bool = True


class ApplyBody(BaseModel):
    decisions: List[Decision]
    source: str = "MEDICATION_RECONCILIATION"


def build_router(require_roles, roles, scoped_refs, regimen_key, remember_catalog, med_public) -> APIRouter:
    r = APIRouter()

    @r.post("/internal/patients/{patient_ref}/medications/organize")
    async def organize_ep(patient_ref: str, body: OrganizeBody, user: dict = Depends(require_roles(*roles))):
        refs, _, p = await scoped_refs(patient_ref, user)
        return await organize(refs, text=body.text)

    @r.post("/internal/patients/{patient_ref}/medications/reconcile")
    async def reconcile_ep(patient_ref: str, body: ApplyBody, user: dict = Depends(require_roles(*roles))):
        refs, _, p = await scoped_refs(patient_ref, user)
        pid = p["id"] if p else refs[0]
        res = await apply(pid, [d.model_dump() for d in body.decisions], body.source, user, regimen_key, remember_catalog, refs=refs)
        res["medications"] = [med_public(x) for x in await db.patient_medications.find({"patient_id": {"$in": refs}, "active": True}, {"_id": 0}).to_list(200)]
        return res

    @r.patch("/internal/patients/{patient_ref}/medications/{med_id}/portal-visibility")
    async def visibility_ep(patient_ref: str, med_id: str, body: dict, user: dict = Depends(require_roles(*roles))):
        refs, _, _ = await scoped_refs(patient_ref, user)
        vis = bool(body.get("portal_visible", True))
        res = await db.patient_medications.update_one({"id": med_id, "patient_id": {"$in": refs}}, {"$set": {"portal_visible": vis, "updated_at": now_iso()}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Medication not found")
        await audit("medication_portal_visibility_changed", "patient_medication", med_id, user, meta={"portal_visible": vis})
        return {"id": med_id, "portal_visible": vis}

    return r
