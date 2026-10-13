import { Fragment, useEffect, useRef, useState } from "react";
import { HeartPulse, Delete, CornerDownLeft, Eraser, ArrowDownToLine, Activity, Ruler, Weight, Gauge, Target, Thermometer, CircleDot, Triangle } from "lucide-react";
import { api, formatErr } from "../lib/api";

/* Dr. Aguayo Access vitals row — EXACT visible labels/order. Editable = physician-measured; ro = derived automatically. */
export const VITAL_ROW = [
    { k: "systolic_bp", label: "Sst", tip: "Systolic", w: "w-11", Icon: Activity },
    { k: "diastolic_bp", label: "Dst", tip: "Diastolic", w: "w-11", Icon: Activity },
    { k: "heart_rate", label: "Bpm", tip: "Heart rate", w: "w-11", Icon: HeartPulse },
    { k: "height_cm", label: "Hgt", tip: "Height (m)", w: "w-12", Icon: Ruler },
    { k: "weight_kg", label: "WK", tip: "Weight kilos", w: "w-12", Icon: Weight },
    { k: "weight_lb", label: "WL", tip: "Weight pounds (auto)", w: "w-14", ro: true, Icon: Weight },
    { k: "bmi", label: "BMI", tip: "Body mass index (auto)", w: "w-12", ro: true, Icon: Gauge, breakBefore: true },
    { k: "iwk", label: "IWK", tip: "Ideal weight kilos = 24 × Hgt² (auto)", w: "w-14", ro: true, Icon: Target },
    { k: "iwl", label: "IWL", tip: "Ideal weight pounds = IWK × 2.20462 (auto)", w: "w-14", ro: true, Icon: Target },
    { k: "temperature_c", label: "°C", tip: "Temperature", w: "w-12", Icon: Thermometer },
    { k: "head_circumference_cm", label: "HC", tip: "Head circumference (cm)", w: "w-12", Icon: CircleDot },
    { k: "length_cm", label: "Lgt", tip: "Length (cm) — pediatric", w: "w-12", Icon: Ruler },
];
/* Editable navigation only — Next/Enter skips WL/BMI/IWK/IWL: Sst → Dst → Bpm → Hgt → WK → °C → HC */
const ORDER = ["systolic_bp", "diastolic_bp", "heart_rate", "height_cm", "weight_kg", "temperature_c", "head_circumference_cm", "length_cm"];
const TARGET_LABEL = Object.fromEntries(VITAL_ROW.map((f) => [f.k, f.label]));
const DECIMAL_OK = { temperature_c: true, weight_kg: true, height_cm: true, head_circumference_cm: true, length_cm: true };
const toStr = (v) => (v === null || v === undefined ? "" : String(v));
const cmToM = (cm) => (cm === null || cm === undefined ? "" : (Number(cm) / 100).toFixed(2));
/* Hgt is entered in METRES. Guard: a cm-style value (>= 20, e.g. 176) is treated as cm -> 1.76, never 176 -> 17600 cm. */
const normHgtM = (m) => { const n = Number(m); return Number.isFinite(n) && n >= 20 ? (n / 100).toFixed(2) : m; };
const mToCm = (m) => (m === "" ? null : Math.round(Number(normHgtM(m)) * 1000) / 10);
const kgToLb = (kg) => (kg ? Math.round(kg * 2.20462 * 100) / 100 : null);  // WL = WK × 2.20462
const idealKg = (height_cm) => (height_cm ? Math.round(24 * (height_cm / 100) ** 2 * 100) / 100 : null);  // IWK = 24 × Hgt(m)²
const fmt1 = (n) => (n === null || n === undefined ? null : Number(n).toFixed(1).replace(/\.0$/, ""));

/* Access Dimensions → Objective. CURRENT structured values only — nothing fabricated, missing values omitted.
   bp  → "Sst: 170; Dst: 75;"
   all → "Sst: 170; Dst: 75; bpm: 62; Hgt: 168; Wgt Kg: 78; Wgt Lb: 171.96; Id W Kg: 67.74; Id W Lb: 149.34;"
   Hgt in Objective is Access-style cm (168) even though the UI entry is metres (1.68). BMI intentionally NOT included. */
export function vitalsToObjective(v, which) {
    const parts = [];
    const push = (label, val) => { if (val !== null && val !== undefined && val !== "" && !Number.isNaN(val)) parts.push(`${label}: ${val};`); };
    const bpComplete = v.systolic_bp != null && v.diastolic_bp != null;
    if (which === "bp") {
        if (!bpComplete) return "";
        push("Sst", v.systolic_bp); push("Dst", v.diastolic_bp);
    } else {
        if (bpComplete) { push("Sst", v.systolic_bp); push("Dst", v.diastolic_bp); }
        push("bpm", v.heart_rate);
        push("Hgt", v.height_cm);
        push("Wgt Kg", v.weight_kg); push("Wgt Lb", kgToLb(v.weight_kg));
        const iwk = idealKg(v.height_cm);
        push("Id W Kg", iwk); push("Id W Lb", iwk != null ? kgToLb(iwk) : null);
    }
    return parts.join(" ");
}

export function VitalsPanel({ visitId, patientRef, initial, onInsertObjective, onSaved }) {
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
        let cur = formRef.current;
        const patch = {};
        if (cur.height_cm !== "" && normHgtM(cur.height_cm) !== cur.height_cm) { cur = { ...cur, height_cm: normHgtM(cur.height_cm) }; formRef.current = cur; setForm(cur); }
        ORDER.forEach((k) => { if (cur[k] !== saved.current[k]) patch[k] = cur[k] === "" ? null : k === "height_cm" ? mToCm(cur[k]) : Number(cur[k]); });
        if (!Object.keys(patch).length) return;
        if (Object.values(patch).some((v) => v !== null && Number.isNaN(v))) { setState("failed"); setErr("Enter numbers only."); return; }
        setState("saving"); setErr("");
        try {
            const { data } = await api.patch(`/internal/visits/${visitId}/vitals`, patch);
            Object.keys(patch).forEach((k) => { saved.current[k] = cur[k]; });
            setBmi(data.vitals.bmi);
            onSaved?.(); setState("saved");
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
    const iwk = idealKg(current.height_cm);
    const derived = { weight_lb: weightLb, bmi, iwk, iwl: iwk != null ? kgToLb(iwk) : null }; // Access VBA: BMI=WK/Hgt², IWK=24×Hgt², ×2.20462
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
                <div className="flex flex-wrap items-end gap-x-1 gap-y-1 text-xs" data-testid="vitals-fields">
                    {VITAL_ROW.map(({ k, label, tip, w, ro, Icon, breakBefore }) => (<Fragment key={k}>
                        {breakBefore && <div className="basis-full h-0" aria-hidden="true" />}
                        <div className="flex flex-col gap-0.5" data-testid={`vital-cell-${k}`} data-readonly={ro ? "true" : undefined}>
                            <span className={`inline-flex items-center gap-0.5 text-[10px] font-bold leading-none whitespace-nowrap ${ro ? "text-slate-400" : "text-slate-700"}`} title={tip}>
                                <Icon className={`w-3 h-3 ${ro ? "text-slate-300" : "text-[#15803d]"}`} />{label}
                            </span>
                            {ro ? (
                                <span title={tip} data-testid={`vital-${k}`} data-auto={derived[k] != null ? "true" : undefined}
                                    className={`${w} h-7 px-1.5 inline-flex items-center justify-end rounded-sm border border-dashed border-slate-300 bg-slate-50 font-mono text-sm ${derived[k] != null ? "text-visita-ribbon font-semibold" : "text-slate-300"}`}>
                                    {derived[k] ?? "—"}
                                </span>
                            ) : renderInput(k, w)}
                        </div>
                        {k === "heart_rate" && onInsertObjective && (() => { const text = vitalsToObjective(current, "bp"); return (
                            <button type="button" disabled={!text} onClick={() => onInsertObjective(text)} data-testid="quick-obj-bp" title={text ? `${text} → Objective` : "BP incomplete"}
                                className="self-end inline-flex items-center gap-0.5 h-7 px-1.5 rounded-sm border border-[#14532d] bg-[#15803d] text-[11px] font-bold text-white hover:bg-[#16a34a] active:bg-[#166534] disabled:opacity-40 disabled:cursor-not-allowed">
                                <ArrowDownToLine className="w-3 h-3" /> BP
                            </button>
                        ); })()}
                        {k === "length_cm" && onInsertObjective && (() => { const text = vitalsToObjective(current, "all"); return (
                            <button type="button" disabled={!text} onClick={() => onInsertObjective(text)} data-testid="quick-obj-dimensions" aria-label="Send dimensions to Objective"
                                title={text ? `Send dimensions to Objective\n${text}` : "No values recorded yet"}
                                className="self-end inline-flex items-center gap-0.5 h-7 px-1.5 rounded-sm border border-[#14532d] bg-[#15803d] text-[11px] font-bold text-white hover:bg-[#16a34a] active:bg-[#166534] disabled:opacity-40 disabled:cursor-not-allowed">
                                <ArrowDownToLine className="w-3 h-3" /><Triangle className="w-3 h-3" />
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
            </div>
            {err && <div className="px-2 pb-1.5 text-[11px] text-red-700" data-testid="vitals-error">{err}</div>}
        </section>
    );
}
