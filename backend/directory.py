"""VISITA patient directory: import, normalization and identity matching.

One collection `patient_directory` holds the clinic's complete known patient
directory. `patient_status` (ACTIVE / FORMER_CLOSED, extensible later) keeps the
two populations logically separate. Matching only ASSISTS staff — it never
independently activates a portal account.
"""
import re
from datetime import date, datetime

from db import mask_hcn, now_iso

ACTIVE = "ACTIVE"
FORMER_CLOSED = "FORMER_CLOSED"

# Registration review classifications
ACTIVE_MATCH = "ACTIVE_MATCH"
FORMER_MATCH = "FORMER_PATIENT_REVIEW"
AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
UNMATCHED = "UNMATCHED_CURRENT_PATIENT"


def norm_name(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().upper())


def norm_hcn(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def norm_dob(s) -> str:
    if not s:
        return ""
    if isinstance(s, (datetime, date)):
        return s.date().isoformat() if isinstance(s, datetime) else s.isoformat()
    txt = str(s).strip()
    # accept YYYY-MM-DD or ISO datetime
    return txt[:10]


def _val(row, headers, key):
    idx = headers.get(key)
    return row[idx] if idx is not None and idx < len(row) else None


def build_directory_doc(row, headers, patient_status, import_source):
    import uuid
    first = _val(row, headers, "first_name")
    last = _val(row, headers, "last_name")
    dob = _val(row, headers, "date_of_birth")
    hcn = _val(row, headers, "ohip_number")
    return {
        "id": str(uuid.uuid4()),
        "visita_patient_id": (str(_val(row, headers, "visita_patient_id")).strip()
                              if _val(row, headers, "visita_patient_id") not in (None, "") else None),
        "first_name": (str(first).strip() if first else ""),
        "last_name": (str(last).strip() if last else ""),
        "date_of_birth": norm_dob(dob),
        "health_card_number": (str(hcn).strip() if hcn else None),
        "health_card_version_code": (str(_val(row, headers, "ohip_version_code")).strip()
                                     if _val(row, headers, "ohip_version_code") else None),
        "sex_code": (str(_val(row, headers, "sex_code")).strip() if _val(row, headers, "sex_code") else None),
        "address": (str(_val(row, headers, "address")).strip() if _val(row, headers, "address") else None),
        "unit": (str(_val(row, headers, "unit")).strip() if _val(row, headers, "unit") else None),
        "city": (str(_val(row, headers, "city")).strip() if _val(row, headers, "city") else None),
        "province": (str(_val(row, headers, "province")).strip() if _val(row, headers, "province") else None),
        "postal_code": (str(_val(row, headers, "postal_code")).strip() if _val(row, headers, "postal_code") else None),
        "home_phone": (str(_val(row, headers, "home_phone")).strip() if _val(row, headers, "home_phone") else None),
        "cell_phone": (str(_val(row, headers, "cell_phone")).strip() if _val(row, headers, "cell_phone") else None),
        "email": (str(_val(row, headers, "email")).strip().lower() if _val(row, headers, "email") else None),
        "patient_status": patient_status,
        "source_close_marker": _val(row, headers, "source_close_marker"),
        "linked_patient_id": None,
        # normalized comparison keys (do not alter original values)
        "norm_first": norm_name(first),
        "norm_last": norm_name(last),
        "norm_dob": norm_dob(dob),
        "norm_hcn": norm_hcn(hcn) if hcn else "",
        "import_source": import_source,
        "imported_at": now_iso(),
        "updated_at": now_iso(),
    }


def serialize_candidate(d: dict) -> dict:
    return {
        "id": d["id"],
        "visita_patient_id": d.get("visita_patient_id"),
        "first_name": d.get("first_name"),
        "last_name": d.get("last_name"),
        "date_of_birth": d.get("date_of_birth"),
        "health_card_masked": mask_hcn(d.get("health_card_number")),
        "health_card_version_code": d.get("health_card_version_code"),
        "phone": d.get("cell_phone") or d.get("home_phone"),
        "email": d.get("email"),
        "city": d.get("city"),
        "province": d.get("province"),
        "postal_code": d.get("postal_code"),
        "patient_status": d.get("patient_status"),
        "linked_patient_id": d.get("linked_patient_id"),
    }


async def import_directory(db):
    """One-time import of both bundled workbooks into patient_directory."""
    from pathlib import Path
    import openpyxl

    data_dir = Path(__file__).parent / "data"
    files = [
        (data_dir / "VISITA_PatientPortal_ACTIVE_Only.xlsx", ACTIVE),
        (data_dir / "VISITA_Former_Patients_Reference.xlsx", FORMER_CLOSED),
    ]
    total = 0
    for path, status in files:
        if not path.exists():
            continue
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header_row = next(rows)
        headers = {str(h).strip(): i for i, h in enumerate(header_row) if h}
        batch = []
        for row in rows:
            if row is None or all(c is None for c in row):
                continue
            doc = build_directory_doc(row, headers, status, path.name)
            if not doc["norm_last"] and not doc["norm_hcn"]:
                continue
            batch.append(doc)
            if len(batch) >= 500:
                await db.patient_directory.insert_many(batch)
                total += len(batch)
                batch = []
        if batch:
            await db.patient_directory.insert_many(batch)
            total += len(batch)
        wb.close()
    return total


async def match_registration(db, first_name, last_name, date_of_birth, health_card_number):
    """Return an assist result for a current-patient registration.

    outcome: ACTIVE_MATCH | FORMER_PATIENT_REVIEW | AMBIGUOUS_MATCH | UNMATCHED_CURRENT_PATIENT
    """
    nf, nl, nd = norm_name(first_name), norm_name(last_name), norm_dob(date_of_birth)
    nh = norm_hcn(health_card_number) if health_card_number else ""

    def uniq(docs):
        seen, out = set(), []
        for d in docs:
            if d["id"] not in seen:
                seen.add(d["id"])
                out.append(d)
        return out

    active_hcn = former_hcn = []
    if nh:
        hcn_docs = await db.patient_directory.find({"norm_hcn": nh}).to_list(50)
        active_hcn = [d for d in hcn_docs if d["patient_status"] == ACTIVE]
        former_hcn = [d for d in hcn_docs if d["patient_status"] == FORMER_CLOSED]

    nd_docs = []
    if nf and nl and nd:
        nd_docs = await db.patient_directory.find(
            {"norm_first": nf, "norm_last": nl, "norm_dob": nd}).to_list(50)
    active_nd = [d for d in nd_docs if d["patient_status"] == ACTIVE]
    former_nd = [d for d in nd_docs if d["patient_status"] == FORMER_CLOSED]

    active = uniq(active_hcn + active_nd)
    former = uniq(former_hcn + former_nd)

    if active:
        strength = "strong" if active_hcn else "possible"
        if len(active) > 1:
            return {"outcome": AMBIGUOUS_MATCH, "strength": strength, "matched_status": ACTIVE,
                    "candidates": [serialize_candidate(d) for d in active]}
        return {"outcome": ACTIVE_MATCH, "strength": strength, "matched_status": ACTIVE,
                "matched_id": active[0]["id"], "candidates": [serialize_candidate(active[0])]}
    if former:
        strength = "strong" if former_hcn else "possible"
        outcome = AMBIGUOUS_MATCH if len(former) > 1 else FORMER_MATCH
        return {"outcome": FORMER_MATCH, "strength": strength, "matched_status": FORMER_CLOSED,
                "ambiguous": len(former) > 1, "matched_id": former[0]["id"] if len(former) == 1 else None,
                "candidates": [serialize_candidate(d) for d in former]}
    return {"outcome": UNMATCHED, "strength": "none", "candidates": []}
