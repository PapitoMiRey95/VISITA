import { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Receipt, Upload, Loader2, FileText, CheckCircle2, Info, Copy } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { usePortal, Card } from "./shared";
import { formatMoney } from "../lib/billing";
import { formatDate, formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

const STATUS_STYLE = {
    DRAFT: "bg-slate-100 text-slate-600",
    ISSUED: "bg-amber-100 text-amber-700",
    PAYMENT_SUBMITTED: "bg-blue-100 text-blue-700",
    PAID: "bg-emerald-100 text-emerald-700",
    VOID: "bg-slate-100 text-slate-500",
};

function StatusPill({ status }) {
    const { t } = useTranslation("portal");
    return (
        <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-bold ${STATUS_STYLE[status] || "bg-slate-100 text-slate-600"}`}>
            {t(`invoices.statuses.${status}`, status)}
        </span>
    );
}

function ProofUpload({ invoice, onDone }) {
    const { t } = useTranslation("portal");
    const [uploading, setUploading] = useState(false);
    const inputRef = useRef(null);

    const onPick = async (e) => {
        const file = e.target.files?.[0];
        if (inputRef.current) inputRef.current.value = "";
        if (!file) return;
        if (file.size > 15 * 1024 * 1024) { toast.error(t("invoices.toastFileTooLarge")); return; }
        setUploading(true);
        try {
            const fd = new FormData();
            fd.append("file", file);
            await api.post(`/portal/invoices/${invoice.id}/proof`, fd, { headers: { "Content-Type": "multipart/form-data" } });
            toast.success(t("invoices.toastProof"));
            onDone();
        } catch (err) { toast.error(formatErr(err)); } finally { setUploading(false); }
    };

    return (
        <>
            <input ref={inputRef} type="file" accept={ACCEPT} className="hidden" data-testid={`proof-input-${invoice.id}`} onChange={onPick} />
            <Button size="sm" disabled={uploading} data-testid={`proof-upload-${invoice.id}`}
                onClick={() => inputRef.current?.click()}
                className="bg-portal-blue hover:bg-portal-blueDark text-white">
                {uploading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Upload className="w-4 h-4 mr-1" />}
                {invoice.payment_proof ? t("invoices.replaceProof") : t("invoices.uploadProof")}
            </Button>
        </>
    );
}

function InvoiceCard({ inv, onRefresh }) {
    const { t } = useTranslation("portal");
    const canUpload = inv.payment_required && (inv.status === "ISSUED" || inv.status === "PAYMENT_SUBMITTED");
    const copyEmail = () => { navigator.clipboard?.writeText(inv.etransfer_email || ""); toast.success(t("invoices.toastCopied")); };
    const viewProof = async () => {
        try { await openAttachment(`/portal/invoices/${inv.id}/proof/${inv.payment_proof.attachment_id}/download`); }
        catch (e) { toast.error(formatErr(e)); }
    };
    // Localized contextual reason: prefer the stable backend reason_code (mapped to
    // portal:invoiceReason.*), fall back to the English reason_message if missing.
    const reasonText = inv.reason_code
        ? t(`invoiceReason.${inv.reason_code}`, { defaultValue: inv.reason_message || "" })
        : (inv.reason_message || "");
    return (
        <Card className="p-4" data-testid="invoice-card">
            <div className="flex justify-between items-start gap-2">
                <div>
                    <div className="font-bold text-slate-800">{inv.service_description}</div>
                    <div className="text-sm text-slate-500">{inv.invoice_number}{inv.issue_date ? ` · ${t("invoices.issuedOn", { date: formatDate(inv.issue_date) })}` : ""}</div>
                </div>
                <div className="text-right">
                    <div className="text-lg font-extrabold text-slate-900">{formatMoney(inv.amount, inv.currency)}</div>
                    <StatusPill status={inv.status} />
                </div>
            </div>

            <div className="text-xs text-slate-500 mt-1">{t("invoices.payment")}: {t(`invoices.paymentModes.${inv.payment_mode}`, inv.payment_mode)}</div>

            {reasonText && (
                <div className="mt-2 flex items-start gap-2 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-600" data-testid={`reason-notice-${inv.id}`}>
                    <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-slate-400" />
                    <div>
                        <p className="font-semibold text-slate-700">{t("invoiceReason.title")}</p>
                        {reasonText}
                    </div>
                </div>
            )}

            {inv.status === "VOID" && (
                <div className="mt-2 text-sm text-slate-500">{t("invoices.voided")}</div>
            )}

            {inv.status === "PAID" && (
                <div className="mt-2 flex items-center gap-2 text-emerald-700 font-semibold text-sm">
                    <CheckCircle2 className="w-4 h-4" /> {inv.paid_at ? t("invoices.paymentVerifiedOn", { date: formatDate(inv.paid_at) }) : t("invoices.paymentVerified")}
                </div>
            )}

            {canUpload && (
                <div className="mt-3 bg-amber-50 border border-amber-200 rounded-xl p-3 space-y-2" data-testid={`invoice-pay-${inv.id}`}>
                    <div className="flex items-start gap-2 text-amber-900 text-sm">
                        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                        <div>
                            <p className="font-bold">{t("invoices.paymentRequired")}</p>
                            {t("invoices.etransferOf", { amount: formatMoney(inv.amount, inv.currency) })}
                        </div>
                    </div>
                    <div className="flex items-center gap-2 bg-white border border-amber-200 rounded-lg px-3 py-2">
                        <span className="font-mono text-sm text-slate-800 break-all" data-testid={`etransfer-email-${inv.id}`}>{inv.etransfer_email}</span>
                        <button onClick={copyEmail} className="ml-auto text-slate-400 hover:text-portal-blueDark shrink-0" title={t("invoices.copyEmailTitle")} data-testid={`copy-email-${inv.id}`}>
                            <Copy className="w-4 h-4" />
                        </button>
                    </div>
                    <p className="text-xs text-amber-800">{t("invoices.afterSending")}</p>
                    <ProofUpload invoice={inv} onDone={onRefresh} />
                </div>
            )}

            {inv.payment_proof && (
                <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-100 pt-2">
                    <div className="text-xs text-slate-500 flex items-center gap-1.5 min-w-0">
                        <FileText className="w-4 h-4 shrink-0" />
                        <span className="truncate">{inv.payment_proof.original_filename}</span>
                        <span className="text-slate-400 shrink-0">· {formatDateTime(inv.payment_proof.uploaded_at)}</span>
                    </div>
                    <button onClick={viewProof} data-testid={`view-proof-${inv.id}`} className="text-portal-blueDark text-xs font-semibold hover:underline shrink-0">{t("invoices.viewProof")}</button>
                </div>
            )}
        </Card>
    );
}

export default function PortalInvoices() {
    const { t } = useTranslation("portal");
    const { refetch } = usePortal();
    const listQ = useQuery({ queryKey: ["invoices"], queryFn: async () => (await api.get("/portal/invoices")).data });
    const list = listQ.data || [];
    const refresh = () => { listQ.refetch(); refetch?.(); };

    return (
        <div className="space-y-5 animate-fade-in">
            <div className="flex items-center gap-2">
                <Receipt className="w-6 h-6 text-portal-blue" />
                <h1 className="text-2xl font-bold text-slate-900">{t("invoices.title")}</h1>
            </div>
            <p className="text-sm text-slate-500">{t("invoices.subtitle")}</p>

            {list.length === 0 && (
                <Card className="text-center text-slate-500 text-sm py-8">{t("invoices.none")}</Card>
            )}
            <div className="space-y-3">
                {list.map((inv) => <InvoiceCard key={inv.id} inv={inv} onRefresh={refresh} />)}
            </div>
        </div>
    );
}
