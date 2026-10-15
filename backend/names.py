"""Shared canonical patient full-name formatter. Clinical convention: 'LAST NAME(S), First Name(s)'.
Preserves every stored given name / surname (incl. compound surnames in a single field and the
optional middle_name / second_last_name portal fields). Never invents or duplicates parts."""
import re


def _parts(base, extra):
    b = [t for t in re.split(r"\s+", str(base or "").strip()) if t]
    e = [t for t in re.split(r"\s+", str(extra or "").strip()) if t]
    bu = {t.upper() for t in b}
    if e and all(t.upper() in bu for t in e):
        e = []  # supplemental field merely repeats the base field — do not duplicate
    return b + e


def family_names(doc: dict) -> str:
    return " ".join(_parts(doc.get("last_name"), doc.get("second_last_name"))).upper()


def given_names(doc: dict) -> str:
    return " ".join(_parts(doc.get("first_name"), doc.get("middle_name")))


def full_display_name(doc: dict) -> str:
    fam, giv = family_names(doc or {}), given_names(doc or {})
    if fam and giv:
        return f"{fam}, {giv}"
    return fam or giv or ""
