"""Test credentials come from environment only (backend/.env is git-ignored). Never commit passwords."""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
for _k in ("TEST_STAFF_PASSWORD", "TEST_PHYSICIAN_PASSWORD"):
    if not os.environ.get(_k):
        raise RuntimeError(f"{_k} is not set — add it to backend/.env (not committed) before running tests.")
