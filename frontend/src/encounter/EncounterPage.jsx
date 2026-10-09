import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Pill, ClipboardList, Stethoscope, Scissors, AlertTriangle, FlaskConical } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDateTime } from "../lib/date";
import { Textarea } from "../components/ui/textarea";
import { SafetyHeader, useElapsed } from "./SafetyHeader";
import { useSoapAutosave } from "./useSoapAutosave";
import { encounterTypeLabel } from "./StartEncounter";
import { VitalsPanel } from "./VitalsPanel";
import { IssuePlanHistory } from "./IssuePlanHistory";
import { SoapHelperTool } from "./SoapHelperTool";

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
                    <span className="text-xs font-bold text-slate-700 leading-none" title={label}><span className="inline-flex w-5 h-5 items-center justify-center rounded-sm bg-visita-ribbon text-white text-[11px]">{letter}</span></span>
                    <Textarea value={soap[k]} onChange={(e) => onChange(k, e.target.value)} onBlur={onBlur}
                        data-testid={`soap-${k}`} placeholder={`${label}…`}
                        className="flex-1 min-h-[72px] resize-none text-sm bg-white overflow-auto border-slate-300 focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:border-visita-ribbon" />
                </label>
            ))}
        </div>
    );
}

function CenterControls({ visit, state, savedAt, onInsert }) {
    return (
        <div className="flex flex-col gap-2" data-testid="encounter-center">
            <div className="flex items-center gap-x-3 px-2 py-1 bg-white border border-slate-300 rounded-sm text-[11px] text-slate-600 whitespace-nowrap overflow-hidden" data-testid="encounter-info">
                <span className="font-semibold text-slate-800" data-testid="encounter-ref">{visit.ref_number}</span>
                <span data-testid="encounter-center-type">{encounterTypeLabel(visit.encounter_type)}</span>
                <span className="hidden 2xl:inline" data-testid="encounter-started">{formatDateTime(visit.started_at)}</span>
                <span className="ml-auto shrink-0" data-testid="encounter-autosave"><SaveState state={state} savedAt={savedAt} /></span>
            </div>
            <SoapHelperTool visitId={visit.id} patientRef={visit.patient_ref} onInsert={onInsert} />
            <VitalsPanel visitId={visit.id} initial={visit.vitals} />
            <div className="border border-dashed border-slate-300 rounded-sm px-2 py-2 text-[11px] text-slate-400" data-testid="rapid-entry-reserved">
                <div className="font-bold uppercase tracking-wide text-[10px] text-slate-500">Rapid entry · Service · Diagnosis</div>
                <div className="italic">Reserved for the fast clinical-entry keypad and selectors (next phases).</div>
            </div>
        </div>
    );
}

const EmptyLine = ({ children, testid }) => <div className="text-[11px] text-slate-400 italic" data-testid={testid}>{children}</div>;

function ContextColumn({ ctx }) {
    const meds = ctx?.medications_active || [];
    return (
        <div className="flex flex-col gap-2" data-testid="encounter-context">
            <Panel title="Past medical Hx" Icon={Stethoscope} testid="ctx-pmhx">
                <EmptyLine testid="ctx-pmhx-empty">No structured past medical history recorded in VIen yet.</EmptyLine>
            </Panel>
            <Panel title="Medications" Icon={Pill} testid="ctx-medications">
                {meds.length ? meds.map((m) => (
                    <div key={m.id} className="py-0.5 border-b last:border-0 border-slate-100 text-[11px] leading-snug">
                        <span className="font-semibold text-slate-900">{m.drug}</span>
                        {(m.strength_display || m.strength) && <span className="text-slate-700"> {m.strength_display || m.strength}</span>}
                        {m.form && <span className="text-slate-600"> {m.form}</span>}
                        {m.sig && <span className="text-slate-600">; {m.sig}</span>}
                        {m.status && <span className="text-slate-400"> · {m.status}</span>}
                    </div>
                )) : <EmptyLine testid="ctx-medications-empty">No physician-confirmed active medications on record.</EmptyLine>}
            </Panel>
            <Panel title="Past surgical Hx" Icon={Scissors} testid="ctx-pshx">
                <EmptyLine testid="ctx-pshx-empty">No surgical history recorded in VIen yet.</EmptyLine>
            </Panel>
            <Panel title="Allergies" Icon={AlertTriangle} testid="ctx-allergies">
                <EmptyLine testid="ctx-allergies-empty">No allergy data recorded in VIen yet.</EmptyLine>
            </Panel>
            <Panel title="Studies / Exams" Icon={FlaskConical} testid="ctx-studies">
                <EmptyLine testid="ctx-studies-empty">No physician-reviewed studies or results available in VIen yet.</EmptyLine>
            </Panel>
        </div>
    );
}

function Workspace({ visit }) {
    const nav = useNavigate();
    const [exiting, setExiting] = useState(false);
    const elapsed = useElapsed(visit.started_at, visit.server_time);
    const { soap, onChange, onBlur, insertText, state, savedAt, flush } = useSoapAutosave(visit.id, { ...visit.soap, last_saved_at: visit.last_saved_at });

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
            <main className="flex-1 min-h-0 grid grid-cols-[minmax(0,1.45fr)_minmax(270px,0.68fr)_minmax(270px,0.87fr)] gap-3 p-3">
                <div className="min-h-0 flex flex-col gap-2" data-testid="encounter-left">
                    <div className="flex-[3] min-h-0"><SoapColumn soap={soap} onChange={onChange} onBlur={onBlur} /></div>
                    <div className="flex-[1.15] min-h-[120px]"><IssuePlanHistory patientRef={visit.patient_ref} currentVisitId={visit.id} /></div>
                </div>
                <div className="min-h-0 overflow-y-auto"><CenterControls visit={visit} state={state} savedAt={savedAt} onInsert={insertText} /></div>
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
