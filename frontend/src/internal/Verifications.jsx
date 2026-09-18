import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { UserCheck, UserX } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

const TYPE = { ohip: "OHIP", private: "Private / Uninsured", tourist: "Tourist / Visitor" };

const REVIEW = {
    ACTIVE_MATCH: ["Active match — verify & link", "bg-emerald-100 text-emerald-700"],
    AMBIGUOUS_MATCH: ["Ambiguous match — confirm identity", "bg-amber-100 text-amber-700"],
    UNMATCHED_CURRENT_PATIENT: ["Unmatched — staff review required", "bg-slate-100 text-slate-600"],
};

export default function Verifications() {
    const invalidate = useInvalidate();
    const [visitaIds, setVisitaIds] = useState({});
    const list = useQuery({ queryKey: ["queue", "/internal/verifications"], queryFn: async () => (await api.get("/internal/verifications")).data });
    const items = list.data || [];

    const decide = async (id, decision) => {
        try {
            await api.post(`/internal/verifications/${id}`, { decision, visita_patient_id: visitaIds[id] || undefined });
            toast.success(decision === "verified" ? "Patient verified." : "Patient rejected.");
            invalidate(); list.refetch();
        } catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="animate-fade-in max-w-4xl">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Patient Verifications</h1>
            <p className="text-sm text-slate-500 mb-4">Manually verify new portal accounts and match them to VISITA patient records.</p>

            <div className="space-y-2">
                {items.length === 0 && <p className="text-slate-400 text-sm">No pending verifications.</p>}
                {items.map((p) => (
                    <div key={p.id} data-testid="verification-item" className="bg-white border border-slate-300 rounded-sm p-4">
                        <div className="flex items-start justify-between gap-3 flex-wrap">
                            <div className="text-sm space-y-0.5">
                                {p.review_queue && REVIEW[p.review_queue] && (
                                    <span data-testid="verification-review-badge" className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold mb-1 ${REVIEW[p.review_queue][1]}`}>
                                        {REVIEW[p.review_queue][0]}
                                    </span>
                                )}
                                <div className="font-bold text-slate-800 text-base">{p.last_name}, {p.first_name}</div>
                                <div className="text-slate-600">DOB: {p.date_of_birth} · {TYPE[p.patient_type] || p.patient_type}</div>
                                <div className="text-slate-600">Phone: {p.phone} · Email: {p.email}</div>
                                {p.health_card_masked && <div className="text-slate-600">Health Card: {p.health_card_masked}</div>}
                                {p.province && <div className="text-slate-600">Province: {p.province}</div>}
                                {p.country && <div className="text-slate-600">Country: {p.country}</div>}
                                {p.extra_info && <div className="text-slate-600">Note: {p.extra_info}</div>}

                                {(p.directory_match?.candidates || []).length > 0 && (
                                    <div className="mt-2 border-t border-slate-200 pt-1.5">
                                        <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">
                                            Suggested VISITA record{(p.directory_match.candidates.length > 1) ? "s" : ""} · {p.directory_match.strength} match
                                        </div>
                                        {p.directory_match.candidates.map((c) => (
                                            <div key={c.id} data-testid="verification-candidate" className="text-xs text-slate-600 bg-emerald-50 rounded-sm px-2 py-1 mb-1">
                                                {c.last_name}, {c.first_name} · DOB {c.date_of_birth} · HC {c.health_card_masked || "—"}
                                                {c.visita_patient_id ? ` · VISITA #${c.visita_patient_id}` : ""} · {c.city || ""} {c.province || ""}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                            <div className="flex flex-col gap-2 items-end">
                                <div>
                                    <Label className="text-xs">VISITA Patient ID (optional)</Label>
                                    <Input className="h-8 w-44" value={visitaIds[p.id] || ""} onChange={(e) => setVisitaIds({ ...visitaIds, [p.id]: e.target.value })} data-testid="visita-id-input" />
                                </div>
                                <div className="flex gap-2">
                                    <Button size="sm" onClick={() => decide(p.id, "verified")} data-testid="verify-approve" className="bg-visita-green hover:bg-visita-greenDark text-white"><UserCheck className="w-4 h-4 mr-1" /> Verify</Button>
                                    <Button size="sm" variant="outline" onClick={() => decide(p.id, "rejected")} data-testid="verify-reject" className="text-red-600 border-red-200"><UserX className="w-4 h-4 mr-1" /> Reject</Button>
                                </div>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
