import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CalendarDays } from "lucide-react";
import { api } from "../lib/api";
import { formatCombinedName } from "../lib/name";
import { formatDate } from "../lib/date";
import { StatusPill } from "./statusPill";

export function useAppointmentReviews() {
    return useQuery({
        queryKey: ["queue", "/internal/appointments/reviews"],
        queryFn: async () => (await api.get("/internal/appointments/reviews")).data,
        refetchInterval: 60000,
    });
}

const timeLabel = (t) => {
    if (!t) return "";
    const [h, m] = t.split(":").map(Number);
    return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
};

function ApptLine({ a, showDate }) {
    return (
        <li className="flex flex-wrap items-center gap-x-2 text-xs" data-testid="review-appt">
            <span className="text-slate-500">{a.ref_number}</span>
            <span className="font-semibold">{showDate ? `${formatDate(a.date)} · ` : ""}{timeLabel(a.time)}</span>
            <span className="text-slate-700">{a.reason || "—"}</span>
            <StatusPill status={a.status} />
            {a.same_day_override && <span className="text-[10px] font-bold text-amber-800 bg-amber-100 border border-amber-300 rounded px-1" title={a.same_day_override.reason}>OVERRIDE</span>}
        </li>
    );
}

export default function AppointmentReviews({ data, loading }) {
    const flags = data?.week_flags || [];
    const dupes = data?.same_day_duplicates || [];
    return (
        <div className="space-y-5" data-testid="appt-review-panel">
            <section>
                <h2 className="text-sm font-bold text-amber-800 flex items-center gap-2 mb-2">
                    <AlertTriangle className="w-4 h-4" /> MULTIPLE APPOINTMENTS THIS WEEK — REVIEW ({flags.length})
                </h2>
                <p className="text-xs text-slate-500 mb-2">Patients with 2 or more active appointments in the same Monday–Sunday week. Bookings were allowed; flags resolve automatically when cancellations bring the week below 2.</p>
                {loading && <div className="text-xs text-slate-400">Loading…</div>}
                {!loading && flags.length === 0 && <div className="text-sm text-slate-400 border border-dashed rounded-sm p-4 text-center" data-testid="week-flags-empty">No weekly review flags.</div>}
                <div className="space-y-2">
                    {flags.map((f) => (
                        <div key={f.id} className="bg-white border border-amber-300 rounded-sm p-3" data-testid="week-flag">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="font-semibold text-sm">
                                    {formatCombinedName(f.patient_name)} <span className="text-slate-500 font-normal">· PIN {f.pin || "—"}</span>
                                </div>
                                <div className="text-xs text-slate-600 flex items-center gap-1">
                                    <CalendarDays className="w-3.5 h-3.5" /> Week of {formatDate(f.week_start)} – {formatDate(f.week_end)} ·
                                    <b data-testid="week-flag-count">{f.count} appointments</b>
                                </div>
                            </div>
                            <ul className="mt-2 space-y-1">{(f.appointments || []).map((a) => <ApptLine key={a.id} a={a} showDate />)}</ul>
                        </div>
                    ))}
                </div>
            </section>
            <section>
                <h2 className="text-sm font-bold text-red-800 flex items-center gap-2 mb-2">
                    <AlertTriangle className="w-4 h-4" /> Same-day active duplicates ({dupes.length})
                </h2>
                <p className="text-xs text-slate-500 mb-2">Existing patients with more than one active appointment on the same day (today onward). Nothing is changed automatically — review and cancel or move from the Calendar if needed.</p>
                {!loading && dupes.length === 0 && <div className="text-sm text-slate-400 border border-dashed rounded-sm p-4 text-center" data-testid="same-day-dupes-empty">No same-day duplicates.</div>}
                <div className="space-y-2">
                    {dupes.map((g) => (
                        <div key={`${g.patient_key}-${g.date}`} className="bg-white border border-red-300 rounded-sm p-3" data-testid="same-day-dupe">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="font-semibold text-sm">{formatCombinedName(g.patient_name)} <span className="text-slate-500 font-normal">· PIN {g.pin || "—"}</span></div>
                                <div className="text-xs text-slate-600">{formatDate(g.date)} · <b>{g.count} appointments</b></div>
                            </div>
                            <ul className="mt-2 space-y-1">{g.appointments.map((a) => <ApptLine key={a.id} a={a} />)}</ul>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    );
}
