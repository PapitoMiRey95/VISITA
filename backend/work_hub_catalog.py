"""Single source for Work Hub structured clinical choices (type → reason / detail / clinic action).
Codes are stable; labels are snapshotted onto each work item so history stays readable if labels change.
Deliberately small — not a medical terminology system."""
from typing import Optional

CLINICAL_TYPES = ("CALL_BOOK_PATIENT", "CONSULT_SPECIALIST", "PROCEDURE_SURGERY", "REFERRAL_FOLLOWUP", "IMAGING", "BLOODWORK")

CALL_TRANSFER_ON_ARRIVAL = "CALL_TRANSFER_ON_ARRIVAL"
CALL_TRANSFER_LABEL = "Call patient — put through to me when I arrive"

REFERRAL_REASONS = [
    ("DECLINED", "Declined"), ("MORE_INFO_REQUESTED", "More information requested"), ("PROVIDER_UPDATE", "Provider moved / contact update"),
    ("ACCEPTED_IN_PROCESS", "Accepted / in process"), ("APPOINTMENT_BOOKED", "Appointment booked"), ("FOLLOW_UP_NEEDED", "Follow-up needed"),
    ("NEW_REFERRAL_NEEDED", "New referral needed"), ("OTHER", "Other"),
]

REASONS = {
    "CALL_BOOK_PATIENT": [
        ("BOOK_FOLLOWUP", "Book follow-up"), ("CALL_PATIENT", "Call patient"), (CALL_TRANSFER_ON_ARRIVAL, CALL_TRANSFER_LABEL),
        ("DISCUSS_WITH_PATIENT", "Discuss with patient"), ("PATIENT_REQUESTED_CALL", "Patient requested physician call"),
        ("REVIEW_ISSUE", "Review issue with patient"), ("OTHER", "Other"),
    ],
    "CONSULT_SPECIALIST": [
        ("BOOK_CONSULT", "Book specialist consultation"), ("CONSULT_PENDING", "Specialist consultation pending"), ("SPECIALIST_FOLLOWUP", "Specialist follow-up"),
        ("DISCUSS_RECOMMENDATION", "Discuss specialist recommendation"), ("REVIEW_LETTER", "Review consultation letter"),
        ("PATIENT_ASKING", "Patient asking about consultation"), ("NEW_SPECIALIST", "New specialist needed"), ("OTHER", "Other"),
    ],
    "PROCEDURE_SURGERY": [
        ("BOOK_PROCEDURE", "Book procedure"), ("DISCUSS_PROCEDURE", "Discuss procedure"), ("PRE_PROCEDURE", "Pre-procedure follow-up"),
        ("POST_PROCEDURE", "Post-procedure follow-up"), ("REVIEW_RESULT", "Review procedure result"), ("PATIENT_ASKING", "Patient asking about procedure"), ("OTHER", "Other"),
    ],
    "REFERRAL_FOLLOWUP": REFERRAL_REASONS,
    "IMAGING": [
        ("BOOK_IMAGING", "Book imaging"), ("REVIEW_RESULT", "Review result"), ("DISCUSS_ABNORMAL", "Discuss abnormal result"), ("REPEAT_IMAGING", "Repeat imaging"),
        ("FOLLOWUP_IMAGING", "Follow-up imaging"), ("PATIENT_ASKING", "Patient asking about imaging"), ("OTHER", "Other"),
    ],
    "BLOODWORK": [
        ("REVIEW_RESULT", "Review result"), ("DISCUSS_ABNORMAL", "Discuss abnormal result"), ("REPEAT_BLOODWORK", "Repeat bloodwork"), ("ROUTINE_MONITORING", "Routine monitoring"),
        ("MEDICATION_MONITORING", "Medication monitoring"), ("SCREENING_FOLLOWUP", "Screening / follow-up"), ("PRE_PROCEDURE", "Pre-procedure / pre-op"),
        ("PATIENT_ASKING", "Patient asking about result"), ("OTHER", "Other"),
    ],
}

# Detail selectors per type: field name → (label, multi, options). Any option code "OTHER" accepts free text.
DETAILS = {
    "PROCEDURE_SURGERY": [("procedure", "Procedure", False, [
        ("COLONOSCOPY", "Colonoscopy"), ("OGD", "OGD / Gastroscopy"), ("ENDOSCOPY", "Endoscopy"), ("BIOPSY", "Biopsy"), ("EXCISION", "Excision"),
        ("MINOR_PROCEDURE", "Minor procedure"), ("SURGERY", "Surgery"), ("OTHER", "Other procedure"),
    ])],
    "IMAGING": [
        ("modality", "Modality", False, [
            ("XRAY", "X-ray"), ("US", "Ultrasound"), ("CT", "CT"), ("MRI", "MRI"), ("MAMMO", "Mammogram"), ("BMD", "Bone density / BMD"), ("OTHER", "Other imaging"),
        ]),
        ("body_site", "Body area", False, [
            ("HEAD", "Head / Brain"), ("NECK", "Neck"), ("CHEST", "Chest"), ("ABDOMEN", "Abdomen"), ("PELVIS", "Pelvis"), ("ABDO_PELVIS", "Abdomen + Pelvis"),
            ("C_SPINE", "Cervical spine"), ("T_SPINE", "Thoracic spine"), ("L_SPINE", "Lumbar spine"), ("SHOULDER", "Shoulder"), ("ELBOW", "Elbow"),
            ("WRIST_HAND", "Wrist / Hand"), ("HIP", "Hip"), ("KNEE", "Knee"), ("ANKLE_FOOT", "Ankle / Foot"), ("BREAST", "Breast"), ("THYROID", "Thyroid"),
            ("LIVER", "Liver"), ("KIDNEY_URINARY", "Kidney / Urinary"), ("OTHER", "Other / specify"),
        ]),
    ],
    "BLOODWORK": [("bloodwork_tests", "Tests", True, [
        ("CBC", "CBC / Hgb"), ("LP", "LP / Lipid Profile"), ("HBA1C", "HbA1c"), ("PSA", "PSA"), ("TSH", "TSH"), ("FERRITIN", "Ferritin / Iron studies"),
        ("B12", "Vitamin B12"), ("CREAT_EGFR", "Creatinine / eGFR"), ("LYTES", "Electrolytes"), ("LFT", "Liver enzymes / LFT"), ("GLUCOSE", "Glucose"),
        ("INR", "INR"), ("UA", "Urinalysis"), ("OTHER", "Other bloodwork"),
    ])],
}

CLINIC_ACTIONS = [
    ("BOOK_PATIENT", "Book patient"), ("CALL_PATIENT", "Call patient"), (CALL_TRANSFER_ON_ARRIVAL, CALL_TRANSFER_LABEL),
    ("ASK_PATIENT_TO_BOOK", "Ask patient to book"), ("RELAY_INSTRUCTION", "Relay physician instruction"),
    ("INTERNAL", "No patient contact / internal task"), ("OTHER", "Other"),
]


def catalog() -> dict:
    """Serialized for the frontend (one source; never duplicated in React)."""
    return {
        "clinical_types": list(CLINICAL_TYPES),
        "reasons": {t: [{"code": c, "label": l} for c, l in opts] for t, opts in REASONS.items()},
        "details": {t: [{"field": f, "label": lab, "multi": multi, "options": [{"code": c, "label": l} for c, l in opts]} for f, lab, multi, opts in fields] for t, fields in DETAILS.items()},
        "clinic_actions": [{"code": c, "label": l} for c, l in CLINIC_ACTIONS],
        "call_transfer_code": CALL_TRANSFER_ON_ARRIVAL,
    }


def _label(options, code) -> Optional[str]:
    return next((l for c, l in options if c == code), None)


def validate_structured(category: str, reason_code: Optional[str], detail: Optional[dict], clinic_action: Optional[str]):
    """Returns (reason_label, clinical_detail snapshot or None, clinic_action_label, error). Codes outside the catalog are rejected."""
    if category not in CLINICAL_TYPES:
        if reason_code or detail or clinic_action:
            return None, None, None, "Reason, details and clinic action apply to clinical work types only."
        return None, None, None, None
    reason_label = None
    if reason_code:
        reason_label = _label(REASONS[category], reason_code)
        if not reason_label:
            return None, None, None, "Please choose a valid reason."
    snap = None
    if detail:
        snap = {}
        allowed = {f: (multi, opts) for f, _, multi, opts in DETAILS.get(category, [])}
        for field, value in detail.items():
            if field == "other_text":
                if value:
                    snap["other_text"] = str(value).strip()[:300]
                continue
            if field not in allowed:
                return None, None, None, f"'{field}' does not apply to this work type."
            multi, opts = allowed[field]
            codes = value if isinstance(value, list) else [value]
            codes = [c for c in codes if c]
            if not codes:
                continue
            if not multi and len(codes) > 1:
                return None, None, None, "Please choose a single option."
            labelled = []
            for c in codes:
                lab = _label(opts, c)
                if not lab:
                    return None, None, None, "Please choose a valid option."
                labelled.append({"code": c, "label": lab})
            snap[field] = labelled if multi else labelled[0]
        if not snap:
            snap = None
    action_label = None
    if clinic_action:
        action_label = _label(CLINIC_ACTIONS, clinic_action)
        if not action_label:
            return None, None, None, "Please choose a valid clinic action."
    return reason_label, snap, action_label, None


def detail_summary(snap: Optional[dict]) -> Optional[str]:
    """Deterministic 'MRI · Liver' / 'CBC / Hgb + LP / Lipid Profile' / 'Colonoscopy' text (never AI-generated)."""
    if not snap:
        return None
    parts = []
    other, used_other = snap.get("other_text"), False
    def lab(v):
        nonlocal used_other
        if v["code"] == "OTHER" and other and not used_other:
            used_other = True
            return other
        return v["label"]
    for key in ("procedure", "modality", "body_site"):
        v = snap.get(key)
        if v:
            parts.append(lab(v))
    tests = snap.get("bloodwork_tests")
    if tests:
        parts.append(" + ".join(lab(t) for t in tests))
    return " · ".join(parts) or None


def auto_message(type_label: str, summary: Optional[str], reason_label: Optional[str], action_label: Optional[str], priority_text: Optional[str]) -> str:
    """Fallback 'What needs to be done?' text when the physician leaves it blank."""
    head = " · ".join(p for p in (type_label, summary) if p)
    body = " — ".join(p for p in (head, reason_label) if p)
    if CALL_TRANSFER_LABEL in (reason_label, action_label):
        priority_text = None  # transfer instruction already says what to do; the priority badge carries urgency
    tail = [p for p in (action_label if action_label != reason_label else None, priority_text) if p]
    return ". ".join([body, *tail]).rstrip(".") + "."
