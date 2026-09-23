import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { UserPlus, RotateCcw, Check, X, Send, Clock, MessageSquarePlus, IdCard } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { formatDate } from "../lib/date";

const APP_STATUS = {
    REQUEST_RECEIVED: ["Request Received", "bg-slate-100 text-slate-600"],
    WAITING_LIST: ["Waiting List", "bg-amber-100 text-amber-700"],
    UNDER_REVIEW: ["Under Review", "bg-blue-100 text-blue-700"],
    SENT_TO_PHYSICIAN: ["Sent to Physician", "bg-purple-100 text-purple-700"],
    ACCEPTED: ["Accepted", "bg-emerald-100 text-emerald-700"],
    NOT_ACCEPTING: ["Not Accepting", "bg-red-100 text-red-700"],
    CLOSED: ["Closed", "bg-slate-200 text-slate-600"],
};

function AppPill({ status }) {
    const [label, cls] = APP_STATUS[status] || [status, "bg-slate-100 text-slate-600"];
    return <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`}>{label}</span>;
}

const FILTERS = [
    { key: "", label: "All" },
    { key: "former_return", label: "Former Returns", param: "type" },
    { key: "new_patient", label: "New Patients", param: "type" },
    { key: "WAITING_LIST", label: "Waiting List", param: "status" },
];

export default function Applications() {
    const { user } = useAuth();
    const physician = user?.role === "physician";
    const invalidate = useInvalidate();
    const [filter, setFilter] = useState("");
    const [noteDraft, setNoteDraft] = useState({});
    const [pinOpen, setPinOpen] = useState(null);      // application id whose PIN editor is open
    const [pinSug, setPinSug] = useState([]);          // suggested PINs
    const [pinVal, setPinVal] = useState("");
    const [pinBusy, setPinBusy] = useState(false);

    const list = useQuery({
        queryKey: ["queue", "/internal/applications", filter],
        queryFn: async () => {
            const f = FILTERS.find((x) => x.key === filter);
            const qs = f?.param ? `?${f.param}=${f.key}` : "";
            return (await api.get(`/internal/applications${qs}`)).data;
        },
    });
    const items = list.data || [];

    const patch = async (id, body, msg = "Updated.") => {
        try {
            await api.patch(`/internal/applications/${id}`, body);
            toast.success(msg);
            invalidate(); list.refetch();
            setNoteDraft((d) => ({ ...d, [id]: "" }));
        } catch (e) { toast.error(formatErr(e)); }
    };

    const finalDone = (a) => ["ACCEPTED", "NOT_ACCEPTING", "CLOSED"].includes(a.internal_status);

    const openPin = async (a) => {
        setPinOpen(a.id); setPinVal(a.created_visita_patient_id || ""); setPinSug([]);
        try {
            const { data } = await api.get("/internal/visita-pin/suggestions", { params: { count: 5 } });
            setPinSug(data.suggestions || []);
        } catch (e) { toast.error(formatErr(e)); }
    };

    const savePin = async (id) => {
        if (!/^\d{4}$/.test(pinVal)) return toast.error("VISITA PIN must be a 4-digit number.");
        setPinBusy(true);
        try {
            await api.post(`/internal/applications/${id}/assign-pin`, { pin: pinVal });
            toast.success(`VISITA PIN ${pinVal} assigned.`);
            setPinOpen(null); invalidate(); list.refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setPinBusy(false); }
    };

    return (
        <div className="animate-fade-in max-w-4xl">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Patient Applications</h1>
            <p className="text-sm text-slate-500 mb-4">
                New-patient requests and former-patient return requests. Final acceptance is made by the physician.
            </p>

            <div className="flex gap-2 mb-4">
                {FILTERS.map((f) => (
                    <button key={f.key} data-testid={`app-filter-${f.key || "all"}`} onClick={() => setFilter(f.key)}
                        className={`px-3 py-1.5 rounded-sm text-sm font-medium border ${
                            filter === f.key ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                        }`}>
                        {f.label}
                    </button>
                ))}
            </div>

            <div className="space-y-3">
                {items.length === 0 && <p className="text-slate-400 text-sm">No applications.</p>}
                {items.map((a) => {
                    const isFormer = a.application_type === "former_return";
                    const cands = a.directory_match?.candidates || [];
                    return (
                        <div key={a.id} data-testid="application-item" className="bg-white border border-slate-300 rounded-sm p-4">
                            <div className="flex items-start justify-between gap-3 flex-wrap">
                                <div className="text-sm space-y-0.5">
                                    <div className="flex items-center gap-2">
                                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold ${isFormer ? "bg-orange-100 text-orange-700" : "bg-indigo-100 text-indigo-700"}`}>
                                            {isFormer ? <RotateCcw className="w-3 h-3" /> : <UserPlus className="w-3 h-3" />}
                                            {isFormer ? "Former Return" : "New Patient"}
                                        </span>
                                        <AppPill status={a.internal_status} />
                                    </div>
                                    <div className="font-bold text-slate-800 text-base mt-1">{a.last_name}, {a.first_name}</div>
                                    <div className="text-slate-600">DOB: {formatDate(a.date_of_birth)} · {a.ref_number}</div>
                                    <div className="text-slate-600">Phone: {a.phone} · Email: {a.email}</div>
                                    {a.health_card_masked && <div className="text-slate-600">Health Card: {a.health_card_masked}</div>}
                                    {(a.address || a.city || a.province) && (
                                        <div className="text-slate-600">Address: {[a.address, a.city, a.province, a.postal_code].filter(Boolean).join(", ")}</div>
                                    )}
                                    {a.patient_message && <div className="text-slate-600 italic">"{a.patient_message}"</div>}
                                    {a.accepted_by && <div className="text-emerald-700 font-medium">Accepted by {a.accepted_by}</div>}
                                </div>

                                <div className="flex flex-col gap-1.5 items-end min-w-[190px]">
                                    {!finalDone(a) && (
                                        <>
                                            <Button size="sm" variant="outline" className="h-8 w-full justify-start" data-testid="app-waitlist"
                                                onClick={() => patch(a.id, { action: "waitlist" }, "Added to waiting list.")}>
                                                <Clock className="w-4 h-4 mr-1" /> Add to Waiting List
                                            </Button>
                                            {!physician && a.internal_status !== "SENT_TO_PHYSICIAN" && (
                                                <Button size="sm" variant="outline" className="h-8 w-full justify-start" data-testid="app-send-physician"
                                                    onClick={() => patch(a.id, { action: "send_to_physician" }, "Sent to physician.")}>
                                                    <Send className="w-4 h-4 mr-1" /> Send to Physician
                                                </Button>
                                            )}
                                            {physician && (
                                                <Button size="sm" className="h-8 w-full justify-start bg-visita-green hover:bg-visita-greenDark text-white" data-testid="app-accept"
                                                    onClick={() => patch(a.id, { action: "accept" }, "Patient accepted.")}>
                                                    <Check className="w-4 h-4 mr-1" /> {isFormer ? "Accept back to practice" : "Accept"}
                                                </Button>
                                            )}
                                            {physician && (
                                                <Button size="sm" variant="outline" className="h-8 w-full justify-start text-red-600 border-red-200" data-testid="app-decline"
                                                    onClick={() => patch(a.id, { action: "not_accepting" }, "Marked not accepting.")}>
                                                    <X className="w-4 h-4 mr-1" /> Not accepting at this time
                                                </Button>
                                            )}
                                            <Button size="sm" variant="ghost" className="h-8 w-full justify-start text-slate-500" data-testid="app-close"
                                                onClick={() => patch(a.id, { action: "close" }, "Closed.")}>
                                                Close request
                                            </Button>
                                        </>
                                    )}
                                </div>
                            </div>

                            {isFormer && cands.length > 0 && (
                                <div className="mt-3 border-t border-slate-200 pt-2">
                                    <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">
                                        Matched VISITA record{cands.length > 1 ? "s (ambiguous — confirm identity)" : ""} · {a.directory_match?.strength} match
                                    </div>
                                    {cands.map((c) => (
                                        <div key={c.id} className="text-xs text-slate-600 bg-orange-50 rounded-sm px-2 py-1 mb-1">
                                            {c.last_name}, {c.first_name} · DOB {formatDate(c.date_of_birth)} · HC {c.health_card_masked || "—"} · Status {c.patient_status}
                                            {c.visita_patient_id ? ` · VISITA #${c.visita_patient_id}` : ""}
                                        </div>
                                    ))}
                                </div>
                            )}

                            {!isFormer && a.internal_status === "ACCEPTED" && a.created_patient_id && (
                                <div className="mt-3 border-t border-slate-200 pt-3" data-testid="app-pin-panel">
                                    <div className="flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-2 text-sm">
                                            <IdCard className="w-4 h-4 text-visita-green" />
                                            <span className="text-slate-500">VISITA PIN / ID:</span>
                                            <span className="font-bold text-slate-800" data-testid="app-pin-current">{a.created_visita_patient_id || "Not assigned"}</span>
                                        </div>
                                        {pinOpen !== a.id && (
                                            <Button size="sm" variant="outline" className="h-8" data-testid="app-assign-pin" onClick={() => openPin(a)}>
                                                {a.created_visita_patient_id ? "Change PIN" : "Assign PIN"}
                                            </Button>
                                        )}
                                    </div>
                                    {pinOpen === a.id && (
                                        <div className="mt-2 space-y-2" data-testid="app-pin-editor">
                                            <div className="text-xs text-slate-500">Pick a suggested number or enter your own (4 digits):</div>
                                            <div className="flex flex-wrap gap-1.5">
                                                {pinSug.map((s) => (
                                                    <button key={s} type="button" data-testid="app-pin-option"
                                                        onClick={() => setPinVal(s)}
                                                        className={`px-2.5 py-1 rounded-sm text-sm font-mono border ${pinVal === s ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"}`}>
                                                        {s}
                                                    </button>
                                                ))}
                                                {pinSug.length === 0 && <span className="text-xs text-slate-400">Loading suggestions…</span>}
                                            </div>
                                            <div className="flex gap-2 items-center">
                                                <Input className="h-8 w-28 font-mono" maxLength={4} inputMode="numeric" data-testid="app-pin-input"
                                                    value={pinVal} onChange={(e) => setPinVal(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="0000" />
                                                <Button size="sm" className="h-8 bg-visita-green hover:bg-visita-greenDark text-white" disabled={pinBusy || pinVal === (a.created_visita_patient_id || "") || !/^\d{4}$/.test(pinVal)} data-testid="app-pin-save" onClick={() => savePin(a.id)}>Save PIN</Button>
                                                <Button size="sm" variant="outline" className="h-8" onClick={() => setPinOpen(null)}>Cancel</Button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}

                            {a.internal_notes?.length > 0 && (
                                <div className="mt-2 text-xs text-slate-500 space-y-0.5">
                                    {a.internal_notes.map((n, i) => (
                                        <div key={i}>📝 {n.by}: {n.note}</div>
                                    ))}
                                </div>
                            )}

                            {!finalDone(a) && (
                                <div className="mt-2 flex gap-2">
                                    <Input placeholder="Add internal note…" className="h-8 text-sm" data-testid="app-note-input"
                                        value={noteDraft[a.id] || ""} onChange={(e) => setNoteDraft({ ...noteDraft, [a.id]: e.target.value })} />
                                    <Button size="sm" variant="outline" className="h-8" data-testid="app-note-add"
                                        disabled={!noteDraft[a.id]}
                                        onClick={() => patch(a.id, { internal_note: noteDraft[a.id] }, "Note added.")}>
                                        <MessageSquarePlus className="w-4 h-4" />
                                    </Button>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
