import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";

const OUTCOMES = [
    ["PRESCRIPTION_SENT_VIEN", "Prescription sent through VIen", "Only when a VIen Rx transmission exists for this request (auto-detected)."],
    ["PRESCRIPTION_VERIFIED_EXTERNAL", "Doctor prescribed/sent outside VIen — verified by clinic", "Reconciles the medications in this request with the patient's list. Adds only safe missing medications; conflicts are flagged."],
    ["APPOINTMENT_REQUIRED", "Appointment required", "The patient needs a visit before a prescription."],
    ["NO_PRESCRIPTION_ISSUED", "No prescription issued", "Closed without a prescription."],
    ["OTHER", "Other", "Add a short note."],
];
const SAFE = { ALREADY_ON_LIST: "skip", ADD_MISSING: "add", POSSIBLE_DOSE_CHANGE: "flag", SIG_DIFFERENCE: "flag", POSSIBLE_RESTART: "flag", REVIEW_REQUIRED: "flag" };

/* Structured Rx request completion. Generic "complete" never implies a VIen prescription was sent. */
export function RxCompleteDialog({ item, onClose, onDone }) {
    const [preview, setPreview] = useState(null);
    const [outcome, setOutcome] = useState(null);
    const [note, setNote] = useState("");
    const [confirm, setConfirm] = useState(false);
    const [busy, setBusy] = useState(false);
    useEffect(() => { api.get(`/internal/prescriptions/${item.id}/completion-preview`).then(({ data }) => { setPreview(data); if (data.vien_transmission) setOutcome("PRESCRIPTION_SENT_VIEN"); }).catch((e) => toast.error(formatErr(e))); }, [item.id]);
    const recon = preview?.reconciliation?.items || [];
    const submit = async () => {
        setBusy(true);
        try {
            await api.post(`/internal/prescriptions/${item.id}/complete`, {
                outcome, note, confirm_external: confirm,
                decisions: outcome === "PRESCRIPTION_VERIFIED_EXTERNAL" ? recon.map((r) => ({ med: r.parsed, classification: r.classification, decision: SAFE[r.classification], match_id: r.match?.id || null, portal_visible: true })) : null,
            });
            toast.success("Request completed."); onDone(); onClose();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const needConfirm = outcome === "PRESCRIPTION_VERIFIED_EXTERNAL" && !confirm;
    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-lg" data-testid="rx-complete-dialog">
                <DialogHeader><DialogTitle>How was this request completed?</DialogTitle><DialogDescription>{item.ref_number} · {item.patient_name}</DialogDescription></DialogHeader>
                <div className="space-y-1.5">
                    {OUTCOMES.map(([v, t, h]) => {
                        const disabled = v === "PRESCRIPTION_SENT_VIEN" && preview && !preview.vien_transmission;
                        return (
                            <label key={v} className={`flex gap-2 items-start rounded-md border p-2 text-xs ${outcome === v ? "border-[#0b2545] border-2" : "border-slate-200"} ${disabled ? "opacity-50" : "cursor-pointer"}`} data-testid={`rx-outcome-${v.toLowerCase()}`}>
                                <input type="radio" name="outcome" disabled={disabled} checked={outcome === v} onChange={() => setOutcome(v)} className="mt-0.5" />
                                <span><b>{t}</b><br /><span className="text-slate-500">{h}</span></span>
                            </label>
                        );
                    })}
                </div>
                {outcome === "PRESCRIPTION_VERIFIED_EXTERNAL" && (
                    <div className="rounded-md border border-slate-200 p-2.5 text-xs" data-testid="rx-complete-recon">
                        <div className="font-bold text-slate-700 mb-1">Reconciliation preview</div>
                        {preview && !preview.canonical_patient_id && <div className="text-amber-700">No linked patient record — the request will be completed without medication changes.</div>}
                        {recon.map((r, i) => <div key={i} className={r.classification === "ADD_MISSING" ? "text-sky-700" : r.classification === "ALREADY_ON_LIST" ? "text-emerald-700" : "text-amber-700"} data-testid={`rx-recon-${i}`}>{r.summary}</div>)}
                        {!recon.length && preview?.canonical_patient_id && <div className="text-slate-500">No medications could be read from this request.</div>}
                        <label className="mt-2 flex gap-2 text-slate-700"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} data-testid="rx-complete-confirm" /> I confirm the physician prescribed these medications outside VIen.</label>
                        <div className="text-[11px] text-slate-500 mt-1">Patient sees: “Processed by clinic — external prescription verified”. Your name is recorded as the verifier.</div>
                    </div>
                )}
                {(outcome === "OTHER" || outcome === "NO_PRESCRIPTION_ISSUED") && <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Short note (optional)" className="h-8 text-xs" data-testid="rx-complete-note" />}
                <DialogFooter><Button variant="outline" size="sm" onClick={onClose}>Cancel</Button><Button size="sm" disabled={busy || !outcome || needConfirm} onClick={submit} data-testid="rx-complete-submit">Complete request</Button></DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
