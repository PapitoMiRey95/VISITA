import os
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt

JWT_ALGORITHM = "HS256"
ACCESS_TTL_HOURS = 12


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str, role: str, extra: dict | None = None) -> str:
    payload = {**(extra or {}),
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=ACCESS_TTL_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])


PASSWORD_SPECIALS = r"""!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?~`"""


def password_policy_failures(password: str) -> list:
    """Patient-portal password policy: ≥8 chars, ≥1 uppercase, ≥1 special. Returns the failed rule codes."""
    import re
    pw = password or ""
    failed = []
    if len(pw) < 8:
        failed.append("min_length")
    if not re.search(r"[A-Z]", pw):
        failed.append("uppercase")
    if not re.search(f"[{PASSWORD_SPECIALS}]", pw):
        failed.append("special")
    return failed
