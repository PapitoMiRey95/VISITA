import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Receipt, Plus, Search, X, UserRound, Send, CheckCircle2, Ban, FileText, Loader2, Info } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { formatPatientName, formatCombinedName } from "../lib/name";
import { formatDate, formatDateTime } from "../lib/date";
import { formatMoney, InvoiceStatusPill, PAYMENT_MODE } from "../lib/billing";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";

// Only portal patients (with a patient_id) can be billed — they need a login to see the invoice.
function PatientPicker({ selected, onSelect, onClear }) {
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const boxRef = useRef(null);

    const search = useCallback(async (term) => {
        if (term.trim().length < 2) { setResults([]); return; }
        setLoading(true);
        try {
            const { data } = await api.get("/internal/patients", { params: { q: term.trim() } });
            setResults(data || []);
            setOpen(true);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, []);

    useEffect(() => {
        if (selected) return;
        const t = setTimeout(() => search(q), 250);
        return () => clearTimeout(t);
    }, [q, selected, search]);

    useEffect(() => {
        function onDoc(e) { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); }
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, []);

    if (selected) {
        return (
            <div data-testid="inv-patient-selected" className="flex items-start justify-between gap-2 rounded-sm border border-visita-green/40 bg-visita-greenLight px-2.5 py-2">
                <div className="min-w-0">
                    <div className="font-semibold text-slate-800 text-sm flex items-center gap-1.5"><UserRound className="w-3.5 h-3.5 text-visita-greenDark" /> {formatPatientName(selected)} <CoverageBadge type={selected.patient_type} /></div>
                    <span className="text-xs text-slate-500">PIN: {selected.visita_patient_id || "Not assigned"} · DOB: {formatDate(selected.date_of_birth) || "—"}</span>
                </div>
                <button type="button" data-testid="inv-patient-clear" onClick={onClear} className="text-slate-400 hover:text-red-600 shrink-0"><X className="w-4 h-4" /></button>
            </div>
        );
    }
    return (
        <div ref={boxRef} className="relative">
            <div className="relative">
                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                <Input data-testid="inv-patient-search" value={q} onChange={(e) => setQ(e.target.value)}
                    onFocus={() => { if (results.length) setOpen(true); }}
                    placeholder="Search registered patient by PIN / name…" className="pl-8" />
            </div>
            {open && q.trim().length >= 2 && (
                <div data-testid="inv-patient-results" className="absolute z-30 mt-1 w-full bg-white border border-slate-300 rounded-sm shadow-lg divide-y max-h-72 overflow-y-auto">
                    {loading && <div className="px-3 py-3 text-xs text-slate-400">Searching…</div>}
                    {!loading && results.length === 0 && <div className="px-3 py-3 text-xs text-slate-400">No registered portal patients found. Invoices require a portal account.</div>}
                    {!loading && results.map((r) => (
                        <button key={r.id} type="button" data-testid="inv-patient-result" onClick={() => { onSelect(r); setOpen(false); setQ(""); }} className="w-full text-left px-3 py-2 hover:bg-slate-50">
                            <div className="font-semibold text-slate-800 text-sm">{formatPatientName(r)} <CoverageBadge type={r.patient_type} /></div>
                            <span className="text-xs text-slate-500">PIN: {r.visita_patient_id || "Not assigned"} · DOB: {formatDate(r.date_of_birth) || "—"}</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

function CreateInvoice({ onCreated }) {
    const [patient, setPatient] = useState(null);
    const [desc, setDesc] = useState("");
    const [code, setCode] = useState("");
    const [amount, setAmount] = useState("");
    const [mode, setMode] = useState("INVOICE_AFTER_SERVICE");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);

    const submit = async (issue) => {
        if (!patient?.id) return toast.error("Select a registered portal patient.");
        if (!desc.trim()) return toast.error("Enter a service description.");
        if (!amount || Number(amount) <= 0) return toast.error("Enter a valid amount.");
        setBusy(true);
        try {
            const { data } = await api.post("/internal/invoices", {
                patient_id: patient.id, service_description: desc.trim(),
                service_code: code.trim() || undefined, amount: Number(amount),
                payment_mode: mode, internal_note: note.trim() || undefined,
            });
            if (issue) await api.post(`/internal/invoices/${data.id}/issue`);
            toast.success(issue ? "Invoice issued." : "Draft invoice created.");
            setPatient(null); setDesc(""); setCode(""); setAmount(""); setNote(""); setMode("INVOICE_AFTER_SERVICE");
            onCreated();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3" data-testid="inv-create">
            <div className="font-bold text-slate-800 flex items-center gap-2"><Plus className="w-4 h-4" /> New Invoice</div>
            <div><Label className="text-xs">Patient</Label><PatientPicker selected={patient} onSelect={setPatient} onClear={() => setPatient(null)} /></div>
            {patient?.patient_type === "ohip" && (
                <div className="flex items-start gap-2 bg-sky-50 border border-sky-200 rounded-md p-2.5 text-xs text-sky-800" data-testid="ohip-billing-notice">
                    <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                    <span>This is an <span className="font-semibold">OHIP patient</span>. Some services are not covered by OHIP and may require payment. Creating this invoice does not change the patient's coverage.</span>
                </div>
            )}
            <div className="grid grid-cols-2 gap-2">
                <div><Label className="text-xs">Service description</Label><Input data-testid="inv-desc" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="e.g. Medical letter" /></div>
                <div><Label className="text-xs">Service code (optional)</Label><Input data-testid="inv-code" value={code} onChange={(e) => setCode(e.target.value)} /></div>
            </div>
            <div className="grid grid-cols-2 gap-2">
                <div><Label className="text-xs">Amount (CAD)</Label><Input type="number" min="0" step="0.01" data-testid="inv-amount" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
                <div>
                    <Label className="text-xs">Payment mode</Label>
                    <Select value={mode} onValueChange={setMode}>
                        <SelectTrigger data-testid="inv-mode"><SelectValue /></SelectTrigger>
                        <SelectContent>
                            <SelectItem value="INVOICE_AFTER_SERVICE">Invoice After Service</SelectItem>
                            <SelectItem value="PREPAYMENT_REQUIRED">Prepayment Required</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            </div>
            <div><Label className="text-xs">Internal note (optional)</Label><Textarea data-testid="inv-note" value={note} onChange={(e) => setNote(e.target.value)} /></div>
            <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={busy} data-testid="inv-save-draft" onClick={() => submit(false)}>Save as draft</Button>
                <Button size="sm" disabled={busy} data-testid="inv-issue-now" onClick={() => submit(true)} className="bg-visita-green hover:bg-visita-greenDark text-white">
                    {busy ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Send className="w-4 h-4 mr-1" />} Create & issue
                </Button>
            </div>
        </div>
    );
}

const FILTERS = ["", "DRAFT", "ISSUED", "PAYMENT_SUBMITTED", "PAID", "VOID"];

const COVERAGE = { ohip: ["OHIP", "bg-sky-100 text-sky-700"], private: ["Private", "bg-amber-100 text-amber-700"], uninsured: ["Uninsured", "bg-amber-100 text-amber-700"], tourist: ["Tourist", "bg-violet-100 text-violet-700"] };
function CoverageBadge({ type }) {
    if (!type) return null;
    const [label, cls] = COVERAGE[type] || [type, "bg-slate-100 text-slate-600"];
    return <span className={`inline-block px-1.5 py-0.5 rounded-sm text-[10px] font-bold ${cls}`}>{label}</span>;
}

export default function Billing() {
    const invalidate = useInvalidate();
    const { user } = useAuth();
    const canVerify = ["staff", "admin"].includes(user?.role);
    const [filter, setFilter] = useState("");
    const [showCreate, setShowCreate] = useState(false);

    const listQ = useQuery({
        queryKey: ["queue", "/internal/invoices", filter],
        queryFn: async () => (await api.get("/internal/invoices", { params: filter ? { status: filter } : {} })).data,
    });
    const items = listQ.data || [];
    const refresh = () => { listQ.refetch(); invalidate(); };

    const act = async (id, path, body) => {
        try { await api.post(`/internal/invoices/${id}/${path}`, body || {}); toast.success("Done."); refresh(); }
        catch (e) { toast.error(formatErr(e)); }
    };
    const viewProof = async (inv) => {
        try { await openAttachment(`/internal/invoices/${inv.id}/proof/${inv.payment_proof.attachment_id}/download`); }
        catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center justify-between gap-2 mb-1">
                <div className="flex items-center gap-2">
                    <Receipt className="w-5 h-5 text-visita-greenDark" />
                    <h1 className="text-2xl font-bold text-slate-900">Billing & Invoices</h1>
                </div>
                <Button size="sm" data-testid="inv-new-toggle" onClick={() => setShowCreate((s) => !s)} className="bg-visita-green hover:bg-visita-greenDark text-white">
                    <Plus className="w-4 h-4 mr-1" /> New Invoice
                </Button>
            </div>
            <p className="text-sm text-slate-500 mb-4">Uninsured services invoices. Voided invoices are preserved for audit.</p>

            {showCreate && <div className="mb-4"><CreateInvoice onCreated={() => { setShowCreate(false); refresh(); }} /></div>}

            <div className="flex flex-wrap gap-1.5 mb-3">
                {FILTERS.map((f) => (
                    <button key={f || "all"} data-testid={`inv-filter-${f || "all"}`} onClick={() => setFilter(f)}
                        className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${filter === f ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-200"}`}>
                        {f ? f.replace(/_/g, " ") : "All"}
                    </button>
                ))}
            </div>

            <div className="space-y-2">
                {items.length === 0 && <p className="text-slate-400 text-sm">No invoices.</p>}
                {items.map((inv) => (
                    <div key={inv.id} data-testid={`inv-row-${inv.id}`} className="bg-white border border-slate-200 rounded-lg p-3">
                        <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                                <div className="font-semibold text-slate-800">{formatCombinedName(inv.patient_name)}</div>
                                <div className="text-xs text-slate-500">{inv.invoice_number} · {inv.service_description}</div>
                                <div className="text-xs text-slate-400 mt-0.5">{PAYMENT_MODE[inv.payment_mode] || inv.payment_mode}{inv.issue_date ? ` · Issued ${formatDate(inv.issue_date)}` : ""}</div>
                                {inv.patient_coverage === "ohip" && <span className="inline-block mt-1 px-1.5 py-0.5 rounded-sm text-[10px] font-bold bg-sky-100 text-sky-700" data-testid={`inv-context-${inv.id}`}>OHIP — UNINSURED SERVICE</span>}
                            </div>
                            <div className="text-right shrink-0">
                                <div className="font-extrabold text-slate-900">{formatMoney(inv.amount, inv.currency)}</div>
                                <InvoiceStatusPill status={inv.status} />
                            </div>
                        </div>

                        {inv.payment_proof && (
                            <div className="mt-2 flex items-center gap-2 text-xs text-slate-600">
                                <FileText className="w-3.5 h-3.5" />
                                <span className="truncate">{inv.payment_proof.original_filename} · {formatDateTime(inv.payment_proof.uploaded_at)}</span>
                                <button onClick={() => viewProof(inv)} data-testid={`inv-view-proof-${inv.id}`} className="text-visita-greenDark font-semibold hover:underline ml-auto">View proof</button>
                            </div>
                        )}

                        <div className="flex flex-wrap gap-2 mt-2 border-t border-slate-100 pt-2">
                            {inv.status === "DRAFT" && (
                                <Button size="sm" data-testid={`inv-issue-${inv.id}`} onClick={() => act(inv.id, "issue")} className="bg-visita-green hover:bg-visita-greenDark text-white">
                                    <Send className="w-4 h-4 mr-1" /> Issue
                                </Button>
                            )}
                            {canVerify && (inv.status === "ISSUED" || inv.status === "PAYMENT_SUBMITTED") && (
                                <Button size="sm" data-testid={`inv-verify-${inv.id}`} onClick={() => act(inv.id, "verify-payment")} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                                    <CheckCircle2 className="w-4 h-4 mr-1" /> Verify payment (mark PAID)
                                </Button>
                            )}
                            {canVerify && inv.status !== "VOID" && inv.status !== "PAID" && (
                                <Button size="sm" variant="outline" data-testid={`inv-void-${inv.id}`} onClick={() => { const r = window.prompt("Reason for voiding this invoice (optional):") || undefined; act(inv.id, "void", { reason: r }); }} className="text-red-600 border-red-200">
                                    <Ban className="w-4 h-4 mr-1" /> Void
                                </Button>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
