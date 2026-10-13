import { useEffect, useState } from "react";
import { BarChart3 } from "lucide-react";
import { api } from "../lib/api";
import { formatDate } from "../lib/date";

/* Longitudinal METRICS instrument (backend-aggregated). Sits directly above VITALS — TODAY. Read-only. */
const COLS = [["recent", "Recent", "RECENT — most recent valid observation"], ["avg_3mo", "3 Mo", "3 MO AVG — mean of valid observations, rolling last 3 months"],
    ["avg_12mo", "12 Mo", "12 MO AVG — mean of valid observations, rolling last 12 months"], ["avg_global", "Global", "GLOBAL AVG — mean of all valid observations"]];
const fmt = (v) => (v === null || v === undefined ? "—" : Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100));

export function MetricsGrid({ patientRef, refreshKey }) {
    const [data, setData] = useState(null);
    useEffect(() => {
        if (!patientRef) return;
        api.get(`/internal/patients/${encodeURIComponent(patientRef)}/metrics-summary`).then(({ data }) => setData(data)).catch(() => setData({ rows: [] }));
    }, [patientRef, refreshKey]);
    return (
        <section className="bg-white border border-slate-300 rounded-sm" data-testid="metrics-grid">
            <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                <BarChart3 className="w-3.5 h-3.5" /> Metrics
                {data && <span className="ml-auto normal-case font-medium text-[10px] text-slate-400" title={`Daily-deduplicated vitals observations · 3 mo from ${data.window_3mo_from} · 12 mo from ${data.window_12mo_from}`}>{data.observation_days ?? 0} obs. days</span>}
            </div>
            <table className="w-full text-[11px] tabular-nums leading-tight" data-testid="metrics-table">
                <thead>
                    <tr className="text-[9px] uppercase tracking-wide text-slate-500">
                        <th className="text-left font-bold pl-2 py-0.5" title="Metric">Metrics</th>
                        {COLS.map(([k, short, tip]) => <th key={k} className="text-right font-bold pr-2 py-0.5 whitespace-nowrap" title={tip}>{short}</th>)}
                    </tr>
                </thead>
                <tbody>
                    {!data ? <tr><td colSpan={5} className="px-2 py-1 text-slate-400">Loading…</td></tr> : data.rows.map((r) => (
                        <tr key={r.key} className={`border-t border-slate-100 ${r.status === "PENDING" ? "text-slate-400" : "text-slate-800"}`} data-testid={`metric-row-${r.label.replace("/", "_")}`} data-status={r.status}>
                            <td className="pl-2 py-px font-semibold whitespace-nowrap" title={r.tooltip + (r.status === "PENDING" ? " — no structured source yet" : "")}>{r.label}</td>
                            {COLS.map(([k]) => (
                                <td key={k} className="text-right pr-2 py-px" title={k === "recent" && r.recent_at ? `Observed ${formatDate(r.recent_at.slice(0, 10))}` : undefined}>{fmt(r[k])}</td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </section>
    );
}
