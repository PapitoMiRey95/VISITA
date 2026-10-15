import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Stethoscope } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { toast } from "sonner";
import { formatDateTime } from "../lib/date";
import { encounterTypeLabel } from "./StartEncounter";

/* Lightweight encounter history for the selected patient (physician/admin). */
export function VisitHistory({ patientRef, refreshKey }) {
    const nav = useNavigate();
    const [rows, setRows] = useState(null);
    useEffect(() => {
        if (!patientRef) return;
        api.get(`/internal/patients/${encodeURIComponent(patientRef)}/visits`).then(({ data }) => setRows(data.visits)).catch(() => setRows([]));
    }, [patientRef, refreshKey]);
    if (!patientRef) return null;
    return (
        <div className="mt-6 pt-4 border-t border-slate-200" data-testid="visit-history">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-800 mb-2"><Stethoscope className="w-4 h-4" /> Encounters</div>
            {!rows ? <div className="text-xs text-slate-400">Loading…</div> : !rows.length ? (
                <div className="text-xs text-slate-400 italic" data-testid="visit-history-empty">No encounters recorded yet.</div>
            ) : (
                <table className="w-full text-xs">
                    <thead><tr className="text-left text-slate-500"><th className="py-1">Ref</th><th>Type</th><th>Started</th><th>Status</th><th>Last saved</th><th>Physician</th><th></th></tr></thead>
                    <tbody>
                        {rows.map((v) => (
                            <tr key={v.id} className="border-t border-slate-100" data-testid={`visit-row-${v.ref_number}`}>
                                <td className="py-1 font-semibold">{v.ref_number}</td>
                                <td>{encounterTypeLabel(v.encounter_type)}</td>
                                <td>{formatDateTime(v.started_at)}</td>
                                <td><span className="px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-800 font-bold">{v.status === "IN_PROGRESS" ? "IN PROGRESS" : v.status}</span></td>
                                <td>{v.last_saved_at ? formatDateTime(v.last_saved_at) : "—"}</td>
                                <td>{v.physician_name}</td>
                                <td className="text-right">
                                    {v.status === "IN_PROGRESS" && (
                                        <button type="button" className="text-visita-ribbon font-semibold hover:underline" data-testid={`visit-open-${v.ref_number}`}
                                            onClick={async () => { try { await api.post(`/internal/visits/${v.id}/resume`); nav(`/internal/encounter/${v.id}`); } catch (e) { toast.error(`Could not resume ${v.ref_number}: ${formatErr(e)}`); } }}>
                                            Resume
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </div>
    );
}
