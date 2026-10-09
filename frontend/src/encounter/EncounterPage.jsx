import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Pill, CalendarDays, FileText, ClipboardList } from "lucide-react";
import { ApptTypeBadge } from "../components/ApptTypeBadge";
import { api, formatErr } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/date";
import { Textarea } from "../components/ui/textarea";
import { SafetyHeader, useElapsed } from "./SafetyHeader";
import { useSoapAutosave } from "./useSoapAutosave";
import { encounterTypeLabel } from "./StartEncounter";

const SOAP = [
    { k: "subjective", letter: "S", label: "Subjective" },
    { k: "objective", letter: "O", label: "Objective" },
    { k: "assessment", letter: "A", label: "Assessment" },
    { k: "plan", letter: "P", label: "Plan" },
];

function SaveState({ state, savedAt }) {
    const t = savedAt ? new Date(savedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;
    const map = {
        idle: ["text-slate-500", t ? `Saved ${t}` : "Not saved yet"],
        dirty: ["text-slate-500", "Unsaved changes…"],
        saving: ["text-sky-700", "Saving…"],
        saved: ["text-emerald-700", `Saved ${t || ""}`],
        failed: ["text-red-700 font-semibold", "Save failed — retrying on next change"],
    };
    const [cls, text] = map[state] || map.idle;
    return <span className={`text-xs ${cls}`} data-testid="autosave-state" data-state={state}>{text}</span>;
}

function Panel({ title, Icon, children, testid }) {
    return (
        <section className="bg-white border border-slate-300 rounded-sm" data-testid={testid}>
            <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                <Icon className="w-3.5 h-3.5" /> {title}
            </div>
            <div className="p-2 text-sm">{children}</div>
        </section>
    );
}

const Empty = ({ children }) => <div className="text-xs text-slate-400 italic">{children}</div>;

function SoapColumn({ soap, onChange, onBlur }) {
    return (
        <div className="flex flex-col gap-2 min-h-0 h-full" data-testid="soap-column">
            {SOAP.map(({ k, letter, label }) => (
                <label key={k} className="flex flex-col gap-0.5 flex-1 min-h-0">
                    <span className="text-xs font-bold text-slate-700 leading-none"><span className="inline-flex w-5 h-5 items-center justify-center rounded-sm bg-visita-ribbon text-white mr-1.5 text-[11px]">{letter}</span>{label}</span>
                    <Textarea value={soap[k]} onChange={(e) => onChange(k, e.target.value)} onBlur={onBlur}
                        data-testid={`soap-${k}`} placeholder={`${label}…`}
                        className="flex-1 min-h-[72px] resize-none text-sm bg-white overflow-auto border-slate-300 focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:border-visita-ribbon" />
                </label>
            ))}
        </div>
    );
}

function CenterControls({ visit, state, savedAt }) {
    return (
        <div className="flex flex-col gap-2" data-testid="encounter-center">
            <Panel title="Encounter" Icon={ClipboardList} testid="encounter-info">
                <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs">
                    <dt className="text-slate-500">Ref</dt><dd className="font-semibold" data-testid="encounter-ref">{visit.ref_number}</dd>
                    <dt className="text-slate-500">Type</dt><dd data-testid="encounter-center-type">{encounterTypeLabel(visit.encounter_type)}</dd>
                    <dt className="text-slate-500">Started</dt><dd data-testid="encounter-started">{formatDateTime(visit.started_at)}</dd>
                    {visit.appointment_ref && (<><dt className="text-slate-500">Appt</dt><dd>{visit.appointment_ref}</dd></>)}
                    {visit.reason && (<><dt className="text-slate-500">Reason</dt><dd>{visit.reason}</dd></>)}
                </dl>
                <div className="mt-2 pt-2 border-t border-slate-200" data-testid="encounter-autosave">
                    <SaveState state={state} savedAt={savedAt} />
                    <div className="text-[10px] text-slate-400 mt-0.5 leading-snug">Notes save automatically. Exit keeps this encounter in progress.</div>
                </div>
            </Panel>
            <div className="text-[10px] text-slate-400 italic px-1" data-testid="encounter-tools">Clinical tools (vitals, helpers, orders) — later phase.</div>
        </div>
    );
}

function ContextColumn({ ctx }) {
    const meds = ctx?.medications_active || [], appts = ctx?.recent_appointments || [], docs = ctx?.documents || [];
    const emptyNames = [!meds.length && "medications", !appts.length && "appointments", !docs.length && "documents"].filter(Boolean);
    return (
        <div className="flex flex-col gap-2" data-testid="encounter-context">
            {meds.length > 0 && (
                <Panel title="Active medications" Icon={Pill} testid="ctx-medications">
                    {meds.map((m) => (
                        <div key={m.id} className="py-0.5 border-b last:border-0 border-slate-100">
                            <div className="font-semibold text-xs">{m.drug}</div>
                            <div className="text-[11px] text-slate-500">{[m.strength_display || m.strength, m.form, m.sig].filter(Boolean).join(" · ")}</div>
                        </div>
                    ))}
                </Panel>
            )}
            {appts.length > 0 && (
                <Panel title="Recent appointments" Icon={CalendarDays} testid="ctx-appointments">
                    {appts.map((a) => (
                        <div key={a.ref_number} className="flex items-center gap-2 py-0.5 border-b last:border-0 border-slate-100 text-[11px]">
                            <span className="whitespace-nowrap">{formatDate(a.date)} {a.time}</span>
                            {a.appointment_type && <ApptTypeBadge type={a.appointment_type} />}
                            <span className="text-slate-500 truncate ml-auto">{a.reason || a.status}</span>
                        </div>
                    ))}
                </Panel>
            )}
            {docs.length > 0 && (
                <Panel title="Documents" Icon={FileText} testid="ctx-documents">
                    {docs.map((d) => <div key={d.id} className="text-[11px] py-0.5 truncate">{d.original_filename || d.title}</div>)}
                </Panel>
            )}
            {emptyNames.length > 0 && (
                <div className="bg-white/60 border border-dashed border-slate-300 rounded-sm px-2 py-1.5 text-[11px] text-slate-500" data-testid="ctx-empty">
                    No {emptyNames.join(", ")} on record for this patient.
                </div>
            )}
            <div className="bg-white/60 border border-dashed border-slate-300 rounded-sm px-2 py-1.5 text-[11px] text-slate-400 italic" data-testid="ctx-coming-later">
                Diagnoses · PMHx · Allergies — not yet recorded in VIen (later phase).
            </div>
        </div>
    );
}

function Workspace({ visit }) {
    const nav = useNavigate();
    const [exiting, setExiting] = useState(false);
    const elapsed = useElapsed(visit.started_at, visit.server_time);
    const { soap, onChange, onBlur, state, savedAt, flush } = useSoapAutosave(visit.id, { ...visit.soap, last_saved_at: visit.last_saved_at });

    const onExit = async () => {
        setExiting(true);
        const ok = await flush();
        if (!ok) { setExiting(false); toast.error("Your note could not be saved. Please check your connection and try again before exiting."); return; }
        try {
            await api.post(`/internal/visits/${visit.id}/exit`);
            nav(`/internal/patients?patient_ref=${encodeURIComponent(visit.patient_ref)}`);
        } catch (e) { toast.error(formatErr(e)); setExiting(false); }
    };

    return (
        <div className="h-screen bg-visita-bg flex flex-col" data-testid="encounter-mode">
            <SafetyHeader visit={visit} elapsed={elapsed} typeLabel={encounterTypeLabel(visit.encounter_type)} onExit={onExit} exiting={exiting} />
            <main className="flex-1 min-h-0 grid grid-cols-[minmax(0,1.55fr)_minmax(200px,0.5fr)_minmax(280px,0.95fr)] gap-3 p-3">
                <SoapColumn soap={soap} onChange={onChange} onBlur={onBlur} />
                <div className="min-h-0 overflow-y-auto"><CenterControls visit={visit} state={state} savedAt={savedAt} /></div>
                <div className="min-h-0 overflow-y-auto"><ContextColumn ctx={visit.context} /></div>
            </main>
        </div>
    );
}

export default function EncounterPage() {
    const { visitId } = useParams();
    const [visit, setVisit] = useState(null);
    const [err, setErr] = useState("");
    useEffect(() => {
        api.get(`/internal/visits/${visitId}`).then(({ data }) => setVisit(data)).catch((e) => setErr(formatErr(e)));
    }, [visitId]);
    if (err) return <div className="p-8 text-red-700" data-testid="encounter-error">{err}</div>;
    if (!visit) return <div className="p-8 text-slate-500" data-testid="encounter-loading">Loading encounter…</div>;
    return <Workspace visit={visit} />;
}
