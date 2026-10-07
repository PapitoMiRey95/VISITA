import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatCombinedName } from "../lib/name";
import { formatDate } from "../lib/date";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

// Slot picker driven by the SAME availability engine as the patient portal (/availability/slots).
// mode="book": create a confirmed appointment from a source request.
// mode="reschedule": Change Time — server atomically reserves the new slot, releases the old one.
export default function BookAppointmentModal({ open, onClose, onDone, mode = "book", source, sourceType, defaultReason }) {
    const [reason, setReason] = useState(defaultReason || "");
    const [chosen, setChosen] = useState(null);
    const [day, setDay] = useState(null);
    const [busy, setBusy] = useState(false);

    const slotsQ = useQuery({
        queryKey: ["slots-book"],
        queryFn: async () => (await api.get("/availability/slots", { params: { days: 42 } })).data,
        enabled: open, staleTime: 0, refetchOnMount: "always",
    });
    const slots = slotsQ.data?.slots || [];
    const byDate = useMemo(() => {
        const m = {};
        for (const s of slots) (m[s.date] = m[s.date] || []).push(s);
        return m;
    }, [slots]);
    const dates = Object.keys(byDate).sort();
    const activeDay = day && byDate[day] ? day : dates[0];

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
                    action: "change_time", confirmed_date: chosen.date, confirmed_time: chosen.time,
                    confirmed_display: chosen.display,
                });
                toast.success("Time changed — new slot reserved, old slot released, patient notified.");
            }
            onDone?.();
            onClose?.();
        } catch (e) {
            toast.error(formatErr(e));
            if (e?.response?.status === 409) { setChosen(null); slotsQ.refetch(); }
        } finally { setBusy(false); }
    };

    const current = source?.confirmed_display || (source?.slot_date ? `${formatDate(source.slot_date)} · ${source.slot_time}` : null);

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
            <DialogContent className="max-w-lg font-plex max-h-[90vh] overflow-y-auto" data-testid="book-appointment-modal">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <CalendarClock className="w-5 h-5 text-visita-green" />
                        {mode === "book" ? "Book Appointment" : "Change Time"}
                    </DialogTitle>
                </DialogHeader>
                <div className="space-y-3 text-sm">
                    <div className="text-slate-600">
                        Patient: <b>{formatCombinedName(source?.patient_name)}</b>
                        {sourceType && mode === "book" && <> · from {sourceType} <b>{source?.ref_number}</b></>}
                        {mode !== "book" && current && <div className="text-xs text-slate-500" data-testid="change-time-current">Current: {current}</div>}
                    </div>
                    {mode === "book" && (
                        <div>
                            <Label className="text-xs">Appointment reason</Label>
                            <Input value={reason} onChange={(e) => setReason(e.target.value)} data-testid="book-reason" />
                        </div>
                    )}
                    <div>
                        <Label className="text-xs">Clinic availability (next 6 weeks) — pick ONE time</Label>
                        {slotsQ.isLoading && <p className="text-slate-400 text-xs mt-1">Loading available times…</p>}
                        {!slotsQ.isLoading && dates.length === 0 && <div className="px-2 py-3 text-slate-400 text-xs">No available times.</div>}
                        {dates.length > 0 && (
                            <div className="flex gap-2 mt-1">
                                <div className="w-40 max-h-64 overflow-y-auto border border-slate-200 rounded-sm divide-y" data-testid="book-dates">
                                    {dates.map((d) => (
                                        <button key={d} type="button" data-testid={`book-date-${d}`} onClick={() => { setDay(d); setChosen(null); }}
                                            className={`w-full text-left px-2 py-1.5 text-xs ${activeDay === d ? "bg-visita-green text-white font-semibold" : "hover:bg-slate-50"}`}>
                                            {formatDate(d)} <span className="opacity-70">({byDate[d][0].weekday.slice(0, 3)})</span>
                                        </button>
                                    ))}
                                </div>
                                <div className="flex-1 grid grid-cols-3 gap-1.5 content-start" data-testid="book-times">
                                    {(byDate[activeDay] || []).map((s, idx) => {
                                        const on = chosen && chosen.date === s.date && chosen.time === s.time;
                                        return (
                                            <button key={s.time} type="button" data-testid={`book-slot-${idx}`} onClick={() => setChosen(s)}
                                                className={`h-9 rounded-sm border text-xs font-semibold ${on ? "bg-visita-green text-white border-visita-green" : "bg-white border-slate-200 hover:border-visita-green"}`}>
                                                {s.label}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                    {chosen && <div className="text-xs text-slate-600" data-testid="book-chosen">Selected: <b>{chosen.display}</b></div>}
                    <Button disabled={busy || !chosen} onClick={submit} data-testid="book-confirm"
                        className="w-full bg-visita-green hover:bg-visita-greenDark text-white">
                        {mode === "book" ? "Confirm & Book Appointment" : "Confirm New Time"}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
