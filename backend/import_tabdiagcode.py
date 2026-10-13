"""Idempotent PREVIEW import of Access tabDiagCode.xlsx -> diagnosis_catalog. Usage: python import_tabdiagcode.py <xlsx>"""
import asyncio
import os
import sys

import openpyxl
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

import diagnosis

load_dotenv()


async def main(path):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await diagnosis.ensure_indexes(db)
    ws = openpyxl.load_workbook(path, read_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    assert [str(c).strip() for c in rows[0][:3]] == ["ID", "Code", "Diagnosis"], rows[0]
    counts = await diagnosis.import_rows(db, [r[:3] for r in rows[1:] if r and r[0] is not None])
    counts["collection_total"] = await db[diagnosis.COLL].count_documents({"source_type": diagnosis.SOURCE_TYPE})
    counts["collection_inactive"] = await db[diagnosis.COLL].count_documents({"source_type": diagnosis.SOURCE_TYPE, "active": False})
    print(counts)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
