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


export function PaymentStatusPill({ status }) {
    if (!status) return null;
    const [label, cls] = PAYMENT_STATUS[status] || [status, "bg-slate-100 text-slate-600"];
    return <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`}>{label}</span>;
}
