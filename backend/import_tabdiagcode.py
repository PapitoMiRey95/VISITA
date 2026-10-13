"""Idempotent PREVIEW import of Dr. Aguayo's tabDiagCode -> diagnosis_catalog.
Preferred input: normalized VIen_Diagnosis_Catalog_Import.csv (+ optional manifest JSON as contract).
Fallback: raw tabDiagCode.xlsx (ID, Code, Diagnosis). Identity = legacy_id_raw; code is never a key.
Usage: python import_tabdiagcode.py <csv|xlsx> [manifest.json] [--dry-run]"""
import asyncio
import csv
import json
import os
import sys

import openpyxl
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

import diagnosis

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
CSV_COLS = ("source_type", "legacy_id_raw", "diagnosis_code", "diagnosis_text", "active", "import_key",
            "exact_duplicate_count", "same_text_multi_code", "review_flag", "review_reason")
BOOL = {"true": True, "false": False}


def _bool(v):
    return BOOL.get(str(v).strip().lower(), None) if v not in (None, "") else None


def load_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        assert tuple(rd.fieldnames) == CSV_COLS, rd.fieldnames
        rows = []
        for r in rd:
            assert r["source_type"] == diagnosis.SOURCE_TYPE, r
            assert r["import_key"] == f"{diagnosis.SOURCE_TYPE}|{r['legacy_id_raw']}", r
            rows.append({"legacy_id_raw": int(r["legacy_id_raw"]), "diagnosis_code": r["diagnosis_code"] or None,
                         "diagnosis_text": r["diagnosis_text"], "active": _bool(r["active"]), "import_key": r["import_key"],
                         "exact_duplicate_count": int(r["exact_duplicate_count"] or 1), "same_text_multi_code": _bool(r["same_text_multi_code"]) or False,
                         "review_flag": _bool(r["review_flag"]) or False, "review_reason": r["review_reason"] or None})
    return rows


def load_xlsx(path):
    ws = openpyxl.load_workbook(path, read_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    assert [str(c).strip() for c in rows[0][:3]] == ["ID", "Code", "Diagnosis"], rows[0]
    return [r[:3] for r in rows[1:] if r and r[0] is not None]


def check_manifest(rows, manifest_path):
    m = json.load(open(manifest_path))
    assert m["source_type"] == diagnosis.SOURCE_TYPE and m["do_not_use_as_unique_key"] == "diagnosis_code", m
    c = m["counts"]
    got = {"source_rows": len(rows), "inactive_rows": sum(1 for r in rows if r.get("active") is False),
           "distinct_legacy_ids": len({r["legacy_id_raw"] for r in rows}), "review_flag_rows": sum(1 for r in rows if r.get("review_flag"))}
    bad = {k: (got[k], c[k]) for k in got if got[k] != c[k]}
    assert not bad, f"manifest mismatch {bad}"
    return got


async def main(argv):
    dry = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]
    path, manifest = args[0], (args[1] if len(args) > 1 else None)
    rows = load_csv(path) if path.lower().endswith(".csv") else load_xlsx(path)
    if manifest:
        print("manifest check OK:", check_manifest(rows, manifest))
    if dry:
        print({"dry_run": True, "rows": len(rows), "would_upsert_on": "(source_type, legacy_id_raw)"})
        return
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await diagnosis.ensure_indexes(db)
    counts = await diagnosis.import_rows(db, rows)
    counts["collection_total"] = await db[diagnosis.COLL].count_documents({"source_type": diagnosis.SOURCE_TYPE})
    counts["collection_inactive"] = await db[diagnosis.COLL].count_documents({"source_type": diagnosis.SOURCE_TYPE, "active": False})
    print(counts)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
