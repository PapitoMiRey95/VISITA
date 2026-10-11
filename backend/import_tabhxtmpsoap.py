"""PREVIEW: canonical Access SOAP templates (tabHxTmpSOAP_F.xlsx) -> soap_helpers as LEGACY_TABHXTMPSOAP_F.
Column = destination (Subjective/Objective/Plan IP). Text preserved EXACTLY. Additive, idempotent, no dedup, no renumbering.
Usage: python import_tabhxtmpsoap.py data_imports/tabHxTmpSOAP_F.xlsx"""
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import openpyxl
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SOURCE_TYPE = "LEGACY_TABHXTMPSOAP_F"
EXPECTED_HEADER = ("ID", "Nombre", "Subjective", "Objective", "Plan IP", "Favourite", "Gender", "Description")
GENDER_MAP = {"F": "FEMALE", "M": "MALE"}


def _txt(v):
    return "" if v is None else str(v)  # exact; no strip/rewrite


def _bool(v):
    return str(v).strip().lower() in ("true", "1", "yes", "-1") if v is not None else False


def read_rows(path):
    ws = openpyxl.load_workbook(path, data_only=True)[openpyxl.load_workbook(path, read_only=True).sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    assert tuple(rows[0][:8]) == EXPECTED_HEADER, f"Unexpected header: {rows[0]}"
    out = []
    for r in rows[1:]:
        if r[0] is None and not (r[1] or "").strip():
            continue
        legacy_id_raw = str(r[0]) if r[0] is not None else ""
        name = _txt(r[1])
        gender = (_txt(r[6]).strip() or None)
        out.append({
            "legacy_id_raw": legacy_id_raw, "legacy_id_is_integer": legacy_id_raw.replace(".0", "", 1).isdigit() and float(legacy_id_raw).is_integer(),
            "name": name, "subjective_text": _txt(r[2]), "objective_text": _txt(r[3]), "plan_text": _txt(r[4]),
            "favorite": _bool(r[5]), "source_gender": gender, "sex_filter": GENDER_MAP.get(gender) if gender else None,
            "description": (_txt(r[7]) or None),
            "import_key": hashlib.sha1(f"{SOURCE_TYPE}|{legacy_id_raw}|{name}".encode()).hexdigest()[:24],
        })
    return out


async def main(path):
    recs = read_rows(path)
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    practice = await db.practices.find_one({"active": True}, {"_id": 0, "id": 1})
    await db.soap_helpers.create_index([("source_type", 1), ("import_key", 1), ("practice_id", 1)], sparse=True)
    now = datetime.now(timezone.utc).isoformat()
    counts = {"rows": len(recs), "imported": 0, "updated": 0}
    for r in recs:
        res = await db.soap_helpers.update_one(
            {"source_type": SOURCE_TYPE, "import_key": r["import_key"], "practice_id": practice["id"]},
            {"$set": {**r, "key": r["name"], "source_type": SOURCE_TYPE, "legacy_source": "tabHxTmpSOAP_F", "active": True, "updated_at": now},
             "$setOnInsert": {"id": str(uuid.uuid4()), "practice_id": practice["id"], "physician_user_id": None, "encounter_types": ["ANY"],
                              "yes_no_mode": False, "created_at": now, "created_by": {"id": "import", "name": "tabHxTmpSOAP_F import"}}},
            upsert=True)
        counts["imported" if res.upserted_id else "updated"] += 1
    counts.update({
        "favorite_true": sum(r["favorite"] for r in recs), "female": sum(r["sex_filter"] == "FEMALE" for r in recs),
        "male": sum(r["sex_filter"] == "MALE" for r in recs), "gender_blank": sum(r["sex_filter"] is None for r in recs),
        "blank_objective": sum(not r["objective_text"].strip() for r in recs), "blank_subjective": sum(not r["subjective_text"].strip() for r in recs),
        "blank_plan": sum(not r["plan_text"].strip() for r in recs), "non_integer_ids": sum(not r["legacy_id_is_integer"] for r in recs),
        "distinct_import_keys": len({r["import_key"] for r in recs}),
        "collection_total_for_source": await db.soap_helpers.count_documents({"source_type": SOURCE_TYPE}),
    })
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
