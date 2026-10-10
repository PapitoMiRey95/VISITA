"""Import Access tabDiagText package into `diagnosis_text_catalog` (PREVIEW). Additive/idempotent; never deletes.
Usage: python import_diagnosis_catalog.py /path/to/tabDiagText_emergent_import.json"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

import diagnosis_catalog

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


async def main(path):
    pkg = json.load(open(path))
    assert pkg.get("schema") == "vien.diagnosis_text_catalog.import.v1", "Unexpected package schema"
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await diagnosis_catalog.ensure_indexes(db)
    counts = await diagnosis_catalog.import_package(db, pkg)
    counts["collection_total"] = await db[diagnosis_catalog.COLL].count_documents({})
    print(json.dumps({"source": pkg.get("source_file"), "review_summary": pkg.get("review_summary"), **counts}, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
