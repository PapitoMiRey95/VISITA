"""One-time, bounded, INSERT-MISSING-ONLY reference catalog import (soap_helpers, diagnosis_catalog,
service_catalog). Reuses the approved importer loaders/validators and import_rows logic, but only
for source identities that do not yet exist — existing rows are never updated, deleted or reset.
Hard-coded sources; no generic collection/importer selection."""
import os
import uuid
from datetime import datetime, timezone

import diagnosis as dx_mod
import import_tabbillcode as billcode_pkg
import import_tabdiagcode as diagcode_pkg
import import_tabhxtmpsoap as soap_pkg
import service_coding as svc_mod

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = {
    "soap_helpers": {"file": os.path.join(HERE, "data_imports", "tabHxTmpSOAP_F.xlsx"), "source_type": soap_pkg.SOURCE_TYPE},
    "diagnosis_catalog": {"file": os.path.join(HERE, "data", "VIen_Diagnosis_Catalog_Import.csv"),
                          "manifest": os.path.join(HERE, "data", "VIen_Diagnosis_Catalog_Manifest.json"), "source_type": dx_mod.SOURCE_TYPE},
    "service_catalog": {"file": os.path.join(HERE, "data", "VIen_Service_Catalog_Import.csv"),
                        "manifest": os.path.join(HERE, "data", "VIen_Service_Catalog_Manifest.json"), "source_type": svc_mod.SOURCE_TYPE},
}


def _result(source, existing, missing):
    return {"SOURCE": source, "EXISTS": existing, "MISSING": missing, "INSERTED": 0, "FAILED": 0}


async def _soap(db, apply: bool) -> dict:
    rows = soap_pkg.read_rows(SOURCES["soap_helpers"]["file"])
    practice = await db.practices.find_one({"active": True}, {"_id": 0, "id": 1})
    if not practice:
        return {**_result(len(rows), 0, 0), "FAILED": len(rows), "error": "no active practice"}
    st, pid = soap_pkg.SOURCE_TYPE, practice["id"]
    have = {d["import_key"] async for d in db.soap_helpers.find({"source_type": st, "practice_id": pid}, {"_id": 0, "import_key": 1})}
    missing = [r for r in rows if r["import_key"] not in have]
    res = {**_result(len(rows), len(rows) - len(missing), len(missing)), "practice_id": pid}
    if not apply:
        return res
    now = datetime.now(timezone.utc).isoformat()
    for r in missing:
        try:
            # Same document shape as import_tabhxtmpsoap; insert only (identity absent by construction).
            await db.soap_helpers.insert_one({
                **r, "id": str(uuid.uuid4()), "key": r["name"], "source_type": st, "legacy_source": "tabHxTmpSOAP_F", "active": True,
                "practice_id": pid, "physician_user_id": None, "encounter_types": ["REGULAR_IN_CLINIC", "PHYSICAL"], "yes_no_mode": False,
                "created_at": now, "updated_at": now, "created_by": {"id": "import", "name": "tabHxTmpSOAP_F import"}})
            res["INSERTED"] += 1
        except Exception:
            res["FAILED"] += 1
    return res


async def _legacy_rows(db, catalog: str, rows: list, mod, apply: bool) -> dict:
    coll, st = mod.COLL, mod.SOURCE_TYPE
    have = {d["legacy_id_raw"] async for d in db[coll].find({"source_type": st}, {"_id": 0, "legacy_id_raw": 1})}
    missing = [r for r in rows if int(r["legacy_id_raw"]) not in have]
    res = _result(len(rows), len(rows) - len(missing), len(missing))
    if not apply or not missing:
        return res
    try:
        counts = await mod.import_rows(db, missing)  # approved logic, fed ONLY missing identities -> inserts only
        res["INSERTED"] = counts.get("inserted", 0)
        res["FAILED"] = len(missing) - counts.get("inserted", 0) - counts.get("skipped_blank", 0)
        if counts.get("skipped_blank"):
            res["SKIPPED_BLANK"] = counts["skipped_blank"]
    except Exception as e:
        res["FAILED"], res["error"] = len(missing), f"{type(e).__name__}: {e}"[:200]
    return res


async def _diagnosis(db, apply: bool) -> dict:
    src = SOURCES["diagnosis_catalog"]
    rows = diagcode_pkg.load_csv(src["file"])
    manifest = diagcode_pkg.check_manifest(rows, src["manifest"])
    return {**await _legacy_rows(db, "diagnosis_catalog", rows, dx_mod, apply), "manifest": manifest}


async def _service(db, apply: bool) -> dict:
    import json
    src = SOURCES["service_catalog"]
    rows = billcode_pkg.load(src["file"])
    manifest = billcode_pkg.reconcile(rows, json.load(open(src["manifest"])))
    return {**await _legacy_rows(db, "service_catalog", rows, svc_mod, apply), "manifest": manifest}


async def run(db, apply: bool = False) -> dict:
    """Dry-run (default) performs zero writes. Apply inserts only missing identities."""
    out = {}
    for name, fn in (("soap_helpers", _soap), ("diagnosis_catalog", _diagnosis), ("service_catalog", _service)):
        try:
            out[name] = await fn(db, apply)
        except AssertionError as e:  # manifest/header validation failure -> nothing written for that catalog
            out[name] = {**_result(0, 0, 0), "FAILED": 1, "error": f"validation: {e}"[:300]}
    return out
