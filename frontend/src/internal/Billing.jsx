import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Receipt, Plus, Search, X, UserRound, Send, CheckCircle2, Ban, FileText, Loader2, Info, Check, ChevronsUpDown } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { formatPatientName, formatCombinedName } from "../lib/name";
import { formatDate, formatDateTime } from "../lib/date";
import { formatMoney, InvoiceStatusPill, PAYMENT_MODE, HOURS_OPTIONS, PARTIAL_OPTIONS, computeTimeBasedTotal, SERVICE_CATEGORIES, CATEGORY_LABEL, CLASSIFICATION_LABEL } from "../lib/billing";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem, SelectGroup, SelectLabel } from "../components/ui/select";
import { Popover, PopoverTrigger, PopoverContent } from "../components/ui/popover";
import { Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem } from "../components/ui/command";

// Searchable Set-Service picker: physician can type a hint word (e.g. "sick",
// "OCF", "camp") to instantly filter the ~71-item catalogue. Grouped by category;
// No-Charge / no-amount services stay visible but non-selectable.
function SetServiceCombobox({ services, value, onChange }) {
    const [open, setOpen] = useState(false);
    const selected = services.find((s) => s.code === value);
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <button type="button" role="combobox" aria-expanded={open} data-testid="inv-service-select"
                    className="w-full flex items-center justify-between rounded-md border border-slate-200 bg-white px-3 h-9 text-sm text-left hover:border-slate-300">
                    <span className={selected ? "text-slate-800 truncate" : "text-slate-400"}>{selected ? selected.description : "Select a service"}</span>
                    <ChevronsUpDown className="w-4 h-4 opacity-50 shrink-0 ml-2" />
                </button>
            </PopoverTrigger>
            <PopoverContent className="p-0 w-[--radix-popover-trigger-width] min-w-[22rem]" align="start">
                <Command>
                    <CommandInput placeholder="Type a hint word to filter…" data-testid="inv-service-search" />
                    <CommandList>
                        <CommandEmpty>No matching service.</CommandEmpty>
                        {SERVICE_CATEGORIES.map(([cat, label]) => {
                            const rows = services.filter((s) => (s.category || "OTHER") === cat && (s.billing_type || "SET_SERVICE") === "SET_SERVICE");
                            if (rows.length === 0) return null;
                            return (
                                <CommandGroup key={cat} heading={label}>
                                    {rows.map((s) => {
                                        const noCharge = s.billing_classification === "NO_CHARGE";
                                        const noAmount = s.amount == null || s.amount === "";
                                        const disabled = noCharge || noAmount;
                                        return (
                                            <CommandItem key={s.code} value={s.code} keywords={[s.description, label, s.code]}
                                                disabled={disabled} onSelect={() => { onChange(s.code); setOpen(false); }}
                                                data-testid={`inv-service-opt-${s.code}`}>
                                                <Check className={`w-4 h-4 ${value === s.code ? "opacity-100 text-visita-greenDark" : "opacity-0"}`} />
                                                <span className="flex-1 min-w-0 truncate">{s.description}{noCharge ? " · No charge" : ""}</span>
                                                <span className="font-semibold tabular-nums text-slate-500">{noAmount ? (noCharge ? "—" : "Not set") : formatMoney(s.amount)}</span>
                                            </CommandItem>
                                        );
                                    })}
                                </CommandGroup>
                            );
                        })}
                    </CommandList>
                </Command>
            </PopoverContent>
        </Popover>
    );
}

// Billing patient search covers ALL current/active patients — verified portal
// accounts AND active patient_directory records (via the shared /internal/patient-lookup
// endpoints, same rule as the Patients page). A portal account is NOT required to be
// found; but issuing an invoice still needs a linked portal patient_id (see submit()).
function PatientPicker({ selected, onSelect, onClear }) {
    const [q, setQ] = useState("");
    const [pinQ, setPinQ] = useState("");
    const [results, setResults] = useState([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const boxRef = useRef(null);

    // GENERAL search across active portal + directory patients (name / full name /
    // health card / phone / DOB). PIN is intentionally excluded here.
    const search = useCallback(async (term) => {
        if (term.trim().length < 2) { setResults([]); return; }
        setLoading(true);
        try {
            const { data } = await api.get("/internal/patient-lookup", { params: { q: term.trim(), include_pin: false } });
            setResults(data || []);
            setOpen(true);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, []);

    // Dedicated EXACT VISITA PIN search (active patients only, PIN field only).
    const searchPin = async () => {
        const pin = pinQ.trim();
        if (!/^\d+$/.test(pin)) { toast.error("VISITA PIN must be numeric."); return; }
        setLoading(true);
        setOpen(true);
        try {
            const { data } = await api.get("/internal/patient-lookup/pin", { params: { pin } });
            setResults(data || []);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    };

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
        const billable = !!selected.patient_id;
        return (
            <div className="space-y-1.5">
                <div data-testid="inv-patient-selected" className="flex items-start justify-between gap-2 rounded-sm border border-visita-green/40 bg-visita-greenLight px-2.5 py-2">
                    <div className="min-w-0">
                        <div className="font-semibold text-slate-800 text-sm flex items-center gap-1.5"><UserRound className="w-3.5 h-3.5 text-visita-greenDark" /> {formatPatientName(selected)} <CoverageBadge type={selected.patient_type} /></div>
                        <span className="text-xs text-slate-500">PIN: {selected.visita_patient_id || "Not assigned"} · DOB: {formatDate(selected.date_of_birth) || "—"}</span>
                    </div>
                    <button type="button" data-testid="inv-patient-clear" onClick={onClear} className="text-slate-400 hover:text-red-600 shrink-0"><X className="w-4 h-4" /></button>
                </div>
                {!billable && (
                    <div data-testid="inv-patient-no-portal" className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-sm px-2.5 py-2 text-xs text-amber-800">
                        <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                        <span>This is a current patient in the directory but has <span className="font-semibold">no Patient Portal account yet</span>. Invoices are sent and paid through the portal, so this patient can't be invoiced until they register. No account is created automatically.</span>
                    </div>
                )}
            </div>
        );
    }
    return (
        <div ref={boxRef} className="relative space-y-2">
            <div className="flex flex-col sm:flex-row gap-2">
                <div className="relative flex-1">
                    <Label className="text-[11px] font-bold uppercase tracking-wide text-slate-400">General search</Label>
                    <div className="relative">
                        <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                        <Input data-testid="inv-patient-search" value={q} onChange={(e) => setQ(e.target.value)}
                            onFocus={() => { if (results.length) setOpen(true); }}
                            placeholder="Search current patient by name…" className="pl-8" />
                    </div>
                </div>
                <div className="sm:w-56 shrink-0">
                    <Label className="text-[11px] font-bold uppercase tracking-wide text-slate-400">VISITA PIN only</Label>
                    <div className="flex gap-1.5">
                        <Input data-testid="inv-patient-pin" value={pinQ} inputMode="numeric"
                            onChange={(e) => setPinQ(e.target.value.replace(/\D/g, ""))}
                            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); searchPin(); } }}
                            placeholder="Exact PIN" />
                        <Button type="button" size="sm" variant="outline" data-testid="inv-patient-pin-btn" onClick={searchPin}>PIN</Button>
                    </div>
                </div>
            </div>
            {open && (
                <div data-testid="inv-patient-results" className="absolute z-30 mt-1 w-full bg-white border border-slate-300 rounded-sm shadow-lg divide-y max-h-72 overflow-y-auto">
                    {loading && <div className="px-3 py-3 text-xs text-slate-400">Searching…</div>}
                    {!loading && results.length === 0 && <div className="px-3 py-3 text-xs text-slate-400">No current patients found.</div>}
                    {!loading && results.map((r) => (
                        <button key={r.id} type="button" data-testid="inv-patient-result" onClick={() => { onSelect(r); setOpen(false); setQ(""); setPinQ(""); }} className="w-full text-left px-3 py-2 hover:bg-slate-50">
                            <div className="font-semibold text-slate-800 text-sm flex items-center gap-1.5">
                                {formatPatientName(r)} <CoverageBadge type={r.patient_type} />
                                {!r.patient_id && <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-700 bg-amber-100 rounded px-1 py-0.5">No portal</span>}
                            </div>
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
    const [method, setMethod] = useState("MANUAL"); // MANUAL | SET_SERVICE | TIME_BASED
    const [desc, setDesc] = useState("");
    const [code, setCode] = useState("");
    const [amount, setAmount] = useState("");
    const [mode, setMode] = useState("INVOICE_AFTER_SERVICE");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);
    // Direct billing
    const [cfg, setCfg] = useState({ hourly_rate: null, services: [] });
    const [svcCode, setSvcCode] = useState("");
    const [tbDesc, setTbDesc] = useState("");
    const [tbSvc, setTbSvc] = useState("");
    const [hours, setHours] = useState(0);
    const [partial, setPartial] = useState(0); // minutes

    useEffect(() => {
        api.get("/internal/direct-billing/config", { params: { active_only: true } })
            .then(({ data }) => setCfg({ hourly_rate: data.hourly_rate, services: data.services || [] }))
            .catch(() => {});
    }, []);

    const partialOpt = PARTIAL_OPTIONS.find((p) => p.min === Number(partial)) || PARTIAL_OPTIONS[0];
    const tbSvcObj = cfg.services.find((s) => s.code === tbSvc) || null;
    const tbRate = tbSvcObj?.hourly_rate_override != null ? tbSvcObj.hourly_rate_override : cfg.hourly_rate;
    const tbMin = tbSvcObj?.minimum_fee != null ? tbSvcObj.minimum_fee : null;
    const tbRaw = computeTimeBasedTotal(tbRate, hours, partialOpt.mult);
    const tbMinApplied = tbMin != null && tbRaw < tbMin;
    const tbTotal = tbMinApplied ? tbMin : tbRaw;
    const selectedSvc = cfg.services.find((s) => s.code === svcCode);

    const reset = () => {
        setPatient(null); setMethod("MANUAL"); setDesc(""); setCode(""); setAmount(""); setNote("");
        setMode("INVOICE_AFTER_SERVICE"); setSvcCode(""); setTbDesc(""); setTbSvc(""); setHours(0); setPartial(0);
    };

    const submit = async (issue) => {
        const billTo = patient?.patient_id;
        if (!billTo) return toast.error("This patient has no Patient Portal account yet, so an invoice can't be issued. A portal account is required to send and pay invoices.");
        setBusy(true);
        try {
            let data;
            if (method === "MANUAL") {
                if (!desc.trim()) throw new Error("Enter a service description.");
                if (!amount || Number(amount) <= 0) throw new Error("Enter a valid amount.");
                ({ data } = await api.post("/internal/invoices", {
                    patient_id: billTo, service_description: desc.trim(),
                    service_code: code.trim() || undefined, amount: Number(amount),
                    payment_mode: mode, internal_note: note.trim() || undefined,
                }));
            } else if (method === "SET_SERVICE") {
                if (!svcCode) throw new Error("Select a predefined service.");
                ({ data } = await api.post("/internal/direct-billing/invoices", {
                    patient_id: billTo, billing_method: "SET_SERVICE", service_code: svcCode,
                    payment_mode: mode, internal_note: note.trim() || undefined,
                }));
            } else {
                if (!tbDesc.trim()) throw new Error("Enter a service description.");
                if (tbRate == null) throw new Error("No hourly rate configured. Set it in Clinic Settings.");
                if (tbTotal <= 0) throw new Error("Select some time worked.");
                ({ data } = await api.post("/internal/direct-billing/invoices", {
                    patient_id: billTo, billing_method: "TIME_BASED", description: tbDesc.trim(),
                    service_code: tbSvc || undefined,
                    whole_hours: Number(hours), partial_minutes: Number(partial),
                    payment_mode: mode, internal_note: note.trim() || undefined,
                }));
            }
            if (issue) await api.post(`/internal/invoices/${data.id}/issue`);
            toast.success(issue ? "Invoice issued." : "Draft invoice created.");
            reset();
            onCreated();
        } catch (e) { toast.error(e?.response ? formatErr(e) : e.message); } finally { setBusy(false); }
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

            <div>
                <Label className="text-xs">Billing method</Label>
                <Select value={method} onValueChange={setMethod}>
                    <SelectTrigger data-testid="inv-method"><SelectValue /></SelectTrigger>
                    <SelectContent>
                        <SelectItem value="MANUAL">Manual amount</SelectItem>
                        <SelectItem value="SET_SERVICE">Direct 3rd Party — Set Service</SelectItem>
                        <SelectItem value="TIME_BASED">Direct 3rd Party — Time-Based</SelectItem>
                    </SelectContent>
                </Select>
            </div>

            {method === "MANUAL" && (
                <>
                    <div className="grid grid-cols-2 gap-2">
                        <div><Label className="text-xs">Service description</Label><Input data-testid="inv-desc" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="e.g. Medical letter" /></div>
                        <div><Label className="text-xs">Service code (optional)</Label><Input data-testid="inv-code" value={code} onChange={(e) => setCode(e.target.value)} /></div>
                    </div>
                    <div><Label className="text-xs">Amount (CAD)</Label><Input type="number" min="0" step="0.01" data-testid="inv-amount" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
                </>
            )}

            {method === "SET_SERVICE" && (
                <div data-testid="inv-set-service">
                    <Label className="text-xs">Predefined service</Label>
                    {cfg.services.length === 0 ? (
                        <p className="text-xs text-amber-600">No active services configured. Add them in Clinic Settings → Direct 3rd Party Billing.</p>
                    ) : (
                        <SetServiceCombobox services={cfg.services} value={svcCode} onChange={setSvcCode} />
                    )}
                    {selectedSvc && (
                        <div className="mt-2 flex items-center justify-between bg-slate-50 border border-slate-200 rounded-sm px-3 py-2 text-sm" data-testid="inv-service-summary">
                            <span className="text-slate-700">{selectedSvc.description}<span className="ml-1.5 text-[10px] uppercase tracking-wide text-slate-400">{CLASSIFICATION_LABEL[selectedSvc.billing_classification] || ""}</span></span>
                            <span className="font-bold tabular-nums">{selectedSvc.amount != null ? formatMoney(selectedSvc.amount) : "Not set"}</span>
                        </div>
                    )}
                </div>
            )}

            {method === "TIME_BASED" && (
                <div className="space-y-2" data-testid="inv-time-based">
                    <div>
                        <Label className="text-xs">Time-based service (optional — OMA)</Label>
                        <Select value={tbSvc || "__none"} onValueChange={(v) => { const code = v === "__none" ? "" : v; setTbSvc(code); const s = cfg.services.find((x) => x.code === code); if (s) setTbDesc(s.description); }}>
                            <SelectTrigger data-testid="tb-service"><SelectValue placeholder="Custom (use clinic rate)" /></SelectTrigger>
                            <SelectContent className="max-h-72">
                                <SelectItem value="__none">Custom (use clinic rate)</SelectItem>
                                {cfg.services.filter((s) => (s.billing_type === "TIME_BASED") && s.billing_classification !== "NO_CHARGE").map((s) => (
                                    <SelectItem key={s.code} value={s.code}>
                                        <span className="inline-flex justify-between gap-6 w-full min-w-[18rem]"><span>{s.description}</span><span className="text-slate-400">{s.hourly_rate_override ? `${formatMoney(s.hourly_rate_override)}/hr` : s.minimum_fee ? `min ${formatMoney(s.minimum_fee)}` : ""}</span></span>
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div><Label className="text-xs">Description</Label><Input data-testid="tb-desc" value={tbDesc} onChange={(e) => setTbDesc(e.target.value)} placeholder="e.g. Legal report preparation" /></div>
                    <div className="grid grid-cols-3 gap-2">
                        <div>
                            <Label className="text-xs">Hourly Rate</Label>
                            <div className="h-9 flex items-center px-3 rounded-md border border-slate-200 bg-slate-50 font-semibold tabular-nums" data-testid="tb-rate">
                                {tbRate != null ? formatMoney(tbRate) : "Not set"}{tbSvcObj?.hourly_rate_override ? " (OMA)" : ""}
                            </div>
                        </div>
                        <div>
                            <Label className="text-xs">Hours Worked</Label>
                            <Select value={String(hours)} onValueChange={(v) => setHours(Number(v))}>
                                <SelectTrigger data-testid="tb-hours"><SelectValue /></SelectTrigger>
                                <SelectContent className="max-h-64">
                                    {HOURS_OPTIONS.map((h) => <SelectItem key={h} value={String(h)}>{h} hr{h === 1 ? "" : "s"}</SelectItem>)}
                                </SelectContent>
                            </Select>
                        </div>
                        <div>
                            <Label className="text-xs">Partial Hours</Label>
                            <Select value={String(partial)} onValueChange={(v) => setPartial(Number(v))}>
                                <SelectTrigger data-testid="tb-partial"><SelectValue /></SelectTrigger>
                                <SelectContent className="max-h-64">
                                    {PARTIAL_OPTIONS.map((p) => <SelectItem key={p.min} value={String(p.min)}>{String(p.min).padStart(2, "0")} mins | {p.mult}</SelectItem>)}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>
                    <div className="flex items-center justify-between bg-visita-greenLight border border-visita-green/40 rounded-sm px-3 py-2">
                        <span className="text-xs uppercase tracking-wide text-slate-500 font-semibold">Total Amount{tbMinApplied ? " (minimum applied)" : ""}</span>
                        <span className="text-2xl font-extrabold text-slate-900 tabular-nums" data-testid="tb-total">{formatMoney(tbTotal)}</span>
                    </div>
                    {tbRate != null && (
                        <p className="text-[11px] text-slate-400">{formatMoney(tbRate)} × ({hours} + {partialOpt.mult}){tbMin ? `, minimum ${formatMoney(tbMin)}` : ""} — rate snapshotted onto the invoice.</p>
                    )}
                    {tbSvcObj?.external_payer_note && <p className="text-[11px] text-amber-600" data-testid="tb-ext-note">{tbSvcObj.external_payer_note}</p>}
                </div>
            )}

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
            <div><Label className="text-xs">Internal note (optional)</Label><Textarea data-testid="inv-note" value={note} onChange={(e) => setNote(e.target.value)} /></div>
            <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={busy || (patient && !patient.patient_id)} data-testid="inv-save-draft" onClick={() => submit(false)}>Save as draft</Button>
                <Button size="sm" disabled={busy || (patient && !patient.patient_id)} data-testid="inv-issue-now" onClick={() => submit(true)} className="bg-visita-green hover:bg-visita-greenDark text-white">
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
            <p className="text-sm text-slate-500 mb-4">Invoices for services not covered by OHIP. Voided invoices are preserved for audit.</p>

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
                                {inv.billing_method === "TIME_BASED" && (
                                    <div className="text-[11px] text-slate-500 mt-0.5" data-testid={`inv-timebased-${inv.id}`}>
                                        Time-based · {formatMoney(inv.hourly_rate_used)}/hr × ({inv.whole_hours} + {inv.partial_multiplier}) · {inv.whole_hours} hr {String(inv.partial_minutes).padStart(2, "0")} min
                                    </div>
                                )}
                                {inv.billing_method === "SET_SERVICE" && (
                                    <div className="text-[11px] text-slate-500 mt-0.5" data-testid={`inv-setservice-${inv.id}`}>Set service{inv.service_code ? ` · ${inv.service_code}` : ""}</div>
                                )}
                                {inv.patient_coverage === "ohip" && <span className="inline-block mt-1 px-1.5 py-0.5 rounded-sm text-[10px] font-bold bg-sky-100 text-sky-700" data-testid={`inv-context-${inv.id}`}>NOT COVERED BY OHIP SERVICE</span>}
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
