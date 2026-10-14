import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Pill, FlaskConical } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { PmhxSection, PshxSection, AllergySection } from "./ClinicalHistory";
import { formatDateTime } from "../lib/date";
import { Textarea } from "../components/ui/textarea";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";
import { SafetyHeader, VisitTimerStrip, useElapsed } from "./SafetyHeader";
import { useSoapAutosave } from "./useSoapAutosave";
import { encounterTypeLabel, EncounterTypeDialog } from "./StartEncounter";
import { VisitToggle } from "./VisitToggle";
import { DiagnosisSearch } from "./DiagnosisSearch";
import { AnnualExamMonth } from "./AnnualExamMonth";
import { ServiceSelector, CodingRow } from "./ServiceSelector";
import { MetricsGrid } from "./MetricsGrid";
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
        <div className="flex flex-col min-h-0 h-full divide-y divide-black bg-white" data-testid="soap-column">
            {SOAP.map(({ k, label }) => (
                <label key={k} className="flex flex-col flex-1 min-h-0">
                    <Textarea value={soap[k]} onChange={(e) => onChange(k, e.target.value)} onBlur={onBlur}
                        data-testid={`soap-${k}`} aria-label={label} title={label}
                        className="flex-1 min-h-[72px] resize-none text-sm bg-white overflow-auto border-0 rounded-none shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:bg-cyan-50/40" />
                </label>
            ))}
        </div>
    );
}

function CenterControls({ visit, patientRef, state, savedAt, onInsert, onPrepend, toggle, timerStrip }) {
    const [metricsTick, setMetricsTick] = useState(0);
    const [dx, setDx] = useState(visit?.diagnoses?.[0] || null);
    const [svc, setSvc] = useState(visit?.service || null);
    useEffect(() => { setDx(visit?.diagnoses?.[0] || null); setSvc(visit?.service || null); }, [visit?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    return (
        <div className="flex flex-col bg-white [&>*]:border-0 [&>*]:border-t [&>*]:border-black [&>*:first-child]:border-t-0 [&>*]:rounded-none" data-testid="encounter-center">
            {timerStrip}
            <div className="flex items-center gap-x-3 px-2 py-1 bg-white border border-slate-300 rounded-sm text-[11px] text-slate-600 whitespace-nowrap overflow-hidden" data-testid="encounter-info">
                {visit ? (<>
                    <span className="font-semibold text-slate-800" data-testid="encounter-ref">{visit.ref_number}</span>
                    <span data-testid="encounter-center-type">{encounterTypeLabel(visit.encounter_type)}</span>
                    <span className="hidden 2xl:inline" data-testid="encounter-started">{formatDateTime(visit.started_at)}</span>
                    <span className="ml-auto shrink-0" data-testid="encounter-autosave"><SaveState state={state} savedAt={savedAt} /></span>
                </>) : <span className="italic text-slate-500" data-testid="encounter-ready-hint">No visit started — press Start Visit to begin documenting.</span>}
            </div>
            <fieldset disabled={!visit} className="flex flex-col min-w-0 [&>section]:border-0 [&>section]:border-t [&>section]:border-black [&>section:first-child]:border-t-0 [&>section]:rounded-none" data-testid="center-tools">
                <SoapHelperTool visitId={visit?.id} patientRef={patientRef} onInsert={onInsert} />
            </fieldset>
            <fieldset disabled={!visit} className="flex flex-col min-w-0 [&>section]:border-0 [&>section]:rounded-none" data-testid="center-tools-vitals">
                <VitalsPanel key={visit?.id || "ready"} visitId={visit?.id} patientRef={patientRef} initial={visit?.vitals}
                    onInsertObjective={(text) => onPrepend("objective", text)} onSaved={() => setMetricsTick((t) => t + 1)} />
            </fieldset>
            <MetricsGrid patientRef={patientRef} refreshKey={metricsTick} />
            <DiagnosisSearch visitId={visit?.id} initial={visit?.diagnoses} onChange={setDx} />
            <AnnualExamMonth patientRef={patientRef} canEdit={!!visit} />
            <ServiceSelector visitId={visit?.id} initial={visit?.service} onChange={setSvc} />
            <CodingRow service={svc} diagnosis={dx} />
            <div className="bg-white px-2 py-1.5" data-testid="lower-visit-toggle-wrap">{toggle}</div>
        </div>
    );
}

const EmptyLine = ({ children, testid }) => <div className="text-[11px] text-slate-400 italic" data-testid={testid}>{children}</div>;

function ContextColumn({ ctx, patientRef }) {
    const { user } = useAuth();
    const canEdit = user?.role === "physician";
    const meds = ctx?.medications_active || [];
    return (
        <div className="flex flex-col gap-2" data-testid="encounter-context">
            <PmhxSection patientRef={patientRef} canEdit={canEdit} />
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
            <PshxSection patientRef={patientRef} canEdit={canEdit} />
            <AllergySection patientRef={patientRef} canEdit={canEdit} />
            <Panel title="Studies / Exams" Icon={FlaskConical} testid="ctx-studies">
                <EmptyLine testid="ctx-studies-empty">No physician-reviewed studies or results available in VIen yet.</EmptyLine>
            </Panel>
        </div>
    );
}

/* shell = ready context (no visit) or the visit itself. `visit` null => READY state. */
function Workspace({ shell, visit, setVisit }) {
    const nav = useNavigate();
    const [exiting, setExiting] = useState(false);
    const [typeOpen, setTypeOpen] = useState(false);
    const [exitWarn, setExitWarn] = useState(false);
    const [busy, setBusy] = useState(false);
    const patientRef = shell.patient_ref;
    const timer = visit ? { timer_state: visit.timer_state, elapsed_seconds: visit.elapsed_seconds, running_since: visit.running_since } : null;
    const timerState = visit ? visit.timer_state : "READY";
    const elapsed = useElapsed(timer, shell.server_time);
    const { soap, onChange, onBlur, insertText, prependGenerated, state, savedAt, flush } = useSoapAutosave(visit?.id, { ...(visit?.soap || {}), last_saved_at: visit?.last_saved_at });

    const applyTimer = (data) => setVisit((v) => ({ ...v, timer_state: data.timer_state, elapsed_seconds: data.elapsed_seconds,
        running_since: data.running_since, paused_at: data.paused_at, server_time: data.server_time }));
    const stop = async () => { const { data } = await api.post(`/internal/visits/${visit.id}/stop`); applyTimer(data); return data; };

    const onToggle = async () => {
        if (!visit) { setTypeOpen(true); return; }
        setBusy(true);
        try {
            if (visit.timer_state === "RUNNING") await stop();
            else { const { data } = await api.post(`/internal/visits/${visit.id}/resume`); applyTimer(data); }
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const onStartContinue = async (encounterType) => {
        setBusy(true);
        try {
            const { data } = await api.post("/internal/visits", { patient_ref: patientRef, encounter_type: encounterType, source: "patients" });
            setTypeOpen(false);
            nav(`/internal/encounter/${data.id}`, { replace: true });
        } catch (e) {
            const d = e?.response?.data?.detail;
            if (e?.response?.status === 409 && d?.visit_id) { setTypeOpen(false); nav(`/internal/encounter/${d.visit_id}`, { replace: true }); }
            else toast.error(formatErr(e));
        } finally { setBusy(false); }
    };

    const leave = () => nav(`/internal/patients?patient_ref=${encodeURIComponent(patientRef)}`);
    const doExit = async (stopFirst) => {
        setExitWarn(false);
        if (!visit) { leave(); return; }
        setExiting(true);
        const ok = await flush();
        if (!ok) { setExiting(false); toast.error("Your note could not be saved. Please check your connection and try again before exiting."); return; }
        try {
            if (stopFirst) await stop();
            await api.post(`/internal/visits/${visit.id}/exit`);
            leave();
        } catch (e) { toast.error(formatErr(e)); setExiting(false); }
    };
    const onExit = () => { if (visit?.timer_state === "RUNNING") setExitWarn(true); else doExit(false); };

    const toggle = (testid, compact, fullWidth) => <VisitToggle timerState={timerState} onClick={onToggle} busy={busy} testid={testid} compact={compact} fullWidth={fullWidth} />;

    return (
        <div className="h-screen bg-visita-bg flex flex-col" data-testid="encounter-mode" data-timer-state={timerState}>
            <SafetyHeader visit={shell} typeLabel={visit ? encounterTypeLabel(visit.encounter_type) : "Not started"} onExit={onExit} exiting={exiting} />
            <main className="flex-1 min-h-0 grid grid-cols-[minmax(0,1.25fr)_minmax(272px,0.62fr)_minmax(270px,1fr)] gap-0 p-0 bg-white border-t border-black">
                <div className="min-h-0 flex flex-col border-r border-black" data-testid="encounter-left">
                    <fieldset disabled={!visit} className="contents"><div className="flex-[3] min-h-0"><SoapColumn soap={soap} onChange={onChange} onBlur={onBlur} /></div></fieldset>
                    <div className="flex-[1.15] min-h-[120px] border-t border-black [&>section]:border-0 [&>section]:rounded-none"><IssuePlanHistory patientRef={patientRef} currentVisitId={visit?.id} /></div>
                </div>
                <div className="min-h-0 overflow-y-auto border-r border-black"><CenterControls visit={visit} patientRef={patientRef} state={state} savedAt={savedAt} onInsert={insertText} onPrepend={prependGenerated} toggle={toggle("visit-toggle-lower", true, true)}
                    timerStrip={<VisitTimerStrip timerState={timerState} elapsed={elapsed} toggle={toggle("visit-toggle-top", true)} />} /></div>
                <div className="min-h-0 overflow-y-auto [&_[data-testid=encounter-context]]:gap-0 [&_[data-testid=encounter-context]>*]:border-0 [&_[data-testid=encounter-context]>*]:border-b [&_[data-testid=encounter-context]>*]:border-black [&_[data-testid=encounter-context]>*]:rounded-none [&_[data-testid=encounter-context]>*]:ring-0"><ContextColumn ctx={shell.context} patientRef={patientRef} /></div>
            </main>
            <EncounterTypeDialog open={typeOpen} busy={busy} onCancel={() => setTypeOpen(false)} onContinue={onStartContinue} />
            <Dialog open={exitWarn} onOpenChange={setExitWarn}>
                <DialogContent className="max-w-sm" data-testid="exit-running-dialog">
                    <DialogHeader>
                        <DialogTitle>Visit timer is currently running.</DialogTitle>
                        <DialogDescription>Stop the visit time before leaving, or stay in the encounter. Nothing is signed or completed.</DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" data-testid="exit-stay-btn" onClick={() => setExitWarn(false)}>Stay</Button>
                        <Button data-testid="exit-stop-and-exit-btn" onClick={() => doExit(true)} className="bg-red-600 hover:bg-red-700 text-white">Stop Visit &amp; Exit</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

export default function EncounterPage() {
    const { visitId } = useParams();
    const [params] = useSearchParams();
    const nav = useNavigate();
    const patientRef = params.get("patient_ref");
    const [shell, setShell] = useState(null);
    const [visit, setVisit] = useState(null);
    const [err, setErr] = useState("");
    useEffect(() => {
        setShell(null); setVisit(null); setErr("");
        if (visitId) {
            api.get(`/internal/visits/${visitId}`).then(({ data }) => { setVisit(data); setShell(data); }).catch((e) => setErr(formatErr(e)));
        } else if (patientRef) {
            api.get("/internal/visits/ready", { params: { patient_ref: patientRef } }).then(({ data }) => {
                if (data.active) nav(`/internal/encounter/${data.active.id}`, { replace: true });
                else setShell(data);
            }).catch((e) => setErr(formatErr(e)));
        } else setErr("No patient selected.");
    }, [visitId, patientRef, nav]);
    if (err) return <div className="p-8 text-red-700" data-testid="encounter-error">{err}</div>;
    if (!shell) return <div className="p-8 text-slate-500" data-testid="encounter-loading">Loading encounter…</div>;
    return <Workspace key={visitId || "ready"} shell={shell} visit={visit} setVisit={setVisit} />;
}
