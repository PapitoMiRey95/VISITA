import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, CalendarDays, Ban, Plus, Search } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { useInvalidate } from "./hooks";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { StatusPill } from "./statusPill";
import BookAppointmentModal from "./BookAppointmentModal";

function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
}
function todayISO() { return new Date().toISOString().slice(0, 10); }

export default function Calendar() {
    const invalidate = useInvalidate();
    const [view, setView] = useState("week"); // day | week
    const [start, setStart] = useState(todayISO());
    const [resched, setResched] = useState(null);
    const [booking, setBooking] = useState(null); // {date, time, label}
    const [blocking, setBlocking] = useState(null); // {date}

    const days = view === "day" ? 1 : 7;
    const cal = useQuery({
        queryKey: ["calendar", start, days],
        queryFn: async () => (await api.get("/internal/calendar", { params: { start, days } })).data,
    });

    const refresh = () => { invalidate(); cal.refetch(); };
    const act = async (id, body, msg) => {
        try { await api.patch(`/internal/appointments/${id}`, body); toast.success(msg); refresh(); }
        catch (e) { toast.error(formatErr(e)); }
    };
    const unblockDay = async (date) => {
        try { await api.post("/internal/calendar/unblock-day", { date }); toast.success("Day unblocked."); refresh(); }
        catch (e) { toast.error(formatErr(e)); }
    };

    const rows = cal.data?.days || [];

    return (
        <div className="animate-fade-in">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
                        <CalendarDays className="w-6 h-6 text-visita-green" /> Clinic Calendar
                    </h1>
                    <p className="text-sm text-slate-500">Native VIen EMR schedule · {cal.data?.timezone || "America/Toronto"}</p>
                </div>
                <div className="flex items-center gap-2">
                    <div className="flex rounded-sm border border-slate-300 overflow-hidden">
                        <button data-testid="cal-view-day" onClick={() => setView("day")} className={`px-3 py-1.5 text-sm ${view === "day" ? "bg-visita-green text-white" : "bg-white"}`}>Day</button>
                        <button data-testid="cal-view-week" onClick={() => setView("week")} className={`px-3 py-1.5 text-sm ${view === "week" ? "bg-visita-green text-white" : "bg-white"}`}>Week</button>
                    </div>
                    <Button size="icon" variant="outline" data-testid="cal-prev" onClick={() => setStart(addDays(start, -days))}><ChevronLeft className="w-4 h-4" /></Button>
                    <Button size="sm" variant="outline" data-testid="cal-today" onClick={() => setStart(todayISO())}>Today</Button>
                    <Button size="icon" variant="outline" data-testid="cal-next" onClick={() => setStart(addDays(start, days))}><ChevronRight className="w-4 h-4" /></Button>
                </div>
            </div>

            <div className={`grid gap-3 ${view === "week" ? "grid-cols-1 md:grid-cols-2 xl:grid-cols-4" : "grid-cols-1 max-w-2xl"}`}>
                {rows.map((d) => (
                    <div key={d.date} data-testid="cal-day" className="bg-white border border-slate-300 rounded-sm p-3">
                        <div className="flex items-center justify-between mb-2">
                            <div className="font-semibold text-slate-800 text-sm">{d.weekday}<div className="text-xs text-slate-500">{formatDate(d.date)}</div></div>
                            {!d.closed && (
                                d.day_blocked ? (
                                    <button data-testid="cal-unblock" onClick={() => unblockDay(d.date)} className="text-xs text-red-600 hover:text-slate-600 flex items-center gap-1">
                                        <Ban className="w-3 h-3" /> Unblock Day
                                    </button>
                                ) : (
                                    <button data-testid="cal-block" onClick={() => setBlocking({ date: d.date })} className="text-xs text-slate-400 hover:text-red-600 flex items-center gap-1">
                                        <Ban className="w-3 h-3" /> Block
                                    </button>
                                )
                            )}
                        </div>
                        {d.closed ? (
                            <div className="text-xs text-slate-400 py-3 text-center italic">{d.reason || "Closed"}</div>
                        ) : (
                            <div className="space-y-1">
                                {d.day_blocked && (
                                    <div data-testid="cal-day-blocked" className="rounded-sm bg-red-50 border border-red-200 text-red-700 text-xs font-semibold px-2 py-1 text-center">
                                        DAY BLOCKED — remaining slots unavailable
                                    </div>
                                )}
                                {d.appointments.map((a) => (
                                    <div key={a.id} data-testid="cal-appt" className="rounded-sm bg-emerald-50 border border-emerald-200 px-2 py-1 text-xs">
                                        <div className="flex justify-between items-center">
                                            <span className="font-semibold text-slate-800">{a.label || a.time} · {a.patient_name}</span>
                                            <StatusPill status={a.status} />
                                        </div>
                                        {a.reason && <div className="text-slate-500 truncate">{a.reason}</div>}
                                        {(a.status === "confirmed" || a.status === "rescheduled") && (
                                            <div className="flex gap-1 mt-1">
                                                <button className="text-[11px] text-slate-500 hover:text-visita-greenDark" onClick={() => setResched(a)} data-testid="cal-reschedule">Reschedule</button>
                                                <button className="text-[11px] text-slate-500 hover:text-slate-800" onClick={() => act(a.id, { action: "complete" }, "Marked completed.")} data-testid="cal-complete">Complete</button>
                                                <button className="text-[11px] text-amber-600" onClick={() => act(a.id, { action: "no_show" }, "Marked no-show.")} data-testid="cal-noshow">No-show</button>
                                                <button className="text-[11px] text-red-600" onClick={() => act(a.id, { action: "cancel" }, "Cancelled.")} data-testid="cal-cancel">Cancel</button>
                                            </div>
                                        )}
                                    </div>
                                ))}
                                {d.open_slots.map((s) => (
                                    <button key={s.time} data-testid="cal-open-slot" onClick={() => setBooking({ date: d.date, time: s.time, label: s.label })}
                                        className="w-full flex items-center gap-1 text-left rounded-sm border border-dashed border-slate-200 px-2 py-1 text-xs text-slate-500 hover:border-visita-green hover:text-visita-greenDark">
                                        <Plus className="w-3 h-3" /> {s.label}
                                    </button>
                                ))}
                                {d.appointments.length === 0 && d.open_slots.length === 0 && (
                                    <div className="text-xs text-slate-400 py-2 text-center">No availability</div>
                                )}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            {resched && (
                <BookAppointmentModal open onClose={() => setResched(null)} onDone={refresh} mode="reschedule" source={resched} />
            )}
            {booking && <BookSlotDialog slot={booking} onClose={() => setBooking(null)} onDone={refresh} />}
            {blocking && <BlockDialog day={blocking} onClose={() => setBlocking(null)} onDone={refresh} />}
        </div>
    );
}

function BookSlotDialog({ slot, onClose, onDone }) {
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [patient, setPatient] = useState(null);
    const [reason, setReason] = useState("");
    const [busy, setBusy] = useState(false);

    const search = async (e) => {
        e.preventDefault();
        try { setResults((await api.get("/internal/directory", { params: { q } })).data); }
        catch (err) { toast.error(formatErr(err)); }
    };
    const submit = async () => {
        setBusy(true);
        try {
            await api.post("/internal/calendar/book", { directory_id: patient.id, date: slot.date, time: slot.time, label: slot.label, reason: reason || null });
            toast.success("Appointment booked and patient notified.");
            onDone(); onClose();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-md" data-testid="cal-book-dialog">
                <DialogHeader><DialogTitle>Book — {formatDate(slot.date)} · {slot.label}</DialogTitle></DialogHeader>
                {!patient ? (
                    <div className="space-y-2">
                        <form onSubmit={search} className="flex gap-2">
                            <div className="relative flex-1"><Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                                <Input className="pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Patient name or VISITA ID" data-testid="cal-book-search" /></div>
                            <Button type="submit">Search</Button>
                        </form>
                        <div className="max-h-60 overflow-y-auto divide-y border rounded-sm">
                            {results.map((r) => (
                                <button key={r.id} data-testid="cal-book-result" onClick={() => setPatient(r)} className="w-full text-left px-2 py-1.5 text-sm hover:bg-slate-50">
                                    {r.last_name}, {r.first_name} · DOB {formatDate(r.date_of_birth)}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="space-y-3 text-sm">
                        <div>Patient: <b>{patient.last_name}, {patient.first_name}</b> <button className="text-xs text-slate-400 ml-2" onClick={() => setPatient(null)}>change</button></div>
                        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)" data-testid="cal-book-reason" />
                        <Button disabled={busy} onClick={submit} className="w-full bg-visita-green hover:bg-visita-greenDark text-white" data-testid="cal-book-confirm">Confirm & Book</Button>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
}

function BlockDialog({ day, onClose, onDone }) {
    const [busy, setBusy] = useState(false);
    const submit = async () => {
        setBusy(true);
        try {
            const r = await api.post("/internal/calendar/block-day", { date: day.date });
            toast.success(`Day blocked — ${r.data.slots_blocked} open slot(s) made unavailable.`);
            onDone(); onClose();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-sm" data-testid="cal-block-dialog">
                <DialogHeader><DialogTitle>Block day</DialogTitle></DialogHeader>
                <div className="space-y-4 text-sm">
                    <p className="text-slate-700">
                        Block all remaining available appointment slots for <b>{formatDate(day.date)}</b>?
                        Existing appointments are kept unchanged.
                    </p>
                    <div className="flex gap-2 justify-end">
                        <Button variant="outline" onClick={onClose} data-testid="block-cancel">Cancel</Button>
                        <Button disabled={busy} onClick={submit} className="bg-red-600 hover:bg-red-700 text-white" data-testid="block-confirm">
                            {busy ? "Blocking…" : "Block Day"}
                        </Button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
