import { useState, useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { Search, X, UserRound, Bell, ArrowRightLeft, Check, Clock, Play, RotateCcw, MessageSquare, FileCheck2, Flag, AlertTriangle, PhoneCall, FileOutput, Microscope, FileText, Scale, FolderOpen, CalendarDays, ClipboardList, Pill, ChevronDown, ChevronUp, Undo2, Stethoscope, Scissors, ScanLine, FlaskConical } from "lucide-react";
import { StructuredFields, structuredBody, structuredEnough, emptyStructured, StructuredSummary, ReasonLine, ClinicActionChip, TransferReasonChip } from "./workHubStructured";
import { api, formatErr } from "../lib/api";
import { formatPatientName } from "../lib/name";
import { formatDate, formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "../components/ui/tooltip";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "../components/ui/dropdown-menu";

// Category → lucide icon + short readable label + accent (always shown together; never color-only; accents never signal urgency).
export const CATEGORY_META = {
    MESSAGE: { icon: MessageSquare, label: "Message", color: "text-cyan-600 dark:text-cyan-400" },
    CALL_BOOK_PATIENT: { icon: PhoneCall, label: "Call / Book", color: "text-teal-600 dark:text-teal-400" },
    CONSULT_SPECIALIST: { icon: Stethoscope, label: "Consult / Specialist", color: "text-sky-700 dark:text-sky-400" },
    PROCEDURE_SURGERY: { icon: Scissors, label: "Procedure / Surgery", color: "text-orange-600 dark:text-orange-400" },
    REFERRAL_FOLLOWUP: { icon: FileOutput, label: "Referral", color: "text-violet-600 dark:text-violet-400" },
    IMAGING: { icon: ScanLine, label: "Imaging", color: "text-indigo-600 dark:text-indigo-400" },
    BLOODWORK: { icon: FlaskConical, label: "Bloodwork", color: "text-red-700 dark:text-red-400" },
    RESULTS: { icon: Microscope, label: "Results / Imaging / BW", color: "text-indigo-600 dark:text-indigo-400" },
    INSURANCE_FORM: { icon: FileText, label: "Form", color: "text-amber-600 dark:text-amber-400" },
    LEGAL: { icon: Scale, label: "Legal", color: "text-rose-600 dark:text-rose-400" },
    CHART_REQUEST: { icon: FolderOpen, label: "Chart Request", color: "text-slate-500 dark:text-slate-300" },
    APPOINTMENT_CALL: { icon: CalendarDays, label: "Appointment", color: "text-emerald-600 dark:text-emerald-400" },
    ADMIN_OTHER: { icon: ClipboardList, label: "Admin", color: "text-slate-500 dark:text-slate-400" },
    RX: { icon: Pill, label: "Rx", color: "text-pink-600 dark:text-pink-400" },
};
export function CategoryTag({ category, testid = "work-category-tag", className = "" }) {
    const m = CATEGORY_META[category] || { icon: ClipboardList, label: category, color: "text-slate-500" };
    const Icon = m.icon;
    return <span data-testid={testid} data-category={category} className={`inline-flex items-center gap-1.5 text-[11px] text-slate-600 uppercase tracking-wide font-semibold ${className}`}><Icon className={`w-4 h-4 shrink-0 ${m.color}`} strokeWidth={2.25} aria-hidden="true" />{m.label}</span>;
}
// Staff → Physician context (workflow metadata, not authorization; separate from physician booking priority).
export const ATTENTION_LABEL = { ROUTINE: "Routine", IMPORTANT: "Important", NEEDS_ATTENTION: "Needs attention soon" };
export const ATTENTION_TONE = { ROUTINE: "bg-emerald-50 text-emerald-700 border-emerald-300", IMPORTANT: "bg-amber-50 text-amber-800 border-amber-400", NEEDS_ATTENTION: "bg-red-50 text-red-700 border-red-400" };
export const ATTENTION_DOT = { ROUTINE: "bg-emerald-500", IMPORTANT: "bg-amber-400", NEEDS_ATTENTION: "bg-red-500" };
export const REQUESTED_ACTION_LABEL = { REVIEW_DECISION: "Review / Decision", PATIENT_INSTRUCTIONS: "Instructions for patient", SIGN_APPROVE: "Sign / Approve", PREPARE_DOCUMENT: "Complete / Prepare document", FYI: "FYI only", OTHER: "Other" };
export const REFERRAL_SUBTYPE_LABEL = { DECLINED: "Declined", MORE_INFO_REQUESTED: "More info requested", PROVIDER_UPDATE: "Provider moved / contact update", ACCEPTED_IN_PROCESS: "Accepted / In process", APPOINTMENT_BOOKED: "Appointment booked", FOLLOW_UP_NEEDED: "Follow-up needed", NEW_REFERRAL_NEEDED: "New referral needed" };
export function AttentionBadge({ level, testid }) {
    if (!level) return null;
    return <Chip tone={ATTENTION_TONE[level]} testid={testid}><span className={`w-1.5 h-1.5 rounded-full mr-1 ${ATTENTION_DOT[level]}`} />{ATTENTION_LABEL[level]}</Chip>;
}
export function RequestedActionBadge({ action, testid }) {
    if (!action) return null;
    return <Chip tone="bg-sky-50 text-sky-800 border-sky-300" testid={testid}>{REQUESTED_ACTION_LABEL[action] || action}</Chip>;
}
export function ReferralSubtypeBadge({ item, testid }) {
    if (item.category !== "REFERRAL_FOLLOWUP" || !item.referral_subtype) return null;
    return <span data-testid={testid} className="text-[10px] font-bold uppercase tracking-wide text-violet-700 border border-violet-300 rounded-sm px-1">{REFERRAL_SUBTYPE_LABEL[item.referral_subtype] || item.referral_subtype}</span>;
}
// Derived (never stored) label for the sender's Sent view: are we still waiting for the doctor?
export function AwaitingBadge({ item, testid }) {
    if (item.status === "COMPLETED" || item.created_by_role === "physician") return null;
    if (item.awaiting_physician) return <Chip tone="bg-indigo-50 text-indigo-800 border-indigo-300" testid={testid}>Awaiting {item.owner_name || "physician"}</Chip>;
    if (item.owner_role === "CLINIC" && (item.events || []).some((e) => e.type === "handoff" && e.to_role === "CLINIC")) return <Chip tone="bg-emerald-50 text-emerald-800 border-emerald-300" testid={testid}>Returned to Clinic</Chip>;
    return null;
}
export const OUTCOME_LABEL = { COMPLETED: "Completed", ALREADY_DONE: "Already done", NO_LONGER_NEEDED: "No longer needed", DUPLICATE: "Duplicate", WITHDRAWN: "Withdrawn" };
export const CLOSE_OUTCOMES = ["ALREADY_DONE", "NO_LONGER_NEEDED", "DUPLICATE"];
// Outcome badge only when the close was not an ordinary Complete.
export function OutcomeBadge({ item, testid }) {
    const o = item.completion_outcome;
    if (item.status !== "COMPLETED" || !o || o === "COMPLETED") return null;
    return <Chip tone="bg-slate-200 text-slate-700 border-slate-300" testid={testid}>{OUTCOME_LABEL[o]}</Chip>;
}

export const STATUS_TONE = {
    NEW: "bg-amber-100 text-amber-800 border-amber-200",
    IN_PROGRESS: "bg-sky-100 text-sky-800 border-sky-200",
    WAITING: "bg-slate-100 text-slate-600 border-slate-200",
    COMPLETED: "bg-emerald-100 text-emerald-800 border-emerald-200",
};
export const STATUS_LABEL = { NEW: "New", IN_PROGRESS: "In progress", WAITING: "Waiting", COMPLETED: "Completed" };
export const OWNER_LABEL = { PHYSICIAN: "Doctor", CLINIC: "Clinic" };
export const PRIORITIES = ["NORMAL", "B2", "B1", "ASAP"];
export const QUEUE_LABEL = { PHYSICIAN: "Any Physician", CLINIC: "Clinic Staff" };
// "With Dr. Pablo Aguayo · Physician" for a person, "With Clinic Staff" for a shared queue.
export function ownerLabel(item) {
    if (item.owner_user_id) return `${item.owner_name || "Member"}${item.owner_position ? ` · ${item.owner_position}` : ""}`;
    return QUEUE_LABEL[item.owner_role] || OWNER_LABEL[item.owner_role];
}
// Compact recipient selector: shared queues + registered members of this practice, grouped. value = "q:CLINIC" | "u:<user_id>".
export function RecipientSelect({ value, onChange, members = [], queues = [], excludeUserId, testid = "work-recipient", className = "" }) {
    const phys = members.filter((m) => m.side === "PHYSICIAN" && m.user_id !== excludeUserId);
    const team = members.filter((m) => m.side === "CLINIC" && m.user_id !== excludeUserId);
    return (
        <select data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} className={`h-9 rounded-sm border border-slate-300 bg-white px-2 text-sm ${className}`}>
            <optgroup label="Shared queues">{queues.map((q) => <option key={q.key} value={`q:${q.key}`}>{q.label}</option>)}</optgroup>
            {phys.length > 0 && <optgroup label="Physicians">{phys.map((m) => <option key={m.user_id} value={`u:${m.user_id}`}>{m.name} — {m.position}</option>)}</optgroup>}
            {team.length > 0 && <optgroup label="Clinic team">{team.map((m) => <option key={m.user_id} value={`u:${m.user_id}`}>{m.name} — {m.position}</option>)}</optgroup>}
        </select>
    );
}
export const targetBody = (v) => (v.startsWith("u:") ? { to_user_id: v.slice(2), send_to: null } : { send_to: v.slice(2), to_user_id: null });
export const targetLabel = (v, members) => (v.startsWith("u:") ? (members.find((m) => m.user_id === v.slice(2))?.name || "member") : QUEUE_LABEL[v.slice(2)]);
export const PRIORITY_LABEL = { NORMAL: "Normal", B2: "B2", B1: "B1", ASAP: "ASAP" };
// Dr. Aguayo's operational meanings — do not reinterpret.
// Stored fallback text when a physician sends a priority without a message (mirrors backend PRIORITY_DEFAULT_TEXT).
export const PRIORITY_DEFAULT_TEXT = { B1: "Book patient in about 1 week.", B2: "Book patient within about 3–4 weeks.", ASAP: "Book patient as soon as possible." };
export const PRIORITY_HELP = { B1: "Book patient in about 1 week.", B2: "Regular follow-up — book patient within about 3–4 weeks.", ASAP: "Book patient as soon as possible." };
const PRIORITY_TONE = {
    B2: "bg-slate-100 text-slate-700 border-slate-300",
    B1: "bg-amber-100 text-amber-900 border-amber-300",
    ASAP: "bg-red-600 text-white border-red-700",
};
// Overdue is derived (due_at < now on a non-completed item) — never a stored status.
export function overdueDays(item) {
    if (!item.due_at || item.status === "COMPLETED") return null;
    const diff = Date.now() - new Date(item.due_at).getTime();
    return diff > 0 ? Math.floor(diff / 86400000) : null;
}
export function PriorityBadge({ priority, testid }) {
    const [open, setOpen] = useState(false);
    if (!priority || priority === "NORMAL") return null;
    return (
        <TooltipProvider delayDuration={150}>
            <Tooltip open={open} onOpenChange={setOpen}>
                <TooltipTrigger asChild>
                    <button type="button" data-testid={testid} aria-label={`${PRIORITY_LABEL[priority]}: ${PRIORITY_HELP[priority]}`}
                        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
                        className={`inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide cursor-help focus:outline-none focus:ring-1 focus:ring-visita-green ${PRIORITY_TONE[priority]}`}>
                        {priority === "ASAP" && <AlertTriangle className="w-3 h-3 mr-0.5" />}{PRIORITY_LABEL[priority]}
                    </button>
                </TooltipTrigger>
                <TooltipContent side="top" data-testid={`${testid}-tooltip`} className="bg-slate-900 text-white">{PRIORITY_HELP[priority]}</TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
export function OverdueBadge({ item, testid }) {
    const d = overdueDays(item);
    if (d === null) return null;
    return <Chip tone="bg-red-100 text-red-700 border-red-300" testid={testid}>Overdue{d > 0 ? ` · ${d} day${d === 1 ? "" : "s"}` : ""}</Chip>;
}
export function SignedBadge({ item, testid }) {
    if (!item.signed || item.status === "COMPLETED" || item.owner_role !== "CLINIC") return null;
    return <Chip tone="bg-emerald-600 text-white border-emerald-700" testid={testid}><FileCheck2 className="w-3 h-3 mr-0.5" />Signed · action required</Chip>;
}
// Compact segmented priority control shared by New dialog and Detail.
export function PriorityControl({ value, onChange, size = "sm", testid = "work-priority" }) {
    return (
        <div className={`inline-flex rounded-sm border border-slate-300 overflow-hidden ${size === "xs" ? "h-6 text-[11px]" : "h-8 text-xs"}`} data-testid={testid}>
            {PRIORITIES.map((p) => (
                <button key={p} type="button" data-testid={`${testid}-${p.toLowerCase()}`} onClick={() => onChange(p)}
                    className={`px-2 border-r last:border-r-0 border-slate-300 font-semibold ${value === p ? (p === "ASAP" ? "bg-red-600 text-white" : p === "B1" ? "bg-amber-500 text-white" : "bg-visita-green text-white") : "bg-white text-slate-600 hover:bg-slate-50"}`}>{PRIORITY_LABEL[p]}</button>
            ))}
        </div>
    );
}

export function Chip({ children, tone = "bg-slate-100 text-slate-600 border-slate-200", testid }) {
    return <span data-testid={testid} className={`inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${tone}`}>{children}</span>;
}

export function whenLabel(iso) {
    if (!iso) return "";
    const d = new Date(iso); const t = new Date();
    const sameDay = d.toDateString() === t.toDateString();
    return sameDay ? `Today ${d.toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit" })}` : formatDateTime(iso);
}

// Canonical VIen patient search (same endpoint as Rx Intake / Patients). Optional for a work item.
export function PatientPicker({ selected, onSelect, onClear }) {
    const [q, setQ] = useState("");
    const [pin, setPin] = useState("");
    const [results, setResults] = useState([]);
    const [open, setOpen] = useState(false);
    const boxRef = useRef(null);
    const searchPin = async () => {
        if (!pin) return;
        try {
            const { data } = await api.get("/internal/patient-lookup/pin", { params: { pin } });
            const r = Array.isArray(data) ? data[0] : data;
            if (r) { onSelect(r); setPin(""); } else toast.error("No patient with that PIN.");
        } catch (err) { toast.error(formatErr(err)); }
    };
    const search = useCallback(async (term) => {
        if (term.trim().length < 2) { setResults([]); return; }
        try { setResults((await api.get("/internal/patient-lookup", { params: { q: term.trim() } })).data); setOpen(true); }
        catch (e) { toast.error(formatErr(e)); }
    }, []);
    useEffect(() => { if (selected) return; const t = setTimeout(() => search(q), 250); return () => clearTimeout(t); }, [q, selected, search]);
    useEffect(() => {
        const onDoc = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
        document.addEventListener("mousedown", onDoc); return () => document.removeEventListener("mousedown", onDoc);
    }, []);
    if (selected) {
        return (
            <div data-testid="work-patient-selected" className="flex items-center justify-between gap-2 rounded-sm border border-visita-green/40 bg-visita-greenLight px-2.5 py-1.5 text-sm">
                <span className="flex items-center gap-1.5 font-semibold min-w-0 truncate"><UserRound className="w-3.5 h-3.5 text-visita-greenDark shrink-0" />{formatPatientName(selected)}
                    <span className="text-xs text-slate-500 font-normal">· PIN {selected.visita_patient_id || "—"} · DOB {formatDate(selected.date_of_birth) || "—"}</span></span>
                <button type="button" data-testid="work-patient-clear" onClick={onClear} className="text-slate-400 hover:text-red-600 shrink-0"><X className="w-4 h-4" /></button>
            </div>
        );
    }
    return (
        <div ref={boxRef} className="relative flex gap-2">
            <div className="relative flex-1">
                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                <Input data-testid="work-patient-search" value={q} onChange={(e) => setQ(e.target.value)} onFocus={() => results.length && setOpen(true)}
                    placeholder="Patient (optional) — name, DOB, phone, health card" className="pl-8" />
            </div>
            <div className="flex gap-1 w-36 shrink-0">
                <Input data-testid="work-patient-pin" value={pin} inputMode="numeric" onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} placeholder="PIN"
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); searchPin(); } }} />
                <Button type="button" size="sm" className="h-9 px-2 bg-visita-green hover:bg-visita-greenDark text-white" data-testid="work-patient-pin-btn" disabled={!pin} onClick={searchPin}><Search className="w-3.5 h-3.5 mr-1" />PIN</Button>
            </div>
            {open && q.trim().length >= 2 && (
                <div data-testid="work-patient-results" className="absolute z-30 top-full left-0 right-0 mt-1 bg-white border border-slate-300 rounded-sm shadow-lg divide-y max-h-64 overflow-y-auto">
                    {results.length === 0 && <div className="px-3 py-2 text-xs text-slate-400">No matching patients found.</div>}
                    {results.map((r) => (
                        <button key={r.id} type="button" data-testid="work-patient-result" onClick={() => { onSelect(r); setOpen(false); setQ(""); }} className="w-full text-left px-3 py-1.5 hover:bg-slate-50">
                            <div className="font-semibold text-sm">{formatPatientName(r)}</div>
                            <div className="text-[11px] text-slate-500">PIN {r.visita_patient_id || "—"} · DOB {formatDate(r.date_of_birth) || "—"}{r.source === "portal" ? " · Portal" : ""}</div>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

const DUE_PRESETS = [["", "None"], ["today", "Today"], ["tomorrow", "Tomorrow"], ["week", "1 week"], ["custom", "Custom"]];
function dueFromPreset(p, custom) {
    const d = new Date(); d.setHours(17, 0, 0, 0);
    if (p === "today") return d.toISOString();
    if (p === "tomorrow") { d.setDate(d.getDate() + 1); return d.toISOString(); }
    if (p === "week") { d.setDate(d.getDate() + 7); return d.toISOString(); }
    if (p === "custom" && custom) return new Date(`${custom}T17:00:00`).toISOString();
    return null;
}

// Compact composer: Patient (optional) → Type → Send to → What needs doing → Due → Send.
export function NewWorkDialog({ side, categories, catalog, members = [], queues = [], userId, onClose, onDone }) {
    const [patient, setPatient] = useState(null);
    const [category, setCategoryRaw] = useState(side === "PHYSICIAN" ? "CALL_BOOK_PATIENT" : "MESSAGE");
    const [sendTo, setSendTo] = useState(side === "PHYSICIAN" ? "q:CLINIC" : (members.find((m) => m.side === "PHYSICIAN") ? `u:${members.find((m) => m.side === "PHYSICIAN").user_id}` : "q:PHYSICIAN"));
    const [message, setMessage] = useState("");
    const [due, setDue] = useState("");
    const [custom, setCustom] = useState("");
    const [priority, setPriority] = useState("NORMAL");
    const [attention, setAttention] = useState("ROUTINE");
    const [requested, setRequested] = useState("REVIEW_DECISION");
    const [struct, setStruct] = useState(emptyStructured());
    const [busy, setBusy] = useState(false);
    const setCategory = (c) => { setCategoryRaw(c); setStruct(emptyStructured()); };
    const toPhysician = sendTo === "q:PHYSICIAN" || members.find((m) => `u:${m.user_id}` === sendTo)?.side === "PHYSICIAN";
    const showAttention = toPhysician && side !== "PHYSICIAN";
    const clinical = Boolean(catalog?.clinical_types.includes(category));
    const messageOptional = priority !== "NORMAL" || (clinical && structuredEnough(struct));
    const submit = async (e) => {
        e.preventDefault(); setBusy(true);
        try {
            await api.post("/internal/work", {
                category, message, ...targetBody(sendTo), priority, due_at: dueFromPreset(due, custom),
                ...(showAttention ? { attention_level: attention, requested_action: requested } : {}),
                ...structuredBody(category, catalog, struct),
                patient_id: patient?.patient_id || (patient?.source === "portal" ? patient?.id : null) || null,
                directory_id: patient?.directory_id || (patient?.source === "directory" ? patient?.id : null) || null,
                patient_name: patient ? formatPatientName(patient) : null,
            });
            toast.success(`Sent to ${targetLabel(sendTo, members)}.`); onDone(); onClose();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };
    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto" data-testid="work-new-dialog">
                <DialogHeader><DialogTitle>New work item</DialogTitle></DialogHeader>
                <form onSubmit={submit} className="space-y-3 text-sm">
                    <PatientPicker selected={patient} onSelect={setPatient} onClear={() => setPatient(null)} />
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div><Label className="text-xs">Type</Label>
                            <select data-testid="work-category" value={category} onChange={(e) => setCategory(e.target.value)} className="w-full h-9 rounded-sm border border-slate-300 bg-white px-2 text-sm">
                                <optgroup label="Clinical follow-up">{categories.filter((c) => catalog?.clinical_types.includes(c.key)).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</optgroup>
                                <optgroup label="Administrative">{categories.filter((c) => !catalog?.clinical_types.includes(c.key)).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</optgroup>
                            </select></div>
                        <div><Label className="text-xs">Send to</Label>
                            <RecipientSelect value={sendTo} onChange={setSendTo} members={members} queues={queues} excludeUserId={userId} testid="work-send-to" className="w-full" /></div>
                    </div>
                    <StructuredFields category={category} catalog={catalog} value={struct} onChange={setStruct} />
                    {showAttention && (
                        <>
                            <div className="flex flex-wrap items-center gap-1.5" data-testid="work-attention">
                                <Label className="text-xs mr-1">Attention</Label>
                                {Object.keys(ATTENTION_LABEL).map((k) => (
                                    <button key={k} type="button" data-testid={`work-attention-${k.toLowerCase()}`} onClick={() => setAttention(k)}
                                        className={`inline-flex items-center rounded-sm border px-2 py-0.5 text-xs ${attention === k ? `${ATTENTION_TONE[k]} font-semibold` : "border-slate-300 text-slate-600"}`}>
                                        <span className={`w-1.5 h-1.5 rounded-full mr-1 ${ATTENTION_DOT[k]}`} />{ATTENTION_LABEL[k]}
                                    </button>
                                ))}
                            </div>
                            <div><Label className="text-xs">What do you need from the doctor?</Label>
                                <select data-testid="work-requested-action" value={requested} onChange={(e) => setRequested(e.target.value)} className="w-full h-9 rounded-sm border border-slate-300 bg-white px-2 text-sm">
                                    {Object.entries(REQUESTED_ACTION_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                                </select></div>
                        </>
                    )}
                    {/* Physician booking priority: keyed to CREATOR role, independent of recipient. */}
                    {side === "PHYSICIAN" && (
                        <div className="flex items-center gap-2">
                            <Label className="text-xs">Priority</Label>
                            <PriorityControl value={priority} onChange={setPriority} />
                        </div>
                    )}
                    <div><Label className="text-xs">What needs to be done?{messageOptional && <span className="text-slate-400 font-normal" data-testid="work-message-optional"> (optional)</span>}</Label>
                        <Input autoFocus={!clinical} required={!messageOptional} data-testid="work-message" value={message} onChange={(e) => setMessage(e.target.value)} placeholder={messageOptional ? (clinical && structuredEnough(struct) ? "Optional — extra context only; your selections above are the instruction" : `Defaults to “${PRIORITY_DEFAULT_TEXT[priority]}”`) : "e.g. Complete insurance form"} maxLength={2000} /></div>
                    <div className="flex flex-wrap items-center gap-1.5">
                        <Label className="text-xs mr-1">Remind / Due</Label>
                        {DUE_PRESETS.map(([k, l]) => (
                            <button key={k} type="button" data-testid={`work-due-${k || "none"}`} onClick={() => setDue(k)}
                                className={`rounded-sm border px-2 py-0.5 text-xs ${due === k ? "border-visita-green bg-visita-greenLight text-visita-greenDark font-semibold" : "border-slate-300 text-slate-600"}`}>{l}</button>
                        ))}
                        {due === "custom" && <Input type="date" data-testid="work-due-custom" value={custom} onChange={(e) => setCustom(e.target.value)} className="h-7 w-40 text-xs" />}
                    </div>
                    <Button type="submit" disabled={busy || (!messageOptional && !message.trim())} data-testid="work-submit" className="w-full bg-visita-green hover:bg-visita-greenDark text-white">Send to {targetLabel(sendTo, members)}</Button>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function EventRow({ ev }) {
    const icon = { created: MessageSquare, reply: MessageSquare, handoff: ArrowRightLeft, waiting: Clock, completed: Check, status: Play, reopened: RotateCcw, PRIORITY_CHANGED: Flag, DOCUMENT_SIGNED: FileCheck2 }[ev.type] || MessageSquare;
    const Icon = icon;
    const who = (name, pos, role) => (name ? `${name}${pos ? ` (${pos})` : ""}` : (QUEUE_LABEL[role] || OWNER_LABEL[role] || role));
    const head = {
        created: `sent to ${who(ev.to_name, ev.to_position, ev.to_role)}`,
        handoff: `${who(ev.from_name, ev.from_position, ev.from_role)} → ${who(ev.to_name, ev.to_position, ev.to_role)}`,
        waiting: ev.waiting_until ? `waiting until ${formatDate(ev.waiting_until.slice(0, 10))}` : "waiting",
        completed: ev.outcome && ev.outcome !== "COMPLETED" ? `closed as ${OUTCOME_LABEL[ev.outcome]}` : "completed task", status: STATUS_LABEL[ev.status] || ev.status, reply: "note", reopened: "reopened", withdrawn: "withdrew this item",
        PRIORITY_CHANGED: `changed priority ${PRIORITY_LABEL[ev.from_priority] || ev.from_priority} → ${PRIORITY_LABEL[ev.to_priority] || ev.to_priority}`,
        DOCUMENT_SIGNED: `document signed → ${who(ev.to_name, ev.to_position, ev.to_role || "CLINIC")}`,
    }[ev.type] || ev.type;
    return (
        <div data-testid="work-event" className="flex gap-2.5 text-sm">
            <Icon className={`w-5 h-5 mt-0.5 shrink-0 ${ev.type === "DOCUMENT_SIGNED" ? "text-emerald-600" : ev.type === "PRIORITY_CHANGED" && ev.to_priority === "ASAP" ? "text-red-600" : "text-visita-greenDark"}`} />
            <div className="min-w-0">
                <div className="text-sm sm:text-base text-slate-600"><span className="font-semibold text-slate-800">{ev.by_name}</span> · {head} · {whenLabel(ev.at)}</div>
                {ev.text && <div className="text-base sm:text-lg leading-relaxed text-slate-900 whitespace-pre-wrap mt-0.5">{ev.text}</div>}
            </div>
        </div>
    );
}

const LATEST_N = 4;

// Right-hand detail: patient, category, owner, status, request, history, valid actions.
export function WorkDetail({ item, side, userId, members = [], queues = [], categories, documentCategories = [], onChanged, onBack }) {
    const [note, setNote] = useState("");
    const [waitUntil, setWaitUntil] = useState("");
    const [busy, setBusy] = useState(false);
    const [showAll, setShowAll] = useState(false);
    const [closing, setClosing] = useState(null);
    const [withdrawing, setWithdrawing] = useState(false);
    const [closeNote, setCloseNote] = useState("");
    const events = item.events || [];
    useEffect(() => { setShowAll(false); setClosing(null); setCloseNote(""); setWithdrawing(false); }, [item.id]);
    const defaultTarget = item.owner_role === "PHYSICIAN" ? "q:CLINIC" : "q:PHYSICIAN";
    const [target, setTarget] = useState(defaultTarget);
    const owned = item.owner_user_id ? item.owner_user_id === userId : item.owner_role === side;
    const mine = owned && item.status !== "COMPLETED";
    const act = async (action, extra = {}) => {
        setBusy(true);
        try {
            await api.post(`/internal/work/${item.id}/action`, { action, note: note || null, ...extra });
            setNote(""); setWaitUntil(""); setClosing(null); setCloseNote(""); setWithdrawing(false); onChanged();
            toast.success(action === "complete" && extra.outcome && extra.outcome !== "COMPLETED" ? `Closed as ${OUTCOME_LABEL[extra.outcome]}.` : { handoff: `Sent to ${targetLabel(target, members)}.`, complete: "Completed.", waiting: "Set to waiting.", in_progress: "In progress.", reply: "Note added.", reopen: "Reopened.", withdraw: "Withdrawn — removed from active work.", signed: `Signed — sent to ${targetLabel(target, members)}.`, priority: "Priority updated." }[action]);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const other = targetLabel(target, members);
    return (
        <div data-testid="work-detail" className="bg-white border border-slate-300 rounded-sm p-3 space-y-3 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1 basis-40">
                    {onBack && <button data-testid="work-detail-back" onClick={onBack} className="text-xs text-slate-400 hover:text-visita-greenDark mb-1 md:hidden">← Back to list</button>}
                    <div className="text-xs text-slate-500 flex items-center gap-1.5 flex-wrap">{item.ref_number} · <CategoryTag category={item.category} testid="work-detail-category" className="whitespace-nowrap" /><StructuredSummary item={item} testid="work-detail-summary" /><ReferralSubtypeBadge item={item} testid="work-detail-referral-subtype" /></div>
                    <div className="font-bold text-slate-900 truncate" data-testid="work-detail-patient">{item.patient_name || "No patient"}</div>
                    {(item.reason_label || item.clinic_action_label) && (
                        <div className="mt-1 flex flex-wrap items-center gap-1.5" data-testid="work-detail-structured">
                            <ReasonLine item={item} testid="work-detail-reason" />
                            <ClinicActionChip item={item} testid="work-detail-clinic-action" />
                            <TransferReasonChip item={item} testid="work-detail-transfer" />
                        </div>
                    )}
                    {(item.attention_level || item.requested_action) && (
                        <div className="mt-1 flex flex-wrap items-center gap-1 text-xs" data-testid="work-detail-attention-row">
                            <AttentionBadge level={item.attention_level} testid="work-detail-attention" />
                            <RequestedActionBadge action={item.requested_action} testid="work-detail-requested-action" />
                        </div>
                    )}
                    <div className="text-[11px] text-slate-500 mt-0.5" data-testid="work-detail-sender">From {item.created_by_name}{item.created_by_role && item.created_by_role !== "physician" ? " (Clinic)" : ""}</div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-1 shrink-0 max-w-full">
                    <span className="flex items-center gap-1">
                        <PriorityBadge priority={item.priority} testid="work-detail-priority" />
                        {side !== "PHYSICIAN" && <AwaitingBadge item={item} testid="work-detail-awaiting" />}
                        <Chip tone="bg-visita-greenLight text-visita-greenDark border-visita-green/40" testid="work-detail-owner">With {ownerLabel(item)}</Chip>
                    </span>
                    <span className="flex items-center gap-1">
                        <OverdueBadge item={item} testid="work-detail-overdue" />
                        <SignedBadge item={item} testid="work-detail-signed" />
                        <Chip tone={STATUS_TONE[item.status]} testid="work-detail-status">{STATUS_LABEL[item.status]}</Chip>
                    </span>
                </div>
            </div>
            {item.status !== "COMPLETED" && side === "PHYSICIAN" && (
                <div className="flex items-center gap-2 text-xs text-slate-500">
                    <span>Priority</span>
                    <PriorityControl size="xs" value={item.priority || "NORMAL"} onChange={(p) => act("priority", { priority: p })} testid="work-detail-priority-control" />
                </div>
            )}
            {side !== "PHYSICIAN" && item.priority && item.priority !== "NORMAL" && (
                <div className="flex items-center gap-2 text-xs text-slate-500" data-testid="work-detail-priority-readonly">
                    <Flag className="w-3 h-3" /><span>Physician priority:</span><PriorityBadge priority={item.priority} testid="work-detail-priority-readonly-badge" /><span className="text-slate-400">{PRIORITY_HELP[item.priority]}</span>
                </div>
            )}
            {(item.due_at || (item.status === "WAITING" && item.waiting_until)) && (
                <div className="text-xs text-slate-500 flex items-center gap-1" data-testid="work-detail-when">
                    <Bell className="w-3 h-3" />{item.status === "WAITING" && item.waiting_until ? `Waiting until ${formatDate(item.waiting_until.slice(0, 10))}` : `Due ${formatDate(item.due_at.slice(0, 10))}`}
                </div>
            )}
            <div className="space-y-3 border-t border-slate-200 pt-3" data-testid="work-history">
                <div className="flex items-center justify-between text-xs uppercase tracking-wide font-semibold text-slate-500">
                    <span>{showAll ? `Full history (${events.length})` : "Latest activity"}</span>
                    {events.length > LATEST_N && (
                        <button type="button" data-testid="work-history-toggle" onClick={() => setShowAll((s) => !s)} className="inline-flex items-center gap-0.5 normal-case tracking-normal text-sm text-visita-greenDark hover:underline">
                            {showAll ? <><ChevronUp className="w-4 h-4" /> Show latest</> : <><ChevronDown className="w-4 h-4" /> View full history ({events.length})</>}
                        </button>
                    )}
                </div>
                {(showAll ? events : events.slice(-LATEST_N)).map((ev, i) => <EventRow key={`${ev.at}-${i}`} ev={ev} />)}
            </div>
            {item.status !== "COMPLETED" && (
                <div className="border-t border-slate-200 pt-2 space-y-2">
                    <Input data-testid="work-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder={mine ? "Reply / note (optional)" : "Add a note"} maxLength={2000} />
                    {mine && <div className="flex items-center gap-2 text-xs text-slate-500"><span>Send to</span><RecipientSelect value={target} onChange={setTarget} members={members} queues={queues} excludeUserId={userId} testid="work-detail-recipient" className="h-8 flex-1 min-w-0" /></div>}
                    <div className="flex flex-wrap gap-1.5">
                        {mine && side === "PHYSICIAN" && documentCategories.includes(item.category) && (
                            <Button size="sm" disabled={busy} data-testid="work-action-signed" onClick={() => act("signed", targetBody(target))} className="h-8 bg-emerald-600 hover:bg-emerald-700 text-white"><FileCheck2 className="w-3.5 h-3.5 mr-1" /> Signed → Send to {other}</Button>
                        )}
                        {mine && <Button size="sm" disabled={busy} data-testid="work-action-handoff" onClick={() => act("handoff", targetBody(target))} className="h-8 bg-visita-green hover:bg-visita-greenDark text-white"><ArrowRightLeft className="w-3.5 h-3.5 mr-1" /> Send to {other}</Button>}
                        {mine && item.status !== "IN_PROGRESS" && <Button size="sm" variant="outline" disabled={busy} data-testid="work-action-in-progress" onClick={() => act("in_progress")} className="h-8"><Play className="w-3.5 h-3.5 mr-1" /> In progress</Button>}
                        {mine && (
                            <span className="inline-flex items-center gap-1">
                                <Button size="sm" variant="outline" disabled={busy} data-testid="work-action-waiting" onClick={() => act("waiting", { waiting_until: waitUntil ? new Date(`${waitUntil}T08:00:00`).toISOString() : null })} className="h-8"><Clock className="w-3.5 h-3.5 mr-1" /> Waiting</Button>
                                <Input type="date" data-testid="work-waiting-until" value={waitUntil} onChange={(e) => setWaitUntil(e.target.value)} className="h-8 w-36 text-xs" title="Waiting until" />
                            </span>
                        )}
                        {mine && (
                            <span className="inline-flex rounded-sm overflow-hidden">
                                <Button size="sm" disabled={busy} data-testid="work-action-complete" onClick={() => act("complete")} className="h-8 rounded-r-none bg-emerald-600 hover:bg-emerald-700 text-white"><Check className="w-3.5 h-3.5 mr-1" /> Complete</Button>
                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <Button size="sm" disabled={busy} data-testid="work-action-close-menu" aria-label="Close as…" className="h-8 w-7 px-0 rounded-l-none border-l border-emerald-800/40 bg-emerald-600 hover:bg-emerald-700 text-white"><ChevronDown className="w-3.5 h-3.5" /></Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end" className="text-xs">
                                        {CLOSE_OUTCOMES.map((o) => <DropdownMenuItem key={o} data-testid={`work-close-${o.toLowerCase()}`} onSelect={() => setClosing(o)}>Close as {OUTCOME_LABEL[o]}</DropdownMenuItem>)}
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </span>
                        )}
                        <Button size="sm" variant="ghost" disabled={busy || !note.trim()} data-testid="work-action-reply" onClick={() => act("reply")} className="h-8"><MessageSquare className="w-3.5 h-3.5 mr-1" /> Add note</Button>
                        {item.created_by === userId && (
                            <Button size="sm" variant="ghost" disabled={busy} data-testid="work-action-withdraw" onClick={() => setWithdrawing(true)} className="h-8 ml-auto text-red-700 hover:text-red-800 hover:bg-red-50" title="Sent by mistake? Withdraw this item (kept in history)."><Undo2 className="w-3.5 h-3.5 mr-1" /> Withdraw</Button>
                        )}
                    </div>
                    {withdrawing && (
                        <div className="flex flex-wrap items-center gap-1.5 rounded-sm border border-red-300 bg-red-50 p-2 text-xs" data-testid="work-withdraw-panel">
                            <span className="font-semibold text-red-800">Withdraw this item? It is removed from active work and kept in History.</span>
                            <Input data-testid="work-withdraw-note" autoFocus value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional reason, e.g. Wrong patient" maxLength={500} className="h-7 flex-1 min-w-[12rem] text-xs" />
                            <Button size="sm" disabled={busy} data-testid="work-withdraw-confirm" onClick={() => act("withdraw")} className="h-7 bg-red-600 hover:bg-red-700 text-white text-xs">Withdraw</Button>
                            <Button size="sm" variant="ghost" disabled={busy} data-testid="work-withdraw-cancel" onClick={() => setWithdrawing(false)} className="h-7 text-xs">Cancel</Button>
                        </div>
                    )}
                    {closing && (
                        <div className="flex flex-wrap items-center gap-1.5 rounded-sm border border-slate-300 bg-slate-50 p-2 text-xs" data-testid="work-close-panel">
                            <span className="font-semibold text-slate-700">Close as {OUTCOME_LABEL[closing]}</span>
                            <Input data-testid="work-close-note" autoFocus value={closeNote} onChange={(e) => setCloseNote(e.target.value)} placeholder="Optional note, e.g. Patient was already booked" maxLength={500} className="h-7 flex-1 min-w-[12rem] text-xs" />
                            <Button size="sm" disabled={busy} data-testid="work-close-confirm" onClick={() => act("complete", { outcome: closing, note: closeNote || null })} className="h-7 bg-slate-700 hover:bg-slate-800 text-white text-xs">Confirm</Button>
                            <Button size="sm" variant="ghost" disabled={busy} data-testid="work-close-cancel" onClick={() => { setClosing(null); setCloseNote(""); }} className="h-7 text-xs">Cancel</Button>
                        </div>
                    )}
                </div>
            )}
            {item.status === "COMPLETED" && (
                <div className="border-t border-slate-200 pt-2 flex items-center justify-between text-xs text-slate-500">
                    <span className="flex items-center gap-1.5"><OutcomeBadge item={item} testid="work-detail-outcome" />{item.completion_outcome && item.completion_outcome !== "COMPLETED" ? "Closed" : "Completed"} by {item.completed_by} · {whenLabel(item.completed_at)}</span>
                    <Button size="sm" variant="ghost" disabled={busy} data-testid="work-action-reopen" onClick={() => act("reopen")} className="h-7 text-xs"><RotateCcw className="w-3 h-3 mr-1" /> Reopen</Button>
                </div>
            )}
        </div>
    );
}
