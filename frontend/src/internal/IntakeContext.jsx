import { useEffect, useState } from "react";
import { FileText, Stethoscope } from "lucide-react";
import { api } from "../lib/api";
import { formatDate } from "../lib/date";

const medLine = (m) => [m.drug, m.strength, m.form].filter(Boolean).join(" ") + (m.sig ? ` — ${m.sig}` : "");

// Read-only: last prescriptions this clinic sent for the patient (rx_transmissions, PHYSICIAN_TO_PHARMACY).
export function LastRxProvided({ patientRef }) {
    const [rows, setRows] = useState(null);
    useEffect(() => {
        if (!patientRef) return;
        api.get(`/internal/patients/${patientRef}/prescriptions`).then(({ data }) => setRows(Array.isArray(data) ? data.slice(0, 5) : [])).catch(() => setRows([]));
    }, [patientRef]);
    return (
        <div className="mt-4 pt-3 border-t border-slate-200" data-testid="intake-last-rx">
            <div className="flex items-center gap-2 mb-2 text-slate-700 font-semibold text-sm"><FileText className="w-4 h-4" /> Last Rx provided</div>
            {rows === null ? <p className="text-xs text-slate-400">Loading…</p> : rows.length === 0 ? <p className="text-xs text-slate-400">No prescriptions sent from this clinic yet.</p> : (
                <div className="space-y-2">
                    {rows.map((t) => (
                        <div key={t.id} className="border border-slate-200 rounded-sm px-2.5 py-2 text-xs" data-testid="intake-last-rx-row">
                            <div className="flex flex-wrap items-center gap-1.5 text-slate-500">
                                <span className="font-mono">{t.ref_number}</span><span>{formatDate(t.sent_at || t.created_at)}</span>
                                {t.physician_name && <span>· {t.physician_name}</span>}{t.pharmacy_name && <span>· {t.pharmacy_name}</span>}
                            </div>
                            <ul className="mt-1 space-y-0.5">
                                {(t.medications || []).map((m, i) => <li key={i} className="text-slate-800 break-words">{medLine(m)}</li>)}
                            </ul>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

// Read-only SOAP Plan history (visits.soap.plan). Authorization is the backend's: physicians + admins only; staff see a notice.
export function PlanHistory({ patientRef }) {
    const [state, setState] = useState({ entries: null, denied: false });
    useEffect(() => {
        if (!patientRef) return;
        api.get(`/internal/patients/${patientRef}/issue-plan-history`)
            .then(({ data }) => setState({ entries: (data?.entries || []).filter((e) => e.plan).slice(0, 8), denied: false }))
            .catch((err) => setState({ entries: [], denied: err?.response?.status === 403 }));
    }, [patientRef]);
    const { entries, denied } = state;
    return (
        <div className="mt-4 pt-3 border-t border-slate-200" data-testid="intake-plan-history">
            <div className="flex items-center gap-2 mb-2 text-slate-700 font-semibold text-sm"><Stethoscope className="w-4 h-4" /> Plan history (SOAP)</div>
            {entries === null ? <p className="text-xs text-slate-400">Loading…</p>
                : denied ? <p className="text-xs text-slate-400" data-testid="intake-plan-history-denied">Plan notes are visible to physicians and admins only.</p>
                : entries.length === 0 ? <p className="text-xs text-slate-400">No Plan notes recorded yet.</p> : (
                <div className="space-y-2">
                    {entries.map((e) => (
                        <div key={e.visit_id} className="border border-slate-200 rounded-sm px-2.5 py-2 text-xs" data-testid="intake-plan-row">
                            <div className="flex flex-wrap items-center gap-1.5 text-slate-500"><span>{formatDate(e.date)}</span>{e.physician_name && <span>· {e.physician_name}</span>}{e.issue && <span className="text-slate-600">· {e.issue}</span>}</div>
                            <div className="mt-0.5 text-slate-800 whitespace-pre-wrap break-words">{e.plan}</div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
