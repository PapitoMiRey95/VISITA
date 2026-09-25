import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Check, Send, Search, X, UserRound } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";
import { formatPatientName, formatCombinedName } from "../lib/name";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

// Standardized patient sub-line: "PIN: 4821 · DOB: 1984 Nov - 18"
function PatientMeta({ p }) {
    return (
        <span className="text-xs text-slate-500">
            PIN: {p.visita_patient_id || "Not assigned"} · DOB: {formatDate(p.date_of_birth) || "—"}
        </span>
    );
}

// Reuses the existing internal patient search endpoint (/internal/patients).
// Optional: a task can be created with no patient. Links the stable patient id.
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
            setResults(data);
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
            <div data-testid="task-patient-selected"
                className="flex items-start justify-between gap-2 rounded-sm border border-visita-green/40 bg-visita-greenLight px-2.5 py-2">
                <div className="min-w-0">
                    <div className="font-semibold text-slate-800 text-sm flex items-center gap-1.5">
                        <UserRound className="w-3.5 h-3.5 text-visita-greenDark" /> {formatPatientName(selected)}
                    </div>
                    <PatientMeta p={selected} />
                </div>
                <button type="button" data-testid="task-patient-clear" onClick={onClear}
                    className="text-slate-400 hover:text-red-600 shrink-0" title="Change patient">
                    <X className="w-4 h-4" />
                </button>
            </div>
        );
    }

    return (
        <div ref={boxRef} className="relative">
            <div className="relative">
                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                <Input data-testid="task-patient-search" value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onFocus={() => { if (results.length) setOpen(true); }}
                    placeholder="Search PIN, first or last name…" className="pl-8" />
            </div>
            {open && q.trim().length >= 2 && (
                <div data-testid="task-patient-results"
                    className="absolute z-30 mt-1 w-full bg-white border border-slate-300 rounded-sm shadow-lg divide-y max-h-72 overflow-y-auto">
                    {loading && <div className="px-3 py-3 text-xs text-slate-400">Searching…</div>}
                    {!loading && results.length === 0 && (
                        <div className="px-3 py-3 text-xs text-slate-400">No matching patients found.</div>
                    )}
                    {!loading && results.map((r) => (
                        <button key={r.id} type="button" data-testid="task-patient-result"
                            onClick={() => { onSelect(r); setOpen(false); setQ(""); }}
                            className="w-full text-left px-3 py-2 hover:bg-slate-50">
                            <div className="font-semibold text-slate-800 text-sm">{formatPatientName(r)}</div>
                            <PatientMeta p={r} />
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

export default function TaskQueue() {
    const { user } = useAuth();
    const physician = user?.role === "physician";
    const invalidate = useInvalidate();
    const [message, setMessage] = useState("");
    const [patient, setPatient] = useState(null);
    const [busy, setBusy] = useState(false);

    const list = useQuery({ queryKey: ["queue", "/internal/tasks"], queryFn: async () => (await api.get("/internal/tasks")).data });
    const items = list.data || [];

    const create = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await api.post("/internal/tasks", {
                recipient_role: physician ? "staff" : "physician",
                patient_id: patient?.id || undefined,
                patient_name: patient ? formatPatientName(patient) : undefined,
                message,
            });
            toast.success(physician ? "Task sent to clinic staff." : "Message sent to physician.");
            setMessage(""); setPatient(null);
            invalidate(); list.refetch();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const patch = async (id, body) => {
        try { await api.patch(`/internal/tasks/${id}`, body); invalidate(); list.refetch(); toast.success("Updated."); }
        catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="animate-fade-in max-w-3xl">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
                {physician ? "Intercom — Messages from Staff" : "Doctor Tasks & Intercom"}
            </h1>
            <p className="text-sm text-slate-500 mb-4">Internal communication between clinic staff and physician.</p>

            <form onSubmit={create} className="bg-white border border-slate-300 rounded-sm p-4 mb-5 space-y-3">
                <div className="font-semibold text-slate-700 flex items-center gap-2">
                    <Plus className="w-4 h-4 text-visita-green" /> {physician ? "New Task for Staff" : "New Message to Doctor"}
                </div>
                <div className="grid grid-cols-3 gap-2 items-start">
                    <div>
                        <Label className="text-xs">Patient (optional)</Label>
                        <PatientPicker selected={patient} onSelect={setPatient} onClear={() => setPatient(null)} />
                    </div>
                    <div className="col-span-2">
                        <Label className="text-xs">Message</Label>
                        <Input required value={message} onChange={(e) => setMessage(e.target.value)} data-testid="task-message" />
                    </div>
                </div>
                <Button type="submit" disabled={busy} data-testid="task-submit" className="bg-visita-green hover:bg-visita-greenDark text-white">Send</Button>
            </form>

            <div className="space-y-2">
                {items.length === 0 && <p className="text-slate-400 text-sm">No items.</p>}
                {items.map((t) => (
                    <div key={t.id} data-testid="task-item" className="bg-white border border-slate-300 rounded-sm p-3 flex items-start justify-between gap-3">
                        <div className="text-sm">
                            <div className="text-xs text-slate-500">
                                {t.ref_number} · FROM: {t.sender_name}
                                {t.patient_name ? <> · PATIENT: <span className="font-semibold text-slate-700">{formatCombinedName(t.patient_name)}</span></> : ""}
                            </div>
                            <div className="text-slate-800 font-medium mt-0.5">{t.message}</div>
                            <div className="mt-1"><StatusPill status={t.status} /></div>
                        </div>
                        <div className="flex flex-col gap-1.5">
                            {t.status !== "completed" && (
                                <Button size="sm" onClick={() => patch(t.id, { action: "complete" })} data-testid="task-complete" className="bg-visita-green hover:bg-visita-greenDark text-white h-8">
                                    <Check className="w-4 h-4 mr-1" /> Complete
                                </Button>
                            )}
                            {!physician && t.recipient_role === "staff" && t.status !== "completed" && (
                                <Button size="sm" variant="outline" onClick={() => patch(t.id, { action: "send_to_physician" })} data-testid="task-escalate" className="h-8">
                                    <Send className="w-4 h-4 mr-1" /> Send to Doctor
                                </Button>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
