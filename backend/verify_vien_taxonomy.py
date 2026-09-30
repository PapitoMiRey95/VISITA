"""READ-ONLY pre-flight / post-seed verification for the VIen-native taxonomy.

    python verify_vien_taxonomy.py preflight   # expects all 8 collections absent/empty
    python verify_vien_taxonomy.py postcheck   # expects exact counts 2/32/115/90/157/97/24/13

Performs only list_collection_names + count_documents. Never prints MONGO_URL.
Exit code 0 = expectation met, 1 = NOT met.
"""
import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

from seed_vien_professional_taxonomy import BUILDERS

EXPECTED = {coll: len(build()) for coll, build in BUILDERS}


async def main(mode: str) -> int:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    existing = set(await db.list_collection_names())
    print(f"Connected database: {db.name}")
    ok = True
    for coll, expected in EXPECTED.items():
        n = await db[coll].count_documents({}) if coll in existing else None
        state = "ABSENT" if n is None else str(n)
        if mode == "preflight":
            good = n in (None, 0)
            print(f"  {coll:42s} current={state:7s} expected=empty  {'OK' if good else 'FAIL (unexpected data)'}")
        else:
            good = n == expected
            print(f"  {coll:42s} current={state:7s} expected={expected:<4d} {'OK' if good else 'FAIL'}")
        ok &= good
    print("Legacy/other collections are not inspected or touched.")
    print("RESULT:", ("ALL 8 TARGET COLLECTIONS EMPTY — safe to seed" if mode == "preflight" else "COUNTS MATCH") if ok
          else ("STOP — target collection(s) contain data" if mode == "preflight" else "COUNT MISMATCH"))
    client.close()
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("preflight", "postcheck"):
        sys.exit("usage: verify_vien_taxonomy.py preflight|postcheck")
    sys.exit(asyncio.run(main(sys.argv[1])))
