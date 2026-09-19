import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { CalendarClock, CheckCircle2, AlertTriangle, Phone, X, Clock, CalendarDays } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { Calendar } from "../components/ui/calendar";
import { formatDate } from "../lib/date";

const isoOf = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const dateFromIso = (s) => {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
};

export default function PortalAppointments() {
    const { overview, refetch } = usePortal();
    const nav = useNavigate();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const hasFee = !!p?.has_outstanding_fee;
    const list = overview.data?.appointments || [];

    const slotsQ = useQuery({
        queryKey: ["slots"],
        queryFn: async () => (await api.get("/availability/slots", { params: { days: 60 } })).data,
        enabled: verified,
    });
    const slots = slotsQ.data?.slots || [];

    // Group available slots by date -> only these dates are selectable.
    const { byDate, availableDates, minDate, maxDate } = useMemo(() => {
        const map = {};
        for (const s of slots) {
            (map[s.date] = map[s.date] || []).push(s);
        }
        const keys = Object.keys(map).sort();
        return {
            byDate: map,
            availableDates: new Set(keys),
            minDate: keys.length ? dateFromIso(keys[0]) : new Date(),
            maxDate: keys.length ? dateFromIso(keys[keys.length - 1]) : undefined,
        };
    }, [slots]);

    const [selDate, setSelDate] = useState(null);     // Date object
    const [selSlot, setSelSlot] = useState(null);     // slot object
    const [reason, setReason] = useState("");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);

    const [selecting, setSelecting] = useState({});
    const [reschedId, setReschedId] = useState(null);
    const [reschedPick, setReschedPick] = useState("");

    const selIso = selDate ? isoOf(selDate) : null;
    const dayTimes = selIso ? (byDate[selIso] || []) : [];

    const pickDate = (d) => {
        if (!d) return;
        setSelDate(d);
        setSelSlot(null);
    };

    const submit = async (e) => {
        e.preventDefault();
        if (!selSlot) return toast.error("Please select a date and time.");
        if (!reason.trim()) return toast.error("Please enter a reason for the appointment.");
        setBusy(true);
        try {
            await api.post("/portal/appointments", {
                reason: reason.trim(), patient_note: note || undefined,
                options: [{ date: selSlot.date, time: selSlot.time, label: selSlot.label, display: selSlot.display }],
            });
            toast.success("Appointment request submitted. The clinic will confirm your time.");
            setSelDate(null); setSelSlot(null); setReason(""); setNote("");
            refetch();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const confirmSlot = async (apptId) => {
        const index = selecting[apptId];
        if (index === undefined) return toast.error("Please select a time.");
        try {
            await api.post(`/portal/appointments/${apptId}/select`, { index });
            toast.success("Appointment confirmed!");
            refetch();
        } catch (err) { toast.error(formatErr(err)); }
    };

    const cancelAppt = async (id) => {
        if (!window.confirm("Cancel this appointment? This can't be undone online.")) return;
        try {
            await api.post(`/portal/appointments/${id}/cancel`);
            toast.success("Appointment cancelled.");
            refetch();
        } catch (err) { toast.error(formatErr(err)); }
    };

    const submitReschedule = async (id) => {
        if (reschedPick === "") return toast.error("Choose a new time.");
        const slot = slots[Number(reschedPick)];
        try {
            await api.post(`/portal/appointments/${id}/reschedule`, {
                date: slot.date, time: slot.time, label: slot.label, display: slot.display,
            });
            toast.success("Appointment rescheduled.");
            setReschedId(null); setReschedPick("");
            refetch();
        } catch (err) { toast.error(formatErr(err)); }
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Request an Appointment</h1>
            <EmergencyNotice />
            {p && <PendingBanner status={p.verification_status} />}

            {hasFee && (
                <div data-testid="outstanding-fee-banner" className="bg-red-50 border border-red-200 text-red-800 rounded-xl p-4 text-sm flex gap-2">
                    <AlertTriangle className="w-5 h-5 flex-shrink-0" />
                    <div>
                        <p className="font-bold mb-1">Outstanding late-cancellation fee</p>
                        Please contact the clinic to resolve the outstanding late-cancellation fee before scheduling another appointment.
                        <div className="mt-2">
                            <Button size="sm" variant="outline" data-testid="fee-contact-clinic" onClick={() => nav("/portal/messages")}>
                                <Phone className="w-4 h-4 mr-1" /> Contact Clinic
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {verified && !hasFee && (
                <Card>
                    <form onSubmit={submit} className="space-y-5" data-testid="appointment-form">
                        {/* Step 1 — Date */}
                        <div>
                            <div className="flex items-center gap-2 mb-2">
                                <span className="w-6 h-6 rounded-full bg-portal-blue text-white text-xs font-bold flex items-center justify-center">1</span>
                                <Label className="font-semibold text-slate-700">Select a date</Label>
                            </div>
                            <p className="text-xs text-slate-500 mb-2">Dr. Aguayo sees patients Monday–Thursday. Only dates with availability can be selected.</p>
                            {slotsQ.isLoading && <p className="text-sm text-slate-400">Loading available dates…</p>}
                            {!slotsQ.isLoading && availableDates.size === 0 && (
                                <p className="text-sm text-amber-700">No available dates right now — please message the clinic.</p>
                            )}
                            {availableDates.size > 0 && (
                                <div className="inline-block rounded-2xl border border-slate-200 bg-white" data-testid="appt-calendar">
                                    <Calendar
                                        mode="single"
                                        selected={selDate || undefined}
                                        onSelect={pickDate}
                                        fromDate={minDate}
                                        toDate={maxDate}
                                        defaultMonth={minDate}
                                        disabled={(d) => !availableDates.has(isoOf(d))}
                                        modifiers={{ available: (d) => availableDates.has(isoOf(d)) }}
                                        modifiersClassNames={{ available: "font-semibold text-portal-blue" }}
                                    />
                                </div>
                            )}
                        </div>

                        {/* Step 2 — Time */}
                        {selDate && (
                            <div data-testid="appt-time-section">
                                <div className="flex items-center gap-2 mb-2">
                                    <span className="w-6 h-6 rounded-full bg-portal-blue text-white text-xs font-bold flex items-center justify-center">2</span>
                                    <Label className="font-semibold text-slate-700">Select an available time</Label>
                                </div>
                                <p className="text-xs text-slate-500 mb-2 flex items-center gap-1">
                                    <CalendarDays className="w-3.5 h-3.5" /> {formatDate(selIso)} · America/Toronto
                                </p>
                                {dayTimes.length === 0 && <p className="text-sm text-amber-700">No times left on this date. Please pick another day.</p>}
                                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                                    {dayTimes.map((s) => {
                                        const on = selSlot && selSlot.time === s.time && selSlot.date === s.date;
                                        return (
                                            <button type="button" key={s.time} data-testid={`appt-time-${s.time}`} onClick={() => setSelSlot(s)}
                                                className={`h-10 rounded-xl border text-sm font-semibold transition-colors ${on
                                                    ? "bg-portal-blue text-white border-portal-blue"
                                                    : "bg-white text-slate-700 border-slate-200 hover:border-portal-blue"}`}>
                                                {s.label}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* Step 3 — Reason */}
                        {selSlot && (
                            <div data-testid="appt-reason-section">
                                <div className="flex items-center gap-2 mb-2">
                                    <span className="w-6 h-6 rounded-full bg-portal-blue text-white text-xs font-bold flex items-center justify-center">3</span>
                                    <Label className="font-semibold text-slate-700">Reason for appointment</Label>
                                </div>
                                <Input required value={reason} onChange={(e) => setReason(e.target.value)} data-testid="appt-reason"
                                    placeholder="e.g. Annual physical, medication review" />
                                <div className="mt-3">
                                    <Label className="font-semibold text-slate-700">Short note (optional)</Label>
                                    <Textarea className="mt-1" value={note} onChange={(e) => setNote(e.target.value)} data-testid="appt-note" />
                                </div>
                            </div>
                        )}

                        {/* Step 4 — Review + Submit */}
                        {selSlot && (
                            <div className="bg-sky-50 border border-sky-200 rounded-xl p-3" data-testid="appt-review">
                                <div className="flex items-center gap-2 text-sky-900 font-bold text-sm mb-1">
                                    <Clock className="w-4 h-4" /> Review
                                </div>
                                <div className="text-sm text-slate-700">
                                    <div><span className="text-slate-500">When:</span> <span className="font-semibold" data-testid="appt-review-when">{formatDate(selSlot.date)} at {selSlot.label}</span></div>
                                    {reason.trim() && <div><span className="text-slate-500">Reason:</span> <span className="font-semibold">{reason.trim()}</span></div>}
                                </div>
                                <p className="text-xs text-slate-500 mt-2">This request still requires clinic approval before it becomes confirmed.</p>
                            </div>
                        )}

                        <Button type="submit" disabled={busy || !selSlot || !reason.trim()} data-testid="appt-submit"
                            className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                            {busy ? "Submitting…" : "Submit Appointment Request"}
                        </Button>
                    </form>
                </Card>
            )}

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">Your appointment requests</h2>
                {list.length === 0 && <p className="text-slate-500 text-sm">No requests yet.</p>}
                {list.map((a) => (
                    <Card key={a.id} className="p-4" data-testid="appt-card">
                        <div className="flex justify-between items-start gap-2">
                            <div>
                                <div className="font-bold text-slate-800">{a.reason}</div>
                                <div className="text-sm text-slate-500">{a.ref_number}</div>
                            </div>
                            <StatusPill status={a.status} />
                        </div>

                        {(a.raw_status === "confirmed" || a.raw_status === "rescheduled") && a.confirmed_display && (
                            <div className="mt-2 space-y-2">
                                <div className="flex items-center gap-2 text-emerald-700 font-semibold text-sm">
                                    <CheckCircle2 className="w-4 h-4" /> {a.confirmed_display}
                                </div>

                                {a.can_self_modify && reschedId !== a.id && (
                                    <div className="flex gap-2" data-testid={`appt-actions-${a.id}`}>
                                        <Button size="sm" variant="outline" data-testid={`patient-reschedule-${a.id}`}
                                            onClick={() => { setReschedId(a.id); setReschedPick(""); }}>
                                            <CalendarClock className="w-4 h-4 mr-1" /> Reschedule
                                        </Button>
                                        <Button size="sm" variant="outline" className="text-red-600 border-red-200"
                                            data-testid={`patient-cancel-${a.id}`} onClick={() => cancelAppt(a.id)}>
                                            <X className="w-4 h-4 mr-1" /> Cancel
                                        </Button>
                                    </div>
                                )}

                                {a.can_self_modify && reschedId === a.id && (
                                    <div className="bg-sky-50 border border-sky-200 rounded-xl p-3" data-testid={`reschedule-picker-${a.id}`}>
                                        <Label className="text-xs text-slate-600">Choose a new time</Label>
                                        <select data-testid={`reschedule-select-${a.id}`} value={reschedPick} onChange={(e) => setReschedPick(e.target.value)}
                                            className="w-full border border-slate-200 rounded-xl h-11 px-2 mt-1 bg-white">
                                            <option value="">— Select a time —</option>
                                            {slots.map((s, idx) => <option key={idx} value={idx}>{s.display}</option>)}
                                        </select>
                                        <div className="flex gap-2 mt-2">
                                            <Button size="sm" data-testid={`reschedule-confirm-${a.id}`} onClick={() => submitReschedule(a.id)}
                                                className="bg-portal-blue hover:bg-portal-blueDark text-white">Confirm New Time</Button>
                                            <Button size="sm" variant="ghost" onClick={() => setReschedId(null)}>Back</Button>
                                        </div>
                                    </div>
                                )}

                                {!a.can_self_modify && (
                                    <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-900" data-testid={`within-24h-notice-${a.id}`}>
                                        <div className="flex items-center gap-2 font-bold mb-1">
                                            <AlertTriangle className="w-4 h-4" /> Within 24 hours
                                        </div>
                                        Online cancellation and rescheduling are no longer available because this appointment is within 24 hours.
                                        Late cancellations are subject to a $40 fee. If you need to cancel or reschedule, please contact Dr. Aguayo's office.
                                        The outstanding fee must be resolved with the clinic before a new appointment can be scheduled.
                                        <div className="mt-2">
                                            <Button size="sm" variant="outline" data-testid={`contact-clinic-${a.id}`} onClick={() => nav("/portal/messages")}>
                                                <Phone className="w-4 h-4 mr-1" /> Contact Clinic
                                            </Button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {a.raw_status === "alternatives_offered" && (
                            <div className="mt-3 bg-sky-50 border border-sky-200 rounded-xl p-3" data-testid="offered-slots">
                                <div className="flex items-center gap-2 text-sky-800 font-bold text-sm mb-2">
                                    <CalendarClock className="w-4 h-4" /> Select an appointment time
                                </div>
                                <p className="text-xs text-slate-600 mb-2">The time you requested wasn't available. Please choose one of these:</p>
                                <div className="space-y-2">
                                    {(a.offered_slots || []).map((s, idx) => (
                                        <label key={idx} data-testid={`offer-option-${idx}`}
                                            className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer ${selecting[a.id] === idx ? "border-portal-blue bg-white" : "border-slate-200 bg-white"}`}>
                                            <input type="radio" name={`sel-${a.id}`} checked={selecting[a.id] === idx}
                                                onChange={() => setSelecting({ ...selecting, [a.id]: idx })} />
                                            <span className="font-semibold text-slate-800">{s.display}</span>
                                        </label>
                                    ))}
                                </div>
                                <Button onClick={() => confirmSlot(a.id)} data-testid={`confirm-slot-${a.id}`}
                                    className="mt-3 w-full h-11 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white">
                                    Confirm This Time
                                </Button>
                            </div>
                        )}

                        {a.staff_note && a.raw_status !== "alternatives_offered" && (
                            <div className="text-sm text-slate-600 mt-2">Note: {a.staff_note}</div>
                        )}
                    </Card>
                ))}
            </div>
        </div>
    );
}
