import { Check, X } from "lucide-react";

export const CMP_ROWS = [
    { key: "name", label: "Name" },
    { key: "dob", label: "DOB" },
    { key: "ohip", label: "OHIP number", field: "ohip_display" },
    { key: "version", label: "Version code", field: "version" },
    { key: "issue", label: "Issue date", field: "issue" },
    { key: "expiry", label: "Expiry date", field: "expiry" },
];

// Shared side-by-side patient match widget (Portal Access + Verifications).
export default function MatchComparison({ cmp, loading }) {
    if (loading && !cmp) return <div className="mt-3 text-sm text-slate-400" data-testid="match-comparison-loading">Comparing…</div>;
    if (!cmp) return null;
    const matches = CMP_ROWS.filter((r) => cmp.match[r.key]).length;
    return (
        <div className="mt-3 border border-slate-200 rounded-xl overflow-hidden" data-testid="match-comparison">
            <div className="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-slate-200">
                <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Patient match check</span>
                <span data-testid="match-score" className={`text-xs font-bold ${matches === CMP_ROWS.length ? "text-emerald-600" : "text-amber-600"}`}>{matches}/{CMP_ROWS.length} fields match</span>
            </div>
            <div className="grid grid-cols-[88px_1fr_1fr] text-xs">
                <div className="px-3 py-1.5 font-semibold text-slate-400 bg-slate-50/50"></div>
                <div className="px-3 py-1.5 font-semibold text-slate-500 bg-slate-50/50 border-l border-slate-100">Submitted</div>
                <div className="px-3 py-1.5 font-semibold text-slate-500 bg-slate-50/50 border-l border-slate-100">Canonical</div>
                {CMP_ROWS.map((r) => {
                    const ok = cmp.match[r.key];
                    const f = r.field || r.key;
                    return (
                        <div key={r.key} className="contents" data-testid={`cmp-row-${r.key}`}>
                            <div className="px-3 py-1.5 text-slate-500 border-t border-slate-100">{r.label}</div>
                            <div className={`px-3 py-1.5 border-t border-l border-slate-100 ${ok ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800"}`}>
                                {cmp.submitted[f] || "—"}
                            </div>
                            <div className={`px-3 py-1.5 border-t border-l border-slate-100 flex items-center justify-between gap-1 ${ok ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800"}`}>
                                <span>{cmp.canonical[f] || "—"}</span>
                                {ok ? <Check className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" /> : <X className="w-3.5 h-3.5 text-rose-500 flex-shrink-0" />}
                            </div>
                        </div>
                    );
                })}
            </div>
            <p className="px-3 py-2 text-[11px] text-slate-400 border-t border-slate-100">Review and confirm the patient yourself — matching fields do not auto-approve. OHIP numbers are compared securely and shown masked.</p>
        </div>
    );
}
