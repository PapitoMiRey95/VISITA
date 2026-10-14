import { useEffect, useMemo, useState } from "react";
import { Search, ShieldCheck, History } from "lucide-react";
import { api } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/date";
import { encounterTypeLabel } from "./StartEncounter";
import { CodingBand } from "./ServiceSelector";

/* Visit Hx — READ-ONLY historical Visit viewer. Zero mutation controls. SIGNED visits render from signed_snapshot. */
const STATUS_BADGE = {
    SIGNED: "bg-visita-ribbon text-white", READY_TO_SIGN: "bg-amber-100 text-amber-900", IN_PROGRESS: "bg-emerald-100 text-emerald-800", COMPLETED: "bg-slate-200 text-slate-700",
};
const statusLabel = (s) => ({ SIGNED: "SIGNED", READY_TO_SIGN: "STOPPED · UNSIGNED", IN_PROGRESS: "IN PROGRESS", COMPLETED: "COMPLETED (LEGACY)" }[s] || s || "—");

export function VisitHx({ patientRef, currentVisitId, active }) {
    const [rows, setRows] = useState(null);
    const [q, setQ] = useState("");
    const [selId, setSelId] = useState(null);
    const [rec, setRec] = useState(null);

    useEffect(() => {
        if (!patientRef || !active) return;
        api.get(`/internal/patients/${encodeURIComponent(patientRef)}/visits`, { params: currentVisitId ? { exclude_visit_id: currentVisitId } : {} })
            .then(({ data }) => setRows(data.visits)).catch(() => setRows([]));
    }, [patientRef, currentVisitId, active]);
    useEffect(() => {
        if (!selId) { setRec(null); return; }
        api.get(`/internal/visits/${selId}/record`).then(({ data }) => setRec(data)).catch(() => setRec(null));
    }, [selId]);

    const list = useMemo(() => {
        const t = q.trim().toLowerCase();
        return (rows || []).filter((r) => !t || (r.primary_dx?.diagnosis_text || "").toLowerCase().includes(t) || (r.ref_number || "").toLowerCase().includes(t)
            || formatDate(r.started_at).toLowerCase().includes(t) || (r.primary_dx?.diagnosis_code || "").includes(t));
    }, [rows, q]);

    return (
        <div className="h-full min-h-0 grid grid-cols-[minmax(300px,0.9fr)_minmax(0,2.1fr)] bg-white" data-testid="visit-hx">
            <aside className="min-h-0 flex flex-col border-r border-black">
                <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-300 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                    <History className="w-3.5 h-3.5" /> Visit Hx <span className="font-normal normal-case text-slate-400" data-testid="visit-hx-count">{rows ? `${rows.length} previous` : ""}</span>
                </div>
                <div className="relative px-2 py-1 border-b border-slate-200">
                    <Search className="w-3.5 h-3.5 absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by Dx, ref or date…" data-testid="visit-hx-search"
                        className="w-full h-7 pl-7 pr-2 text-xs rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500" />
                </div>
                <div className="grid grid-cols-[108px_1fr_82px] px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-slate-500 bg-slate-100 border-b border-slate-300">
                    <span>Date</span><span>Dx</span><span className="text-right">Visit Ref</span>
                </div>
                <ul className="min-h-0 overflow-y-auto divide-y divide-slate-100 text-xs" data-testid="visit-hx-list">
                    {rows === null && <li className="px-2 py-2 text-slate-400 italic">Loading…</li>}
                    {rows && !list.length && <li className="px-2 py-2 text-slate-400 italic" data-testid="visit-hx-empty">No previous visits.</li>}
                    {list.map((r) => (
                        <li key={r.id}>
                            <button type="button" onClick={() => setSelId(r.id)} data-testid={`visit-hx-row-${r.ref_number}`} aria-selected={selId === r.id}
                                className={`w-full grid grid-cols-[108px_1fr_82px] items-baseline gap-x-1 px-2 py-1 text-left hover:bg-visita-bg ${selId === r.id ? "bg-cyan-50" : ""}`}>
                                <span className="font-semibold text-slate-900 whitespace-nowrap">{formatDate(r.started_at)}</span>
                                <span className={`truncate ${r.primary_dx ? "text-slate-800" : "text-slate-400"}`} title={r.primary_dx?.diagnosis_text || ""}>{r.primary_dx?.diagnosis_text || "—"}</span>
                                <span className="text-right font-mono text-[10px] text-slate-600 whitespace-nowrap">{r.ref_number}{r.status === "SIGNED" && <ShieldCheck className="inline w-3 h-3 ml-0.5 text-visita-ribbon" />}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            </aside>
            <section className="min-h-0 overflow-y-auto" data-testid="visit-hx-detail">
                {!rec ? (
                    <div className="p-6 text-sm text-slate-400 italic" data-testid="visit-hx-none">{selId ? "Loading visit…" : "Select a previous visit to review it (read-only)."}</div>
                ) : <HistoricalVisit data={rec} />}
            </section>
        </div>
    );
}

const VIT = [["Sst", "systolic_bp"], ["Dst", "diastolic_bp"], ["Bpm", "heart_rate"], ["Hgt", "height_cm"], ["WK", "weight_kg"], ["WL", "weight_lb"], ["BMI", "bmi"], ["°C", "temperature_c"], ["HC", "head_circumference_cm"], ["Lgt", "length_cm"]];
const fmtHgt = (cm) => (cm == null ? null : (cm / 100).toFixed(2));

function HistoricalVisit({ data }) {
    const r = data.record || {};
    const dx = (r.diagnoses || [])[0] || null;
    const vit = r.vitals || {};
    const hasVit = VIT.some(([, k]) => vit[k] != null);
    const sec = (label, text, testid) => (
        <div className="border-b border-black" data-testid={testid}>
            <div className="px-2 pt-1 text-[9px] font-bold uppercase tracking-wide text-slate-400">{label}</div>
            <div className="px-2 pb-2 text-sm whitespace-pre-wrap min-h-[56px] text-slate-900">{text || <span className="text-slate-300">—</span>}</div>
        </div>
    );
    return (
        <div className="flex flex-col" data-testid="visit-hx-record" data-source={data.source}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1 bg-slate-50 border-b border-black text-[11px] text-slate-700" data-testid="visit-hx-meta">
                <span className="font-bold text-slate-900" data-testid="visit-hx-ref">{r.ref_number}</span>
                <span>{formatDateTime(r.started_at)}</span>
                <span>{encounterTypeLabel(r.encounter_type)}</span>
                <span>{r.physician_name}</span>
                <span className={`px-1.5 py-px rounded-sm text-[10px] font-bold ${STATUS_BADGE[data.status] || "bg-slate-200 text-slate-700"}`} data-testid="visit-hx-status">{statusLabel(data.status)}</span>
                <span className="ml-auto text-[10px] font-bold text-amber-800" data-testid="visit-hx-readonly">READ ONLY</span>
            </div>
            {data.source === "SIGNED_SNAPSHOT" && (
                <div className="px-2 py-1 bg-visita-ribbon/5 border-b border-black text-[11px] text-slate-800 flex items-center gap-1.5" data-testid="visit-hx-signature">
                    <ShieldCheck className="w-3.5 h-3.5 text-visita-ribbon" />
                    <span className="font-bold">SIGNED</span> · {data.signed_by?.physician_name} · {formatDateTime(data.signed_at)}
                    <span className="ml-auto font-mono text-[9px] text-slate-500">{(data.signed_snapshot_hash || "").slice(0, 23)}…</span>
                </div>
            )}
            {sec("Subjective", r.soap?.subjective, "visit-hx-subjective")}
            {sec("Objective", r.soap?.objective, "visit-hx-objective")}
            <div className="border-b border-black" data-testid="visit-hx-assessment"><CodingBand service={r.service} diagnosis={dx} /></div>
            {sec("Plan", r.soap?.plan, "visit-hx-plan")}
            <div className="grid grid-cols-2 gap-x-4 px-2 py-1.5 text-[11px]">
                <div data-testid="visit-hx-vitals">
                    <div className="text-[9px] font-bold uppercase tracking-wide text-slate-400 mb-0.5">Vitals</div>
                    {hasVit ? (
                        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                            {VIT.filter(([, k]) => vit[k] != null).map(([l, k]) => <span key={k}><span className="text-slate-500">{l}</span> <span className="font-semibold font-mono">{k === "height_cm" ? fmtHgt(vit[k]) : vit[k]}</span></span>)}
                        </div>
                    ) : <span className="text-slate-400">—</span>}
                </div>
                <div data-testid="visit-hx-coding">
                    <div className="text-[9px] font-bold uppercase tracking-wide text-slate-400 mb-0.5">Diagnosis · Service</div>
                    <div>{dx ? <><span className="font-semibold">{dx.diagnosis_text}</span> <span className="font-mono text-slate-600">{dx.diagnosis_code}</span></> : <span className="text-slate-400">—</span>}</div>
                    <div>{r.service?.primary ? <><span className="font-semibold">{r.service.primary.service_description}</span> <span className="font-mono text-slate-600">{r.service.primary.service_code}</span></> : <span className="text-slate-400">—</span>}
                        {(r.service?.additional_codes || []).map((a) => <span key={a.catalog_id} className="ml-2 font-mono text-slate-600">+{a.service_code}</span>)}</div>
                </div>
            </div>
        </div>
    );
}
