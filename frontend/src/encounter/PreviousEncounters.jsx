import { useEffect, useState } from "react";
import { History } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/date";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../components/ui/dialog";
import { encounterTypeLabel } from "./StartEncounter";

const SOAP = [["subjective", "S", "Subjective"], ["objective", "O", "Objective"], ["assessment", "A", "Assessment"], ["plan", "P", "Plan"]];
const VIT = [["systolic_bp", "BP sys", "mmHg"], ["diastolic_bp", "BP dia", "mmHg"], ["heart_rate", "HR", "bpm"],
             ["temperature_c", "Temp", "°C"], ["weight_kg", "Wt", "kg"], ["height_cm", "Ht", "cm"], ["bmi", "BMI", ""]];
const statusLabel = (s) => (s === "IN_PROGRESS" ? "IN PROGRESS" : s);

/* READ-ONLY viewer for a historical visit. Never writes; never touches the current encounter state. */
function PreviousEncounterDialog({ visitId, onClose }) {
    const [v, setV] = useState(null);
    const [err, setErr] = useState("");
    useEffect(() => {
        if (!visitId) return;
        setV(null); setErr("");
        api.get(`/internal/visits/${visitId}`).then(({ data }) => setV(data)).catch((e) => setErr(formatErr(e)));
    }, [visitId]);
    const vit = v?.vitals || {};
    const hasVitals = VIT.some(([k]) => vit[k] !== null && vit[k] !== undefined);
    return (
        <Dialog open={!!visitId} onOpenChange={(o) => { if (!o) onClose(); }}>
            <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto" data-testid="previous-encounter-dialog">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        Previous encounter {v?.ref_number && <span className="font-mono text-sm text-slate-500">{v.ref_number}</span>}
                        <span className="ml-auto text-[10px] font-bold tracking-wide px-1.5 py-0.5 rounded-sm bg-slate-100 text-slate-600">READ-ONLY</span>
                    </DialogTitle>
                    <DialogDescription>
                        {v ? `${formatDateTime(v.started_at)} · ${encounterTypeLabel(v.encounter_type)} · ${v.physician_name} · ${statusLabel(v.status)}` : err || "Loading…"}
                    </DialogDescription>
                </DialogHeader>
                {v && (
                    <div className="space-y-3 text-sm" data-testid="previous-encounter-body">
                        {SOAP.map(([k, letter, label]) => (
                            <div key={k}>
                                <div className="text-xs font-bold text-slate-700 mb-0.5"><span className="inline-flex w-5 h-5 items-center justify-center rounded-sm bg-slate-500 text-white mr-1.5 text-[11px]">{letter}</span>{label}</div>
                                <div className="whitespace-pre-wrap rounded-sm border border-slate-200 bg-slate-50 px-2 py-1.5 min-h-[32px] text-slate-800" data-testid={`prev-soap-${k}`}>{v.soap?.[k] || <span className="text-slate-400 italic">—</span>}</div>
                            </div>
                        ))}
                        <div>
                            <div className="text-xs font-bold text-slate-700 mb-0.5">Vitals</div>
                            {hasVitals ? (
                                <div className="flex flex-wrap gap-x-4 gap-y-1 rounded-sm border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs" data-testid="prev-vitals">
                                    {VIT.filter(([k]) => vit[k] !== null && vit[k] !== undefined).map(([k, l, u]) => (
                                        <span key={k}><span className="text-slate-500">{l}</span> <span className="font-semibold">{vit[k]}</span> <span className="text-slate-400">{u}</span></span>
                                    ))}
                                </div>
                            ) : <div className="text-xs text-slate-400 italic" data-testid="prev-vitals-empty">No vitals recorded for this encounter.</div>}
                        </div>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
}

export function PreviousEncounters({ patientRef, currentVisitId }) {
    const [rows, setRows] = useState(null);
    const [open, setOpen] = useState(null);
    useEffect(() => {
        if (!patientRef) return;
        api.get(`/internal/patients/${encodeURIComponent(patientRef)}/visits`)
            .then(({ data }) => setRows(data.visits.filter((v) => v.id !== currentVisitId)))
            .catch(() => setRows([]));
    }, [patientRef, currentVisitId]);
    return (
        <section className="bg-white border border-slate-300 rounded-sm" data-testid="ctx-previous-encounters">
            <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                <History className="w-3.5 h-3.5" /> Previous encounters {rows && <span className="ml-auto text-slate-400 normal-case font-medium">{rows.length}</span>}
            </div>
            <div className="p-1 text-xs">
                {!rows ? <div className="px-1 py-1 text-slate-400">Loading…</div> : !rows.length ? (
                    <div className="px-1 py-1 text-slate-400 italic" data-testid="prev-encounters-empty">No previous encounters for this patient.</div>
                ) : rows.map((r) => (
                    <button key={r.id} type="button" onClick={() => setOpen(r.id)} data-testid={`prev-encounter-${r.ref_number}`}
                        className="w-full grid grid-cols-[auto_1fr_auto] items-center gap-x-2 px-1 py-1 rounded-sm text-left hover:bg-visita-bg border-b last:border-0 border-slate-100">
                        <span className="font-semibold whitespace-nowrap">{formatDate(r.started_at?.slice(0, 10))}</span>
                        <span className="truncate text-slate-700">{encounterTypeLabel(r.encounter_type)} · <span className="text-slate-500">{r.physician_name}</span></span>
                        <span className={`text-[9px] font-bold tracking-wide px-1 py-px rounded-sm ${r.status === "IN_PROGRESS" ? "bg-cyan-100 text-cyan-800" : "bg-slate-100 text-slate-600"}`}>{statusLabel(r.status)}</span>
                    </button>
                ))}
            </div>
            <PreviousEncounterDialog visitId={open} onClose={() => setOpen(null)} />
        </section>
    );
}
