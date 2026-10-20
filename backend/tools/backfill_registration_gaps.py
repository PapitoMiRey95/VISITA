"""Controlled backfill: canonical patient_directory ← preserved verified portal registration. DRY-RUN by default; --apply to write.
Same logic as POST /api/internal/system/backfill-registration-gaps (profile_completion.backfill_registration_gaps)."""
import argparse, asyncio, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from profile_completion import backfill_registration_gaps  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); ap.add_argument("--pin", action="append", default=[]); ap.add_argument("--include-demo", action="store_true")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(backfill_registration_gaps(apply=a.apply, pins=a.pin or None, include_demo=a.include_demo)), indent=1, default=str))
