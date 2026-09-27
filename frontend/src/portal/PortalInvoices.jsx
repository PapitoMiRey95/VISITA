import { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Receipt, Upload, Loader2, FileText, CheckCircle2, Info, Copy } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { usePortal, Card } from "./shared";
import { formatMoney, InvoiceStatusPill, PAYMENT_MODE } from "../lib/billing";
import { formatDate, formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

function ProofUpload({ invoice, onDone }) {
    const [uploading, setUploading] = useState(false);
    const inputRef = useRef(null);

    const onPick = async (e) => {
        const file = e.target.files?.[0];
        if (inputRef.current) inputRef.current.value = "";
        if (!file) return;
        if (file.size > 15 * 1024 * 1024) { toast.error("File too large. Maximum size is 15 MB."); return; }
        setUploading(true);
        try {
            const fd = new FormData();
            fd.append("file", file);
            await api.post(`/portal/invoices/${invoice.id}/proof`, fd, { headers: { "Content-Type": "multipart/form-data" } });
            toast.success("Payment proof submitted. The clinic will verify it.");
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
                {invoice.payment_proof ? "Replace proof of payment" : "Upload proof of payment"}
            </Button>
        </>
    );
}

function InvoiceCard({ inv, onRefresh }) {
    const canUpload = inv.payment_required && (inv.status === "ISSUED" || inv.status === "PAYMENT_SUBMITTED");
    const copyEmail = () => { navigator.clipboard?.writeText(inv.etransfer_email || ""); toast.success("E-transfer email copied."); };
    const viewProof = async () => {
        try { await openAttachment(`/portal/invoices/${inv.id}/proof/${inv.payment_proof.attachment_id}/download`); }
        catch (e) { toast.error(formatErr(e)); }
    };
    return (
        <Card className="p-4" data-testid="invoice-card">
            <div className="flex justify-between items-start gap-2">
                <div>
                    <div className="font-bold text-slate-800">{inv.service_description}</div>
                    <div className="text-sm text-slate-500">{inv.invoice_number}{inv.issue_date ? ` · Issued ${formatDate(inv.issue_date)}` : ""}</div>
                </div>
                <div className="text-right">
                    <div className="text-lg font-extrabold text-slate-900">{formatMoney(inv.amount, inv.currency)}</div>
                    <InvoiceStatusPill status={inv.status} />
                </div>
            </div>

            <div className="text-xs text-slate-500 mt-1">Payment: {PAYMENT_MODE[inv.payment_mode] || inv.payment_mode}</div>

            {inv.reason_message && (
                <div className="mt-2 flex items-start gap-2 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-600" data-testid={`reason-notice-${inv.id}`}>
                    <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-slate-400" />
                    <div>
                        {inv.reason_title && <p className="font-semibold text-slate-700">{inv.reason_title}</p>}
                        {inv.reason_message}
                    </div>
                </div>
            )}

            {inv.status === "VOID" && (
                <div className="mt-2 text-sm text-slate-500">This invoice has been voided by the clinic.</div>
            )}

            {inv.status === "PAID" && (
                <div className="mt-2 flex items-center gap-2 text-emerald-700 font-semibold text-sm">
                    <CheckCircle2 className="w-4 h-4" /> Payment verified{inv.paid_at ? ` on ${formatDate(inv.paid_at)}` : ""}.
                </div>
            )}

            {canUpload && (
                <div className="mt-3 bg-amber-50 border border-amber-200 rounded-xl p-3 space-y-2" data-testid={`invoice-pay-${inv.id}`}>
                    <div className="flex items-start gap-2 text-amber-900 text-sm">
                        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                        <div>
                            <p className="font-bold">Payment required</p>
                            Please send an Interac e-Transfer of <span className="font-bold">{formatMoney(inv.amount, inv.currency)}</span> to:
                        </div>
                    </div>
                    <div className="flex items-center gap-2 bg-white border border-amber-200 rounded-lg px-3 py-2">
                        <span className="font-mono text-sm text-slate-800 break-all" data-testid={`etransfer-email-${inv.id}`}>{inv.etransfer_email}</span>
                        <button onClick={copyEmail} className="ml-auto text-slate-400 hover:text-portal-blueDark shrink-0" title="Copy email" data-testid={`copy-email-${inv.id}`}>
                            <Copy className="w-4 h-4" />
                        </button>
                    </div>
                    <p className="text-xs text-amber-800">After sending, upload your proof of payment below. Uploading is not payment confirmation — the clinic will verify receipt.</p>
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
                    <button onClick={viewProof} data-testid={`view-proof-${inv.id}`} className="text-portal-blueDark text-xs font-semibold hover:underline shrink-0">View</button>
                </div>
            )}
        </Card>
    );
}

export default function PortalInvoices() {
    const { refetch } = usePortal();
    const listQ = useQuery({ queryKey: ["invoices"], queryFn: async () => (await api.get("/portal/invoices")).data });
    const list = listQ.data || [];
    const refresh = () => { listQ.refetch(); refetch?.(); };

    return (
        <div className="space-y-5 animate-fade-in">
            <div className="flex items-center gap-2">
                <Receipt className="w-6 h-6 text-portal-blue" />
                <h1 className="text-2xl font-bold text-slate-900">Invoices</h1>
            </div>
            <p className="text-sm text-slate-500">This invoice is for a service that is not covered under your OHIP coverage.</p>

            {list.length === 0 && (
                <Card className="text-center text-slate-500 text-sm py-8" >You have no invoices yet.</Card>
            )}
            <div className="space-y-3">
                {list.map((inv) => <InvoiceCard key={inv.id} inv={inv} onRefresh={refresh} />)}
            </div>
        </div>
    );
}
