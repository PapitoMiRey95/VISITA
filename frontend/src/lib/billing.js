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

export function PaymentStatusPill({ status }) {
    if (!status) return null;
    const [label, cls] = PAYMENT_STATUS[status] || [status, "bg-slate-100 text-slate-600"];
    return <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`}>{label}</span>;
}
