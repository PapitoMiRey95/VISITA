"""Canonical patient-sex resolver (shared by clinical modules). Returns MALE | FEMALE | UNKNOWN — never guesses.
Priority: portal `patients.sex` -> authoritative directory sex -> UNKNOWN.

Directory `sex_code` is stored raw ('1' / '2' from the Access tblPatient export). Its meaning is NOT yet proven from
VIen data (no linked patient has both portal sex and directory sex_code), so the mapping below is intentionally EMPTY.
Once confirmed, fill DIRECTORY_SEX_CODE (e.g. {"1": "MALE", "2": "FEMALE"}) — this is the only place that needs to change."""

MALE, FEMALE, UNKNOWN = "MALE", "FEMALE", "UNKNOWN"
PORTAL_SEX = {"male": MALE, "m": MALE, "female": FEMALE, "f": FEMALE}
DIRECTORY_SEX_CODE: dict[str, str] = {}  # pending confirmation — see module docstring


def resolve_patient_sex(portal: dict | None, directory: dict | None) -> str:
    raw = (portal or {}).get("sex")
    if raw and PORTAL_SEX.get(str(raw).strip().lower()):
        return PORTAL_SEX[str(raw).strip().lower()]
    code = (directory or {}).get("sex_code")
    if code is not None and DIRECTORY_SEX_CODE.get(str(code).strip()):
        return DIRECTORY_SEX_CODE[str(code).strip()]
    return UNKNOWN
