import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CreditCard, Check, X, Clock } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";

export default function HealthCardUpdates() {
    const [items, setItems] = useState(null);
    const [busy, setBusy] = useState(null);

    const load = () => api.get("/internal/health-card-updates").then(({ data }) => setItems(data)).catch((e) => toast.error(formatErr(e)));
    useEffect(() => { load(); }, []);

    const review = async (patientId, action) => {
        setBusy(`${patientId}:${action}`);
        try {
            await api.post(`/internal/patients/${patientId}/health-card/${action}`);
            toast.success(action === "approve" ? "Health Card update approved." : "Health Card update declined.");
            load();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(null); }
    };

    return (
        <div data-testid="health-card-updates-page" className="max-w-3xl">
            <div className="flex items-center gap-2 mb-1">
                <CreditCard className="w-5 h-5 text-indigo-600" />
                <h1 className="text-2xl font-bold text-slate-900">Health Card Updates</h1>
            </div>
            <p className="text-sm text-slate-500 mb-5">Caregiver-submitted Health Card updates awaiting staff review. Approving updates the authoritative patient record.</p>

            {items === null ? (
                <p className="text-slate-400 text-sm" data-testid="hcu-loading">Loading…</p>
            ) : items.length === 0 ? (
                <p className="text-slate-400 text-sm" data-testid="hcu-empty">No pending Health Card updates.</p>
            ) : (
                <div className="space-y-3">
                    {items.map((it) => (
                        <div key={it.patient_id} data-testid="hcu-item" className="bg-white rounded-xl border border-slate-200 p-4">
                            <div className="flex items-center justify-between">
                                <div>
                                    <div className="font-bold text-slate-800" data-testid="hcu-patient-name">{it.patient_name}</div>
                                    <div className="text-xs text-slate-500">PIN {it.visita_patient_id || "—"} · DOB {it.date_of_birth || "—"}</div>
                                </div>
                                <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-700 bg-amber-50 px-2 py-1 rounded-full"><Clock className="w-3 h-3" /> Pending</span>
                            </div>
                            <div className="grid grid-cols-2 gap-3 mt-3">
                                <div className="rounded-lg border border-slate-200 p-3">
                                    <p className="text-[10px] uppercase font-bold text-slate-400">Current on file</p>
                                    <div className="font-semibold text-slate-700 tracking-wide" data-testid="hcu-current">{it.current.display || "—"}</div>
                                    <div className="text-xs text-slate-500 mt-0.5">Issue {it.current.issue_date || "—"} · Expiry {it.current.expiry_date || "—"}</div>
                                </div>
                                <div className="rounded-lg border border-indigo-200 bg-indigo-50/40 p-3">
                                    <p className="text-[10px] uppercase font-bold text-indigo-500">Submitted</p>
                                    <div className="font-semibold text-indigo-900 tracking-wide" data-testid="hcu-submitted">{it.submitted.display || "—"}</div>
                                    <div className="text-xs text-indigo-700/80 mt-0.5">Issue {it.submitted.issue_date || "—"} · Expiry {it.submitted.expiry_date || "—"}</div>
                                </div>
                            </div>
                            <div className="text-xs text-slate-500 mt-2">
                                Submitted by {it.submitted.submitted_by_name || "caregiver"}{it.submitted.relationship ? ` (${it.submitted.relationship})` : ""}{it.submitted.submitted_at ? ` · ${new Date(it.submitted.submitted_at).toLocaleString()}` : ""}
                            </div>
                            <div className="flex gap-2 mt-3">
                                <Button data-testid="hcu-approve" size="sm" disabled={busy} onClick={() => review(it.patient_id, "approve")} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                                    <Check className="w-4 h-4 mr-1" /> Approve
                                </Button>
                                <Button data-testid="hcu-decline" size="sm" variant="outline" disabled={busy} onClick={() => review(it.patient_id, "reject")}>
                                    <X className="w-4 h-4 mr-1" /> Decline
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
