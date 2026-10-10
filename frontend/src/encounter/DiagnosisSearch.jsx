import { useEffect, useRef, useState } from "react";
import { Search, Stethoscope, X } from "lucide-react";
import { api } from "../lib/api";

/* Diagnosis catalog search (tabDiagText). Search only — selection is explicit and NOT yet persisted (next phase). */
export function DiagnosisSearch({ patientRef }) {
    const [q, setQ] = useState("");
    const [items, setItems] = useState([]);
    const [sel, setSel] = useState(null);
    const timer = useRef(null);

    useEffect(() => {
        clearTimeout(timer.current);
        if (q.trim().length < 2) { setItems([]); return undefined; }
        timer.current = setTimeout(() => {
            api.get("/internal/diagnosis-catalog/search", { params: { q, patient_ref: patientRef } })
                .then(({ data }) => setItems(data.items)).catch(() => setItems([]));
        }, 200);
        return () => clearTimeout(timer.current);
    }, [q, patientRef]);

    return (
        <div className="px-2 py-1.5" data-testid="diagnosis-search">
            <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-500 mb-1">
                <Stethoscope className="w-3 h-3" /> Diagnosis <span className="normal-case font-medium text-slate-400 tracking-normal">search · Key / Text / PMHx</span>
            </div>
            <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                <input value={q} onChange={(e) => { setQ(e.target.value); }} placeholder="Search diagnosis…" data-testid="diagnosis-search-input"
                    className="w-full h-7 pl-7 pr-2 text-xs rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500" />
            </div>
            {items.length > 0 && (
                <ul className="mt-1 max-h-40 overflow-y-auto border border-slate-200 rounded-sm divide-y divide-slate-100 text-xs" data-testid="diagnosis-results">
                    {items.map((d) => (
                        <li key={d.id}>
                            <button type="button" onClick={() => { setSel(d); setQ(""); setItems([]); }} data-testid={`diagnosis-result-${d.legacy_id}`}
                                className="w-full text-left px-2 py-1 hover:bg-visita-bg leading-snug">
                                <span className="font-semibold text-slate-800">{d.text}</span>
                                {d.coded && <span className="ml-1 text-[9px] font-bold text-visita-ribbon">CODED</span>}
                                {d.sex_filter && d.sex_filter !== "ANY" && <span className="ml-1 text-[9px] font-bold text-slate-400">{d.sex_filter}</span>}
                                {d.pmhx_description && d.pmhx_description !== d.text && <div className="text-[10px] text-slate-500 truncate">{d.pmhx_description}</div>}
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            {sel && (
                <div className="mt-1 flex items-start gap-1 text-xs border border-dashed border-slate-300 rounded-sm px-2 py-1 bg-slate-50" data-testid="diagnosis-selected">
                    <span className="flex-1 leading-snug"><span className="font-semibold">{sel.text}</span>
                        <span className="block text-[10px] text-slate-500">Selected · not yet saved to this encounter (next phase)</span></span>
                    <button type="button" onClick={() => setSel(null)} aria-label="Clear selection" data-testid="diagnosis-clear" className="text-slate-400 hover:text-slate-700"><X className="w-3.5 h-3.5" /></button>
                </div>
            )}
        </div>
    );
}
