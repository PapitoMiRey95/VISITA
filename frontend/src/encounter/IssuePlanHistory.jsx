import { useEffect, useRef, useState } from "react";
import { Search, History } from "lucide-react";
import { api } from "../lib/api";
import { formatDate } from "../lib/date";
import { PreviousEncounterDialog } from "./PreviousEncounters";

/* Left-bottom READ-ONLY Issue (Assessment) / Plan history with fast keyword search.
   Clicking an entry opens the historical visit read-only; never touches the current note. */
export function IssuePlanHistory({ patientRef, currentVisitId }) {
    const [q, setQ] = useState("");
    const [rows, setRows] = useState(null);
    const [open, setOpen] = useState(null);
    const timer = useRef(null);
    useEffect(() => {
        if (!patientRef) return undefined;
        clearTimeout(timer.current);
        timer.current = setTimeout(() => {
            api.get(`/internal/patients/${encodeURIComponent(patientRef)}/issue-plan-history`, { params: { search: q, exclude: currentVisitId } })
                .then(({ data }) => setRows(data.entries)).catch(() => setRows([]));
        }, 250);
        return () => clearTimeout(timer.current);
    }, [patientRef, currentVisitId, q]);
    return (
        <section className="bg-white border border-slate-300 rounded-sm flex flex-col min-h-0 h-full" data-testid="issue-plan-history">
            <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                <History className="w-3.5 h-3.5" /> Issue / Plan history
                {rows && <span className="text-slate-400 normal-case font-medium">{rows.length}</span>}
                <div className="relative ml-auto w-64">
                    <Search className="absolute left-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-400" />
                    <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search previous Issue / Plan…" data-testid="issue-plan-search"
                        className="w-full h-6 pl-6 pr-2 text-[11px] font-normal normal-case tracking-normal rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-visita-ribbon" />
                </div>
            </div>
            <div className="overflow-y-auto min-h-0 flex-1 text-xs" data-testid="issue-plan-rows">
                {!rows ? <div className="px-2 py-1.5 text-slate-400">Loading…</div> : !rows.length ? (
                    <div className="px-2 py-1.5 text-slate-400 italic" data-testid="issue-plan-empty">{q ? "No matching Issue / Plan entries." : "No previous Issue / Plan entries for this patient."}</div>
                ) : rows.map((r) => (
                    <button key={r.visit_id} type="button" onClick={() => setOpen(r.visit_id)} data-testid={`issue-plan-row-${r.ref_number}`}
                        className="w-full grid grid-cols-[2.2rem_1fr_auto] gap-x-2 gap-y-0.5 px-2 py-1.5 text-left border-b last:border-0 border-slate-100 hover:bg-visita-bg">
                        <span className="text-[10px] font-bold text-slate-500 pt-px">ISS:</span>
                        <span className="font-semibold text-slate-900 leading-snug line-clamp-2">{r.issue || <span className="text-slate-400 italic font-normal">—</span>}</span>
                        <span className="row-span-2 text-[11px] font-semibold text-slate-600 whitespace-nowrap pl-2 border-l border-slate-200" data-testid="issue-plan-date">{formatDate(r.date)}</span>
                        <span className="text-[10px] font-bold text-slate-500 pt-px">PLN:</span>
                        <span className="text-slate-800 leading-snug line-clamp-2">{r.plan || <span className="text-slate-400 italic">—</span>}</span>
                    </button>
                ))}
            </div>
            <PreviousEncounterDialog visitId={open} onClose={() => setOpen(null)} />
        </section>
    );
}
