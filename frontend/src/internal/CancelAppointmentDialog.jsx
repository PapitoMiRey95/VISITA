import { useState } from "react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { formatCombinedName } from "../lib/name";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

export const CANCEL_REASONS = ["Physician unavailable", "Clinic schedule change", "Unexpected closure", "Patient requested cancellation", "Other"];

// Admin/Physician cancellation. Never deletes: appointment stays in history as CANCELLED.
// For a REQUESTED (held) request this acts as "Cancel & Notify" (decline + release slot).
export default function CancelAppointmentDialog({ appt, onClose, onDone }) {
    const isRequest = appt?.status === "requested";
    const [reason, setReason] = useState("");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);

    const run = async (freeSlot) => {
        if (!reason) { toast.error("Please select a cancellation reason."); return; }
        setBusy(true);
        try {
            const body = isRequest
                ? { action: "decline", cancel_reason: reason, staff_note: note || undefined }
                : { action: "cancel", cancel_reason: reason, free_slot: freeSlot, staff_note: note || undefined };
            await api.patch(`/internal/appointments/${appt.id}`, body);
            toast.success(isRequest ? "Request cancelled, time released and patient notified."
                : freeSlot ? "Appointment cancelled — time is available again. Patient notified."
                    : "Appointment cancelled — time kept blocked. Patient notified.");
            onDone?.(); onClose?.();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <Dialog open onOpenChange={(o) => !o && onClose?.()}>
            <DialogContent className="max-w-md font-plex" data-testid="cancel-appointment-dialog">
                <DialogHeader><DialogTitle>{isRequest ? "Cancel request & notify" : "Cancel appointment"}</DialogTitle></DialogHeader>
                <div className="space-y-3 text-sm">
                    <div className="text-slate-600">Patient: <b>{formatCombinedName(appt?.patient_name)}</b> · {appt?.ref_number}</div>
                    <div>
                        <Label className="text-xs">Reason</Label>
                        <div className="mt-1 space-y-1" data-testid="cancel-reason-list">
                            {CANCEL_REASONS.map((r) => (
                                <label key={r} className={`flex items-center gap-2 px-2 py-1.5 rounded-sm border cursor-pointer ${reason === r ? "border-visita-green bg-visita-greenLight" : "border-slate-200"}`}>
                                    <input type="radio" name="cancel-reason" checked={reason === r} onChange={() => setReason(r)} data-testid={`cancel-reason-${r.toLowerCase().replace(/ /g, "-")}`} />
                                    {r}
                                </label>
                            ))}
                        </div>
                    </div>
                    <div>
                        <Label className="text-xs">Short note to patient (optional)</Label>
                        <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} data-testid="cancel-note" />
                    </div>
                    {isRequest ? (
                        <Button disabled={busy || !reason} onClick={() => run(true)} data-testid="cancel-confirm-request"
                            className="w-full bg-red-600 hover:bg-red-700 text-white">Cancel request & notify patient</Button>
                    ) : (
                        <div className="grid grid-cols-1 gap-2">
                            <Button disabled={busy || !reason} onClick={() => run(true)} data-testid="cancel-free-slot"
                                className="w-full bg-red-600 hover:bg-red-700 text-white">A) Cancel & FREE this time</Button>
                            <Button disabled={busy || !reason} onClick={() => run(false)} data-testid="cancel-keep-blocked"
                                variant="outline" className="w-full text-red-700 border-red-300">B) Cancel & KEEP this time blocked</Button>
                            <p className="text-xs text-slate-500">The appointment stays in the calendar history in red either way; only the time's availability differs.</p>
                        </div>
                    )}
                </div>
            </DialogContent>
        </Dialog>
    );
}
