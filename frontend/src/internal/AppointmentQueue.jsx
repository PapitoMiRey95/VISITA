import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search, CalendarClock, UserX, Phone, CheckCircle2, XCircle } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatLastFirst, formatCombinedName } from "../lib/name";
import { useInvalidate } from "./hooks";
import { StatusPill } from "./statusPill";
import { KV } from "./Queue";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import BookAppointmentModal from "./BookAppointmentModal";
import CancelAppointmentDialog from "./CancelAppointmentDialog";
import { InternalNotes } from "./InternalNotes";
import { ApptTypeBadge } from "../components/ApptTypeBadge";
import { ApptTypeEditor } from "../components/ApptTypeEditor";
import { formatDate, formatDateTime } from "../lib/date";

const timeLabel = (t) => {
    if (!t) return "";
    const [h, m] = t.split(":").map(Number);
    return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
};
const whenOf = (a) => a.confirmed_display || (a.slot_date ? `${formatDate(a.slot_date)} · ${timeLabel(a.slot_time)}` : "—");

export default function AppointmentQueue() {
    const invalidate = useInvalidate();
    const [q, setQ] = useState("");
    const [view, setView] = useState("bookings"); // bookings | legacy | no_show | reschedule
    const [bookingSel, setBookingSel] = useState(null);
    const [status, setStatus] = useState("confirmed");
    const [sel, setSel] = useState(null);
    const [busy, setBusy] = useState(false);
    const [changeOpen, setChangeOpen] = useState(false);
    const [cancelOpen, setCancelOpen] = useState(false);
    const [linkOpen, setLinkOpen] = useState(false);
    const [linkQ, setLinkQ] = useState("");
    const [linkResults, setLinkResults] = useState([]);
    const [linkBusy, setLinkBusy] = useState(false);

    const list = useQuery({
        queryKey: ["queue", "/internal/appointments", q, status],
        queryFn: async () => (await api.get("/internal/appointments", { params: { q: q || undefined, status: status || undefined } })).data,
    });
    // Legacy pending requests (old approval workflow) — kept separate until resolved.
    const legacyQ = useQuery({
        queryKey: ["queue", "/internal/appointments", "legacy-requested"],
        queryFn: async () => (await api.get("/internal/appointments", { params: { status: "requested" } })).data,
    });
    const legacy = legacyQ.data || [];
    const followupsQ = useQuery({
        queryKey: ["queue", "/internal/appointments/followups"],
        queryFn: async () => (await api.get("/internal/appointments/followups")).data,
        enabled: view !== "queue",
    });
    const [feeBusy, setFeeBusy] = useState(null);

    const issueNoShowFee = async (row) => {
        if (!window.confirm(`Issue a $40 no-show fee invoice to ${formatCombinedName(row.patient_name)}?`)) return;
        setFeeBusy(row.id);
        try {
            await api.post(`/internal/appointments/${row.id}/no-show-invoice`);
            toast.success("$40 no-show invoice issued to the patient.");
            invalidate(); followupsQ.refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setFeeBusy(null); }
    };
    const removeNoShowFee = async (row) => {
        if (!row.no_show_invoice) return;
        const reason = window.prompt("Remove the no-show charge — reason (e.g. doctor waived):", "Doctor waived — do not charge") || undefined;
        setFeeBusy(row.id);
        try {
            await api.post(`/internal/invoices/${row.no_show_invoice.id}/void`, { reason });
            toast.success("No-show charge removed (invoice voided).");
            invalidate(); followupsQ.refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setFeeBusy(null); }
    };

    const open = (i) => { setSel(i); setLinkOpen(false); setLinkQ(""); setLinkResults([]); };
    const close = () => setSel(null);
    const refreshAll = () => { invalidate(); list.refetch(); legacyQ.refetch(); };

    const searchDirectory = async () => {
        if (!linkQ.trim()) return;
        setLinkBusy(true);
        try {
            const r = await api.get("/internal/directory", { params: { q: linkQ.trim() } });
            setLinkResults(r.data || []);
        } catch (e) { toast.error(formatErr(e)); } finally { setLinkBusy(false); }
    };
    const linkPatient = async (directoryId) => {
        setLinkBusy(true);
        try {
            await api.post(`/internal/appointments/${sel.id}/link-patient`, { directory_id: directoryId });
            toast.success("Patient linked to appointment.");
            refreshAll(); close();
        } catch (e) { toast.error(formatErr(e)); } finally { setLinkBusy(false); }
    };

    const undoStatus = async (id) => {
        try {
            await api.patch(`/internal/appointments/${id}`, { action: "undo_status" });
            toast.success("Reverted to Confirmed."); refreshAll();
        } catch (e) { toast.error(formatErr(e)); }
    };

    const act = async (body, okMsg) => {
        setBusy(true);
        const id = sel.id;
        try {
            await api.patch(`/internal/appointments/${id}`, body);
            if (body.action === "no_show" || body.action === "complete") {
                toast.success(body.action === "no_show" ? "Marked as No Show." : "Marked as Completed.", {
                    action: { label: "Undo", onClick: () => undoStatus(id) }, duration: 8000,
                });
            } else {
                toast.success(okMsg || "Appointment updated.");
            }
            refreshAll(); close();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const items = list.data || [];
    const isReq = sel?.status === "requested";
    const isConf = sel?.status === "confirmed" || sel?.status === "rescheduled";

    return (
        <div className="animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Recent Bookings</h1>
            <p className="text-sm text-slate-500 mb-3">Verified patients book directly — appointments are confirmed instantly. Use the Calendar to change or cancel a booking.</p>

            <div className="flex gap-1 mb-3 border-b border-slate-200 flex-wrap">
                {[["bookings", "Recent Bookings"], ["legacy", `Legacy pending requests (${legacy.length})`], ["no_show", "No-Shows"], ["reschedule", "Reschedule Requested"]].map(([v, l]) => (
                    <button key={v} data-testid={`appt-tab-${v}`} onClick={() => setView(v)}
                        className={`px-3 py-2 text-sm font-semibold -mb-px border-b-2 ${view === v ? "border-visita-green text-visita-greenDark" : "border-transparent text-slate-500 hover:text-slate-700"} ${v === "legacy" && legacy.length ? "text-amber-700" : ""}`}>
                        {v === "no_show" && <UserX className="w-4 h-4 inline mr-1" />}
                        {v === "reschedule" && <CalendarClock className="w-4 h-4 inline mr-1" />}
                        {l}
                    </button>
                ))}
            </div>

            {view === "no_show" && <FollowupTable testid="no-show-table" rows={followupsQ.data?.no_shows || []} emptyText="No patients flagged as no-show."
                onIssueFee={issueNoShowFee} onRemoveFee={removeNoShowFee} feeBusy={feeBusy} />}
            {view === "reschedule" && <FollowupTable testid="reschedule-table" rows={followupsQ.data?.reschedules || []} showType emptyText="No reschedule requests." />}

            {view === "bookings" && <RecentBookings items={items} q={q} setQ={setQ} status={status} setStatus={setStatus} onOpen={setBookingSel} />}

            {view === "legacy" && (<>
                <div className="bg-amber-50 border border-amber-200 rounded-sm p-2 mb-3 text-xs text-amber-800" data-testid="legacy-pending-banner">
                    These are older requests created under the previous approval workflow. Approve, change time or cancel each one; new verified-patient bookings no longer arrive here.
                </div>
                <div className="flex flex-wrap items-center gap-2 mb-3">
                    <div className="relative">
                        <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                        <Input data-testid="queue-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search patient, reason, APT-…" className="pl-8 h-9 w-64 bg-white" />
                    </div>

                </div>

                <div className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="bg-slate-100 text-left text-xs uppercase tracking-wider text-slate-600">
                                <th className="px-3 py-2 font-medium">Ref</th><th className="px-3 py-2 font-medium">Patient</th>
                                <th className="px-3 py-2 font-medium">PIN</th>
                                <th className="px-3 py-2 font-medium">Reason</th><th className="px-3 py-2 font-medium">Type</th>
                                <th className="px-3 py-2 font-medium">Requested / Confirmed time</th>
                                <th className="px-3 py-2 font-medium">Status</th><th />
                            </tr>
                        </thead>
                        <tbody>
                            {legacy.length === 0 && <tr><td colSpan={8} className="px-3 py-8 text-center text-slate-400">No legacy pending requests — all clear.</td></tr>}
                            {legacy.map((i) => (
                                <tr key={i.id} data-testid="queue-row" onClick={() => open(i)} className={`border-b border-slate-200 even:bg-slate-50/60 hover:bg-visita-bg cursor-pointer ${i.status === "cancelled" ? "text-red-700" : ""}`}>
                                    <td className="px-3 py-2 text-slate-500">{i.ref_number}</td>
                                    <td className="px-3 py-2 font-semibold">{formatCombinedName(i.patient_name)}</td>
                                    <td className="px-3 py-2 text-slate-500">{i.patient_pin || "—"}</td>
                                    <td className="px-3 py-2">{i.reason}</td>
                                    <td className="px-3 py-2"><ApptTypeBadge type={i.appointment_type} /></td>
                                    <td className="px-3 py-2" data-testid="queue-when">{whenOf(i)}</td>
                                    <td className="px-3 py-2"><StatusPill status={i.status} /></td>
                                    <td className="px-3 py-2 text-right"><Button size="sm" variant="ghost" className="h-7 text-visita-green" data-testid="queue-open">Open</Button></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </>)}

            <Dialog open={!!sel} onOpenChange={(o) => !o && close()}>
                <DialogContent className="max-w-lg font-plex max-h-[90vh] overflow-y-auto" data-testid="appt-request-dialog">
                    {sel && (
                        <>
                            <DialogHeader><DialogTitle>{sel.ref_number} · {formatCombinedName(sel.patient_name)}</DialogTitle></DialogHeader>
                            {sel.patient_link_required && (
                                <div className="bg-amber-50 border border-amber-200 rounded-sm p-2 mb-1" data-testid="patient-link-required">
                                    <div className="flex items-center justify-between gap-2">
                                        <div className="text-xs text-amber-800">
                                            <span className="font-bold">PATIENT LINK REQUIRED</span>
                                            <div>Imported as: <span className="font-semibold">{formatCombinedName(sel.original_imported_name || sel.patient_name)}</span></div>
                                        </div>
                                        <Button size="sm" variant="outline" className="text-amber-800 border-amber-300" data-testid="link-patient-open"
                                            onClick={() => setLinkOpen((v) => !v)}>{linkOpen ? "Close" : "Link Patient"}</Button>
                                    </div>
                                    {linkOpen && (
                                        <div className="mt-2" data-testid="link-patient-panel">
                                            <div className="flex gap-2">
                                                <Input value={linkQ} onChange={(e) => setLinkQ(e.target.value)}
                                                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), searchDirectory())}
                                                    placeholder="Search name, VISITA ID or Health Card" className="h-9 bg-white" data-testid="link-patient-search" />
                                                <Button size="sm" onClick={searchDirectory} disabled={linkBusy} data-testid="link-patient-search-btn"
                                                    className="bg-visita-green hover:bg-visita-greenDark text-white">Search</Button>
                                            </div>
                                            <div className="mt-2 max-h-56 overflow-y-auto divide-y border border-slate-200 rounded-sm bg-white">
                                                {linkResults.length === 0 && <div className="px-2 py-3 text-xs text-slate-400">No results yet — search above.</div>}
                                                {linkResults.map((r) => (
                                                    <div key={r.id} className="flex items-center justify-between gap-2 px-2 py-1.5" data-testid="link-patient-result">
                                                        <div className="text-xs">
                                                            <div className="font-semibold text-slate-800">{formatLastFirst(r.last_name, r.first_name)}</div>
                                                            <div className="text-slate-500">DOB {formatDate(r.date_of_birth)} · VISITA {r.visita_patient_id || "—"} · {r.patient_status}</div>
                                                        </div>
                                                        <Button size="sm" variant="outline" disabled={linkBusy} onClick={() => linkPatient(r.id)}
                                                            data-testid={`link-to-appointment-${r.id}`}>Link</Button>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}

                            <div className="space-y-2 text-sm">
                                <div className="grid grid-cols-2 gap-x-4 gap-y-1 bg-slate-50 border border-slate-200 rounded-sm p-2" data-testid="appt-patient-block">
                                    <KV label="Patient">{formatCombinedName(sel.patient_name)}</KV>
                                    <KV label="PIN">{sel.patient_pin || "—"}</KV>
                                    <KV label="DOB">{sel.patient_dob ? formatDate(sel.patient_dob) : "—"}</KV>
                                    <KV label="Phone">{sel.patient_phone ? <a href={`tel:${sel.patient_phone}`} className="text-visita-greenDark underline" data-testid="appt-phone">{sel.patient_phone}</a> : "—"}</KV>
                                </div>
                                <div className="flex items-center gap-2" data-testid="appt-detail-type">
                                    <ApptTypeEditor appt={sel} size="lg" onSaved={(updated) => { setSel({ ...sel, ...updated }); refreshAll(); }} />
                                </div>
                                <KV label={isReq ? "Requested date/time" : "Date/time"}>
                                    <span className={isReq ? "text-amber-700 font-semibold" : "font-semibold"} data-testid="appt-when">{whenOf(sel)}</span>
                                    {isReq && <span className="ml-2 text-xs text-amber-700">(time held)</span>}
                                </KV>
                                {sel.original_requested_slot && sel.original_requested_slot.date !== sel.slot_date && (
                                    <KV label="Originally requested">{formatDate(sel.original_requested_slot.date)} · {timeLabel(sel.original_requested_slot.time)}</KV>
                                )}
                                <KV label="Reason">{sel.reason}</KV>
                                <KV label="Patient note">{sel.patient_note || "—"}</KV>
                                <KV label="Status"><StatusPill status={sel.status} /></KV>
                                {sel.submitted_by_delegate && <div className="text-xs text-sky-700">Submitted by caregiver on behalf of the patient.</div>}

                                {sel.status === "cancelled" && sel.cancellation && (
                                    <div className="bg-red-50 border border-red-200 rounded-sm p-2 text-xs text-red-800" data-testid="appt-cancellation-block">
                                        <div className="font-bold">CANCELLED — {sel.cancellation.free_slot ? "time freed" : "time kept blocked"}</div>
                                        <div>Reason: {sel.cancellation.reason}</div>
                                        <div>By {sel.cancelled_by} · {sel.cancelled_at ? formatDateTime(sel.cancelled_at) : ""}</div>
                                    </div>
                                )}
                                {sel.status === "declined" && (
                                    <div className="bg-red-50 border border-red-200 rounded-sm p-2 text-xs text-red-800" data-testid="appt-declined-block">
                                        Declined by {sel.declined_by || "clinic"}{sel.declined_at ? ` · ${formatDateTime(sel.declined_at)}` : ""} — time released.
                                        {sel.staff_note && <div>Note to patient: {sel.staff_note}</div>}
                                    </div>
                                )}

                                {isReq && (
                                    <div className="pt-2 space-y-2" data-testid="appt-request-actions">
                                        <Button disabled={busy} onClick={() => act({ action: "approve" }, "Appointment approved and patient notified.")}
                                            data-testid="appt-approve" className="w-full bg-visita-green hover:bg-visita-greenDark text-white h-11">
                                            <CheckCircle2 className="w-4 h-4 mr-1" /> Approve Appointment
                                        </Button>
                                        <div className="flex flex-wrap gap-2">
                                            <Button disabled={busy} variant="outline" onClick={() => setChangeOpen(true)} data-testid="appt-change-time">
                                                <CalendarClock className="w-4 h-4 mr-1" /> Change Time
                                            </Button>
                                            <Button disabled={busy} variant="outline" onClick={() => setCancelOpen(true)} data-testid="appt-cancel-notify" className="text-red-600 border-red-200">
                                                <XCircle className="w-4 h-4 mr-1" /> Cancel & Notify
                                            </Button>
                                            {sel.patient_phone && (
                                                <Button asChild variant="outline" data-testid="appt-call-patient">
                                                    <a href={`tel:${sel.patient_phone}`}><Phone className="w-4 h-4 mr-1" /> Call Patient</a>
                                                </Button>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {isConf && (
                                    <div className="bg-emerald-50 border border-emerald-200 rounded-sm p-2" data-testid="appt-confirmed-block">
                                        <div className="text-emerald-800 font-semibold">Confirmed: {whenOf(sel)}</div>
                                        {sel.booked_from && <div className="text-xs text-emerald-700">Booked from {sel.booked_from.source_type} {sel.booked_from.source_ref || ""}</div>}
                                        <div className="flex gap-2 mt-2 flex-wrap">
                                            <Button size="sm" variant="outline" data-testid="appt-change-time" onClick={() => setChangeOpen(true)}>
                                                <CalendarClock className="w-4 h-4 mr-1" /> Change Time
                                            </Button>
                                            <Button size="sm" variant="outline" data-testid="appt-complete" disabled={busy} onClick={() => act({ action: "complete" })}>Completed</Button>
                                            <Button size="sm" variant="outline" className="text-amber-700 border-amber-200" data-testid="appt-noshow" disabled={busy} onClick={() => act({ action: "no_show" })}>No Show</Button>
                                            <Button size="sm" variant="outline" className="text-red-600 border-red-200" data-testid="appt-cancel" disabled={busy} onClick={() => setCancelOpen(true)}>Cancel</Button>
                                            {sel.patient_phone && (
                                                <Button asChild size="sm" variant="outline" data-testid="appt-call-patient">
                                                    <a href={`tel:${sel.patient_phone}`}><Phone className="w-4 h-4 mr-1" /> Call</a>
                                                </Button>
                                            )}
                                        </div>
                                        <div className="flex gap-2 mt-2 flex-wrap items-center border-t border-emerald-200 pt-2" data-testid="late-fee-controls">
                                            {sel.late_fee?.status === "outstanding" ? (
                                                <>
                                                    <span className="text-xs font-semibold text-red-700" data-testid="fee-status">Late fee ${sel.late_fee.amount} — Outstanding</span>
                                                    <Button size="sm" variant="outline" data-testid="appt-fee-paid" disabled={busy} onClick={() => act({ action: "mark_fee_paid" })}>Mark Fee Paid</Button>
                                                    <Button size="sm" variant="outline" data-testid="appt-fee-waive" disabled={busy} onClick={() => act({ action: "waive_fee" })}>Waive Fee</Button>
                                                </>
                                            ) : sel.late_fee ? (
                                                <span className="text-xs font-semibold text-slate-600" data-testid="fee-status">Late fee ${sel.late_fee.amount} — {sel.late_fee.status === "paid" ? "Paid" : "Waived"}</span>
                                            ) : (
                                                <Button size="sm" variant="outline" className="text-amber-700 border-amber-200" data-testid="appt-record-fee" disabled={busy} onClick={() => act({ action: "record_fee" })}>Record $40 Late Fee</Button>
                                            )}
                                        </div>
                                    </div>
                                )}

                                <InternalNotes appt={sel} onSaved={(updated) => { setSel({ ...sel, ...updated }); refreshAll(); }} />

                                {(sel.history || []).length > 0 && (
                                    <details className="text-xs text-slate-500" data-testid="appt-history">
                                        <summary className="cursor-pointer">History ({sel.history.length})</summary>
                                        <ul className="mt-1 space-y-0.5">
                                            {[...sel.history].reverse().map((h, i) => (
                                                <li key={i}>{h.at ? formatDateTime(h.at) : ""} · <b>{h.status}</b> · {h.by}{h.note ? ` — ${h.note}` : ""}</li>
                                            ))}
                                        </ul>
                                    </details>
                                )}
                            </div>
                        </>
                    )}
                </DialogContent>
            </Dialog>

            {sel && changeOpen && (
                <BookAppointmentModal open onClose={() => setChangeOpen(false)} onDone={() => { refreshAll(); close(); }} mode="reschedule" source={sel} />
            )}
            {sel && cancelOpen && (
                <CancelAppointmentDialog appt={sel} onClose={() => setCancelOpen(false)} onDone={() => { refreshAll(); close(); }} />
            )}
            {bookingSel && <BookingDetail appt={bookingSel} onClose={() => setBookingSel(null)} onSaved={(u) => setBookingSel({ ...bookingSel, ...u })} />}
        </div>
    );
}

// Informational list of confirmed bookings, most recently booked first. Schedule changes live in the Calendar.
function RecentBookings({ items, q, setQ, status, setStatus, onOpen }) {
    const rows = [...items].sort((a, b) => (b.booked_at || "").localeCompare(a.booked_at || ""));
    const chips = [["confirmed", "Confirmed"], ["cancelled", "Cancelled"], ["completed", "Completed"], ["", "All"]];
    return (<>
        <div className="flex flex-wrap items-center gap-2 mb-3">
            <div className="relative">
                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                <Input data-testid="bookings-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search patient, reason, APT-…" className="pl-8 h-9 w-64 bg-white" />
            </div>
            <div className="flex gap-1 flex-wrap">
                {chips.map(([v, l]) => (
                    <button key={l} data-testid={`bookings-filter-${l.toLowerCase()}`} onClick={() => setStatus(v)}
                        className={`px-2.5 py-1 rounded-sm text-xs font-medium border ${status === v ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-300"}`}>{l}</button>
                ))}
            </div>
        </div>
        <div className="bg-white border border-slate-300 rounded-sm overflow-hidden" data-testid="recent-bookings-table">
            <table className="w-full text-sm">
                <thead>
                    <tr className="bg-slate-100 text-left text-xs uppercase tracking-wider text-slate-600">
                        <th className="px-3 py-2 font-medium">Patient</th><th className="px-3 py-2 font-medium">PIN</th>
                        <th className="px-3 py-2 font-medium">Phone</th><th className="px-3 py-2 font-medium">Appointment</th>
                        <th className="px-3 py-2 font-medium">Type</th><th className="px-3 py-2 font-medium">Reason</th>
                        <th className="px-3 py-2 font-medium">Booked at</th><th className="px-3 py-2 font-medium">Status</th><th />
                    </tr>
                </thead>
                <tbody>
                    {rows.length === 0 && <tr><td colSpan={9} className="px-3 py-8 text-center text-slate-400">No bookings.</td></tr>}
                    {rows.map((i) => (
                        <tr key={i.id} data-testid="booking-row" onClick={() => onOpen(i)} className={`border-b border-slate-200 even:bg-slate-50/60 hover:bg-visita-bg cursor-pointer ${i.status === "cancelled" ? "text-red-700" : ""}`}>
                            <td className="px-3 py-2 font-semibold">{formatCombinedName(i.patient_name)}<div className="text-xs font-normal text-slate-400">{i.ref_number}</div></td>
                            <td className="px-3 py-2 text-slate-500">{i.patient_pin || "—"}</td>
                            <td className="px-3 py-2">{i.patient_phone ? <a href={`tel:${i.patient_phone}`} className="text-visita-greenDark underline" onClick={(e) => e.stopPropagation()}>{i.patient_phone}</a> : "—"}</td>
                            <td className="px-3 py-2 font-semibold" data-testid="booking-when">{whenOf(i)}</td>
                            <td className="px-3 py-2"><ApptTypeBadge type={i.appointment_type} /></td>
                            <td className="px-3 py-2">{i.reason}</td>
                            <td className="px-3 py-2 text-slate-500" data-testid="booking-booked-at">{i.booked_at ? formatDateTime(i.booked_at) : "—"}<div className="text-xs text-slate-400">{i.booked_by_label}</div></td>
                            <td className="px-3 py-2"><StatusPill status={i.status} /></td>
                            <td className="px-3 py-2 text-right"><Button size="sm" variant="ghost" className="h-7 text-visita-green" data-testid="booking-open">Open</Button></td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    </>);
}

// Informational only — no approval/decline. Schedule changes are done in the Calendar.
function BookingDetail({ appt, onClose, onSaved }) {
    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-md font-plex max-h-[90vh] overflow-y-auto" data-testid="booking-detail-dialog">
                <DialogHeader><DialogTitle>{appt.ref_number} · {formatCombinedName(appt.patient_name)}</DialogTitle></DialogHeader>
                <div className="space-y-2 text-sm">
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 bg-slate-50 border border-slate-200 rounded-sm p-2">
                        <KV label="Patient">{formatCombinedName(appt.patient_name)}</KV>
                        <KV label="PIN">{appt.patient_pin || "—"}</KV>
                        <KV label="DOB">{appt.patient_dob ? formatDate(appt.patient_dob) : "—"}</KV>
                        <KV label="Phone">{appt.patient_phone ? <a href={`tel:${appt.patient_phone}`} className="text-visita-greenDark underline">{appt.patient_phone}</a> : "—"}</KV>
                    </div>
                    <KV label="Appointment"><span className="font-semibold" data-testid="booking-detail-when">{whenOf(appt)}</span></KV>
                    <KV label="Type"><ApptTypeBadge type={appt.appointment_type} /></KV>
                    <KV label="Reason">{appt.reason}</KV>
                    <KV label="Patient note">{appt.patient_note || "—"}</KV>
                    <KV label="Booked at">{appt.booked_at ? formatDateTime(appt.booked_at) : "—"}</KV>
                    <KV label="Booked by">{appt.booked_by_label}</KV>
                    <KV label="Status"><StatusPill status={appt.status} /></KV>
                    {appt.status === "cancelled" && appt.cancellation && (
                        <div className="bg-red-50 border border-red-200 rounded-sm p-2 text-xs text-red-800">
                            Cancelled — {appt.cancellation.reason} — {appt.cancellation.free_slot ? "time freed" : "time kept blocked"} · by {appt.cancelled_by}
                        </div>
                    )}
                    <p className="text-xs text-slate-500 border-t border-slate-200 pt-2" data-testid="booking-detail-hint">
                        To change the time, cancel, or mark completed / no-show, use the <b>Calendar</b>.
                    </p>
                    <InternalNotes appt={appt} onSaved={onSaved} />
                </div>
            </DialogContent>
        </Dialog>
    );
}

function FollowupTable({ rows, testid, showType = false, emptyText, onIssueFee, onRemoveFee, feeBusy }) {
    const showFee = !!onIssueFee;
    const cols = 4 + (showType ? 1 : 0) + (showFee ? 1 : 0);
    return (
        <div className="bg-white border border-slate-300 rounded-sm overflow-hidden" data-testid={testid}>
            <table className="w-full text-sm">
                <thead>
                    <tr className="bg-slate-100 text-left text-xs uppercase tracking-wider text-slate-600">
                        <th className="px-3 py-2 font-medium">Patient</th>
                        <th className="px-3 py-2 font-medium">Appointment</th>
                        <th className="px-3 py-2 font-medium">Reason</th>
                        {showType && <th className="px-3 py-2 font-medium">Type</th>}
                        <th className="px-3 py-2 font-medium">By</th>
                        <th className="px-3 py-2 font-medium">When</th>
                        {showFee && <th className="px-3 py-2 font-medium">No-Show Fee ($40)</th>}
                    </tr>
                </thead>
                <tbody>
                    {rows.length === 0 && <tr><td colSpan={cols} className="px-3 py-8 text-center text-slate-400">{emptyText}</td></tr>}
                    {rows.map((r) => (
                        <tr key={r.id} data-testid="followup-row" className="border-b border-slate-200 even:bg-slate-50/60">
                            <td className="px-3 py-2 font-semibold">{formatCombinedName(r.patient_name)}<div className="text-xs font-normal text-slate-400">{r.ref_number}</div></td>
                            <td className="px-3 py-2">{r.appt_display}</td>
                            <td className="px-3 py-2">{r.reason || "—"}</td>
                            {showType && <td className="px-3 py-2">
                                <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold ${r.resched_type === "offered" ? "bg-amber-100 text-amber-700" : "bg-sky-100 text-sky-700"}`}>
                                    {r.resched_type === "offered" ? "Awaiting patient (legacy)" : "Staff rescheduled"}
                                </span>
                            </td>}
                            <td className="px-3 py-2 text-slate-600">{r.actor || "—"}</td>
                            <td className="px-3 py-2 text-slate-500">{r.actor_at ? formatDateTime(r.actor_at) : "—"}</td>
                            {showFee && <td className="px-3 py-2">
                                {r.no_show_invoice ? (
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="inline-block px-2 py-0.5 rounded-sm text-xs font-semibold bg-emerald-100 text-emerald-700">
                                            {r.no_show_invoice.invoice_number} · {r.no_show_invoice.status}
                                        </span>
                                        <Button size="sm" variant="outline" data-testid={`no-show-remove-${r.id}`} disabled={feeBusy === r.id}
                                            onClick={() => onRemoveFee(r)} className="h-7 text-red-600 border-red-200">Remove charge</Button>
                                    </div>
                                ) : (
                                    <Button size="sm" data-testid={`no-show-fee-${r.id}`} disabled={feeBusy === r.id || !r.patient_id}
                                        title={!r.patient_id ? "Link a portal patient first" : "Issue a $40 no-show invoice"}
                                        onClick={() => onIssueFee(r)} className="h-7 bg-visita-green hover:bg-visita-greenDark text-white">Issue $40 fee</Button>
                                )}
                            </td>}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
