"""Medication-history reconciliation: SENT rx_transmissions (authoritative) vs patient_medications.
Read-only audit + bounded backfill (dry-run default). Never reads prescription_requests as evidence."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from db import audit, db, now_iso


def regimen_key(patient_id: str, m: dict) -> str:
    return "|".join([patient_id, (m.get("drug") or "").lower().strip(), (m.get("strength") or "").lower().strip(),
                     (m.get("form") or "").lower().strip(), (m.get("sig") or "").lower().strip()])


async def canonical_patient_id(tx: dict) -> Optional[str]:
    """Portal patient id a transmission belongs to, following directory → linked_patient_id. None = not linkable."""
    pid, did = tx.get("patient_id"), tx.get("patient_directory_id")
    if pid and await db.patients.find_one({"id": pid}, {"_id": 1}):
        return pid
    d = await db.patient_directory.find_one({"id": {"$in": [x for x in (did, pid) if x]}}, {"_id": 0, "linked_patient_id": 1})
    if d and d.get("linked_patient_id") and await db.patients.find_one({"id": d["linked_patient_id"]}, {"_id": 1}):
        return d["linked_patient_id"]
    return None


def _med_doc(pid: str, m: dict, tx: dict) -> dict:
    now = now_iso()
    keep = ("drug", "action", "strength", "unit", "form", "attributes", "sig", "quantity", "quantity_unit", "route", "duration_value",
            "duration_unit", "concentration", "prn_reason", "eye", "ear", "interval", "site", "device", "brand", "generic", "din",
            "manufacturer", "additional_instructions", "original_text", "note")
    return {"id": str(uuid.uuid4()), "regimen_key": regimen_key(pid, m), "patient_id": pid, **{k: m.get(k) for k in keep},
            "attributes": m.get("attributes") or [], "months": tx.get("months"), "refills": tx.get("refills"),
            "last_prescribed_at": tx["sent_at"], "last_tx_id": tx["id"], "physician_id": tx.get("physician_id"),
            "physician_name": tx.get("physician_name"), "active": True, "source": "historical_backfill", "created_at": now, "updated_at": now}


async def reconcile(apply: bool = False, actor: dict = None) -> dict:
    """A represented · B safe candidate · C ambiguous identity · D linkage problem · E completed request never sent."""
    counts = {"A_already_represented": 0, "B_safe_candidate": 0, "C_ambiguous": 0, "D_linkage_problem": 0, "E_completed_never_sent": 0,
              "transmissions": 0, "transmissions_pdf_only": 0, "applied": 0}
    candidates, linkage, ambiguous = [], [], []
    planned = {}
    cur = db.rx_transmissions.find({"direction": "PHYSICIAN_TO_PHARMACY", "status": {"$in": ["SENT", "VIEWED", "ACKNOWLEDGED"]}},
                                   {"_id": 0}).sort("sent_at", 1)
    async for tx in cur:
        counts["transmissions"] += 1
        meds = [m for m in (tx.get("medications") or []) if (m or {}).get("drug")]
        if not meds:
            counts["transmissions_pdf_only"] += 1
            continue
        pid = await canonical_patient_id(tx)
        if not pid:
            counts["D_linkage_problem"] += len(meds)
            linkage.append({"tx_ref": tx.get("ref_number"), "patient_name": tx.get("patient_name"), "patient_id": tx.get("patient_id"),
                            "directory_id": tx.get("patient_directory_id"), "meds": [m["drug"] for m in meds], "sent_at": tx.get("sent_at")})
            continue
        refs = {x for x in (pid, tx.get("patient_id"), tx.get("patient_directory_id")) if x}
        for m in meds:
            key = regimen_key(pid, m)
            keys = [regimen_key(r, m) for r in refs]  # portal reads union of patient id + directory id (no rewrite needed)
            if await db.patient_medications.find_one({"regimen_key": {"$in": keys}}, {"_id": 1}) or key in planned:
                counts["A_already_represented"] += 1
                if key in planned and tx["sent_at"] > planned[key]["last_prescribed_at"]:
                    planned[key].update(last_prescribed_at=tx["sent_at"], last_tx_id=tx["id"])
                continue
            if not m.get("strength") and not m.get("original_text"):
                counts["C_ambiguous"] += 1
                ambiguous.append({"tx_ref": tx.get("ref_number"), "patient_id": pid, "drug": m["drug"], "reason": "no strength"})
                continue
            counts["B_safe_candidate"] += 1
            planned[key] = _med_doc(pid, m, tx)
            candidates.append({"tx_ref": tx.get("ref_number"), "patient_id": pid, "patient_name": tx.get("patient_name"), "drug": m["drug"],
                               "strength": m.get("strength"), "form": m.get("form"), "sig": m.get("sig"), "sent_at": tx.get("sent_at")})
    # E — administratively completed requests with no sent transmission behind them (evidence check only; never backfilled)
    sent_src = {t.get("source_request_id") async for t in db.rx_transmissions.find({"source_request_id": {"$ne": None}}, {"_id": 0, "source_request_id": 1})}
    async for r in db.prescription_requests.find({"internal_status": "completed"}, {"_id": 0, "id": 1, "linked_transmission_ref": 1}):
        if r["id"] not in sent_src and not r.get("linked_transmission_ref"):
            counts["E_completed_never_sent"] += 1
    if apply:
        for doc in planned.values():
            await db.patient_medications.insert_one({**doc})
            await audit("medication_history_backfill", "patient_medication", doc["id"], actor,
                        meta={"patient_id": doc["patient_id"], "drug": doc["drug"], "strength": doc["strength"], "tx_id": doc["last_tx_id"]})
            counts["applied"] += 1
    return {"apply": apply, "counts": counts, "candidates": candidates[:200], "linkage_problems": linkage[:100], "ambiguous": ambiguous[:100]}


class BackfillBody(BaseModel):
    apply: bool = False
    confirm: Optional[str] = None


def build_router(require_roles) -> APIRouter:
    r = APIRouter()

    @r.get("/internal/system/medication-history/audit")
    async def med_audit(user: dict = Depends(require_roles("admin", "physician", "developer_ops"))):
        return await reconcile(apply=False)

    @r.post("/internal/system/medication-history/backfill")
    async def med_backfill(body: BackfillBody, user: dict = Depends(require_roles("admin", "developer_ops"))):
        do_apply = bool(body.apply and body.confirm == "APPLY")
        res = await reconcile(apply=do_apply, actor=user)
        if do_apply:
            await audit("medication_history_backfill_run", "system", "patient_medications", user, meta=res["counts"])
        return res

    return r
