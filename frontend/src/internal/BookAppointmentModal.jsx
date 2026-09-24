import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatCombinedName } from "../lib/name";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

// Reusable slot-based appointment booking modal.
// mode="book": create a confirmed appointment from a source request.
// mode="reschedule": move an existing confirmed appointment to a new slot.
export default function BookAppointmentModal({ open, onClose, onDone, mode = "book", source, sourceType, defaultReason }) {
    const [reason, setReason] = useState(defaultReason || "");
    const [chosen, setChosen] = useState(null);
    const [busy, setBusy] = useState(false);

    const slotsQ = useQuery({
        queryKey: ["slots-book"],
        queryFn: async () => (await api.get("/availability/slots", { params: { days: 28 } })).data,
        enabled: open,
    });
    const slots = slotsQ.data?.slots || [];

    const submit = async () => {
        if (!chosen) { toast.error("Please select an available time."); return; }
        setBusy(true);
        try {
            if (mode === "book") {
                await api.post("/internal/book-appointment", {
                    source_type: sourceType, source_id: source.id, reason: reason || undefined,
                    date: chosen.date, time: chosen.time, label: chosen.label, display: chosen.display,
                });
                toast.success("Appointment booked and patient notified.");
            } else {
                await api.patch(`/internal/appointments/${source.id}`, {
                    action: "reschedule", confirmed_date: chosen.date, confirmed_time: chosen.time,
                    confirmed_display: chosen.display,
                });
                toast.success("Appointment rescheduled and patient notified.");
            }
            onDone?.();
            onClose?.();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
            <DialogContent className="max-w-md font-plex max-h-[90vh] overflow-y-auto" data-testid="book-appointment-modal">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <CalendarClock className="w-5 h-5 text-visita-green" />
                        {mode === "book" ? "Book Appointment" : "Reschedule Appointment"}
                    </DialogTitle>
                </DialogHeader>
                <div className="space-y-3 text-sm">
                    <div className="text-slate-600">
                        Patient: <b>{formatCombinedName(source?.patient_name)}</b>
                        {sourceType && mode === "book" && <> · from {sourceType} <b>{source?.ref_number}</b></>}
                    </div>
                    {mode === "book" && (
                        <div>
                            <Label className="text-xs">Appointment reason</Label>
                            <Input value={reason} onChange={(e) => setReason(e.target.value)} data-testid="book-reason" />
                        </div>
                    )}
                    <div>
                        <Label className="text-xs">Select an available time (Mon–Thu, 11:30 AM–4:30 PM)</Label>
                        {slotsQ.isLoading && <p className="text-slate-400 text-xs mt-1">Loading available times…</p>}
                        <div className="max-h-60 overflow-y-auto border border-slate-200 rounded-sm divide-y mt-1">
                            {slots.map((s, idx) => {
                                const on = chosen && chosen.date === s.date && chosen.time === s.time;
                                return (
                                    <button key={idx} data-testid={`book-slot-${idx}`} onClick={() => setChosen(s)}
                                        className={`w-full text-left px-2 py-1.5 text-sm ${on ? "bg-visita-greenLight font-semibold" : "hover:bg-slate-50"}`}>
                                        {on ? "✓ " : ""}{s.display}
                                    </button>
                                );
                            })}
                            {!slotsQ.isLoading && slots.length === 0 && <div className="px-2 py-3 text-slate-400 text-xs">No available times.</div>}
                        </div>
                    </div>
                    <Button disabled={busy || !chosen} onClick={submit} data-testid="book-confirm"
                        className="w-full bg-visita-green hover:bg-visita-greenDark text-white">
                        {mode === "book" ? "Confirm & Book Appointment" : "Confirm Reschedule"}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
