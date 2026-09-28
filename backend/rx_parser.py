"""Conservative parser for prescriptions pasted from Access EMR.

Assistance only — NEVER fabricates clinical values. Anything not confidently
identified is left blank and flagged in `needs_review`. The exact original line
is always preserved as `original_text`.
"""
import re

_UNIT = r"(?:mg/mL|mcg/mL|µg/mL|mg/g|µg|mcg|mg|g|mL|L|units?|iu|%)"
_STRENGTH_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(" + _UNIT + r")\b", re.IGNORECASE)

_FORMS = [
    "tablet", "capsule", "caplet", "injection", "inj", "cream", "ointment",
    "solution", "suspension", "syrup", "patch", "suppository", "inhaler",
    "drops", "pen", "spray", "gel", "lotion", "powder", "lozenge",
]
_FORM_RE = re.compile(r"\b(" + "|".join(_FORMS) + r")s?\b", re.IGNORECASE)

_ATTRS = [
    "film-coated", "film coated", "uncoated", "scored", "unscored",
    "prefilled pen", "pref pen", "prefilled", "extended-release", "extended release",
    "sustained-release", "sustained release", "modified-release", "modified release",
    "enteric-coated", "enteric coated", "chewable", "effervescent", "sublingual",
]


def _clean_num(s):
    return s.replace(",", ".") if s else s


def _parse_med(left: str, right: str, original: str) -> dict:
    """left = medication descriptor, right = SIG/directions, original = full line."""
    needs = []
    strength = None
    unit = None
    sm = _STRENGTH_RE.search(left)
    if sm:
        strength = f"{_clean_num(sm.group(1))} {sm.group(2)}".strip()
        unit = sm.group(2)
    else:
        needs.append("strength")

    attributes = []
    low = left.lower()
    for a in _ATTRS:
        if a in low:
            attributes.append(a.replace(" ", "-") if "-" not in a else a)

    form = None
    fm = _FORM_RE.search(left)
    if fm:
        form = fm.group(1).lower()
    else:
        needs.append("form")

    # Drug name = text before the strength token; else before the first form word.
    name = left
    if sm:
        name = left[:sm.start()].strip(" -,:")
    elif fm:
        name = left[:fm.start()].strip(" -,:")
    name = re.sub(r"\s{2,}", " ", name).strip(" -,:")
    if not name:
        name = left.strip()
        needs.append("drug")

    sig = right.strip() or None
    if not sig:
        needs.append("sig")

    return {
        "original_text": original.strip(),
        "drug": name or None,
        "strength": strength,
        "unit": unit,
        "form": form,
        "attributes": attributes,
        "sig": sig,
        "quantity": None,   # never fabricated
        "refills": None,    # prescription-level handled separately
        "note": None,
        "needs_review": sorted(set(needs)),
    }


_IDENTITY_KEYS = {
    "patient": "name", "name": "name", "patient name": "name",
    "pin": "pin", "visita pin": "pin", "id": "pin",
    "dob": "dob", "date of birth": "dob",
}


def parse_access_rx(text: str) -> dict:
    lines = [l.rstrip() for l in (text or "").splitlines()]
    meds, notes = [], []
    months = refills = None
    identity = {}

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        low = line.lower()

        m = re.search(r"number of months\s*[:\-]?\s*(\d+)", low)
        if m:
            months = int(m.group(1))
            continue
        m = re.search(r"number of refills\s*[:\-]?\s*(\d+)", low)
        if m:
            refills = int(m.group(1))
            continue
        m = re.search(r"vacation supply for\s*(\d+)\s*months?", low)
        if m:
            months = int(m.group(1))
            notes.append(line)
            continue

        # identity metadata lines (Patient:/PIN:/DOB:)
        if ":" in line:
            key = line.split(":", 1)[0].strip().lower()
            if key in _IDENTITY_KEYS:
                identity[_IDENTITY_KEYS[key]] = line.split(":", 1)[1].strip()
                continue

        # medication line: "descriptor: sig"
        if ":" in line:
            left, right = line.split(":", 1)
            meds.append(_parse_med(left.strip(), right.strip(), line))
        else:
            # a bare line with a strength is likely a medication with no SIG yet
            if _STRENGTH_RE.search(line):
                meds.append(_parse_med(line, "", line))
            else:
                notes.append(line)

    return {
        "medications": meds,
        "months": months,
        "refills": refills,
        "note": " ".join(notes).strip() or None,
        "identity": identity or None,
        "source_text": text or "",
    }
