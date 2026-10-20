"""READ-ONLY audit: canonical patient_directory gaps vs. original portal registration (db.patients).
Usage: python tools/audit_registration_gaps.py [--pin 795 --pin 491]
Never writes. Masks health card numbers. Uses MONGO_URL/DB_NAME from backend/.env."""
import argparse, asyncio, os, sys, json
from collections import Counter
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
SEX_FROM_CODE = {"M": "Male", "F": "Female", "X": "X", "O": "X", "U": None}
# (label, portal field, canonical field) — aliases checked too
FIELDS = [
    ("sex", ["sex", "gender"], ["sex", "sex_code"]),
    ("health_card_number", ["health_card_number", "hc_number", "ohip", "ohip_number", "health_card"], ["health_card_number", "hc_number", "ohip"]),
    ("version_code", ["health_card_version", "version_code", "version", "hc_version", "health_card_version_code"], ["health_card_version_code", "health_card_version", "version_code", "hc_version"]),
    ("hc_issue_date", ["health_card_issue_date", "issue_date", "hc_issue_date"], ["health_card_issue_date", "issue_date", "hc_issue_date"]),
    ("hc_expiry_date", ["health_card_expiry_date", "expiry_date", "hc_expiry_date"], ["health_card_expiry_date", "expiry_date", "hc_expiry_date"]),
    ("email", ["email"], ["email"]),
    ("cell_phone", ["phone", "cell_phone"], ["cell_phone", "phone"]),
    ("home_phone", ["home_phone"], ["home_phone"]),
    ("address", ["address"], ["address"]),
]
NAME_PARTS = [("first_name", "first_name"), ("middle_name", "middle_name"), ("last_name", "last_name"), ("second_last_name", "second_last_name")]


def mask_hc(v):
    if not v:
        return v
    s = "".join(ch for ch in str(v) if ch.isalnum())
    return "*" * max(0, len(s) - 4) + s[-4:]


def first(doc, keys):
    for k in keys:
        v = doc.get(k)
        if v not in (None, "", []):
            return k, (v.strip() if isinstance(v, str) else v)
    return None, None


def norm(x):
    return "".join(ch for ch in str(x or "").lower() if ch.isalnum())


def classify(label, pk, pv, dk, dv, p):
    if dv not in (None, ""):
        if pv in (None, "") or norm(pv) == norm(dv) or (label == "sex" and dk == "sex_code" and SEX_FROM_CODE.get(str(dv).upper()) == pv):
            return "OK"
        return "D_SUBMITTED_BUT_CONFLICTED"
    if pv in (None, ""):
        if label == "sex" and (p.get("created_at") or "") < "2026-10-01":
            return "E_LEGACY_REGISTRATION_FIELD_DID_NOT_EXIST"
        if label in ("version_code", "hc_issue_date", "hc_expiry_date") and p.get("patient_type") != "ohip":
            return "A_NEVER_SUBMITTED_NON_OHIP"
        if (p.get("created_at") or "") < "2026-10-07":
            return "E_LEGACY_REGISTRATION_BEFORE_REQUIRED"
        return "A_NEVER_SUBMITTED"
    if pk and dk is None and label == "version_code" and pk == "health_card_version":
        return "C_STORED_UNDER_DIFFERENT_FIELD_NAME(SAFE)"
    return "B_SUBMITTED_BUT_NOT_COPIED(SAFE)"


async def main(pins):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    q = {"portal_status": "ACTIVE", "active_status": {"$ne": False}, "is_demo": {"$ne": True}, "matched_directory_id": {"$ne": None}}
    agg = Counter(); candidates = []; name_diffs = 0; examined = 0; schema_keys = Counter()
    async for p in db.patients.find(q):
        d = await db.patient_directory.find_one({"id": p["matched_directory_id"]})
        if not d or d.get("patient_status") not in (None, "ACTIVE"):
            continue
        examined += 1
        for k in p.keys():
            schema_keys[k] += 1
        pin = d.get("visita_patient_id")
        rows = []
        for label, pkeys, dkeys in FIELDS:
            pk, pv = first(p, pkeys); dk, dv = first(d, dkeys)
            case = classify(label, pk, pv, dk, dv, p)
            agg[(label, case)] += 1
            if case != "OK":
                show = mask_hc if label == "health_card_number" else (lambda x: x)
                rows.append({"field": label, "case": case, "canonical": show(dv), "canonical_key": dk, "registration": show(pv), "registration_key": pk,
                             "status": "SAFE CANDIDATE" if "SAFE" in case else ("REVIEW REQUIRED" if case.startswith("D") else "NOT RECOVERABLE")})
        nd = {}
        for pk_, dk_ in NAME_PARTS:
            pv, dv = p.get(pk_), d.get(dk_)
            if norm(pv) != norm(dv):
                nd[pk_] = {"canonical": dv, "registration": pv}
        if nd:
            name_diffs += 1
            whole_match = norm(" ".join(str(p.get(k) or "") for k, _ in NAME_PARTS)) == norm(" ".join(str(d.get(k) or "") for _, k in NAME_PARTS)) or \
                norm(str(p.get("first_name")) + str(p.get("middle_name") or "") + str(p.get("last_name")) + str(p.get("second_last_name") or "")) == norm(str(d.get("first_name")) + str(d.get("last_name")))
            rows.append({"field": "name_components", "case": "STRUCTURED_PARTS_SAME_WHOLE_NAME" if whole_match else "D_NAME_DIFFERS", "detail": nd,
                         "status": "REVIEW REQUIRED"})
            agg[("name_components", "same_whole_name" if whole_match else "differs")] += 1
        if rows and (not pins or str(pin) in pins):
            candidates.append({"pin": pin, "patient_id": p["id"], "directory_id": d["id"], "registered_at": p.get("created_at"), "verified": p.get("verification_status"),
                               "patient_type": p.get("patient_type"), "link_source": (p.get("link_meta") or {}).get("source"), "rows": rows})
    out = {"examined_active_portal_patients": examined,
           "aggregate": {f"{k[0]}::{k[1]}": v for k, v in sorted(agg.items())},
           "registration_schema_keys_seen": dict(schema_keys),
           "patients_with_name_component_differences": name_diffs,
           "candidates": candidates if pins else candidates[:50],
           "candidate_count": len(candidates)}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--pin", action="append", default=[])
    asyncio.run(main(ap.parse_args().pin))
