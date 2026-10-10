"""PREVIEW: import Access tabDiagText into soap_helpers (SOAP TEMP.) as LEGACY_TABDIAGTEXT templates. Additive/idempotent.
Usage: python import_tabdiagtext_templates.py data_imports/tabDiagText_emergent_import.json"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

import soap_helpers

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


async def main(path):
    pkg = json.load(open(path))
    assert pkg.get("schema") == "vien.diagnosis_text_catalog.import.v1", "Unexpected package schema"
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    practice = await db.practices.find_one({"active": True}, {"_id": 0, "id": 1})
    await db.soap_helpers.create_index([("legacy_source", 1), ("legacy_id", 1), ("practice_id", 1)], sparse=True)
    counts = await soap_helpers.import_tabdiagtext(db, pkg, practice["id"])
    counts["soap_temp_legacy_total"] = await db.soap_helpers.count_documents({"source_type": soap_helpers.SOURCE_LEGACY})
    print(json.dumps({"source": pkg.get("source_file"), "target": "soap_helpers (SOAP TEMP.)", **counts}, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
