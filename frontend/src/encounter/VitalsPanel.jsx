import { useEffect, useRef, useState } from "react";
import { HeartPulse, Delete, CornerDownLeft, Eraser, ArrowDownToLine, Plus } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";

/* Measured fields. Height is ENTERED/DISPLAYED in metres (1.70 m) but stored canonically as height_cm. */
export const VITAL_FIELDS = [
    { k: "systolic_bp", label: "BP", unit: "mmHg", w: "w-14", pair: "diastolic_bp", hint: "Sst / Dst" },
    { k: "heart_rate", label: "HR", unit: "bpm", w: "w-14", hint: "bpm" },
    { k: "height_cm", label: "Height", unit: "m", w: "w-16", hint: "Hgt" },
    { k: "weight_kg", label: "Weight", unit: "kg", w: "w-16", hint: "WK" },
    { k: "temperature_c", label: "Temp", unit: "°C", w: "w-16" },
    { k: "head_circumference_cm", label: "Head circ.", unit: "cm", w: "w-16", hint: "HC", more: true },
];
/* Dr. Aguayo fast-entry sequence: BP SYS → BP DIA → HR → HEIGHT → WEIGHT (then Temp, then HC when shown) */
const ORDER = ["systolic_bp", "diastolic_bp", "heart_rate", "height_cm", "weight_kg", "temperature_c", "head_circumference_cm"];
const TARGET_LABEL = { systolic_bp: "BP SYS", diastolic_bp: "BP DIA", heart_rate: "HR", height_cm: "HEIGHT (m)", weight_kg: "WEIGHT (kg)", temperature_c: "TEMP", head_circumference_cm: "HEAD CIRC." };
const DECIMAL_OK = { temperature_c: true, weight_kg: true, height_cm: true, head_circumference_cm: true };
const toStr = (v) => (v === null || v === undefined ? "" : String(v));
const cmToM = (cm) => (cm === null || cm === undefined ? "" : (Number(cm) / 100).toFixed(2));
const mToCm = (m) => (m === "" ? null : Math.round(Number(m) * 1000) / 10);
const kgToLb = (kg) => (kg ? Math.round(kg * 2.20462 * 10) / 10 : null);
const ageYears = (dob) => (dob ? (Date.now() - new Date(dob).getTime()) / (365.25 * 24 * 3600 * 1000) : null);
const fmt1 = (n) => (n === null || n === undefined ? null : Number(n).toFixed(1).replace(/\.0$/, ""));

/* Builds the compact Objective snippet from CURRENT structured values only — nothing fabricated. */
export function vitalsToObjective(v, which) {
    const parts = [];
    const bp = v.systolic_bp != null && v.diastolic_bp != null ? `BP ${v.systolic_bp}/${v.diastolic_bp} mmHg` : null;
    const wt = v.weight_kg != null ? `Wt ${fmt1(v.weight_kg)} kg (${Math.round(kgToLb(v.weight_kg))} lb)` : null;
    const bmi = v.bmi != null ? `BMI ${v.bmi}` : null;
    if (which === "bp") { if (bp) parts.push(bp); }
    else if (which === "weight") { if (wt) parts.push(wt); if (bmi) parts.push(bmi); }
    else {
        if (bp) parts.push(bp);
        if (v.heart_rate != null) parts.push(`HR ${v.heart_rate} bpm`);
        if (v.temperature_c != null) parts.push(`Temp ${fmt1(v.temperature_c)} °C`);
        if (v.height_cm != null) parts.push(`Ht ${cmToM(v.height_cm)} m`);
        if (wt) parts.push(wt);
        if (bmi) parts.push(bmi);
        if (v.head_circumference_cm != null) parts.push(`HC ${fmt1(v.head_circumference_cm)} cm`);
    }
    return parts.length ? `${parts.join("; ")}.` : "";
}
const shortDate = (iso) => { const d = iso ? new Date(iso) : null; return d ? d.toLocaleDateString("en-CA", { month: "short", day: "2-digit" }) : "—"; };

/* Compact structured vitals + rapid-entry keypad + Last 3 visits. Autosave contract identical to SOAP. */
export function VitalsPanel({ visitId, patientRef, initial, dob, onInsertObjective }) {
    const [form, setForm] = useState(() => Object.fromEntries(ORDER.map((k) => [k, k === "height_cm" ? cmToM(initial?.[k]) : toStr(initial?.[k])])));
    const [bmi, setBmi] = useState(initial?.bmi ?? null);
    const pediatric = (ageYears(dob) ?? 99) < 3;
    const [moreOpen, setMoreOpen] = useState(false);
    const showHC = pediatric || moreOpen || form.head_circumference_cm !== "";
    const visibleOrder = ORDER.filter((k) => k !== "head_circumference_cm" || showHC);
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
        ORDER.forEach((k) => { if (cur[k] !== saved.current[k]) patch[k] = cur[k] === "" ? null : k === "height_cm" ? mToCm(cur[k]) : Number(cur[k]); });
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
        const i = visibleOrder.indexOf(active);
        if (i === -1) return focusField(visibleOrder[0]);
        if (i < visibleOrder.length - 1) return focusField(visibleOrder[i + 1]);
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

    const renderInput = (k, w) => (
        <input ref={(el) => { inputs.current[k] = el; }} type="text" inputMode="decimal" value={form[k]} aria-label={k} data-testid={`vital-${k}`}
            onChange={(e) => setField(k, e.target.value.replace(/[^0-9.]/g, ""))} onFocus={() => setActive(k)} onBlur={onBlur} onKeyDown={onKeyDown}
            data-active={active === k}
            className={`${w} h-7 px-1.5 text-sm text-right rounded-sm border bg-white focus:outline-none transition-colors ${active === k ? "border-visita-ribbon ring-2 ring-cyan-400 bg-cyan-50" : "border-slate-300"}`} />
    );
    const stateText = { idle: "", dirty: "…", saving: "Saving…", saved: "Saved", failed: "Save failed" }[state];
    const num = (k) => (form[k] === "" || Number.isNaN(Number(form[k])) ? null : Number(form[k]));
    const current = { systolic_bp: num("systolic_bp"), diastolic_bp: num("diastolic_bp"), heart_rate: num("heart_rate"), temperature_c: num("temperature_c"),
        weight_kg: num("weight_kg"), height_cm: form.height_cm === "" ? null : mToCm(form.height_cm), head_circumference_cm: num("head_circumference_cm"), bmi };
    const weightLb = kgToLb(current.weight_kg);
    const prev = recent?.[0];
    const lastCtx = prev && (prev.weight_kg != null || prev.bmi != null) && (current.weight_kg != null || bmi != null) ? {
        last: [prev.weight_kg != null && `${fmt1(prev.weight_kg)} kg`, prev.bmi != null && `BMI ${prev.bmi}`].filter(Boolean).join(" · "),
        today: [current.weight_kg != null && `${fmt1(current.weight_kg)} kg`, bmi != null && `BMI ${bmi}`].filter(Boolean).join(" · "),
        change: prev.weight_kg != null && current.weight_kg != null ? `${current.weight_kg - prev.weight_kg >= 0 ? "+" : ""}${(current.weight_kg - prev.weight_kg).toFixed(1)} kg` : null,
    } : null;
    const Auto = ({ show }) => (show ? <span className="text-[9px] font-bold tracking-wide px-1 rounded-sm bg-slate-100 text-slate-500 border border-slate-200" data-testid="auto-badge">AUTO</span> : <span />);
    /* Access-inspired green rapid-entry keys. tone: number | utility | primary */
    const TONE = {
        number: "bg-[#22c55e] border-[#15803d] text-[#052e16] hover:bg-[#4ade80] active:bg-[#16a34a]",
        utility: "bg-[#15803d] border-[#14532d] text-white hover:bg-[#16a34a] active:bg-[#166534]",
        primary: "bg-[#14532d] border-[#052e16] text-white hover:bg-[#166534] active:bg-[#052e16]",
    };
    const Key = ({ label, onClick, testid, className = "", tone = "number", children, ...rest }) => (
        <button type="button" tabIndex={-1} onMouseDown={(e) => e.preventDefault()} onClick={onClick} data-testid={testid} data-tone={tone} {...rest}
            className={`h-6 border text-xs font-bold leading-none transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:z-10 ${TONE[tone]} ${className}`}>{children || label}</button>
    );
    return (
        <section className="bg-white border border-slate-300 rounded-sm" data-testid="vitals-panel">
            <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                <HeartPulse className="w-3.5 h-3.5" /> Vitals — today
                <span className={`ml-auto normal-case font-medium text-[10px] ${state === "failed" ? "text-red-700" : state === "saved" ? "text-emerald-700" : "text-slate-400"}`} data-testid="vitals-state" data-state={state}>{stateText}</span>
            </div>
            {/* Rapid entry — Access-style horizontal number bank (10-19 over 0-9) + utility keys */}
            <div className="border-b border-slate-200 px-2 py-1.5" data-testid="rapid-entry-keypad">
                <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-bold uppercase tracking-wide text-slate-500 leading-none">Rapid entry</span>
                    <span className="text-[11px] font-bold text-visita-ribbon leading-none" data-testid="rapid-entry-target">
                        {active ? <>Entering: <span className="px-1 rounded-sm bg-cyan-100">{TARGET_LABEL[active]}</span></> : <span className="text-slate-400 font-medium">Select a field</span>}
                    </span>
                </div>
                <div className="flex items-start gap-2">
                    <div className="grid grid-cols-10 gap-px flex-1 min-w-0 bg-[#15803d] border border-[#15803d] rounded-sm overflow-hidden" data-testid="number-bank">
                        {Array.from({ length: 10 }, (_, i) => String(10 + i)).map((d) => <Key key={d} label={d} onClick={() => keypad(d)} testid={`keypad-${d}`} className="rounded-none border-0" />)}
                        {Array.from({ length: 10 }, (_, i) => String(i)).map((d) => <Key key={d} label={d} onClick={() => keypad(d)} testid={`keypad-${d}`} className="rounded-none border-0" />)}
                    </div>
                    <div className="grid grid-cols-2 gap-px shrink-0 bg-[#14532d] border border-[#14532d] rounded-sm overflow-hidden" data-testid="utility-keys">
                        <Key label="." onClick={() => keypad(".")} testid="keypad-dot" tone="utility" className={`w-8 rounded-tl-sm ${active && !DECIMAL_OK[active] ? "opacity-40" : ""}`} />
                        <Key onClick={() => keypad("⌫")} testid="keypad-backspace" aria-label="Backspace" tone="utility" className="w-8 border-0 rounded-none"><Delete className="w-4 h-4 mx-auto" /></Key>
                        <Key onClick={() => keypad("C")} testid="keypad-clear" aria-label="Clear field" tone="utility" className="w-8 border-0 rounded-none"><Eraser className="w-3.5 h-3.5 mx-auto" /></Key>
                        <Key onClick={next} testid="keypad-next" tone="primary" className="w-8 border-0 rounded-none" aria-label="Next field"><CornerDownLeft className="w-4 h-4 mx-auto" /></Key>
                    </div>
                </div>
            </div>
            <div className="p-2">
                {/* Measured vitals laid out sideways (left→right) in the same fast-entry order as the keypad */}
                <div className="flex flex-wrap items-end gap-x-2 gap-y-1 text-xs" data-testid="vitals-fields">
                    {VITAL_FIELDS.filter(({ k }) => k !== "head_circumference_cm" || showHC).map(({ k, label, unit, w, pair, hint }) => (
                        <div key={k} className="flex flex-col gap-0.5" data-testid={`vital-cell-${k}`}>
                            <span className="text-[10px] font-bold uppercase tracking-wide text-slate-600 leading-none whitespace-nowrap" title={hint ? `Access: ${hint}` : undefined}>{label}</span>
                            <span className="flex items-center gap-0.5 whitespace-nowrap">
                                {renderInput(k, w)}
                                {pair && (<><span className="text-slate-400">/</span>{renderInput(pair, w)}</>)}
                                <span className="text-[10px] text-slate-500">{unit}</span>
                            </span>
                        </div>
                    ))}
                    {!showHC && (
                        <button type="button" onClick={() => setMoreOpen(true)} data-testid="vitals-more-btn"
                            className="inline-flex items-center gap-0.5 h-7 text-[10px] font-semibold text-visita-ribbon hover:underline whitespace-nowrap">
                            <Plus className="w-3 h-3" /> More vitals (Head circ.)
                        </button>
                    )}
                </div>
                {/* CALCULATED — derived, never measured */}
                <div className="mt-1.5 border-t border-dashed border-slate-200 pt-1" data-testid="vitals-calculated">
                    <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500 leading-none mb-0.5">Calculated</div>
                    <div className="grid grid-cols-[auto_1fr_auto] gap-x-2 gap-y-px items-baseline text-xs">
                        <span className="text-slate-600">BMI</span>
                        <span className="font-mono text-sm font-semibold text-visita-ribbon" data-testid="vital-bmi">{bmi ?? <span className="text-[10px] text-slate-400 font-sans font-normal">Needs height + weight</span>}</span>
                        <Auto show={bmi != null} />
                        <span className="text-slate-600" title="Access: WL">Weight</span>
                        <span className="font-mono text-sm font-semibold text-visita-ribbon" data-testid="vital-weight-lb">{weightLb != null ? `${weightLb} lb` : <span className="text-[10px] text-slate-400 font-sans font-normal">Needs weight</span>}</span>
                        <Auto show={weightLb != null} />
                        <span className="text-slate-600" title="Access: iWK / iWL">Ideal Weight</span>
                        <span className="text-[10px] text-slate-400 col-span-2" data-testid="vital-ideal-weight">Formula pending confirmation</span>
                    </div>
                    {lastCtx && (
                        <div className="mt-1 text-[10px] text-slate-600 leading-tight" data-testid="vitals-last-context">
                            <span className="text-slate-400">Last:</span> {lastCtx.last} <span className="text-slate-300">·</span> <span className="text-slate-400">Today:</span> {lastCtx.today}
                            {lastCtx.change && <> <span className="text-slate-300">·</span> <span className={`font-semibold ${lastCtx.change.startsWith("+") ? "text-amber-700" : "text-emerald-700"}`}>{lastCtx.change}</span></>}
                        </div>
                    )}
                </div>
                {/* QUICK → OBJECTIVE: append-only documentation convenience; structured vitals stay authoritative */}
                {onInsertObjective && (
                    <div className="mt-1.5 border-t border-dashed border-slate-200 pt-1" data-testid="quick-objective">
                        <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500 leading-none mb-1">Quick to Objective</div>
                        <div className="flex gap-1">
                            {[["bp", "BP", "quick-obj-bp"], ["weight", "Weight / BMI", "quick-obj-weight"], ["all", "All Vitals", "quick-obj-all"]].map(([w, lbl, tid]) => {
                                const text = vitalsToObjective(current, w);
                                return (
                                    <button key={w} type="button" disabled={!text} onClick={() => { onInsertObjective(text); }} data-testid={tid}
                                        title={text || (w === "bp" ? "BP incomplete" : "No values recorded yet")}
                                        className="inline-flex items-center gap-1 h-6 px-2 rounded-sm border border-slate-300 bg-white text-[11px] font-semibold text-slate-700 hover:bg-visita-bg hover:border-visita-ribbon disabled:opacity-40 disabled:cursor-not-allowed">
                                        <ArrowDownToLine className="w-3 h-3" /> {lbl}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                )}
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
                              ["HR", (r) => r.heart_rate], ["Temp", (r) => r.temperature_c], ["Wt", (r) => r.weight_kg], ["Ht m", (r) => (r.height_cm != null ? cmToM(r.height_cm) : null)], ["BMI", (r) => r.bmi],
                              ...(recent.some((r) => r.head_circumference_cm != null) ? [["HC", (r) => r.head_circumference_cm]] : [])].map(([lbl, fn]) => (
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
