"""Patient identity helpers: Health Card normalization/formatting/status and
concurrency-safe VISITA PIN generation. Pure/stateless except PIN claim."""
import re
import random
from datetime import datetime, date
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

TZ = "America/Toronto"


def normalize_health_card(number, version):
    """Return (num10, ver2) or raise ValueError. Strips spaces/punctuation,
    keeps digits for the number, letters for the version (uppercased)."""
    num = re.sub(r"\D", "", str(number or ""))
    ver = re.sub(r"[^A-Za-z]", "", str(version or "")).upper()
    if len(num) != 10:
        raise ValueError("Health Card number must be exactly 10 digits.")
    if len(ver) != 2:
        raise ValueError("Version Code must be exactly 2 letters.")
    return num, ver


def format_health_card(number, version):
    """Display as '#### ### ### XX'. Best-effort if number isn't 10 digits."""
    num = re.sub(r"\D", "", str(number or ""))
    ver = re.sub(r"[^A-Za-z]", "", str(version or "")).upper()
    if not num and not ver:
        return None
    base = f"{num[0:4]} {num[4:7]} {num[7:10]}" if len(num) == 10 else num
    return f"{base} {ver}".strip()


def normalize_phone(s):
    """Format a North American number as '(XXX) XXX-XXXX' when 10 digits; else trimmed input."""
    digits = re.sub(r"\D", "", str(s or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    return str(s or "").strip()


def valid_date(s):
    if not s:
        return True  # optional
    try:
        date.fromisoformat(str(s)[:10])
        return True
    except Exception:
        return False


def health_card_status(expiry_iso, tz=TZ):
    """VALID | EXPIRING_SOON (<=60d) | EXPIRED | INCOMPLETE (no/invalid expiry)."""
    if not expiry_iso:
        return "INCOMPLETE"
    try:
        exp = date.fromisoformat(str(expiry_iso)[:10])
    except Exception:
        return "INCOMPLETE"
    today = datetime.now(ZoneInfo(tz)).date()
    if exp < today:
        return "EXPIRED"
    if (exp - today).days <= 60:
        return "EXPIRING_SOON"
    return "VALID"


async def collect_used_pins(db):
    used = set()
    async for d in db.patient_directory.find({"visita_patient_id": {"$ne": None}}, {"visita_patient_id": 1}):
        used.add(str(d["visita_patient_id"]))
    async for p in db.patients.find({"visita_patient_id": {"$ne": None}}, {"visita_patient_id": 1}):
        used.add(str(p["visita_patient_id"]))
    async for r in db.visita_pins.find({}, {"_id": 1}):
        used.add(str(r["_id"]))
    return used


async def assign_visita_pin(db, patient_id):
    """Atomically assign a unique 4-digit PIN (1000-9999) across patient_directory,
    patients and the visita_pins claim registry. Returns str, or None if exhausted.
    Never reuses a PIN present in any of those sources."""
    used = await collect_used_pins(db)
    candidates = [n for n in range(1000, 10000) if str(n) not in used]
    if not candidates:
        return None
    random.shuffle(candidates)
    for pin in candidates:
        try:
            await db.visita_pins.insert_one({
                "_id": str(pin), "patient_id": patient_id,
                "created_at": datetime.now(ZoneInfo(TZ)).isoformat(),
            })
            return str(pin)
        except DuplicateKeyError:
            continue
    return None
