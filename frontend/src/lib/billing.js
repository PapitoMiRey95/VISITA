// Shared billing display helpers (Phase 2). Keep labels/colors in one place so
// the patient portal and internal views stay consistent.

export function formatMoney(amount, currency = "CAD") {
    if (amount === null || amount === undefined || isNaN(amount)) return "—";
    const n = Number(amount).toLocaleString("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `$${n} ${currency}`;
}

export const INVOICE_STATUS = {
    DRAFT: ["Draft", "bg-slate-100 text-slate-600"],
    ISSUED: ["Issued", "bg-amber-100 text-amber-700"],
    PAYMENT_SUBMITTED: ["Payment Submitted — Pending Verification", "bg-sky-100 text-sky-700"],
    PAID: ["Paid — Verified", "bg-emerald-100 text-emerald-700"],
    VOID: ["Void", "bg-slate-200 text-slate-500 line-through"],
};

export const PAYMENT_MODE = {
    NO_PAYMENT_REQUIRED: "No Payment Required",
    PREPAYMENT_REQUIRED: "Prepayment Required",
    INVOICE_AFTER_SERVICE: "Invoice After Service",
};

export const PAYMENT_STATUS = {
    NONE: ["No Payment Required", "bg-slate-100 text-slate-600"],
    PENDING: ["Payment Pending", "bg-amber-100 text-amber-700"],
    PAYMENT_SUBMITTED: ["Payment Submitted — Pending Verification", "bg-sky-100 text-sky-700"],
    PAID: ["Paid — Verified", "bg-emerald-100 text-emerald-700"],
};

export function InvoiceStatusPill({ status }) {
    const [label, cls] = INVOICE_STATUS[status] || [status, "bg-slate-100 text-slate-600"];
    return <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`}>{label}</span>;
}

// ---- Direct 3rd Party Billing ------------------------------------------------
export const HOURS_OPTIONS = Array.from({ length: 51 }, (_, i) => i); // 0..50

// Minutes -> hour multiplier. MUST match backend billing.PARTIAL_MULTIPLIERS.
export const PARTIAL_OPTIONS = [
    { min: 0, mult: 0.0 }, { min: 5, mult: 0.08 }, { min: 10, mult: 0.17 },
    { min: 15, mult: 0.25 }, { min: 20, mult: 0.33 }, { min: 25, mult: 0.416 },
    { min: 30, mult: 0.50 }, { min: 35, mult: 0.58 }, { min: 40, mult: 0.67 },
    { min: 45, mult: 0.75 }, { min: 50, mult: 0.83 }, { min: 55, mult: 0.92 },
];

export function computeTimeBasedTotal(rate, wholeHours, partialMult) {
    const t = Number(rate || 0) * (Number(wholeHours || 0) + Number(partialMult || 0));
    return Math.round(t * 100) / 100;
}

export const BILLING_METHOD_LABEL = {
    SET_SERVICE: "Set Service",
    TIME_BASED: "Time-Based",
};

// Category display order + labels for the Set Service catalogue.
export const SERVICE_CATEGORIES = [
    ["MEDICAL_NOTES", "Medical Notes / Certificates"],
    ["SCHOOL_EMPLOYMENT_FITNESS", "School / Employment / Fitness"],
    ["DRIVING", "Driving / Transportation"],
    ["INSURANCE_THIRD_PARTY", "Insurance / Third Party"],
    ["DISABILITY_BENEFITS", "Disability / Benefits"],
    ["WSIB_OCCUPATIONAL", "WSIB / Occupational"],
    ["MEDICAL_RECORDS_ADMIN", "Medical Records / Administrative"],
    ["PRESCRIPTION_REQUEST", "Prescription / Request"],
    ["APPOINTMENT", "Appointment"],
    ["OTHER", "Other"],
];
export const CATEGORY_LABEL = Object.fromEntries(SERVICE_CATEGORIES);

export const CLASSIFICATIONS = [
    ["PATIENT_THIRD_PARTY_BILLABLE", "Patient / Third-Party Billable"],
    ["THIRD_PARTY_EXTERNAL_FEE", "Third Party / External Fee Rule"],
    ["NO_CHARGE", "No Charge / Unremunerated"],
    ["REVIEW_REQUIRED", "Review Required"],
];
export const CLASSIFICATION_LABEL = Object.fromEntries(CLASSIFICATIONS);

// Default catalogue: stable codes + descriptions + categories + suggested
// classification. Amounts are intentionally BLANK — the clinic configures fees
// in Settings. Nothing here is chargeable until an amount is set.
const _svc = (code, category, description, billing_classification = "PATIENT_THIRD_PARTY_BILLABLE") =>
    ({ code, category, description, amount: "", billing_classification, active: true, note: "" });
export const DEFAULT_SERVICE_CATALOG = [
    _svc("MED_NOTE_BASIC", "MEDICAL_NOTES", "Basic Medical / Doctor's Note"),
    _svc("MED_NOTE_BACK_TO_WORK", "MEDICAL_NOTES", "Back-to-Work Note"),
    _svc("MED_NOTE_RETURN_SCHOOL", "MEDICAL_NOTES", "Return-to-School Note"),
    _svc("MED_NOTE_WORK_RESTRICTIONS", "MEDICAL_NOTES", "Work Restrictions / Accommodation Note"),
    _svc("MED_CERT_DETAILED", "MEDICAL_NOTES", "Detailed Medical Certificate / Report"),
    _svc("FORM_SCHOOL_CAMP", "SCHOOL_EMPLOYMENT_FITNESS", "School / Camp Form"),
    _svc("FORM_DAYCARE", "SCHOOL_EMPLOYMENT_FITNESS", "Daycare / Preschool Form"),
    _svc("FORM_COLLEGE_UNIV", "SCHOOL_EMPLOYMENT_FITNESS", "College / University Form"),
    _svc("FORM_PRE_EMPLOYMENT", "SCHOOL_EMPLOYMENT_FITNESS", "Pre-Employment Medical / Fitness Form"),
    _svc("FORM_SPORTS_FITNESS", "SCHOOL_EMPLOYMENT_FITNESS", "Sports / Fitness Form"),
    _svc("FORM_DRIVERS_MEDICAL", "DRIVING", "Driver's Medical Examination Form"),
    _svc("FORM_FITNESS_TO_DRIVE", "DRIVING", "Other Driver / Fitness-to-Drive Form"),
    _svc("FORM_LIFE_INSURANCE", "INSURANCE_THIRD_PARTY", "Life Insurance Form", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("FORM_DISABILITY_INSURANCE", "INSURANCE_THIRD_PARTY", "Disability Insurance Form", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("FORM_TRAVEL_INSURANCE", "INSURANCE_THIRD_PARTY", "Travel Insurance Medical Form", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("APS", "INSURANCE_THIRD_PARTY", "Attending Physician Statement", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("REPORT_EMPLOYER", "INSURANCE_THIRD_PARTY", "Employer-Requested Medical Report", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("REPORT_THIRD_PARTY", "INSURANCE_THIRD_PARTY", "Third-Party Medical Report", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("DTC_T2201", "DISABILITY_BENEFITS", "Disability Tax Credit Documentation / T2201", "REVIEW_REQUIRED"),
    _svc("CPP_DISABILITY", "DISABILITY_BENEFITS", "CPP Disability Form / Report", "REVIEW_REQUIRED"),
    _svc("PRIVATE_DISABILITY", "DISABILITY_BENEFITS", "Private Disability Form", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("FUNC_ABILITIES_REPORT", "DISABILITY_BENEFITS", "Functional Abilities / Limitations Report", "REVIEW_REQUIRED"),
    _svc("OTHER_DISABILITY", "DISABILITY_BENEFITS", "Other Disability / Benefits Form", "REVIEW_REQUIRED"),
    _svc("WSIB_FORM", "WSIB_OCCUPATIONAL", "WSIB Form / Report", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("WSIB_FUNC_ABILITIES", "WSIB_OCCUPATIONAL", "Functional Abilities Form", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("WSIB_PROGRESS", "WSIB_OCCUPATIONAL", "WSIB Progress Report", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("OCC_INJURY_DOC", "WSIB_OCCUPATIONAL", "Occupational Injury Documentation", "REVIEW_REQUIRED"),
    _svc("OCC_MENTAL_STRESS", "WSIB_OCCUPATIONAL", "Occupational Mental Stress Documentation", "REVIEW_REQUIRED"),
    _svc("OTHER_WSIB", "WSIB_OCCUPATIONAL", "Other WSIB / Occupational Form", "REVIEW_REQUIRED"),
    _svc("REC_COPY", "MEDICAL_RECORDS_ADMIN", "Copy of Medical Record"),
    _svc("REC_SUMMARY", "MEDICAL_RECORDS_ADMIN", "Medical Record Summary"),
    _svc("REC_TRANSFER", "MEDICAL_RECORDS_ADMIN", "Medical Record Transfer / Copy"),
    _svc("CHART_REVIEW_THIRD_PARTY", "MEDICAL_RECORDS_ADMIN", "Third-Party Chart Review", "THIRD_PARTY_EXTERNAL_FEE"),
    _svc("PHYS_ADMIN_WORK", "MEDICAL_RECORDS_ADMIN", "Physician Administrative Work"),
    _svc("ADMIN_LETTER", "MEDICAL_RECORDS_ADMIN", "Administrative Letter"),
    _svc("RX_NO_VISIT", "PRESCRIPTION_REQUEST", "Prescription Request Without an Associated Insured Visit", "REVIEW_REQUIRED"),
    _svc("RX_RENEWAL_ADMIN", "PRESCRIPTION_REQUEST", "Prescription Renewal Administrative Service", "REVIEW_REQUIRED"),
    _svc("NO_SHOW_FEE", "APPOINTMENT", "Missed Appointment / No-Show Fee"),
    _svc("CUSTOM_FORM", "OTHER", "Custom Form"),
    _svc("CUSTOM_REPORT", "OTHER", "Custom Medical Report"),
    _svc("OTHER_UNINSURED", "OTHER", "Other Uninsured Service"),
];



export function PaymentStatusPill({ status }) {
    if (!status) return null;
    const [label, cls] = PAYMENT_STATUS[status] || [status, "bg-slate-100 text-slate-600"];
    return <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`}>{label}</span>;
}
