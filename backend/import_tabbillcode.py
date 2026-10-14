"""Idempotent PREVIEW import of Access tabBillCode (normalized VIen_Service_Catalog_Import.csv) -> service_catalog.
Usage: python import_tabbillcode.py <csv> <manifest.json> [--apply]   (dry reconciliation by default; STOPs on mismatch)"""
import asyncio
import collections
import csv
import json
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

import service_coding as svc

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
COLS = ("source_type", "import_key", "legacy_id_raw", "service_code", "service_description", "selection_behavior",
        "legacy_fee_reference", "favourite", "active", "review_flag", "review_reason")
_b = lambda v: str(v).strip().lower() == "true"


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        assert tuple(rd.fieldnames) == COLS, rd.fieldnames
        rows = []
        for r in rd:
            assert r["source_type"] == svc.SOURCE_TYPE and r["import_key"] == f"{svc.SOURCE_TYPE}|{r['legacy_id_raw']}", r
            rows.append({**r, "legacy_id_raw": int(r["legacy_id_raw"]), "legacy_fee_reference": float(r["legacy_fee_reference"]) if r["legacy_fee_reference"] else None,
                         "favourite": _b(r["favourite"]), "active": _b(r["active"]), "review_flag": r["review_flag"] or None, "review_reason": r["review_reason"] or None})
    return rows


def reconcile(rows, manifest):
    codes = collections.Counter(r["service_code"] for r in rows)
    append = sorted(r["service_code"] for r in rows if r["selection_behavior"] == "APPEND_CODE")
    got = {"source_rows": len(rows), "distinct_service_codes": len(codes), "a903a_rows": codes["A903A"], "append_code": append,
           "replace_primary": sum(r["selection_behavior"] == "REPLACE_PRIMARY" for r in rows), "blank_descriptions": sum(not r["service_description"].strip() for r in rows)}
    exp = {"source_rows": manifest["source_rows"], "distinct_service_codes": manifest["distinct_service_codes"], "a903a_rows": 2,
           "append_code": sorted(manifest["selection_behavior_contract"]["APPEND_CODE_values"]), "replace_primary": len(rows) - 2, "blank_descriptions": 0}
    bad = {k: (got[k], exp[k]) for k in exp if got[k] != exp[k]}
    assert not bad, f"RECONCILIATION MISMATCH — STOP: {bad}"
    return got


async def main(argv):
    rows, manifest = load(argv[0]), json.load(open(argv[1]))
    print("RECONCILIATION OK", reconcile(rows, manifest))
    if "--apply" not in argv:
        return
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await svc.ensure_indexes(db)
    counts = await svc.import_rows(db, rows)
    counts["collection_total"] = await db[svc.COLL].count_documents({"source_type": svc.SOURCE_TYPE})
    print("APPLIED", counts)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
