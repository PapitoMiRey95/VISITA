import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, CheckCircle2, X, Send, Stethoscope, Clock, Receipt, Ban, FileText, DollarSign } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";
import { formatCombinedName } from "../lib/name";
import { formatDate, formatDateTime } from "../lib/date";
import { formatMoney, InvoiceStatusPill, PaymentStatusPill, PAYMENT_MODE } from "../lib/billing";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";

function BillingPanel({ pr, onSetMode, onInvAct, canVerify, onViewProof }) {
    const [mode, setMode] = useState(pr.payment_mode || "");
    const [amount, setAmount] = useState("");
    const [desc, setDesc] = useState("");
    const invoices = pr.invoices || [];

    const apply = () => {
        if (!mode) return;
        if (mode === "PREPAYMENT_REQUIRED") {
            if (!amount || Number(amount) <= 0) return toast.error("Enter the prepayment amount.");
            onSetMode({ payment_mode: mode, amount: Number(amount), service_description: desc.trim() || undefined })
                .then(() => { setAmount(""); setDesc(""); });
        } else {
            onSetMode({ payment_mode: mode });
        }
    };

    return (
        <div className="border-t border-slate-100 pt-3 space-y-2" data-testid="pr-billing">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-700"><Receipt className="w-4 h-4 text-visita-greenDark" /> Billing</div>
            <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-500">Payment mode:</span>
                <span className="font-semibold text-slate-700">{PAYMENT_MODE[pr.payment_mode] || "Not set"}</span>
                <PaymentStatusPill status={pr.payment_status} />
            </div>

            <div className="rounded-md bg-slate-50 border border-slate-100 p-2.5 space-y-2">
                <div className="flex items-center gap-2">
                    <Select value={mode} onValueChange={setMode}>
                        <SelectTrigger data-testid="pr-payment-mode" className="h-9 text-sm"><SelectValue placeholder="Select payment mode…" /></SelectTrigger>
                        <SelectContent>
                            <SelectItem value="NO_PAYMENT_REQUIRED">No Payment Required</SelectItem>
                            <SelectItem value="PREPAYMENT_REQUIRED">Prepayment Required</SelectItem>
                            <SelectItem value="INVOICE_AFTER_SERVICE">Invoice After Service</SelectItem>
                        </SelectContent>
                    </Select>
                    <Button size="sm" data-testid="pr-payment-apply" disabled={!mode} onClick={apply} className="bg-visita-green hover:bg-visita-greenDark text-white shrink-0">
                        <DollarSign className="w-4 h-4 mr-1" /> Apply
                    </Button>
                </div>
                {mode === "PREPAYMENT_REQUIRED" && (
                    <div className="grid grid-cols-2 gap-2">
                        <Input type="number" min="0" step="0.01" placeholder="Amount (CAD)" data-testid="pr-prepay-amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
                        <Input placeholder="Service (optional)" data-testid="pr-prepay-desc" value={desc} onChange={(e) => setDesc(e.target.value)} />
                    </div>
                )}
                {mode === "PREPAYMENT_REQUIRED" && <p className="text-[11px] text-slate-500">Applying creates an issued invoice; the patient will be asked to pay by e-Transfer and upload proof.</p>}
                {mode === "INVOICE_AFTER_SERVICE" && <p className="text-[11px] text-slate-500">Create the invoice from the Billing page (or below) after the service is completed.</p>}
            </div>

            {invoices.length > 0 && (
                <div className="space-y-1.5">
                    {invoices.map((inv) => (
                        <div key={inv.id} data-testid={`pr-inv-${inv.id}`} className="rounded-md border border-slate-200 p-2 text-sm">
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-xs text-slate-500">{inv.invoice_number}</span>
                                <span className="font-bold text-slate-800">{formatMoney(inv.amount, inv.currency)}</span>
                                <InvoiceStatusPill status={inv.status} />
                            </div>
                            <div className="text-xs text-slate-500 mt-0.5">{inv.service_description}</div>
                            {inv.payment_proof && (
                                <button onClick={() => onViewProof(inv)} data-testid={`pr-inv-proof-${inv.id}`} className="text-xs text-visita-greenDark font-semibold hover:underline flex items-center gap-1 mt-1">
                                    <FileText className="w-3.5 h-3.5" /> View payment proof
                                </button>
                            )}
                            <div className="flex flex-wrap gap-1.5 mt-1.5">
                                {inv.status === "DRAFT" && <Button size="sm" data-testid={`pr-inv-issue-${inv.id}`} onClick={() => onInvAct(inv.id, "issue")} className="h-7 bg-visita-green hover:bg-visita-greenDark text-white"><Send className="w-3.5 h-3.5 mr-1" /> Issue</Button>}
                                {canVerify && (inv.status === "ISSUED" || inv.status === "PAYMENT_SUBMITTED") && <Button size="sm" data-testid={`pr-inv-verify-${inv.id}`} onClick={() => onInvAct(inv.id, "verify-payment")} className="h-7 bg-emerald-600 hover:bg-emerald-700 text-white"><CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Verify</Button>}
                                {canVerify && inv.status !== "VOID" && inv.status !== "PAID" && <Button size="sm" variant="outline" data-testid={`pr-inv-void-${inv.id}`} onClick={() => { const r = window.prompt("Reason for voiding (optional):") || undefined; onInvAct(inv.id, "void", { reason: r }); }} className="h-7 text-red-600 border-red-200"><Ban className="w-3.5 h-3.5 mr-1" /> Void</Button>}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export default function PrivateRequests() {
    const invalidate = useInvalidate();
    const { user } = useAuth();
    const canVerify = ["staff", "admin"].includes(user?.role);
    const [sel, setSel] = useState(null);
    const [offer, setOffer] = useState({ date: "", time: "", note: "" });
    const [msg, setMsg] = useState("");

    const list = useQuery({ queryKey: ["queue", "/internal/private-requests"], queryFn: async () => (await api.get("/internal/private-requests")).data });
    const items = list.data || [];

    const detailQ = useQuery({
        queryKey: ["private-detail", sel],
        queryFn: async () => (await api.get(`/internal/private-requests/${sel}`)).data,
        enabled: !!sel,
    });
    const pr = detailQ.data;

    const refresh = () => { list.refetch(); if (sel) detailQ.refetch(); invalidate(); };
    const act = async (path, body) => {
        try { await api.post(`/internal/private-requests/${sel}/${path}`, body || {}); toast.success("Done."); refresh(); }
        catch (e) { toast.error(formatErr(e)); }
    };
    const invAct = async (id, path, body) => {
        try { await api.post(`/internal/invoices/${id}/${path}`, body || {}); toast.success("Done."); refresh(); }
        catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center gap-2 mb-1">
                <Stethoscope className="w-5 h-5 text-visita-greenDark" />
                <h1 className="text-2xl font-bold text-slate-900">Private / Uninsured Requests</h1>
            </div>
            <p className="text-sm text-slate-500 mb-4">Private appointment requests from private, uninsured, and visitor patients.</p>

            <div className="grid md:grid-cols-2 gap-4">
                <div className="space-y-2">
                    {items.length === 0 && <p className="text-slate-400 text-sm">No private requests.</p>}
                    {items.map((r) => (
                        <button key={r.id} data-testid={`pr-row-${r.id}`} onClick={() => setSel(r.id)}
                            className={`w-full text-left bg-white border rounded-lg p-3 ${sel === r.id ? "border-visita-green ring-1 ring-visita-green" : "border-slate-200"}`}>
                            <div className="flex items-center justify-between gap-2">
                                <span className="font-semibold text-slate-800">{formatCombinedName(r.patient_name)}</span>
                                <StatusPill status={r.status} />
                            </div>
                            <div className="text-xs text-slate-500 mt-0.5">
                                {r.ref_number} · <span className="font-semibold text-amber-700">PRIVATE / UNINSURED</span>
                            </div>
                            <div className="text-xs text-slate-600 mt-0.5">{r.reason_label}</div>
                            {r.preferred_date && <div className="text-xs text-slate-500">Requested: {formatDate(r.preferred_date)} · {r.preferred_time}</div>}
                            {r.preference_mode === "NO_PREFERENCE" && <div className="text-xs text-slate-400">No preference — clinic may choose</div>}
                        </button>
                    ))}
                </div>

                <div>
                    {!pr && <div className="text-slate-400 text-sm bg-white border border-slate-200 rounded-lg p-6 text-center">Select a request to review.</div>}
                    {pr && (
                        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3" data-testid="pr-detail">
                            <div className="flex items-center justify-between">
                                <div className="font-bold text-slate-800">{formatCombinedName(pr.patient_name)}</div>
                                <StatusPill status={pr.status} />
                            </div>
                            <div className="text-xs text-slate-500">{pr.ref_number} · <span className="font-semibold text-amber-700">PRIVATE / UNINSURED</span> · {pr.patient_type}</div>
                            <div className="text-sm"><span className="text-slate-500">Reason:</span> {(pr.reason_path || []).join(" › ")}</div>
                            {pr.preferred_date && <div className="text-sm"><span className="text-slate-500">Requested:</span> {formatDate(pr.preferred_date)} · {pr.preferred_time}</div>}
                            {pr.preference_mode === "NO_PREFERENCE" && <div className="text-sm text-slate-500">No preference — clinic may choose.</div>}
                            {pr.note && <div className="text-sm"><span className="text-slate-500">Note:</span> {pr.note}</div>}

                            {!["CONFIRMED", "COMPLETED", "CANCELLED", "DECLINED"].includes(pr.status) && (
                                <div className="space-y-3 border-t border-slate-100 pt-3">
                                    {pr.preference_mode === "SPECIFIC" && pr.preferred_date && (
                                        <Button size="sm" data-testid="pr-accept-requested" onClick={() => act("accept-requested")}
                                            className="bg-visita-green hover:bg-visita-greenDark text-white w-full">
                                            <CheckCircle2 className="w-4 h-4 mr-1" /> Accept requested time ({formatDate(pr.preferred_date)} · {pr.preferred_time})
                                        </Button>
                                    )}
                                    <div className="rounded-md bg-slate-50 border border-slate-100 p-2.5">
                                        <div className="text-xs font-semibold text-slate-600 mb-1.5 flex items-center gap-1"><CalendarClock className="w-3.5 h-3.5" /> Offer a different date / time</div>
                                        <div className="grid grid-cols-2 gap-2">
                                            <Input type="date" data-testid="pr-offer-date" value={offer.date} onChange={(e) => setOffer({ ...offer, date: e.target.value })} />
                                            <Input type="time" data-testid="pr-offer-time" value={offer.time} onChange={(e) => setOffer({ ...offer, time: e.target.value })} />
                                        </div>
                                        <Input className="mt-2" placeholder="Optional note to patient" data-testid="pr-offer-note" value={offer.note} onChange={(e) => setOffer({ ...offer, note: e.target.value })} />
                                        <Button size="sm" className="mt-2 bg-visita-green hover:bg-visita-greenDark text-white" data-testid="pr-offer-submit"
                                            disabled={!offer.date || !offer.time}
                                            onClick={() => act("offer", { date: offer.date, time: offer.time, note: offer.note || undefined }).then(() => setOffer({ date: "", time: "", note: "" }))}>
                                            <Clock className="w-4 h-4 mr-1" /> Send offer
                                        </Button>
                                    </div>
                                    <div className="flex gap-2">
                                        <Button size="sm" variant="outline" className="text-red-600 border-red-200" data-testid="pr-decline" onClick={() => act("decline")}>
                                            <X className="w-4 h-4 mr-1" /> Decline
                                        </Button>
                                        <Button size="sm" variant="ghost" className="text-red-600" data-testid="pr-cancel" onClick={() => act("cancel")}>Cancel</Button>
                                    </div>
                                </div>
                            )}

                            {pr.status === "CONFIRMED" && (
                                <div className="text-emerald-700 font-semibold text-sm flex items-center gap-2"><CheckCircle2 className="w-4 h-4" /> Confirmed — appears on the Calendar with a PRIVATE badge.</div>
                            )}

                            <BillingPanel pr={pr} canVerify={canVerify}
                                onSetMode={(body) => act("payment-mode", body)}
                                onInvAct={invAct}
                                onViewProof={async (inv) => { try { await openAttachment(`/internal/invoices/${inv.id}/proof/${inv.payment_proof.attachment_id}/download`); } catch (e) { toast.error(formatErr(e)); } }} />

                            <div className="border-t border-slate-100 pt-3">
                                <Label className="text-xs text-slate-600">Conversation</Label>
                                <div className="space-y-1.5 max-h-52 overflow-y-auto my-2">
                                    {(pr.thread || []).length === 0 && <div className="text-xs text-slate-400">No messages yet.</div>}
                                    {(pr.thread || []).map((m, i) => (
                                        <div key={i} className={`text-sm rounded-lg px-2.5 py-1.5 ${m.from === "clinic" ? "bg-visita-greenLight ml-6" : "bg-slate-100 mr-6"}`}>
                                            <div className="text-[10px] uppercase tracking-wide text-slate-400">{m.from === "clinic" ? m.by : "Patient"}</div>
                                            {m.message}
                                        </div>
                                    ))}
                                </div>
                                <div className="flex gap-2">
                                    <Input data-testid="pr-msg-input" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Message the patient…" />
                                    <Button size="sm" data-testid="pr-msg-send" disabled={!msg.trim()}
                                        onClick={() => act("messages", { message: msg.trim() }).then(() => setMsg(""))}
                                        className="bg-visita-green hover:bg-visita-greenDark text-white"><Send className="w-4 h-4" /></Button>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
