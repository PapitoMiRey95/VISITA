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

// Default catalogue seeded with OMA 2026 suggested fees. `amount` is the CLINIC
// fee (blank until set for non-fixed items); `oma_suggested_amount` is advisory.
// TIME_BASED items route to Time-Based billing (with optional minimum_fee /
// hourly_rate_override). Nothing chargeable until an amount/rate is set.
const _svc = (code, category, description, o = {}) => ({
    code, category, description,
    billing_type: o.t || "SET_SERVICE",
    amount: o.amt ?? "",
    oma_suggested_amount: o.oma ?? "",
    hourly_rate_override: o.rate ?? "",
    minimum_fee: o.min ?? "",
    billing_classification: o.cls || "PATIENT_THIRD_PARTY_BILLABLE",
    external_payer_note: o.ext || "",
    oma_year: 2026,
    oma_reference: o.ref || "",
    active: o.active !== false,
    note: o.note || "",
});
const B = "PATIENT_THIRD_PARTY_BILLABLE", EXT = "THIRD_PARTY_EXTERNAL_FEE", NC = "NO_CHARGE", RV = "REVIEW_REQUIRED";
export const DEFAULT_SERVICE_CATALOG = [
    // Fixed OMA fees
    _svc("MED_NOTE_BASIC", "MEDICAL_NOTES", "Basic Sick / Doctor's Note (incl. brief return-to-work / return-to-school)", { amt: 26, oma: 26 }),
    _svc("MED_NOTE_BACK_TO_WORK", "MEDICAL_NOTES", "Back-to-Work Note (brief)", { amt: 26, oma: 26 }),
    _svc("MED_NOTE_RETURN_SCHOOL", "MEDICAL_NOTES", "Return-to-School Note (brief)", { amt: 26, oma: 26 }),
    _svc("CERT_COMMUNICABLE", "MEDICAL_NOTES", "Certificate of Freedom from Communicable Disease", { amt: 26, oma: 26 }),
    _svc("FORM_SCHOOL_CAMP", "SCHOOL_EMPLOYMENT_FITNESS", "School / Camp Physical Form", { amt: 37.25, oma: 37.25 }),
    _svc("FORM_DAYCARE", "SCHOOL_EMPLOYMENT_FITNESS", "Daycare / Preschool Physical Form", { amt: 37.25, oma: 37.25 }),
    _svc("FORM_COLLEGE_UNIV", "SCHOOL_EMPLOYMENT_FITNESS", "College / University Physical Form", { amt: 37.25, oma: 37.25 }),
    _svc("FORM_PRE_EMPLOYMENT", "SCHOOL_EMPLOYMENT_FITNESS", "Pre-Employment Fitness / Fitness Club Form", { amt: 49, oma: 49 }),
    _svc("FORM_SPORTS_FITNESS", "SCHOOL_EMPLOYMENT_FITNESS", "Sports / Fitness Form", { amt: 49, oma: 49 }),
    _svc("HOSPITAL_EMPLOYEE_FORM", "SCHOOL_EMPLOYMENT_FITNESS", "Hospital / Nursing Home Employee Form", { amt: 49, oma: 49 }),
    _svc("FORM_DRIVERS_MEDICAL", "DRIVING", "Driver's Medical Examination — Form Only", { amt: 77, oma: 77, note: "Form completion only — not the full assessment + urine + form workflow." }),
    _svc("FORM_FITNESS_TO_DRIVE", "DRIVING", "Other Driver / Fitness-to-Drive Form", { cls: RV }),
    _svc("EI_SICKNESS_INS5140", "INSURANCE_THIRD_PARTY", "EI Sickness Benefits Medical Certificate (INS5140)", { amt: 52, oma: 52 }),
    _svc("EI_COMPASSIONATE", "INSURANCE_THIRD_PARTY", "EI Compassionate Care Medical Certificate", { amt: 74, oma: 74 }),
    _svc("OCF3", "INSURANCE_THIRD_PARTY", "OCF-3 Disability Certificate", { amt: 262, oma: 262, cls: EXT }),
    _svc("OCF18", "INSURANCE_THIRD_PARTY", "OCF-18 Treatment and Assessment Plan", { amt: 278, oma: 278, cls: EXT }),
    _svc("OCF19", "INSURANCE_THIRD_PARTY", "OCF-19 Determination of Catastrophic Impairment", { amt: 155, oma: 155, cls: EXT }),
    _svc("OCF23", "INSURANCE_THIRD_PARTY", "OCF-23 Treatment Confirmation", { amt: 262, oma: 262, cls: EXT }),
    _svc("INS_QUESTIONNAIRE", "INSURANCE_THIRD_PARTY", "System / Disease-Specific Insurance Questionnaire", { amt: 125, oma: 125, cls: EXT }),
    _svc("INS_SYSTEM_EXAM", "INSURANCE_THIRD_PARTY", "System-Specific Examination", { amt: 152, oma: 152, cls: EXT }),
    _svc("FORM_LIFE_INSURANCE", "INSURANCE_THIRD_PARTY", "Life Insurance Form", { cls: EXT }),
    _svc("FORM_DISABILITY_INSURANCE", "INSURANCE_THIRD_PARTY", "Disability Insurance Form", { cls: EXT }),
    _svc("FORM_TRAVEL_INSURANCE", "INSURANCE_THIRD_PARTY", "Travel Insurance Cancellation", { cls: RV, note: "OMA 2026 guidance varies by cancellation context — physician to choose the applicable rule before enabling." }),
    _svc("CAS_FOSTER_ADOPT", "OTHER", "CAS Medical Report — Prospective Foster / Adoption / Kinship Applicant", { amt: 252, oma: 252 }),
    _svc("RX_NO_VISIT", "PRESCRIPTION_REQUEST", "Prescription Request Without an Associated Insured Visit", { amt: 25.8, oma: 25.8 }),
    _svc("RX_RENEWAL_ADMIN", "PRESCRIPTION_REQUEST", "Prescription / Renewal / Orthotic / Massage-related Uninsured Request", { amt: 25.8, oma: 25.8 }),
    // Time-based
    _svc("MED_CERT_DETAILED", "MEDICAL_NOTES", "Fitness-to-Work Detailed Note", { t: "TIME_BASED", min: 50, oma: 50 }),
    _svc("MED_NOTE_WORK_RESTRICTIONS", "MEDICAL_NOTES", "Work Restrictions / Accommodation Note", { t: "TIME_BASED", min: 50 }),
    _svc("DTC_T2201", "DISABILITY_BENEFITS", "Disability Tax Credit — T2201", { t: "TIME_BASED", min: 150, cls: RV }),
    _svc("APS", "INSURANCE_THIRD_PARTY", "Attending Physician Statement", { t: "TIME_BASED", min: 160, cls: EXT }),
    _svc("INS_MED_EXAM", "INSURANCE_THIRD_PARTY", "Insurance Medical Examination", { t: "TIME_BASED", cls: EXT }),
    _svc("LIFE_DEATH_CERT", "INSURANCE_THIRD_PARTY", "Life Insurance Death Certificate", { t: "TIME_BASED", cls: EXT }),
    _svc("CIVIL_AVIATION", "DRIVING", "Civil Aviation Medical Examination Report", { t: "TIME_BASED" }),
    _svc("IME", "INSURANCE_THIRD_PARTY", "Independent Medical Examination", { t: "TIME_BASED", cls: RV, note: "Independent consideration — set rate/scope per engagement." }),
    _svc("FUNC_ABILITIES_REPORT", "DISABILITY_BENEFITS", "Short-Term Disability / Functional Abilities Form (non-WSIB)", { t: "TIME_BASED", min: 50 }),
    _svc("CPP_DISABILITY", "DISABILITY_BENEFITS", "CPP Disability Medical Report (ISP/SCISP-2519)", { t: "TIME_BASED", min: 200, cls: RV, ext: "Service Canada may reimburse up to $85; remaining balance may be patient responsibility where permitted." }),
    _svc("CPP_TERMINAL", "DISABILITY_BENEFITS", "CPP Terminal Illness Medical Attestation", { t: "TIME_BASED", min: 135, cls: RV, ext: "External payer rule applies." }),
    _svc("CPP_REASSESS", "DISABILITY_BENEFITS", "CPP Reassessment / Recurrence Reports", { t: "TIME_BASED", cls: RV, ext: "External payer reimbursement rules apply." }),
    // OMA-specific hourly overrides ($497/hr)
    _svc("REPORT_CLARIFICATION", "INSURANCE_THIRD_PARTY", "Clarification Report", { t: "TIME_BASED", rate: 497, oma: 497, note: "OMA 2026: $497/hour (service-specific override)." }),
    _svc("REPORT_NARRATIVE", "INSURANCE_THIRD_PARTY", "Full Narrative Report", { t: "TIME_BASED", rate: 497, oma: 497, note: "OMA 2026: $497/hour (service-specific override)." }),
    _svc("REPORT_EMPLOYER", "INSURANCE_THIRD_PARTY", "Employer-Requested Medical Report", { t: "TIME_BASED", cls: EXT }),
    _svc("REPORT_THIRD_PARTY", "INSURANCE_THIRD_PARTY", "Third-Party Medical Report", { t: "TIME_BASED", cls: EXT }),
    // Medical records — REVIEW_REQUIRED (calculated subtype proposed, not auto-fee)
    _svc("REC_COPY", "MEDICAL_RECORDS_ADMIN", "Copy of Medical Record", { cls: RV, note: "OMA 2026: $30 first 20 pages, then $0.25/page. Needs calculated subtype before enabling." }),
    _svc("REC_SUMMARY", "MEDICAL_RECORDS_ADMIN", "Medical Record Summary", { cls: RV, note: "OMA 2026 record fees — needs calculated subtype." }),
    _svc("REC_TRANSFER", "MEDICAL_RECORDS_ADMIN", "Medical Record Transfer / Electronic Copy", { cls: RV, note: "OMA 2026: $30 electronic transfer where applicable." }),
    _svc("CHART_REVIEW_THIRD_PARTY", "MEDICAL_RECORDS_ADMIN", "Physician Review of Records", { cls: RV, note: "OMA 2026: first 15 min included, then $45 per additional 15 min. Needs calculated subtype." }),
    _svc("PHYS_ADMIN_WORK", "MEDICAL_RECORDS_ADMIN", "Physician Administrative Work", { t: "TIME_BASED" }),
    _svc("ADMIN_LETTER", "MEDICAL_RECORDS_ADMIN", "Administrative Letter", {}),
    // No charge / unremunerated
    _svc("PARKING_PERMIT", "OTHER", "Accessible Parking Permit", { cls: NC, note: "No additional form fee; a visit fee may apply where appropriate." }),
    _svc("TRANSIT_ELIGIBILITY", "OTHER", "Accessible Transit Eligibility Application", { cls: NC, note: "No additional form fee." }),
    _svc("ADP_FORMS", "OTHER", "Assistive Devices Program Forms", { cls: NC, note: "No charge where applicable." }),
    _svc("CAS_CHILD", "OTHER", "CAS Forms Completed on Behalf of a Child", { cls: NC }),
    // OHIP-coded / external-rule
    _svc("SPECIAL_DIET", "OTHER", "Special Diet Allowance", { cls: EXT, note: "Paid under OHIP code / external program — do not preload a patient fee." }),
    _svc("HOME_CARE", "OTHER", "Home Care Forms / Orders", { cls: EXT }),
    _svc("LTC_APPLICATION", "OTHER", "Long-Term Care Application", { cls: EXT }),
    _svc("NORTHERN_TRAVEL", "OTHER", "Northern Health Travel Grant", { cls: EXT }),
    _svc("ODSP_HEALTH", "DISABILITY_BENEFITS", "ODSP Health Status / ADL Forms", { cls: EXT }),
    _svc("OW_LIMITATIONS", "DISABILITY_BENEFITS", "Ontario Works Limitations Forms", { cls: EXT }),
    _svc("MED_CONDITION_OHIP", "OTHER", "Medical Condition Report (where OHIP code applies)", { cls: EXT }),
    _svc("WSIB_FORM", "WSIB_OCCUPATIONAL", "WSIB Form / Report", { cls: EXT, note: "Use applicable WSIB form/code/fee rules — not the generic physician fee." }),
    _svc("WSIB_FUNC_ABILITIES", "WSIB_OCCUPATIONAL", "WSIB Functional Abilities Form", { cls: EXT, note: "Use WSIB fee rules." }),
    _svc("WSIB_PROGRESS", "WSIB_OCCUPATIONAL", "WSIB Progress Report", { cls: EXT, note: "Use WSIB fee rules." }),
    _svc("OCC_INJURY_DOC", "WSIB_OCCUPATIONAL", "Occupational Injury Documentation", { cls: EXT }),
    _svc("OCC_MENTAL_STRESS", "WSIB_OCCUPATIONAL", "Occupational Mental Stress Documentation", { cls: EXT }),
    _svc("OTHER_WSIB", "WSIB_OCCUPATIONAL", "Other WSIB / Occupational Form", { cls: EXT }),
    // Other / disability
    _svc("PRIVATE_DISABILITY", "DISABILITY_BENEFITS", "Private Disability Form", { t: "TIME_BASED", cls: EXT }),
    _svc("OTHER_DISABILITY", "DISABILITY_BENEFITS", "Other Disability / Benefits Form", { cls: RV }),
    _svc("NO_SHOW_FEE", "APPOINTMENT", "Missed Appointment / No-Show Fee", {}),
    _svc("CUSTOM_FORM", "OTHER", "Custom Form", {}),
    _svc("CUSTOM_REPORT", "OTHER", "Custom Medical Report", { t: "TIME_BASED" }),
    _svc("OTHER_UNINSURED", "OTHER", "Other Uninsured Service", {}),
];

// Merge OMA catalogue into an existing stored list, matching by code. Updates
// advisory OMA fields + billing_type/classification/minimum/override/notes;
// fills a blank clinic amount with the OMA suggested amount but never overwrites
// a clinic-set amount. Adds any missing codes.
export function applyOmaCatalog(existing) {
    const byCode = new Map((existing || []).map((r) => [r.code, { ...r }]));
    for (const def of DEFAULT_SERVICE_CATALOG) {
        const cur = byCode.get(def.code);
        if (!cur) { byCode.set(def.code, { ...def }); continue; }
        const clinicAmt = (cur.amount === "" || cur.amount == null) ? def.amount : cur.amount;
        byCode.set(def.code, {
            ...cur,
            category: cur.category || def.category,
            description: def.description,
            billing_type: def.billing_type,
            amount: clinicAmt,
            oma_suggested_amount: def.oma_suggested_amount,
            hourly_rate_override: def.hourly_rate_override,
            minimum_fee: def.minimum_fee,
            billing_classification: def.billing_classification,
            external_payer_note: def.external_payer_note,
            oma_year: 2026,
            note: cur.note || def.note,
        });
    }
    return Array.from(byCode.values());
}




export function PaymentStatusPill({ status }) {
    if (!status) return null;
    const [label, cls] = PAYMENT_STATUS[status] || [status, "bg-slate-100 text-slate-600"];
    return <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`}>{label}</span>;
}
