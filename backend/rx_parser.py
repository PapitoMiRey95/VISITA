"""Conservative parser for prescriptions pasted from Access EMR.

Assistance only - NEVER fabricates clinical values. Anything not confidently
identified is left blank and flagged in `needs_review`. The exact original text
for each medication is always preserved as `original_text`.

Key behaviour: medications are segmented by drug/strength boundaries, so a
prescription pasted as a single paragraph (line breaks lost on copy) still
produces ONE structured record per medication. A subsequent medication is never
appended to the previous medication's SIG.
"""
import re

_UNIT = r"(?:mg/mL|mcg/mL|µg/mL|mg/g|µg|mcg|mg|g|mL|L|units?|iu|%)"
_STRENGTH_CORE = r"\d+(?:[.,]\d+)?\s*" + _UNIT + r"(?![A-Za-z])"
# Combo-aware: "16 mg/12.5 mg", "1000 mg/50 mg" count as ONE strength.
_STRENGTH_RE = re.compile(r"(" + _STRENGTH_CORE + r"(?:\s*/\s*" + _STRENGTH_CORE + r")?)", re.IGNORECASE)
_UNIT_RE = re.compile(_UNIT, re.IGNORECASE)

_FORMS = [
    "tablet", "capsule", "caplet", "injection", "inj", "cream", "ointment",
    "solution", "suspension", "syrup", "patch", "suppository", "inhaler",
    "drops", "pen", "spray", "gel", "lotion", "powder", "lozenge",
]
_FORMSET = set(_FORMS) | {f + "s" for f in _FORMS}
_FORM_RE = re.compile(r"\b(" + "|".join(_FORMS) + r")s?\b", re.IGNORECASE)

_ATTRS = [
    "film-coated", "film coated", "uncoated", "scored", "unscored",
    "prefilled pen", "pref pen", "prefilled", "extended-release", "extended release",
    "extended", "coated", "immediate", "sustained-release", "sustained release",
    "modified-release", "modified release", "modified", "release",
    "enteric-coated", "enteric coated", "chewable", "effervescent", "sublingual",
]
_ATTRSET = set()
for _a in _ATTRS:
    for _w in _a.split():
        _ATTRSET.add(_w.lower())

# Action prefixes that qualify the medication (never dropped, never reinterpreted).
_ACTIONS = {
    "hold": "HOLD", "start": "START", "continue": "CONTINUE", "cont": "CONTINUE",
    "stop": "STOP", "discontinue": "DISCONTINUE",
}

# SIG / dosing vocabulary used to (a) terminate backward drug-name capture and
# (b) recognise directions in no-colon lines.
_DOSING = {
    "OD", "BID", "TID", "QID", "QD", "QHS", "QAM", "QPM", "HS", "PRN", "AC", "PC",
    "PO", "SL", "IM", "SC", "SUBQ", "PR", "PV", "OU", "OS", "DAILY", "ONCE",
    "TWICE", "THRICE", "WEEKLY", "MANE", "NOCTE", "MORNING", "NIGHT", "NOON",
    "BEDTIME", "AM", "PM", "EVERY", "BREAKFAST", "DINNER", "LUNCH", "SUPPER",
    "WITH", "MEALS", "MEAL", "THEN", "AT",
}
_FRACTIONS = {"½", "¼", "¾", "⅓", "⅔"}
_PUNCT = " .,;:()[]"


def _clean_num(s):
    return s.replace(",", ".") if s else s


def _extract_attributes(text):
    """Match formulation attributes as whole words; drop any that are a substring
    of a longer matched phrase (so 'unscored' doesn't also yield 'scored', and
    'modified release' doesn't also yield 'modified'/'release')."""
    low = (text or "").lower()
    found = []
    for a in _ATTRS:
        if re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", low):
            found.append(a)
    kept = [a for a in found if not any(a != b and a in b for b in found)]
    seen, out = set(), []
    for a in kept:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _core(tok):
    return tok.strip(_PUNCT)


def _is_dosing_token(tok):
    c = _core(tok)
    if not c:
        return False
    up = c.upper()
    if up in _DOSING:
        return True
    if c.lower() in _FORMSET:
        return True
    if c in _FRACTIONS or c.replace("/", "").isdigit():
        return True
    # dose numbers like "1", "1/2", "0.5"
    if re.fullmatch(r"\d+(?:[.,/]\d+)?", c):
        return True
    # short all-cap abbreviation e.g. OD-BID, QAM
    if re.fullmatch(r"[A-Z]{1,4}(?:-[A-Z]{1,4})?", up) and up not in {"LU"}:
        return True
    return False


def _is_stopword_sig(tok):
    """A capitalised SIG abbreviation that ends backward drug-name capture."""
    c = _core(tok)
    if not c:
        return False
    up = c.upper()
    if up in _DOSING:
        return True
    if re.fullmatch(r"[A-Z]{1,4}(?:-[A-Z]{1,4})?", c) and c == up and up != "LU":
        # all-caps short token that isn't LU (coverage code) -> SIG abbrev
        return True
    return False


# --- Segmentation -----------------------------------------------------------

_TOKEN_RE = re.compile(r"\S+")


def _tokens_before(text, pos):
    return [(m.group(0), m.start()) for m in _TOKEN_RE.finditer(text[:pos])]


def _find_name_start(text, anchor_start):
    """Walk backwards from a strength anchor to locate where the drug name begins.

    Returns (name_start_index, action, uncertain)."""
    toks = _tokens_before(text, anchor_start)
    action = None
    have_capital = False
    name_start = anchor_start
    for tok, start in reversed(toks):
        c = _core(tok)
        if not c:
            break
        low = c.lower()
        if low in _ACTIONS:
            if have_capital:
                action = _ACTIONS[low]
                name_start = start
            break
        if _is_stopword_sig(tok):
            break
        # a plain number / #qty is a SIG/quantity token -> boundary
        if re.fullmatch(r"#?\d+(?:[.,/]\d+)?", c):
            break
        is_connector = ("/" in tok) or tok.startswith("(") or tok.endswith(")")
        first = c[0]
        if is_connector:
            name_start = start
            if any(ch.isupper() for ch in c):
                have_capital = True
            continue
        if first.isalpha() and first.isupper():
            name_start = start
            have_capital = True
            continue
        if first.isalpha() and first.islower():
            if not have_capital:
                # salt / continuation word before the capitalised head (fumarate, besylate)
                name_start = start
                continue
            break
        break
    return name_start, action, (not have_capital)


def _segment(text):
    """Split medication text into (start, end, action, uncertain) segments."""
    anchors = list(_STRENGTH_RE.finditer(text))
    if not anchors:
        return [], text.strip()
    starts = []
    for a in anchors:
        ns, action, uncertain = _find_name_start(text, a.start())
        starts.append((ns, action, uncertain))
    lead = text[:starts[0][0]].strip()
    segments = []
    for i, (ns, action, uncertain) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        segments.append((ns, end, action, uncertain))
    return segments, lead


# --- Directions splitting (no-colon lines) ----------------------------------

def _split_directions(text):
    """Conservatively split trailing free-text into sig / quantity / refills /
    additional_instructions. Only explicitly recognisable data is extracted."""
    raw = (text or "").strip(" .,;:")
    quantity = refills = None
    additional = []
    needs = []
    if not raw:
        return None, None, None, None, needs

    # Markers that terminate the leading SIG portion.
    marker = None
    for pat in [r"#", r"\bLU\b", r"\bdispense\b", r"\bno\s+refills?\b", r"\d+\s+refills?\b"]:
        m = re.search(pat, raw, re.IGNORECASE)
        if m and (marker is None or m.start() < marker):
            marker = m.start()
    sig_part = raw[:marker] if marker is not None else raw
    tail = raw[marker:] if marker is not None else ""

    # SIG = leading run of dosing-like tokens; anything non-dosing in the prefix
    # is preserved (additional) and flagged.
    sig_tokens, leftover = [], []
    broke = False
    for tok in sig_part.split():
        if not broke and _is_dosing_token(tok):
            sig_tokens.append(tok)
        else:
            broke = True
            if _core(tok):
                leftover.append(tok)
    sig = " ".join(sig_tokens).strip(_PUNCT) or None
    if leftover:
        additional.append(" ".join(leftover).strip(_PUNCT))
        needs.append("directions")

    # Quantity from #NN (first occurrence anywhere).
    mq = re.search(r"#\s*(\d+)", raw)
    if mq:
        quantity = mq.group(1)
    # Refills.
    if re.search(r"\bno\s+refills?\b", raw, re.IGNORECASE):
        refills = "0"
    else:
        mr = re.search(r"\b(\d+)\s+refills?\b", raw, re.IGNORECASE)
        if mr:
            refills = mr.group(1)
    # LU coverage codes -> additional.
    for lu in re.findall(r"\bLU\s*\d+\b", raw, re.IGNORECASE):
        additional.append(lu)
    # dispense phrase -> additional (up to refill wording).
    md = re.search(r"\bdispense\b.*?(?=(?:\bno\s+refills?\b)|(?:\d+\s+refills?\b)|$)", raw, re.IGNORECASE)
    if md:
        phrase = md.group(0).strip(" .,;")
        if phrase:
            additional.append(phrase)

    # De-dupe / drop empties while preserving order.
    seen, add_clean = set(), []
    for a in additional:
        a = a.strip(" .,;")
        if a and a.lower() not in seen:
            seen.add(a.lower())
            add_clean.append(a)
    additional_str = "; ".join(add_clean) or None
    return sig, quantity, refills, additional_str, needs


# --- Per-segment parse -------------------------------------------------------

def _parse_segment(seg_text, action, uncertain):
    original = seg_text.strip()
    needs = []
    if uncertain:
        needs.append("boundary")

    # Strip a leading action word if present (already captured separately).
    work = original
    for low, up in _ACTIONS.items():
        m = re.match(r"^\s*" + low + r"\b\s*", work, re.IGNORECASE)
        if m and up == action:
            work = work[m.end():]
            break

    sm = _STRENGTH_RE.search(work)
    strength = unit = None
    if sm:
        strength = re.sub(r"\s+", " ", sm.group(1)).strip()
        strength = strength.replace(" ,", ",")
        um = _UNIT_RE.search(sm.group(1))
        unit = um.group(0) if um else None
    else:
        needs.append("strength")

    # Drug name = text before the strength token (or before first form word).
    if sm:
        name = work[:sm.start()].strip(" -,:")
    else:
        fm0 = _FORM_RE.search(work)
        name = work[:fm0.start()].strip(" -,:") if fm0 else work.strip()
    name = re.sub(r"\s{2,}", " ", name).strip(" -,:")
    if not name:
        name = None
        needs.append("drug")

    rest = work[sm.end():] if sm else ""
    form = None
    attributes = []
    sig = quantity = refills = additional = None

    if ":" in rest:
        descriptor, right = rest.split(":", 1)
        fm = _FORM_RE.search(descriptor)
        if fm:
            form = fm.group(1).lower()
        attributes = _extract_attributes(descriptor)
        sig = right.strip(_PUNCT) or None
        if not sig:
            needs.append("sig")
        mq = re.search(r"#\s*(\d+)", rest)
        if mq:
            quantity = mq.group(1)
    else:
        # No colon: peel leading form/attr words, split the remaining directions.
        toks = rest.strip(_PUNCT).split()
        i = 0
        lead = []
        while i < len(toks) and (_core(toks[i]).lower() in _FORMSET or _core(toks[i]).lower() in _ATTRSET):
            lead.append(_core(toks[i]).lower())
            i += 1
        if lead:
            for w in lead:
                if w in _FORMSET and not form:
                    form = w.rstrip("s")
            attributes = _extract_attributes(" ".join(lead))
        directions = " ".join(toks[i:])
        sig, quantity, refills, additional, dneeds = _split_directions(directions)
        needs.extend(dneeds)
        if not sig and not additional and not quantity:
            needs.append("sig")

    # De-dupe attributes, keep order.
    seen, attrs = set(), []
    for a in attributes:
        if a not in seen:
            seen.add(a)
            attrs.append(a)

    return {
        "original_text": original,
        "action": action,
        "drug": name,
        "strength": strength,
        "unit": unit,
        "form": form,
        "attributes": attrs,
        "sig": sig,
        "quantity": quantity,
        "refills": refills,
        "additional_instructions": additional,
        "note": None,
        "needs_review": sorted(set(needs)),
    }


_IDENTITY_KEYS = {
    "patient": "name", "name": "name", "patient name": "name",
    "pin": "pin", "visita pin": "pin", "id": "pin",
    "dob": "dob", "date of birth": "dob",
}


def _strip_rx_level(text):
    months = refills = None
    notes = []

    def _grab(pat, cast=int):
        nonlocal text
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            text = (text[:m.start()] + " " + text[m.end():]).strip()
            return cast(m.group(1))
        return None

    months = _grab(r"number of months\s*[:\-]?\s*(\d+)")
    refills = _grab(r"number of refills\s*[:\-]?\s*(\d+)")
    m = re.search(r"vacation supply(?:\s+for\s+(\d+)\s+months?)?", text, re.IGNORECASE)
    if m:
        if m.group(1) and months is None:
            months = int(m.group(1))
    return text, months, refills, notes


def parse_access_rx(text: str) -> dict:
    lines = [l.rstrip() for l in (text or "").splitlines()]
    med_parts, notes = [], []
    months = refills = None
    identity = {}

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        low = line.lower()

        m = re.search(r"number of months\s*[:\-]?\s*(\d+)", low)
        if m and line.lower().startswith("number of months"):
            months = int(m.group(1))
            continue
        m = re.search(r"number of refills\s*[:\-]?\s*(\d+)", low)
        if m and line.lower().startswith("number of refills"):
            refills = int(m.group(1))
            continue

        # identity metadata lines (Patient:/PIN:/DOB:)
        if ":" in line:
            key = line.split(":", 1)[0].strip().lower()
            if key in _IDENTITY_KEYS:
                identity[_IDENTITY_KEYS[key]] = line.split(":", 1)[1].strip()
                continue

        # A line with no strength and no colon is prescription-level note text.
        if not _STRENGTH_RE.search(line) and ":" not in line:
            notes.append(line)
            continue

        med_parts.append(line)

    med_text = " ".join(med_parts)
    # Single-paragraph safety: strip Rx-level fields that were glued into the text.
    med_text, m2, r2, _ = _strip_rx_level(med_text)
    if months is None:
        months = m2
    if refills is None:
        refills = r2

    segments, lead = _segment(med_text)
    meds = []
    for (start, end, action, uncertain) in segments:
        seg_text = med_text[start:end].strip()
        if not seg_text:
            continue
        meds.append(_parse_segment(seg_text, action, uncertain))

    if lead:
        notes.insert(0, lead)

    return {
        "medications": meds,
        "months": months,
        "refills": refills,
        "note": " ".join(notes).strip() or None,
        "identity": identity or None,
        "source_text": text or "",
    }
