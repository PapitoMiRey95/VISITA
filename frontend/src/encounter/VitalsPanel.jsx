import { useEffect, useRef, useState } from "react";
import { HeartPulse } from "lucide-react";
import { api, formatErr } from "../lib/api";

export const VITAL_FIELDS = [
    { k: "systolic_bp", label: "BP", unit: "mmHg", step: "1", w: "w-14", pair: "diastolic_bp" },
    { k: "heart_rate", label: "HR", unit: "bpm", step: "1", w: "w-14" },
    { k: "temperature_c", label: "Temp", unit: "°C", step: "0.1", w: "w-16" },
    { k: "weight_kg", label: "Wt", unit: "kg", step: "0.1", w: "w-16" },
    { k: "height_cm", label: "Ht", unit: "cm", step: "0.1", w: "w-16" },
];
const KEYS = ["systolic_bp", "diastolic_bp", "heart_rate", "temperature_c", "weight_kg", "height_cm"];
const toStr = (v) => (v === null || v === undefined ? "" : String(v));

/* Compact structured vitals with debounced server autosave (same contract as SOAP). */
export function VitalsPanel({ visitId, initial }) {
    const [form, setForm] = useState(() => Object.fromEntries(KEYS.map((k) => [k, toStr(initial?.[k])])));
    const [bmi, setBmi] = useState(initial?.bmi ?? null);
    const [state, setState] = useState("idle");
    const [err, setErr] = useState("");
    const saved = useRef({ ...form });
    const timer = useRef(null);
    const formRef = useRef(form);
    formRef.current = form;

    const save = async () => {
        const cur = formRef.current;
        const patch = {};
        KEYS.forEach((k) => {
            if (cur[k] !== saved.current[k]) patch[k] = cur[k] === "" ? null : Number(cur[k]);
        });
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
    const onChange = (k, v) => {
        setForm((f) => ({ ...f, [k]: v }));
        setState("dirty");
        clearTimeout(timer.current);
        timer.current = setTimeout(save, 1500);
    };
    const onBlur = () => { clearTimeout(timer.current); save(); };
    useEffect(() => () => clearTimeout(timer.current), []);

    const renderInput = (k, step, w) => (
        <input type="number" inputMode="decimal" step={step} value={form[k]} onChange={(e) => onChange(k, e.target.value)} onBlur={onBlur}
            data-testid={`vital-${k}`} aria-label={k}
            className={`${w} h-7 px-1.5 text-sm text-right rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-visita-ribbon [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none`} />
    );
    const stateText = { idle: "", dirty: "…", saving: "Saving…", saved: "Saved", failed: "Save failed" }[state];
    return (
        <section className="bg-white border border-slate-300 rounded-sm" data-testid="vitals-panel">
            <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                <HeartPulse className="w-3.5 h-3.5" /> Vitals
                <span className={`ml-auto normal-case font-medium text-[10px] ${state === "failed" ? "text-red-700" : state === "saved" ? "text-emerald-700" : "text-slate-400"}`} data-testid="vitals-state" data-state={state}>{stateText}</span>
            </div>
            <div className="p-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 items-center text-xs">
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
            {err && <div className="px-2 pb-1.5 text-[11px] text-red-700" data-testid="vitals-error">{err}</div>}
        </section>
    );
}
