import { useEffect, useRef, useState } from "react";
import { HeartPulse, Delete, CornerDownLeft, Eraser } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";

export const VITAL_FIELDS = [
    { k: "systolic_bp", label: "BP", unit: "mmHg", step: "1", w: "w-14", pair: "diastolic_bp" },
    { k: "heart_rate", label: "HR", unit: "bpm", step: "1", w: "w-14" },
    { k: "temperature_c", label: "Temp", unit: "°C", step: "0.1", w: "w-16" },
    { k: "weight_kg", label: "Wt", unit: "kg", step: "0.1", w: "w-16" },
    { k: "height_cm", label: "Ht", unit: "cm", step: "0.1", w: "w-16" },
];
/* Rapid-entry sequence: Sys → Dia → HR → Temp → Wt → Ht */
const ORDER = ["systolic_bp", "diastolic_bp", "heart_rate", "temperature_c", "weight_kg", "height_cm"];
const TARGET_LABEL = { systolic_bp: "BP SYS", diastolic_bp: "BP DIA", heart_rate: "HR", temperature_c: "TEMP", weight_kg: "WT", height_cm: "HT" };
const DECIMAL_OK = { temperature_c: true, weight_kg: true, height_cm: true };
const toStr = (v) => (v === null || v === undefined ? "" : String(v));
const shortDate = (iso) => { const d = iso ? new Date(iso) : null; return d ? d.toLocaleDateString("en-CA", { month: "short", day: "2-digit" }) : "—"; };

/* Compact structured vitals + rapid-entry keypad + Last 3 visits. Autosave contract identical to SOAP. */
export function VitalsPanel({ visitId, patientRef, initial }) {
    const [form, setForm] = useState(() => Object.fromEntries(ORDER.map((k) => [k, toStr(initial?.[k])])));
    const [bmi, setBmi] = useState(initial?.bmi ?? null);
    const [state, setState] = useState("idle");
    const [err, setErr] = useState("");
    const [active, setActive] = useState(null);
    const [recent, setRecent] = useState(null);
    const saved = useRef({ ...form });
    const timer = useRef(null);
    const formRef = useRef(form);
    const inputs = useRef({});
    formRef.current = form;

    useEffect(() => {
        if (!patientRef) return;
        api.get(`/internal/patients/${encodeURIComponent(patientRef)}/recent-vitals`, { params: { limit: 3, exclude: visitId } })
            .then(({ data }) => setRecent(data.visits)).catch(() => setRecent([]));
    }, [patientRef, visitId]);

    const save = async () => {
        const cur = formRef.current;
        const patch = {};
        ORDER.forEach((k) => { if (cur[k] !== saved.current[k]) patch[k] = cur[k] === "" ? null : Number(cur[k]); });
        if (!Object.keys(patch).length) return;
        if (Object.values(patch).some((v) => v !== null && Number.isNaN(v))) { setState("failed"); setErr("Enter numbers only."); return; }
        setState("saving"); setErr("");
        try {
            const { data } = await api.patch(`/internal/visits/${visitId}/vitals`, patch);
            Object.keys(patch).forEach((k) => { saved.current[k] = cur[k]; });
            setBmi(data.vitals.bmi);
            setState("saved");
        } catch (e) { setState("failed"); setErr(formatErr(e)); }
    };
    const schedule = () => { clearTimeout(timer.current); timer.current = setTimeout(save, 1500); };
    const setField = (k, v) => { setForm((f) => ({ ...f, [k]: v })); setState("dirty"); schedule(); };
    const onBlur = () => { clearTimeout(timer.current); save(); };
    useEffect(() => () => clearTimeout(timer.current), []);

    const focusField = (k) => { if (k) { setActive(k); inputs.current[k]?.focus(); inputs.current[k]?.select?.(); } };
    const next = () => {
        const i = ORDER.indexOf(active);
        if (i === -1) return focusField(ORDER[0]);
        if (i < ORDER.length - 1) return focusField(ORDER[i + 1]);
        clearTimeout(timer.current); save(); inputs.current[active]?.blur(); setActive(null);
    };
    const keypad = (key) => {
        const k = active || ORDER[0];
        if (!active) setActive(k);
        const cur = formRef.current[k] || "";
        if (key === "⌫") setField(k, cur.slice(0, -1));
        else if (key === "C") setField(k, "");
        else if (key === ".") { if (DECIMAL_OK[k] && !cur.includes(".")) setField(k, cur ? cur + "." : "0."); }
        else setField(k, cur + key);
        inputs.current[k]?.focus();
    };
    const onKeyDown = (e) => { if (e.key === "Enter") { e.preventDefault(); next(); } };

    const renderInput = (k, step, w) => (
        <input ref={(el) => { inputs.current[k] = el; }} type="text" inputMode="decimal" value={form[k]} aria-label={k} data-testid={`vital-${k}`}
            onChange={(e) => setField(k, e.target.value.replace(/[^0-9.]/g, ""))} onFocus={() => setActive(k)} onBlur={onBlur} onKeyDown={onKeyDown}
            data-active={active === k}
            className={`${w} h-7 px-1.5 text-sm text-right rounded-sm border bg-white focus:outline-none transition-colors ${active === k ? "border-visita-ribbon ring-2 ring-cyan-400 bg-cyan-50" : "border-slate-300"}`} />
    );
    const stateText = { idle: "", dirty: "…", saving: "Saving…", saved: "Saved", failed: "Save failed" }[state];
    const Key = ({ label, onClick, testid, className = "", primary = false, children }) => (
        <button type="button" tabIndex={-1} onMouseDown={(e) => e.preventDefault()} onClick={onClick} data-testid={testid}
            className={`h-7 rounded-sm border text-sm font-semibold ${primary ? "bg-visita-ribbon border-visita-ribbon text-white hover:bg-[#162c49]" : "bg-white border-slate-300 text-slate-800 hover:bg-visita-bg active:bg-cyan-100"} ${className}`}>{children || label}</button>
    );
    return (
        <section className="bg-white border border-slate-300 rounded-sm" data-testid="vitals-panel">
            <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                <HeartPulse className="w-3.5 h-3.5" /> Vitals — today
                <span className={`ml-auto normal-case font-medium text-[10px] ${state === "failed" ? "text-red-700" : state === "saved" ? "text-emerald-700" : "text-slate-400"}`} data-testid="vitals-state" data-state={state}>{stateText}</span>
            </div>
            <div className="p-2 flex flex-wrap gap-x-4 gap-y-2 items-start">
                <div className="contents">
                    <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 items-center text-xs" data-testid="vitals-fields">
                        {VITAL_FIELDS.map(({ k, label, unit, step, w, pair }) => (
                            <div key={k} className="contents">
                                <span className="font-bold text-slate-700 w-9">{label}</span>
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                    {renderInput(k, step, w)}
                                    {pair && (<><span className="text-slate-400">/</span>{renderInput(pair, step, w)}</>)}
                                    <span className="text-slate-500">{unit}</span>
                                </span>
                            </div>
                        ))}
                        <span className="font-bold text-slate-700 w-9">BMI</span>
                        <span className="font-mono text-sm font-semibold text-visita-ribbon" data-testid="vital-bmi">{bmi ?? "—"}</span>
                    </div>
                    {/* Rapid entry keypad */}
                    <div className="w-[7.75rem] ml-auto" data-testid="rapid-entry-keypad">
                        <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500 leading-none mb-1">Rapid entry</div>
                        <div className="h-5 mb-1 text-[11px] font-bold text-visita-ribbon" data-testid="rapid-entry-target">
                            {active ? <>Entering: <span className="px-1 rounded-sm bg-cyan-100">{TARGET_LABEL[active]}</span></> : <span className="text-slate-400 font-medium">Select a field</span>}
                        </div>
                        <div className="grid grid-cols-3 gap-1">
                            {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => <Key key={d} label={d} onClick={() => keypad(d)} testid={`keypad-${d}`} />)}
                            <Key label="." onClick={() => keypad(".")} testid="keypad-dot" className={active && !DECIMAL_OK[active] ? "opacity-40" : ""} />
                            <Key label="0" onClick={() => keypad("0")} testid="keypad-0" />
                            <Key onClick={() => keypad("⌫")} testid="keypad-backspace" aria-label="Backspace"><Delete className="w-4 h-4 mx-auto" /></Key>
                            <Key onClick={() => keypad("C")} testid="keypad-clear" className="text-slate-500"><Eraser className="w-3.5 h-3.5 mx-auto" /></Key>
                            <Key onClick={next} testid="keypad-next" primary className="col-span-2">
                                <span className="inline-flex items-center gap-1 justify-center">Next <CornerDownLeft className="w-3.5 h-3.5" /></span>
                            </Key>
                        </div>
                    </div>
                </div>
            </div>
            {err && <div className="px-2 pb-1.5 text-[11px] text-red-700" data-testid="vitals-error">{err}</div>}
            {/* Last 3 visits — read-only */}
            <div className="border-t border-slate-200 px-2 py-1.5" data-testid="last3-visits">
                <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500 mb-1">Last 3 visits</div>
                {!recent ? <div className="text-[11px] text-slate-400">Loading…</div> : !recent.length ? (
                    <div className="text-[11px] text-slate-400 italic" data-testid="last3-empty">No prior vitals recorded.</div>
                ) : (
                    <table className="text-[11px] tabular-nums w-full" data-testid="last3-table">
                        <thead><tr className="text-slate-500">
                            <th className="text-left font-semibold w-9"></th>
                            {recent.map((r) => <th key={r.visit_id} className="text-right font-semibold" title={`${formatDate(r.started_at?.slice(0, 10))} · ${r.ref_number}`} data-testid={`last3-col-${r.ref_number}`}>{shortDate(r.started_at)}</th>)}
                        </tr></thead>
                        <tbody>
                            {[["BP", (r) => (r.systolic_bp != null || r.diastolic_bp != null ? `${r.systolic_bp ?? "—"}/${r.diastolic_bp ?? "—"}` : "—")],
                              ["HR", (r) => r.heart_rate], ["Temp", (r) => r.temperature_c], ["Wt", (r) => r.weight_kg], ["Ht", (r) => r.height_cm], ["BMI", (r) => r.bmi]].map(([lbl, fn]) => (
                                <tr key={lbl} className="border-t border-slate-100">
                                    <td className="font-bold text-slate-600 py-px">{lbl}</td>
                                    {recent.map((r) => <td key={r.visit_id} className="text-right py-px text-slate-800">{fn(r) ?? "—"}</td>)}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </section>
    );
}
