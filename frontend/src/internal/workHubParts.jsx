import { useState, useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { Search, X, UserRound, Bell, ArrowRightLeft, Check, Clock, Play, RotateCcw, MessageSquare, FileCheck2, Flag, AlertTriangle } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatPatientName } from "../lib/name";
import { formatDate, formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";

export const STATUS_TONE = {
    NEW: "bg-amber-100 text-amber-800 border-amber-200",
    IN_PROGRESS: "bg-sky-100 text-sky-800 border-sky-200",
    WAITING: "bg-slate-100 text-slate-600 border-slate-200",
    COMPLETED: "bg-emerald-100 text-emerald-800 border-emerald-200",
};
export const STATUS_LABEL = { NEW: "New", IN_PROGRESS: "In progress", WAITING: "Waiting", COMPLETED: "Completed" };
export const OWNER_LABEL = { PHYSICIAN: "Doctor", CLINIC: "Clinic" };
export const PRIORITIES = ["NORMAL", "B2", "B1", "ASAP"];
export const PRIORITY_LABEL = { NORMAL: "Normal", B2: "B2", B1: "B1", ASAP: "ASAP" };
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
    if (!priority || priority === "NORMAL") return null;
    return <Chip tone={PRIORITY_TONE[priority]} testid={testid}>{priority === "ASAP" && <AlertTriangle className="w-3 h-3 mr-0.5" />}{PRIORITY_LABEL[priority]}</Chip>;
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
                <Button type="button" size="sm" className="h-9 px-2" data-testid="work-patient-pin-btn" disabled={!pin} onClick={searchPin}>PIN</Button>
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
export function NewWorkDialog({ side, categories, onClose, onDone }) {
    const [patient, setPatient] = useState(null);
    const [category, setCategory] = useState("MESSAGE");
    const [sendTo, setSendTo] = useState(side === "PHYSICIAN" ? "CLINIC" : "PHYSICIAN");
    const [message, setMessage] = useState("");
    const [due, setDue] = useState("");
    const [custom, setCustom] = useState("");
    const [priority, setPriority] = useState("NORMAL");
    const [busy, setBusy] = useState(false);
    const submit = async (e) => {
        e.preventDefault(); setBusy(true);
        try {
            await api.post("/internal/work", {
                category, message, send_to: sendTo, priority, due_at: dueFromPreset(due, custom),
                patient_id: patient?.patient_id || (patient?.source === "portal" ? patient?.id : null) || null,
                directory_id: patient?.directory_id || (patient?.source === "directory" ? patient?.id : null) || null,
                patient_name: patient ? formatPatientName(patient) : null,
            });
            toast.success(`Sent to ${OWNER_LABEL[sendTo]}.`); onDone(); onClose();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };
    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-lg" data-testid="work-new-dialog">
                <DialogHeader><DialogTitle>New work item</DialogTitle></DialogHeader>
                <form onSubmit={submit} className="space-y-3 text-sm">
                    <PatientPicker selected={patient} onSelect={setPatient} onClear={() => setPatient(null)} />
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div><Label className="text-xs">Type</Label>
                            <select data-testid="work-category" value={category} onChange={(e) => setCategory(e.target.value)} className="w-full h-9 rounded-sm border border-slate-300 bg-white px-2 text-sm">
                                {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                            </select></div>
                        <div><Label className="text-xs">Send to</Label>
                            <div className="flex rounded-sm border border-slate-300 overflow-hidden h-9" data-testid="work-send-to">
                                {["PHYSICIAN", "CLINIC"].map((o) => (
                                    <button key={o} type="button" data-testid={`work-send-to-${o.toLowerCase()}`} onClick={() => setSendTo(o)}
                                        className={`flex-1 text-sm ${sendTo === o ? "bg-visita-green text-white font-semibold" : "bg-white text-slate-600"}`}>{OWNER_LABEL[o]}</button>
                                ))}
                            </div></div>
                    </div>
                    <div><Label className="text-xs">What needs to be done?</Label>
                        <Input autoFocus required data-testid="work-message" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="e.g. Complete insurance form" maxLength={2000} /></div>
                    <div className="flex items-center gap-2">
                        <Label className="text-xs">Priority</Label>
                        <PriorityControl value={priority} onChange={setPriority} />
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                        <Label className="text-xs mr-1">Remind / Due</Label>
                        {DUE_PRESETS.map(([k, l]) => (
                            <button key={k} type="button" data-testid={`work-due-${k || "none"}`} onClick={() => setDue(k)}
                                className={`rounded-sm border px-2 py-0.5 text-xs ${due === k ? "border-visita-green bg-visita-greenLight text-visita-greenDark font-semibold" : "border-slate-300 text-slate-600"}`}>{l}</button>
                        ))}
                        {due === "custom" && <Input type="date" data-testid="work-due-custom" value={custom} onChange={(e) => setCustom(e.target.value)} className="h-7 w-40 text-xs" />}
                    </div>
                    <Button type="submit" disabled={busy || !message.trim()} data-testid="work-submit" className="w-full bg-visita-green hover:bg-visita-greenDark text-white">Send to {OWNER_LABEL[sendTo]}</Button>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function EventRow({ ev }) {
    const icon = { created: MessageSquare, reply: MessageSquare, handoff: ArrowRightLeft, waiting: Clock, completed: Check, status: Play, reopened: RotateCcw, PRIORITY_CHANGED: Flag, DOCUMENT_SIGNED: FileCheck2 }[ev.type] || MessageSquare;
    const Icon = icon;
    const head = {
        created: `sent to ${OWNER_LABEL[ev.to_role] || ev.to_role}`,
        handoff: `${OWNER_LABEL[ev.from_role] || ev.from_role} → ${OWNER_LABEL[ev.to_role] || ev.to_role}`,
        waiting: ev.waiting_until ? `waiting until ${formatDate(ev.waiting_until.slice(0, 10))}` : "waiting",
        completed: "completed", status: STATUS_LABEL[ev.status] || ev.status, reply: "note", reopened: "reopened",
        PRIORITY_CHANGED: `changed priority ${PRIORITY_LABEL[ev.from_priority] || ev.from_priority} → ${PRIORITY_LABEL[ev.to_priority] || ev.to_priority}`,
        DOCUMENT_SIGNED: "Doctor → Clinic · document signed",
    }[ev.type] || ev.type;
    return (
        <div data-testid="work-event" className="flex gap-2 text-xs">
            <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${ev.type === "DOCUMENT_SIGNED" ? "text-emerald-600" : ev.type === "PRIORITY_CHANGED" && ev.to_priority === "ASAP" ? "text-red-600" : "text-visita-greenDark"}`} />
            <div className="min-w-0">
                <div className="text-slate-500"><span className="font-semibold text-slate-700">{ev.by_name}</span> · {head} · {whenLabel(ev.at)}</div>
                {ev.text && <div className="text-slate-800 whitespace-pre-wrap">{ev.text}</div>}
            </div>
        </div>
    );
}

// Right-hand detail: patient, category, owner, status, request, history, valid actions.
export function WorkDetail({ item, side, categories, documentCategories = [], onChanged, onBack }) {
    const [note, setNote] = useState("");
    const [waitUntil, setWaitUntil] = useState("");
    const [busy, setBusy] = useState(false);
    const mine = item.owner_role === side && item.status !== "COMPLETED";
    const cat = categories.find((c) => c.key === item.category)?.label || item.category;
    const act = async (action, extra = {}) => {
        setBusy(true);
        try {
            await api.post(`/internal/work/${item.id}/action`, { action, note: note || null, ...extra });
            setNote(""); setWaitUntil(""); onChanged();
            toast.success({ handoff: `Sent to ${OWNER_LABEL[item.owner_role === "PHYSICIAN" ? "CLINIC" : "PHYSICIAN"]}.`, complete: "Completed.", waiting: "Set to waiting.", in_progress: "In progress.", reply: "Note added.", reopen: "Reopened.", signed: "Signed — sent to Clinic.", priority: "Priority updated." }[action]);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const other = OWNER_LABEL[item.owner_role === "PHYSICIAN" ? "CLINIC" : "PHYSICIAN"];
    return (
        <div data-testid="work-detail" className="bg-white border border-slate-300 rounded-sm p-3 space-y-3 text-sm">
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    {onBack && <button data-testid="work-detail-back" onClick={onBack} className="text-xs text-slate-400 hover:text-visita-greenDark mb-1 md:hidden">← Back to list</button>}
                    <div className="text-xs text-slate-500">{item.ref_number} · {cat}</div>
                    <div className="font-bold text-slate-900 truncate" data-testid="work-detail-patient">{item.patient_name || "No patient"}</div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                    <span className="flex items-center gap-1">
                        <PriorityBadge priority={item.priority} testid="work-detail-priority" />
                        <Chip tone="bg-visita-greenLight text-visita-greenDark border-visita-green/40" testid="work-detail-owner">With {OWNER_LABEL[item.owner_role]}</Chip>
                    </span>
                    <span className="flex items-center gap-1">
                        <OverdueBadge item={item} testid="work-detail-overdue" />
                        <SignedBadge item={item} testid="work-detail-signed" />
                        <Chip tone={STATUS_TONE[item.status]} testid="work-detail-status">{STATUS_LABEL[item.status]}</Chip>
                    </span>
                </div>
            </div>
            {item.status !== "COMPLETED" && (
                <div className="flex items-center gap-2 text-xs text-slate-500">
                    <span>Priority</span>
                    <PriorityControl size="xs" value={item.priority || "NORMAL"} onChange={(p) => act("priority", { priority: p })} testid="work-detail-priority-control" />
                </div>
            )}
            {(item.due_at || (item.status === "WAITING" && item.waiting_until)) && (
                <div className="text-xs text-slate-500 flex items-center gap-1" data-testid="work-detail-when">
                    <Bell className="w-3 h-3" />{item.status === "WAITING" && item.waiting_until ? `Waiting until ${formatDate(item.waiting_until.slice(0, 10))}` : `Due ${formatDate(item.due_at.slice(0, 10))}`}
                </div>
            )}
            <div className="space-y-2 border-t border-slate-200 pt-2" data-testid="work-history">
                {(item.events || []).map((ev, i) => <EventRow key={i} ev={ev} />)}
            </div>
            {item.status !== "COMPLETED" && (
                <div className="border-t border-slate-200 pt-2 space-y-2">
                    <Input data-testid="work-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder={mine ? "Reply / note (optional)" : "Add a note"} maxLength={2000} />
                    <div className="flex flex-wrap gap-1.5">
                        {mine && side === "PHYSICIAN" && documentCategories.includes(item.category) && (
                            <Button size="sm" disabled={busy} data-testid="work-action-signed" onClick={() => act("signed")} className="h-8 bg-emerald-600 hover:bg-emerald-700 text-white"><FileCheck2 className="w-3.5 h-3.5 mr-1" /> Signed → Send to Clinic</Button>
                        )}
                        {mine && <Button size="sm" disabled={busy} data-testid="work-action-handoff" onClick={() => act("handoff")} className="h-8 bg-visita-green hover:bg-visita-greenDark text-white"><ArrowRightLeft className="w-3.5 h-3.5 mr-1" /> Send to {other}</Button>}
                        {mine && item.status !== "IN_PROGRESS" && <Button size="sm" variant="outline" disabled={busy} data-testid="work-action-in-progress" onClick={() => act("in_progress")} className="h-8"><Play className="w-3.5 h-3.5 mr-1" /> In progress</Button>}
                        {mine && (
                            <span className="inline-flex items-center gap-1">
                                <Button size="sm" variant="outline" disabled={busy} data-testid="work-action-waiting" onClick={() => act("waiting", { waiting_until: waitUntil ? new Date(`${waitUntil}T08:00:00`).toISOString() : null })} className="h-8"><Clock className="w-3.5 h-3.5 mr-1" /> Waiting</Button>
                                <Input type="date" data-testid="work-waiting-until" value={waitUntil} onChange={(e) => setWaitUntil(e.target.value)} className="h-8 w-36 text-xs" title="Waiting until" />
                            </span>
                        )}
                        {mine && <Button size="sm" disabled={busy} data-testid="work-action-complete" onClick={() => act("complete")} className="h-8 bg-emerald-600 hover:bg-emerald-700 text-white"><Check className="w-3.5 h-3.5 mr-1" /> Complete</Button>}
                        <Button size="sm" variant="ghost" disabled={busy || !note.trim()} data-testid="work-action-reply" onClick={() => act("reply")} className="h-8"><MessageSquare className="w-3.5 h-3.5 mr-1" /> Add note</Button>
                    </div>
                </div>
            )}
            {item.status === "COMPLETED" && (
                <div className="border-t border-slate-200 pt-2 flex items-center justify-between text-xs text-slate-500">
                    <span>Completed by {item.completed_by} · {whenLabel(item.completed_at)}</span>
                    <Button size="sm" variant="ghost" disabled={busy} data-testid="work-action-reopen" onClick={() => act("reopen")} className="h-7 text-xs"><RotateCcw className="w-3 h-3 mr-1" /> Reopen</Button>
                </div>
            )}
        </div>
    );
}
