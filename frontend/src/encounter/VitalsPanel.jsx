import { Fragment, useEffect, useRef, useState } from "react";
import { HeartPulse, Delete, CornerDownLeft, Eraser, ArrowDownToLine } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";

/* Dr. Aguayo Access vitals row — EXACT visible labels/order. Editable = physician-measured; ro = derived automatically. */
export const VITAL_ROW = [
    { k: "systolic_bp", label: "Sst", tip: "Systolic", w: "w-12" },
    { k: "diastolic_bp", label: "Dst", tip: "Diastolic", w: "w-12" },
    { k: "heart_rate", label: "Bpm", tip: "Heart rate", w: "w-12" },
    { k: "weight_kg", label: "WK", tip: "Weight kilos", w: "w-14" },
    { k: "weight_lb", label: "WL", tip: "Weight pounds (auto)", w: "w-14", ro: true },
    { k: "height_cm", label: "Hgt", tip: "Height (m)", w: "w-14" },
    { k: "bmi", label: "BMI", tip: "Body mass index (auto)", w: "w-12", ro: true },
    { k: "iwk", label: "IWK", tip: "Ideal weight kilos — formula not yet confirmed", w: "w-12", ro: true },
    { k: "iwl", label: "IWL", tip: "Ideal weight pounds — formula not yet confirmed", w: "w-12", ro: true },
    { k: "temperature_c", label: "°C", tip: "Temperature", w: "w-12" },
    { k: "head_circumference_cm", label: "HC", tip: "Head circumference (cm)", w: "w-12" },
];
/* Editable navigation only — Next/Enter skips WL/BMI/IWK/IWL: Sst → Dst → Bpm → WK → Hgt → °C → HC */
const ORDER = ["systolic_bp", "diastolic_bp", "heart_rate", "weight_kg", "height_cm", "temperature_c", "head_circumference_cm"];
const TARGET_LABEL = Object.fromEntries(VITAL_ROW.map((f) => [f.k, f.label]));
const DECIMAL_OK = { temperature_c: true, weight_kg: true, height_cm: true, head_circumference_cm: true };
const toStr = (v) => (v === null || v === undefined ? "" : String(v));
const cmToM = (cm) => (cm === null || cm === undefined ? "" : (Number(cm) / 100).toFixed(2));
const mToCm = (m) => (m === "" ? null : Math.round(Number(m) * 1000) / 10);
const kgToLb = (kg) => (kg ? Math.round(kg * 2.20462 * 10) / 10 : null);
const fmt1 = (n) => (n === null || n === undefined ? null : Number(n).toFixed(1).replace(/\.0$/, ""));

/* Builds the compact Objective snippet from CURRENT structured values only — nothing fabricated. */
export function vitalsToObjective(v, which) {
    const parts = [];
    const bp = v.systolic_bp != null && v.diastolic_bp != null ? `BP ${v.systolic_bp}/${v.diastolic_bp}` : null;
    const wk = v.weight_kg != null ? `WK ${fmt1(v.weight_kg)}` : null;
    const wl = v.weight_kg != null ? `WL ${Math.round(kgToLb(v.weight_kg))}` : null;
    const bmi = v.bmi != null ? `BMI ${v.bmi}` : null;
    if (which === "bp") { if (bp) parts.push(bp); }
    else if (which === "weight") { if (wk) parts.push(wk, wl); if (bmi) parts.push(bmi); }
    else {
        if (bp) parts.push(bp);
        if (v.heart_rate != null) parts.push(`Bpm ${v.heart_rate}`);
        if (v.height_cm != null) parts.push(`Hgt ${cmToM(v.height_cm)}`);
        if (wk) parts.push(wk, wl);
        if (bmi) parts.push(bmi);
        if (v.temperature_c != null) parts.push(`°C ${fmt1(v.temperature_c)}`);
        if (v.head_circumference_cm != null) parts.push(`HC ${fmt1(v.head_circumference_cm)}`);
    }
    return parts.length ? `${parts.join("; ")}.` : "";
}

export function VitalsPanel({ visitId, patientRef, initial, onInsertObjective }) {
    const [form, setForm] = useState(() => Object.fromEntries(ORDER.map((k) => [k, k === "height_cm" ? cmToM(initial?.[k]) : toStr(initial?.[k])])));
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
        else if (key === "0." || key === "1.") { if (DECIMAL_OK[k] && !cur.includes(".")) setField(k, cur + key); }
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
    const derived = { weight_lb: weightLb, bmi, iwk: null, iwl: null }; // IWK/IWL: formula NOT confirmed — intentionally empty
    const prev = recent?.[0];
    const lastCtx = prev && (prev.weight_kg != null || prev.bmi != null) && (current.weight_kg != null || bmi != null) ? {
        last: [prev.weight_kg != null && `WK ${fmt1(prev.weight_kg)}`, prev.bmi != null && `BMI ${prev.bmi}`].filter(Boolean).join(" · "),
        today: [current.weight_kg != null && `WK ${fmt1(current.weight_kg)}`, bmi != null && `BMI ${bmi}`].filter(Boolean).join(" · "),
        change: prev.weight_kg != null && current.weight_kg != null ? `${current.weight_kg - prev.weight_kg >= 0 ? "+" : ""}${(current.weight_kg - prev.weight_kg).toFixed(1)} WK` : null,
    } : null;
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
                    <div className="grid grid-cols-3 gap-px shrink-0 bg-[#14532d] border border-[#14532d] rounded-sm overflow-hidden" data-testid="utility-keys">
                        {["0.", "1."].map((d) => (
                            <Key key={d} label={d} onClick={() => keypad(d)} testid={`keypad-${d === "0." ? "0dot" : "1dot"}`} tone="utility" disabled={Boolean(active && !DECIMAL_OK[active])}
                                className={`w-8 border-0 rounded-none ${active && !DECIMAL_OK[active] ? "opacity-40 cursor-not-allowed" : ""}`} />
                        ))}
                        <Key label="." onClick={() => keypad(".")} testid="keypad-dot" tone="utility" disabled={Boolean(active && !DECIMAL_OK[active])} className={`w-8 border-0 rounded-none ${active && !DECIMAL_OK[active] ? "opacity-40 cursor-not-allowed" : ""}`} />
                        <Key onClick={() => keypad("⌫")} testid="keypad-backspace" aria-label="Backspace" tone="utility" className="w-8 border-0 rounded-none"><Delete className="w-4 h-4 mx-auto" /></Key>
                        <Key onClick={() => keypad("C")} testid="keypad-clear" aria-label="Clear field" tone="utility" className="w-8 border-0 rounded-none"><Eraser className="w-3.5 h-3.5 mx-auto" /></Key>
                        <Key onClick={next} testid="keypad-next" tone="primary" className="w-8 border-0 rounded-none" aria-label="Next field"><CornerDownLeft className="w-4 h-4 mx-auto" /></Key>
                    </div>
                </div>
            </div>
            <div className="p-2">
                {/* Access vitals row: Sst Dst Bpm WK WL Hgt BMI IWK IWL °C HC — derived cells are read-only AUTO */}
                <div className="flex flex-wrap items-end gap-x-1.5 gap-y-1 text-xs" data-testid="vitals-fields">
                    {VITAL_ROW.map(({ k, label, tip, w, ro }) => (<Fragment key={k}>
                        <div className="flex flex-col gap-0.5" data-testid={`vital-cell-${k}`} data-readonly={ro ? "true" : undefined}>
                            <span className={`text-[10px] font-bold leading-none whitespace-nowrap ${ro ? "text-slate-400" : "text-slate-700"}`} title={tip}>{label}</span>
                            {ro ? (
                                <span title={tip} data-testid={`vital-${k}`} data-auto={derived[k] != null ? "true" : undefined}
                                    className={`${w} h-7 px-1.5 inline-flex items-center justify-end rounded-sm border border-dashed border-slate-300 bg-slate-50 font-mono text-sm ${derived[k] != null ? "text-visita-ribbon font-semibold" : "text-slate-300"}`}>
                                    {derived[k] ?? "—"}
                                </span>
                            ) : renderInput(k, w)}
                        </div>
                        {k === "heart_rate" && onInsertObjective && (() => { const text = vitalsToObjective(current, "bp"); return (
                            <button type="button" disabled={!text} onClick={() => onInsertObjective(text)} data-testid="quick-obj-bp" title={text ? `${text} → Objective` : "BP incomplete"}
                                className="self-end inline-flex items-center gap-0.5 h-7 px-1.5 rounded-sm border border-slate-300 bg-white text-[11px] font-semibold text-slate-700 hover:bg-visita-bg hover:border-visita-ribbon disabled:opacity-40 disabled:cursor-not-allowed">
                                <ArrowDownToLine className="w-3 h-3" /> BP
                            </button>
                        ); })()}
                    </Fragment>))}
                </div>
                {lastCtx && (
                    <div className="mt-1 text-[10px] text-slate-600 leading-tight" data-testid="vitals-last-context">
                        <span className="text-slate-400">Last:</span> {lastCtx.last} <span className="text-slate-300">·</span> <span className="text-slate-400">Today:</span> {lastCtx.today}
                        {lastCtx.change && <> <span className="text-slate-300">·</span> <span className={`font-semibold ${lastCtx.change.startsWith("+") ? "text-amber-700" : "text-emerald-700"}`}>{lastCtx.change}</span></>}
                    </div>
                )}
                {/* QUICK → OBJECTIVE: append-only documentation convenience; structured vitals stay authoritative */}
                {onInsertObjective && (
                    <div className="mt-1.5 border-t border-dashed border-slate-200 pt-1" data-testid="quick-objective">
                        <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500 leading-none mb-1">Quick to Objective</div>
                        <div className="flex gap-1">
                            {[["weight", "WK / BMI", "quick-obj-weight"], ["all", "All Vitals", "quick-obj-all"]].map(([w, lbl, tid]) => {
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
                              ["Bpm", (r) => r.heart_rate], ["WK", (r) => r.weight_kg], ["Hgt", (r) => (r.height_cm != null ? cmToM(r.height_cm) : null)], ["BMI", (r) => r.bmi], ["°C", (r) => r.temperature_c],
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
