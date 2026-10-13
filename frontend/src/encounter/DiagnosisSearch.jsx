import { useEffect, useRef, useState } from "react";
import { Search, Stethoscope, X, History } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";

/* Phase 2A4.1 — Diagnosis (tabDiagCode catalog). Selection is EXPLICIT and stored structurally on the Visit
   (visits.diagnoses[], one primary for now). Never writes SOAP. Previous-for-this-patient is a shortcut, never auto-assigned. */
export function DiagnosisSearch({ visitId, initial }) {
    const [q, setQ] = useState("");
    const [items, setItems] = useState([]);
    const [previous, setPrevious] = useState([]);
    const [open, setOpen] = useState(false);
    const [sel, setSel] = useState(initial?.[0] || null);
    const [err, setErr] = useState("");
    const timer = useRef(null);
    const wrap = useRef(null);

    useEffect(() => { setSel(initial?.[0] || null); }, [initial]);
    useEffect(() => {
        if (!visitId) { setPrevious([]); return; }
        api.get(`/internal/visits/${visitId}/diagnoses/previous`).then(({ data }) => setPrevious(data.items)).catch(() => setPrevious([]));
    }, [visitId]);
    useEffect(() => {
        clearTimeout(timer.current);
        if (!q.trim()) { setItems([]); return undefined; }
        timer.current = setTimeout(() => {
            api.get("/internal/diagnosis-catalog/search", { params: { q } }).then(({ data }) => setItems(data.items)).catch(() => setItems([]));
        }, 180);
        return () => clearTimeout(timer.current);
    }, [q]);
    useEffect(() => {
        const onDoc = (e) => { if (wrap.current && !wrap.current.contains(e.target)) setOpen(false); };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, []);

    const select = async (catalogId, source) => {
        if (!visitId) return;
        setErr("");
        try {
            const { data } = await api.put(`/internal/visits/${visitId}/diagnoses/primary`, { catalog_id: catalogId, source });
            setSel(data.diagnoses[0] || null); setQ(""); setItems([]); setOpen(false);
        } catch (e) { setErr(formatErr(e)); }
    };
    const clear = async () => {
        setErr("");
        try { await api.delete(`/internal/visits/${visitId}/diagnoses/primary`); setSel(null); } catch (e) { setErr(formatErr(e)); }
    };

    const Row = ({ d, source, meta, testid }) => (
        <li>
            <button type="button" onClick={() => select(d.catalog_id || d.id, source)} data-testid={testid}
                className="w-full text-left px-2 py-1 hover:bg-visita-bg leading-snug flex items-baseline gap-2">
                <span className="flex-1 font-semibold text-slate-800">{d.diagnosis_text}</span>
                <span className="shrink-0 text-[10px] text-slate-500 whitespace-nowrap">{d.diagnosis_code}{meta ? ` · ${meta}` : ""}</span>
            </button>
        </li>
    );
    const showPrev = open && !q.trim() && previous.length > 0;
    const showAll = q.trim().length > 0;

    return (
        <div className="px-2 py-1.5" data-testid="diagnosis-search" ref={wrap}>
            <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-500 mb-1">
                <Stethoscope className="w-3 h-3" /> Diagnosis <span className="normal-case font-medium text-slate-400 tracking-normal">search · text / code</span>
            </div>
            {sel ? (
                <div className="flex items-start gap-1 text-xs border border-[#15803d] rounded-sm px-2 py-1 bg-emerald-50" data-testid="diagnosis-selected">
                    <span className="flex-1 leading-snug"><span className="font-semibold text-slate-900" data-testid="diagnosis-selected-text">{sel.diagnosis_text}</span>
                        <span className="block text-[10px] text-slate-600" data-testid="diagnosis-selected-code">Code {sel.diagnosis_code || "—"}</span></span>
                    <button type="button" onClick={() => { setSel(null); setOpen(true); }} data-testid="diagnosis-change" className="text-[10px] font-bold text-visita-ribbon hover:underline">Change</button>
                    <button type="button" onClick={clear} aria-label="Clear diagnosis" data-testid="diagnosis-clear" className="text-slate-400 hover:text-red-700"><X className="w-3.5 h-3.5" /></button>
                </div>
            ) : (
                <div className="relative">
                    <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input value={q} disabled={!visitId} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} placeholder="Search diagnosis…" data-testid="diagnosis-search-input"
                        className="w-full h-7 pl-7 pr-2 text-xs rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:bg-slate-50" />
                </div>
            )}
            {!sel && (showPrev || showAll) && (
                <div className="mt-1 max-h-48 overflow-y-auto border border-slate-200 rounded-sm text-xs" data-testid="diagnosis-dropdown">
                    {showPrev && (<>
                        <div className="px-2 py-0.5 bg-slate-100 text-[9px] font-bold uppercase tracking-wide text-slate-500 flex items-center gap-1"><History className="w-3 h-3" /> Previous for this patient</div>
                        <ul className="divide-y divide-slate-100" data-testid="diagnosis-previous">
                            {previous.map((d) => <Row key={`p-${d.catalog_id}`} d={d} source="PATIENT_HISTORY" meta={`Last used ${formatDate(d.last_used_at)}`} testid={`diagnosis-previous-${d.catalog_id}`} />)}
                        </ul>
                    </>)}
                    {showAll && (<>
                        <div className="px-2 py-0.5 bg-slate-100 text-[9px] font-bold uppercase tracking-wide text-slate-500">All diagnoses</div>
                        {items.length ? (
                            <ul className="divide-y divide-slate-100" data-testid="diagnosis-results">
                                {items.map((d) => <Row key={d.id} d={d} source="CATALOG" testid={`diagnosis-result-${d.legacy_id_raw}`} />)}
                            </ul>
                        ) : <div className="px-2 py-1 text-[10px] text-slate-400 italic" data-testid="diagnosis-no-results">No matching diagnosis.</div>}
                    </>)}
                </div>
            )}
            {err && <div className="mt-1 text-[10px] text-red-700" data-testid="diagnosis-error">{err}</div>}
        </div>
    );
}
