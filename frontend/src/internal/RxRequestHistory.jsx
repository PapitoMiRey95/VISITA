import { useEffect, useState } from "react";
import { History, RotateCw, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "../lib/api";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";

const STATUS_LABEL = { received: "Received", under_review: "Under review", waiting_physician: "Waiting physician", approved_process_visita: "Approved", prescription_sent: "Prescription sent", appointment_booked: "Appointment booked", completed: "Completed", declined: "Declined" };
const TONE = { approved_process_visita: "bg-emerald-100 text-emerald-800", prescription_sent: "bg-emerald-100 text-emerald-800", completed: "bg-slate-200 text-slate-700", declined: "bg-red-100 text-red-700" };
const medsOf = (r) => (r.medications_structured || []).length ? r.medications_structured.map((m) => [m.drug, m.strength].filter(Boolean).join(" ")) : (r.medications || []).filter(Boolean);

// Read-only history of this patient's Rx requests with a one-click "Repeat" that prefills the intake form.
export function RxRequestHistory({ directoryId, patientId, onRepeat }) {
    const [rows, setRows] = useState(null);
    const [open, setOpen] = useState(true);
    useEffect(() => {
        if (!directoryId && !patientId) return;
        api.get("/internal/prescriptions/history", { params: { directory_id: directoryId || undefined, patient_id: patientId || undefined } })
            .then(({ data }) => setRows(data || [])).catch(() => setRows([]));
    }, [directoryId, patientId]);
    if (!rows || rows.length === 0) return null;
    return (
        <div className="border border-slate-300 bg-slate-50 rounded-sm" data-testid="intake-rx-history">
            <button type="button" onClick={() => setOpen((o) => !o)} className="w-full flex items-center justify-between px-2.5 py-2 text-xs font-semibold text-slate-700" data-testid="intake-rx-history-toggle">
                <span className="flex items-center gap-1.5"><History className="w-3.5 h-3.5" /> Previous Rx requests ({rows.length})</span>
                {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            {open && (
                <div className="divide-y divide-slate-200 border-t border-slate-200 max-h-56 overflow-y-auto">
                    {rows.map((r) => (
                        <div key={r.id} className="px-2.5 py-1.5 flex items-start gap-2 text-xs" data-testid="intake-rx-history-row">
                            <div className="flex-1 min-w-0">
                                <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="font-mono text-slate-500">{r.ref_number}</span>
                                    <span className="text-slate-400">{formatDate(r.created_at)}</span>
                                    <span className={`px-1.5 py-0.5 rounded-sm text-[10px] font-bold ${TONE[r.internal_status] || "bg-amber-100 text-amber-800"}`}>{STATUS_LABEL[r.internal_status] || r.internal_status}</span>
                                    {r.linked_transmission_ref && <span className="text-[10px] text-emerald-700 font-semibold">{r.linked_transmission_ref}</span>}
                                </div>
                                <div className="text-slate-800 font-medium truncate" title={medsOf(r).join("; ")}>{medsOf(r).join(" · ") || r.medication_name || "—"}</div>
                                <div className="text-slate-500">{[r.pharmacy, r.duration_qty, r.delivery_method === "pickup" ? "Pick up" : r.delivery_method === "pharmacy" ? "Delivery" : null].filter(Boolean).join(" · ")}</div>
                            </div>
                            <Button type="button" size="sm" variant="outline" data-testid="intake-rx-history-repeat" onClick={() => onRepeat(r)}
                                className="h-7 px-2 text-xs border-visita-green text-visita-greenDark hover:bg-visita-greenLight shrink-0" title="Prefill this request again">
                                <RotateCw className="w-3 h-3 mr-1" /> Repeat
                            </Button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
