import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, CalendarDays, Ban, Plus, Search, Bell, X, Phone } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatLastFirst, formatCombinedName } from "../lib/name";
import { formatDate } from "../lib/date";
import { ApptTypeEditor } from "../components/ApptTypeEditor";
import { useInvalidate } from "./hooks";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { StatusPill } from "./statusPill";
import { ApptTypeBadge } from "../components/ApptTypeBadge";
import BookAppointmentModal from "./BookAppointmentModal";
import CancelAppointmentDialog from "./CancelAppointmentDialog";
import { SameDayOverride, isSameDayConflict } from "./SameDayOverride";
import { InternalNotes } from "./InternalNotes";

// Operational view: only what still affects today's schedule. History (cancelled+freed,
// completed, no-show) is preserved and shown behind the per-day "Show day history" control.
const isHistory = (a) => a.status === "completed" || a.status === "no_show" || (a.status === "cancelled" && !a.slot_blocked);
const liveAppts = (list) => (list || []).filter((a) => !isHistory(a));
const historyAppts = (list) => (list || []).filter(isHistory);

function DayHistory({ appts, open, onToggle, onOpen }) {
    if (!appts.length) return null;
    return (
        <div className="pt-1" data-testid="cal-day-history">
            <button type="button" onClick={onToggle} data-testid="cal-day-history-toggle"
                className="w-full text-left text-[11px] font-semibold text-slate-500 hover:text-slate-800 flex items-center gap-1">
                <ChevronRight className={`w-3 h-3 transition-transform ${open ? "rotate-90" : ""}`} /> {open ? "Hide" : "Show"} day history ({appts.length})
            </button>
            {open && (
                <div className="mt-1 space-y-1" data-testid="cal-day-history-list">
                    {appts.map((a) => {
                        const c = a.cancellation || {};
                        const red = a.status === "cancelled";
                        return (
                            <button type="button" key={a.id} onClick={() => onOpen(a)} data-testid="cal-history-appt" data-status={a.status}
                                className={`w-full text-left rounded-sm border px-2 py-1 text-[11px] ${red ? "bg-red-50 border-red-200 text-red-800" : "bg-slate-50 border-slate-200 text-slate-600"}`}>
                                <div className="flex justify-between gap-1">
                                    <span className={`font-semibold truncate ${red ? "line-through decoration-red-400" : ""}`}>{a.label || a.time} · {formatCombinedName(a.patient_name)}</span>
                                    <StatusPill status={a.status} />
                                </div>
                                {red && <div>{c.reason || "Cancelled"} · {a.slot_blocked ? "TIME KEPT BLOCKED" : "TIME FREED"}{a.cancelled_by ? ` · by ${a.cancelled_by}` : ""}</div>}
                                {a.status === "completed" && a.completed_by && <div>Completed by {a.completed_by}</div>}
                                {a.status === "no_show" && a.marked_by && <div>Marked no-show by {a.marked_by}</div>}
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

// Visual state per appointment status: cancelled = red (history), requested = amber (held).
function apptTone(a) {
    if (a.status === "cancelled") return "bg-red-50 border-red-300 text-red-800";
    if (a.status === "requested") return "bg-amber-50 border-amber-300";
    if (a.is_private) return "bg-amber-50 border-amber-300";
    return "bg-emerald-50 border-emerald-200";
}

function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
}
function addMonths(iso, n) {
    const d = new Date(iso + "T00:00:00");
    d.setDate(1);
    d.setMonth(d.getMonth() + n);
    return d.toISOString().slice(0, 10);
}
function monthFirstISO(iso) { return iso.slice(0, 7) + "-01"; }
function gridStartISO(iso) {
    const d = new Date(monthFirstISO(iso) + "T00:00:00");
    d.setDate(d.getDate() - d.getDay()); // back to Sunday
    return d.toISOString().slice(0, 10);
}
function monthLabel(iso) {
    const d = new Date(monthFirstISO(iso) + "T00:00:00");
    return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}
// Clinic-local "today" (America/Toronto), independent of the device timezone.
function todayISO() { return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Toronto", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date()); }
const OPEN_PREF_KEY = "vien.calendar.showOpenTimes"; // local UI preference only (physician/admin compact mode)
const readOpenPref = () => { try { return localStorage.getItem(OPEN_PREF_KEY) === "1"; } catch { return false; } };
const isMobileViewport = () => typeof window !== "undefined" && window.matchMedia && window.matchMedia("(max-width: 767px)").matches;
const WEEKDAY_HEADERS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const toMin = (t) => { const [h, m] = String(t || "0:0").split(":").map(Number); return h * 60 + (m || 0); };
const fromMin = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const labelOf = (t) => { const m = toMin(t); const h = Math.floor(m / 60); return `${h % 12 || 12}:${String(m % 60).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`; };
const nowMinToronto = () => { const p = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Toronto", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date()); return Number(p.find((x) => x.type === "hour").value) % 24 * 60 + Number(p.find((x) => x.type === "minute").value); };
// Internal-only quick-add rows (physician/admin): 30-min steps after the last normal slot through 11:00 PM.
// Closed/weekend days start at 9:00 AM. Never fed back into patient availability.
function internalRows(d, duration) {
    const dur = duration || 30;
    if (d.date < todayISO()) return [];
    const taken = new Set([...(d.appointments || []).filter((a) => !isHistory(a)).map((a) => a.time), ...(d.reminders || []).map((r) => r.time)]);
    const normal = [...(d.open_slots || []).map((s) => toMin(s.time)),
        ...(d.appointments || []).filter((a) => !a.is_private && a.source !== "calendar_manual").map((a) => toMin(a.time))];
    let start = d.closed || normal.length === 0 ? 9 * 60 : Math.max(...normal) + dur;
    start = Math.ceil(start / 30) * 30;
    const minNow = d.date === todayISO() ? nowMinToronto() : -1;
    const rows = [];
    for (let m = start; m <= 23 * 60; m += 30) {
        const t = fromMin(m);
        if (m <= minNow || taken.has(t)) continue;
        rows.push({ time: t, label: labelOf(t) });
    }
    return rows;
}
// Chronological rows under the appointments: open clinic slots (everyone), reminders + internal after-hours rows (physician/admin).
// Appointments interleaved chronologically with the open/reminder rows.
function mergedRows(d, canManual, duration, showOpen) {
    const appts = liveAppts(d.appointments).map((a) => ({ kind: "appt", time: a.time, id: a.id, appt: a }));
    return [...appts, ...dayRows(d, canManual, duration, showOpen)].sort((a, b) => toMin(a.time) - toMin(b.time));
}
function dayRows(d, canManual, duration, showOpen = true) {
    const rows = (d.open_slots || []).map((s) => ({ kind: "open", time: s.time, label: s.label }));
    if (canManual) {
        rows.push(...(d.reminders || []).map((r) => ({ kind: "reminder", ...r })));
        rows.push(...internalRows(d, duration).map((s) => ({ kind: "internal", ...s })));
        if (!showOpen) return rows.filter((r) => r.kind === "reminder").sort((a, b) => toMin(a.time) - toMin(b.time));
    }
    return rows.sort((a, b) => toMin(a.time) - toMin(b.time));
}

export default function Calendar() {
    const invalidate = useInvalidate();
    const { user } = useAuth();
    const canManual = user?.role === "physician" || user?.role === "admin";
    // Mobile physician/admin: open on today's Day view (set once; manual Day/Week/Month changes are respected).
    const [view, setView] = useState(() => (canManual && isMobileViewport() ? "day" : "month")); // day | week | month
    // Compact mode (physician/admin): empty open/quick-add rows hidden by default; appointments + reminders always shown.
    const [showOpen, setShowOpen] = useState(readOpenPref);
    const toggleOpen = () => setShowOpen((v) => { try { localStorage.setItem(OPEN_PREF_KEY, v ? "0" : "1"); } catch { /* ignore */ } return !v; });
    const [start, setStart] = useState(todayISO());
    const [resched, setResched] = useState(null);
    const [cancelling, setCancelling] = useState(null);
    const [histOpen, setHistOpen] = useState({}); // per-day "Show day history" toggle
    const [booking, setBooking] = useState(null); // {date, time, label} | {date, manual: true}
    const [blocking, setBlocking] = useState(null); // {date}
    const [search, setSearch] = useState(""); // filter by patient name / last name / PIN
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [selectedId, setSelectedId] = useState(null); // highlighted appt after selecting a result
    const [detail, setDetail] = useState(null); // appointment object shown in the detail popup

    // Returns null when no query (neutral), true/false when a query is active.
    const q = search.trim().toLowerCase();
    const matchAppt = (a) => {
        if (!q) return null;
        const hay = `${a.patient_name || ""} ${a.visita_patient_id || ""}`.toLowerCase();
        return hay.includes(q);
    };

    const step = view === "day" ? 1 : 7;
    const fetchStart = view === "month" ? gridStartISO(start) : start;
    const fetchDays = view === "day" ? 1 : view === "week" ? 7 : 42;
    const cal = useQuery({
        queryKey: ["calendar", fetchStart, fetchDays],
        queryFn: async () => (await api.get("/internal/calendar", { params: { start: fetchStart, days: fetchDays } })).data,
    });

    // Global appointment search across ALL dates (not limited to the loaded view).
    const searchQuery = useQuery({
        queryKey: ["appt-search", q],
        queryFn: async () => (await api.get("/internal/appointment-search", { params: { q } })).data,
        enabled: q.length >= 2,
    });
    const searchResults = searchQuery.data?.results || [];

    const goPrev = () => setStart(view === "month" ? addMonths(start, -1) : addDays(start, -step));
    const goNext = () => setStart(view === "month" ? addMonths(start, 1) : addDays(start, step));
    const openDay = (date) => { setStart(date); setView("day"); };

    const refresh = () => { invalidate(); cal.refetch(); };
    const act = async (id, body, msg) => {
        try {
            await api.patch(`/internal/appointments/${id}`, body);
            if (body.action === "no_show" || body.action === "complete") {
                toast.success(msg, {
                    action: {
                        label: "Undo",
                        onClick: async () => {
                            try { await api.patch(`/internal/appointments/${id}`, { action: "undo_status" }); toast.success("Reverted to Confirmed."); refresh(); }
                            catch (e) { toast.error(formatErr(e)); }
                        },
                    },
                    duration: 8000,
                });
            } else {
                toast.success(msg);
            }
            refresh();
        }
        catch (e) { toast.error(formatErr(e)); }
    };
    const deleteReminder = async (id) => {
        try { await api.delete(`/internal/calendar/reminders/${id}`); toast.success("Reminder removed."); refresh(); }
        catch (e) { toast.error(formatErr(e)); }
    };
    const unblockDay = async (date) => {
        try { await api.post("/internal/calendar/unblock-day", { date }); toast.success("Day unblocked."); refresh(); }
        catch (e) { toast.error(formatErr(e)); }
    };

    const rows = cal.data?.days || [];

    // Group global search results by patient for the dropdown.
    const groups = (() => {
        if (q.length < 2) return [];
        const byPatient = new Map();
        for (const a of searchResults) {
            const key = a.visita_patient_id ? `pin:${a.visita_patient_id}` : `name:${(a.patient_name || "").toLowerCase()}`;
            if (!byPatient.has(key)) byPatient.set(key, { name: a.patient_name, pin: a.visita_patient_id, appts: [] });
            byPatient.get(key).appts.push(a);
        }
        return Array.from(byPatient.values()).sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    })();

    const selectResult = (appt) => {
        // Jump to the appointment's date while preserving the current view mode.
        setStart(appt.date);
        setSelectedId(appt.id);
        setDetail(appt);
        setDropdownOpen(false);
    };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
                        <CalendarDays className="w-6 h-6 text-visita-green" /> Clinic Calendar
                    </h1>
                    <p className="text-sm text-slate-500">
                        {view === "month" ? monthLabel(start) : "Native VIen EMR schedule"} · {cal.data?.timezone || "America/Toronto"}
                    </p>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex rounded-sm border border-slate-300 overflow-hidden">
                        <button data-testid="cal-view-day" onClick={() => setView("day")} className={`px-3 py-1.5 text-sm ${view === "day" ? "bg-visita-green text-white" : "bg-white"}`}>Day</button>
                        <button data-testid="cal-view-week" onClick={() => setView("week")} className={`px-3 py-1.5 text-sm border-l border-slate-300 ${view === "week" ? "bg-visita-green text-white" : "bg-white"}`}>Week</button>
                        <button data-testid="cal-view-month" onClick={() => setView("month")} className={`px-3 py-1.5 text-sm border-l border-slate-300 ${view === "month" ? "bg-visita-green text-white" : "bg-white"}`}>Month</button>
                    </div>
                    <Button size="icon" variant="outline" data-testid="cal-prev" onClick={goPrev}><ChevronLeft className="w-4 h-4" /></Button>
                    <Button size="sm" variant="outline" data-testid="cal-today" onClick={() => setStart(todayISO())}>Today</Button>
                    <Button size="icon" variant="outline" data-testid="cal-next" onClick={goNext}><ChevronRight className="w-4 h-4" /></Button>
                    {canManual && (
                        <Button size="sm" data-testid="cal-add-appointment" onClick={() => setBooking({ date: start, time: "", internal: true, editWhen: true })}>
                            <Plus className="w-4 h-4 mr-1" /> Add
                        </Button>
                    )}
                </div>
            </div>

            <div className="mb-3 flex items-center gap-2 flex-wrap">
                <div className="relative w-full sm:max-w-md">
                    <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                    <Input data-testid="cal-search" className="pl-8" value={search}
                        onChange={(e) => { setSearch(e.target.value); setDropdownOpen(true); }}
                        onFocus={() => setDropdownOpen(true)}
                        placeholder="Search appointments — name, last name, or PIN" />
                    {q.length >= 2 && dropdownOpen && (
                        <div data-testid="cal-search-dropdown" className="absolute z-30 mt-1 w-full bg-white border border-slate-300 rounded-md shadow-lg max-h-96 overflow-y-auto">
                            {searchQuery.isLoading ? (
                                <div className="px-3 py-3 text-sm text-slate-400">Searching…</div>
                            ) : groups.length === 0 ? (
                                <div className="px-3 py-3 text-sm text-slate-400" data-testid="cal-search-empty">No matching appointments found.</div>
                            ) : (
                                groups.map((g, gi) => (
                                    <div key={gi} className="border-b border-slate-100 last:border-0">
                                        <div className="px-3 pt-2 pb-1">
                                            <div className="text-sm font-bold text-slate-800">{formatCombinedName(g.name)}</div>
                                            <div className="text-[11px] text-slate-400">{g.pin ? `PIN: ${g.pin}` : "PIN: Not assigned"}</div>
                                        </div>
                                        <div className="pb-1.5">
                                            {g.appts.map((a) => (
                                                <button key={a.id} data-testid="cal-search-result" onClick={() => selectResult(a)}
                                                    className="w-full text-left px-3 py-1.5 hover:bg-visita-bg flex items-center justify-between gap-2">
                                                    <span className="text-xs text-slate-600">
                                                        {formatDate(a.date)} · {a.label || a.time}
                                                        {a.is_private && <span className="ml-1.5 text-[9px] font-bold uppercase text-amber-700">Private</span>}
                                                    </span>
                                                    <span className="flex items-center gap-1.5 shrink-0">
                                                        <ApptTypeBadge type={a.appointment_type} />
                                                        <StatusPill status={a.status} />
                                                    </span>
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    )}
                </div>
                {q && (
                    <div className="flex items-center gap-2 text-sm" data-testid="cal-search-summary">
                        <span className="text-slate-500">{searchResults.length}{searchResults.length === 50 ? "+" : ""} appointment{searchResults.length === 1 ? "" : "s"} found</span>
                        <button data-testid="cal-search-clear" onClick={() => { setSearch(""); setDropdownOpen(false); setSelectedId(null); }} className="text-xs text-visita-greenDark hover:underline">Clear</button>
                    </div>
                )}
            </div>

            {view === "month" ? (
                <MonthGrid anchor={start} rows={rows} onPickDate={openDay} matchAppt={matchAppt} active={!!q} />
            ) : (
            <div className={`grid gap-3 ${view === "week" ? "grid-cols-1 md:grid-cols-2 xl:grid-cols-4" : "grid-cols-1 max-w-2xl"}`}>
                {rows.map((d) => (
                    <div key={d.date} data-testid="cal-day" className="bg-white border border-slate-300 rounded-sm p-2">
                        <div className="flex items-center justify-between mb-1.5">
                            <div className="font-semibold text-slate-800 text-sm leading-tight">{d.weekday}<span className="text-xs text-slate-500 font-normal ml-1.5">{formatDate(d.date)}</span></div>
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
                        {d.closed && !canManual && liveAppts(d.appointments).length === 0 && historyAppts(d.appointments).length === 0 ? (
                            <div className="text-xs text-slate-400 py-2 text-center italic">{d.reason || "Closed"}</div>
                        ) : (
                            <div className="space-y-1">
                                {d.closed && !canManual && <div className="text-[11px] text-slate-400 italic text-center" data-testid="cal-closed-note">{d.reason || "Closed"} — manually scheduled</div>}
                                {d.day_blocked && (
                                    <div data-testid="cal-day-blocked" className="rounded-sm bg-red-50 border border-red-200 text-red-700 text-xs font-semibold px-2 py-0.5 text-center">
                                        DAY BLOCKED — remaining slots unavailable
                                    </div>
                                )}
                                {mergedRows(d, canManual, cal.data?.duration, showOpen).map((row) => row.kind === "appt" ? (() => { const a = row.appt;
                                    const m = matchAppt(a);
                                    const sel = a.id === selectedId;
                                    return (
                                    <div key={a.id} data-testid="cal-appt" data-status={a.status} className={`rounded-sm border px-2 py-1 text-xs transition-all ${apptTone(a)} ${sel ? "ring-2 ring-visita-green ring-offset-2 shadow-md" : m === true ? "ring-2 ring-visita-green ring-offset-1" : ""} ${m === false && !sel ? "opacity-30" : ""}`}>
                                        <div className="flex justify-between items-center gap-1">
                                            <button type="button" data-testid="cal-appt-open" onClick={() => { setSelectedId(a.id); setDetail({ ...a, date: d.date }); }} className={`font-semibold truncate text-left hover:underline ${a.status === "cancelled" ? "text-red-800 line-through decoration-red-400" : "text-slate-800 hover:text-visita-greenDark"}`}>{a.label || a.time} · {formatCombinedName(a.patient_name)}{a.visita_patient_id ? ` · PIN ${a.visita_patient_id}` : ""}</button>
                                            <StatusPill status={a.status} />
                                        </div>
                                        {a.status === "cancelled" && (
                                            <div className="text-[10px] font-bold uppercase tracking-wide text-red-700" data-testid="cal-cancelled-badge">
                                                Cancelled · {a.slot_blocked ? "time kept blocked" : "time freed"}
                                            </div>
                                        )}
                                        {a.is_private && <div className="text-[10px] font-bold uppercase tracking-wide text-amber-700" data-testid="cal-private-badge">Private / Uninsured</div>}
                                        {a.reason && <div className="text-slate-500 truncate leading-tight">{a.reason}</div>}
                                        <div className="flex items-center justify-between gap-2 mt-0.5">
                                            <ApptTypeEditor appt={a} onSaved={refresh} />
                                            {(a.status === "confirmed" || a.status === "rescheduled" || a.status === "requested") && (
                                                <div className="flex gap-1.5 shrink-0">
                                                    {a.status === "requested" && <button className="text-[11px] text-visita-greenDark font-semibold" onClick={() => act(a.id, { action: "approve" }, "Approved — patient notified.")} data-testid="cal-approve">Approve</button>}
                                                    <button className="text-[11px] text-slate-500 hover:text-visita-greenDark" onClick={() => setResched(a)} data-testid="cal-reschedule">Change time</button>
                                                    {a.status !== "requested" && <button className="text-[11px] text-slate-500 hover:text-slate-800" onClick={() => act(a.id, { action: "complete" }, "Marked completed.")} data-testid="cal-complete">Complete</button>}
                                                    {a.status !== "requested" && <button className="text-[11px] text-amber-600" onClick={() => act(a.id, { action: "no_show" }, "Marked no-show.")} data-testid="cal-noshow">No-show</button>}
                                                    <button className="text-[11px] text-red-600" onClick={() => setCancelling(a)} data-testid="cal-cancel">Cancel</button>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    );
                                })() :
                                row.kind === "reminder" ? (
                                    <div key={row.id} data-testid="cal-reminder" className="rounded-sm border border-dashed border-indigo-300 bg-indigo-50/60 px-2 py-1 text-xs flex items-start justify-between gap-2">
                                        <div className="min-w-0">
                                            <div className="font-semibold text-indigo-900 flex items-center gap-1"><Bell className="w-3 h-3 shrink-0" /> {row.label || row.time} · {row.title}</div>
                                            {row.note && <div className="text-indigo-700/80 truncate leading-tight">{row.note}</div>}
                                        </div>
                                        <button type="button" data-testid="cal-reminder-delete" onClick={() => deleteReminder(row.id)} className="text-indigo-400 hover:text-red-600 shrink-0" aria-label="Remove reminder"><X className="w-3 h-3" /></button>
                                    </div>
                                ) : (
                                    <button key={`${row.kind}-${row.time}`} data-testid={row.kind === "open" ? "cal-open-slot" : "cal-internal-slot"}
                                        onClick={() => setBooking({ date: d.date, time: row.time, label: row.label, internal: row.kind === "internal" })}
                                        className={`w-full flex items-center gap-1 text-left rounded-sm border border-dashed px-2 py-0.5 text-xs hover:border-visita-green hover:text-visita-greenDark ${row.kind === "open" ? "border-slate-200 text-slate-500" : "border-slate-200/70 text-slate-400"}`}>
                                        <Plus className="w-3 h-3" /> {row.label}
                                    </button>
                                ))}
                                {!canManual && d.appointments.length === 0 && d.open_slots.length === 0 && (
                                    <div className="text-xs text-slate-400 py-1.5 text-center">No availability</div>
                                )}
                                {canManual && d.date >= todayISO() && (
                                    <button type="button" data-testid="cal-toggle-open-times" onClick={toggleOpen}
                                        className="w-full text-left text-[11px] font-semibold text-slate-400 hover:text-visita-greenDark flex items-center gap-1 pt-0.5">
                                        {showOpen ? <><span className="w-3 text-center">−</span> Hide open times</> : <><Plus className="w-3 h-3" /> Show open times</>}
                                    </button>
                                )}
                                <DayHistory appts={historyAppts(d.appointments)} open={!!histOpen[d.date]}
                                    onToggle={() => setHistOpen((h) => ({ ...h, [d.date]: !h[d.date] }))}
                                    onOpen={(a) => { setSelectedId(a.id); setDetail({ ...a, date: d.date }); }} />
                            </div>
                        )}
                    </div>
                ))}
            </div>
            )}

            {resched && (
                <BookAppointmentModal open onClose={() => setResched(null)} onDone={refresh} mode="reschedule" source={resched} />
            )}
            {cancelling && (
                <CancelAppointmentDialog appt={cancelling} onClose={() => setCancelling(null)} onDone={() => { refresh(); setDetail(null); }} />
            )}
            {booking && <BookSlotDialog slot={booking} canManual={canManual} onClose={() => setBooking(null)} onDone={refresh} />}
            {blocking && <BlockDialog day={blocking} onClose={() => setBlocking(null)} onDone={refresh} />}
            {detail && (
                <AppointmentDetail appt={detail} onClose={() => setDetail(null)}
                    onReschedule={() => { setResched(detail); setDetail(null); }}
                    onCancel={() => { setCancelling(detail); }}
                    onNoteSaved={(u) => { setDetail({ ...detail, internal_notes: u.internal_notes }); refresh(); }}
                    onAction={async (body, msg) => { await act(detail.id, body, msg); setDetail(null); }} />
            )}
        </div>
    );
}

function DRow({ label, children }) {
    if (children === null || children === undefined || children === "") return null;
    return (
        <div className="flex justify-between gap-4 py-1 border-b border-slate-100 last:border-0">
            <span className="text-xs uppercase tracking-wide text-slate-400 shrink-0">{label}</span>
            <span className="text-sm text-slate-800 text-right">{children}</span>
        </div>
    );
}

// Compact appointment detail popup. Reuses StatusPill / ApptTypeBadge and the
// parent's existing appointment actions (no duplicated business logic).
function AppointmentDetail({ appt, onClose, onReschedule, onCancel, onNoteSaved, onAction }) {
    const canAct = appt.status === "confirmed" || appt.status === "rescheduled";
    const isReq = appt.status === "requested";
    const c = appt.cancellation;
    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto" data-testid="cal-appt-detail">
                <DialogHeader><DialogTitle>Appointment Details</DialogTitle></DialogHeader>
                <div className="space-y-3">
                    <div>
                        <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-1">Patient</div>
                        <div className="text-lg font-bold text-slate-900" data-testid="cal-detail-name">{formatCombinedName(appt.patient_name)}</div>
                        <div className="text-xs text-slate-500">{appt.visita_patient_id ? `PIN: ${appt.visita_patient_id}` : "PIN: Not assigned"}</div>
                        <div className="text-xs text-slate-500 flex items-center gap-1.5" data-testid="cal-detail-phone">
                            <span>PHONE:</span>
                            {appt.patient_phone
                                ? <a href={`tel:${appt.patient_phone.replace(/[^\d+]/g, "")}`} className="inline-flex items-center gap-1 text-sky-700 hover:underline font-medium" data-testid="cal-detail-phone-link"><Phone className="w-3 h-3" />{appt.patient_phone}</a>
                                : <span data-testid="cal-detail-phone-none">Not available</span>}
                        </div>
                    </div>
                    {appt.status === "cancelled" && (
                        <div className="bg-red-50 border border-red-200 rounded-sm p-2 text-xs text-red-800" data-testid="cal-detail-cancellation">
                            <div className="font-bold">CANCELLED — {appt.slot_blocked ? "time kept blocked" : "time freed"}</div>
                            {c?.reason && <div>Reason: {c.reason}</div>}
                            <div>By {appt.cancelled_by || c?.by || "—"}{appt.cancelled_at || c?.at ? ` · ${new Date(appt.cancelled_at || c.at).toLocaleString()}` : ""}</div>
                        </div>
                    )}
                    <div>
                        <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-1">Appointment</div>
                        <DRow label="Date">{formatDate(appt.date)}</DRow>
                        <DRow label="Time">{appt.label || appt.time}</DRow>
                        <DRow label="Type"><ApptTypeBadge type={appt.appointment_type} /></DRow>
                        <DRow label="Status"><StatusPill status={appt.status} /></DRow>
                        <DRow label="Reason">{appt.reason || <span className="text-slate-400">—</span>}</DRow>
                        {appt.is_private && <DRow label="Billing"><span className="text-[10px] font-bold uppercase tracking-wide text-amber-700" data-testid="cal-detail-private">Private / Uninsured</span></DRow>}
                        <DRow label="Reference">{appt.ref_number}</DRow>
                        <DRow label="Source">{appt.source}</DRow>
                    </div>
                    {(canAct || isReq) && (
                        <div className="flex flex-wrap gap-2 pt-1">
                            {isReq && <Button size="sm" className="bg-visita-green hover:bg-visita-greenDark text-white" data-testid="cal-detail-approve" onClick={() => onAction({ action: "approve" }, "Approved — patient notified.")}>Approve</Button>}
                            <Button size="sm" variant="outline" data-testid="cal-detail-reschedule" onClick={onReschedule}>Change Time</Button>
                            {canAct && <Button size="sm" variant="outline" data-testid="cal-detail-complete" onClick={() => onAction({ action: "complete" }, "Marked completed.")}>Mark Completed</Button>}
                            {canAct && <Button size="sm" variant="outline" className="text-amber-700 border-amber-300 hover:bg-amber-50" data-testid="cal-detail-noshow" onClick={() => onAction({ action: "no_show" }, "Marked no-show.")}>No-show</Button>}
                            <Button size="sm" variant="outline" className="text-red-600 border-red-300 hover:bg-red-50" data-testid="cal-detail-cancel" onClick={onCancel}>Cancel</Button>
                        </div>
                    )}
                    <InternalNotes appt={appt} onSaved={onNoteSaved} />
                </div>
            </DialogContent>
        </Dialog>
    );
}

function MonthGrid({ anchor, rows, onPickDate, matchAppt, active }) {
    const gridStart = gridStartISO(anchor);
    const monthKey = anchor.slice(0, 7);
    const today = todayISO();
    const byDate = {};
    for (const d of rows) byDate[d.date] = d;
    const cells = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));

    return (
        <div data-testid="cal-month-grid" className="bg-white border border-slate-300 rounded-sm overflow-hidden">
            <div className="grid grid-cols-7 border-b border-slate-200 bg-slate-50">
                {WEEKDAY_HEADERS.map((w) => (
                    <div key={w} className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500 text-center">{w}</div>
                ))}
            </div>
            <div className="grid grid-cols-7">
                {cells.map((iso) => {
                    const d = byDate[iso];
                    const inMonth = iso.slice(0, 7) === monthKey;
                    const isToday = iso === today;
                    const nonWorking = d?.closed;
                    const blocked = d?.day_blocked;
                    const appts = liveAppts(d?.appointments || []);
                    const dayNum = Number(iso.slice(8, 10));
                    const dayHasMatch = active && appts.some((a) => matchAppt(a) === true);
                    return (
                        <button key={iso} type="button" data-testid="cal-month-cell" onClick={() => onPickDate(iso)}
                            className={`min-h-[104px] border-b border-r border-slate-200 p-1.5 text-left align-top transition-colors
                                ${nonWorking ? "bg-slate-50" : "bg-white hover:bg-visita-bg"}
                                ${!inMonth ? "opacity-40" : ""}
                                ${dayHasMatch ? "ring-2 ring-inset ring-visita-green" : ""}
                                ${active && !dayHasMatch && inMonth ? "opacity-40" : ""}`}>
                            <div className="flex items-center justify-between">
                                <span data-testid={isToday ? "cal-month-today" : undefined}
                                    className={`text-xs font-semibold w-5 h-5 flex items-center justify-center rounded-full
                                        ${isToday ? "bg-visita-green text-white" : nonWorking ? "text-slate-400" : "text-slate-700"}`}>
                                    {dayNum}
                                </span>
                                <div className="flex items-center gap-1">
                                    {blocked && <span data-testid="cal-month-blocked" className="text-[9px] font-bold text-red-700 bg-red-50 border border-red-200 rounded px-1">BLOCKED</span>}
                                    {(d?.reminders || []).length > 0 && <span data-testid="cal-month-reminders" className="text-[10px] text-indigo-500 font-semibold flex items-center gap-0.5"><Bell className="w-2.5 h-2.5" />{d.reminders.length}</span>}
                                    {appts.length > 0 && <span className="text-[10px] text-slate-400 font-semibold">{appts.length}</span>}
                                </div>
                            </div>
                            <div className="mt-1 space-y-0.5">
                                {appts.slice(0, 3).map((a) => {
                                    const m = matchAppt(a);
                                    return (
                                    <div key={a.id} data-testid="cal-month-appt" className={`text-[10px] leading-tight truncate rounded-sm px-1 py-0.5 ${m === true ? "bg-visita-green text-white font-bold" : a.status === "cancelled" ? "bg-red-50 text-red-700 line-through" : a.status === "requested" ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-800"}`}>
                                        <span className="font-semibold">{a.time}</span> {(a.patient_name || "").split(",")[0].toUpperCase()}{m === true && a.visita_patient_id ? ` · ${a.visita_patient_id}` : ""}
                                    </div>
                                    );
                                })}
                                {appts.length > 3 && (
                                    <div data-testid="cal-month-more" className="text-[10px] text-slate-500 font-medium px-1">+ {appts.length - 3} more</div>
                                )}
                            </div>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}

// Compact composer: date/time come from the clicked row (editable via "Change"). Appointment uses the
// existing /internal/calendar/book path (manual=true for internal after-hours/weekend rows); Personal reminder
// is a physician/admin-only calendar note (no patient, no portal, no notification).
function BookSlotDialog({ slot, canManual, onClose, onDone }) {
    const internal = !!slot.internal;
    const [kind, setKind] = useState("appointment"); // appointment | reminder
    const [editWhen, setEditWhen] = useState(!!slot.editWhen);
    const [date, setDate] = useState(slot.date);
    const [time, setTime] = useState(slot.time || "");
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [patient, setPatient] = useState(null);
    const [reason, setReason] = useState("");
    const [title, setTitle] = useState("");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);
    const [conflict, setConflict] = useState(null);
    const [overrideReason, setOverrideReason] = useState("");
    const whenLabel = `${formatDate(date)} · ${time ? labelOf(time) : "—"}`;

    const search = async (e) => {
        e.preventDefault();
        try { setResults((await api.get("/internal/patient-lookup", { params: { q } })).data); }
        catch (err) { toast.error(formatErr(err)); }
    };
    const submit = async (override = false) => {
        if (!date || !time) { toast.error("Please choose a date and time."); return; }
        setBusy(true);
        try {
            if (kind === "reminder") {
                await api.post("/internal/calendar/reminders", { date, time, title, note: note || null });
                toast.success("Reminder added to your calendar.");
                onDone(); onClose(); return;
            }
            const body = { date, time, reason: reason || null, manual: internal || editWhen };
            if (!body.manual) body.label = slot.label;
            if (patient.source === "portal") body.patient_id = patient.patient_id || patient.id;
            else body.directory_id = patient.directory_id || patient.id;
            if (override) { body.override_same_day = true; body.override_reason = overrideReason.trim(); }
            await api.post("/internal/calendar/book", body);
            toast.success(override ? "Appointment booked with same-day override (audited)." : "Appointment scheduled (confirmed) and patient notified.");
            onDone(); onClose();
        } catch (e) {
            if (isSameDayConflict(e)) { setConflict(e.response.data.detail); return; }
            toast.error(formatErr(e));
        } finally { setBusy(false); }
    };

    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-md" data-testid="cal-book-dialog">
                <DialogHeader><DialogTitle className="flex items-center justify-between gap-2 pr-6">
                    <span data-testid="cal-composer-when">{whenLabel}</span>
                    {!editWhen && <button type="button" data-testid="cal-composer-change-when" onClick={() => setEditWhen(true)} className="text-xs font-normal text-slate-400 hover:text-visita-greenDark">Change</button>}
                </DialogTitle></DialogHeader>
                {editWhen && (
                    <div className="grid grid-cols-2 gap-2" data-testid="cal-manual-when">
                        <div><Label className="text-xs">Date</Label><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="cal-manual-date" /></div>
                        <div><Label className="text-xs">Time</Label><Input type="time" step="300" value={time} onChange={(e) => setTime(e.target.value)} data-testid="cal-manual-time" /></div>
                    </div>
                )}
                {canManual && (
                    <div className="flex rounded-sm border border-slate-300 overflow-hidden text-xs" data-testid="cal-composer-kind">
                        <button type="button" data-testid="cal-kind-appointment" onClick={() => setKind("appointment")} className={`flex-1 px-3 py-1.5 ${kind === "appointment" ? "bg-visita-green text-white font-semibold" : "bg-white"}`}>Appointment</button>
                        <button type="button" data-testid="cal-kind-reminder" onClick={() => setKind("reminder")} className={`flex-1 px-3 py-1.5 border-l border-slate-300 flex items-center justify-center gap-1 ${kind === "reminder" ? "bg-visita-green text-white font-semibold" : "bg-white"}`}><Bell className="w-3 h-3" /> Personal reminder</button>
                    </div>
                )}
                {kind === "reminder" ? (
                    <div className="space-y-2 text-sm">
                        <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title — e.g. Call cardiologist, Review MRI" data-testid="cal-reminder-title" maxLength={120} />
                        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Short note (optional)" data-testid="cal-reminder-note" maxLength={500} />
                        <p className="text-[11px] text-slate-500">Private to the clinic calendar. No patient, portal or notification involved.</p>
                        <Button disabled={busy || !title.trim()} onClick={() => submit(false)} className="w-full bg-visita-green hover:bg-visita-greenDark text-white" data-testid="cal-reminder-save">Save reminder</Button>
                    </div>
                ) : !patient ? (
                    <div className="space-y-2">
                        <form onSubmit={search} className="flex gap-2">
                            <div className="relative flex-1"><Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                                <Input autoFocus className="pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Patient — name, DOB, phone, health card, or PIN" data-testid="cal-book-search" /></div>
                            <Button type="submit">Search</Button>
                        </form>
                        <div className="max-h-60 overflow-y-auto divide-y border rounded-sm">
                            {results.map((r) => (
                                <button key={r.id} data-testid="cal-book-result" onClick={() => setPatient(r)} className="w-full text-left px-2 py-1.5 text-sm hover:bg-slate-50">
                                    <div className="flex items-center gap-2">
                                        <span>{formatLastFirst(r.last_name, r.first_name)} · DOB {formatDate(r.date_of_birth)}</span>
                                        {r.source === "portal" && <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1">PORTAL</span>}
                                    </div>
                                    <div className="text-[11px] text-slate-400">{r.visita_patient_id ? `PIN ${r.visita_patient_id}` : "PIN Not assigned"}{r.source === "portal" ? " · Verified portal patient" : ""}</div>
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="space-y-3 text-sm">
                        <div>Patient: <b>{formatLastFirst(patient.last_name, patient.first_name)}</b> <button className="text-xs text-slate-400 ml-2" onClick={() => setPatient(null)}>change</button></div>
                        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)" data-testid="cal-book-reason" />
                        {conflict ? (
                            <SameDayOverride conflict={conflict} reason={overrideReason} setReason={setOverrideReason} busy={busy}
                                onConfirm={() => submit(true)} onCancel={onClose} />
                        ) : (
                            <Button disabled={busy} onClick={() => submit(false)} className="w-full bg-visita-green hover:bg-visita-greenDark text-white" data-testid="cal-book-confirm">Confirm & Schedule</Button>
                        )}
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
