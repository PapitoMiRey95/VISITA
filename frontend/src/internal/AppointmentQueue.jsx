import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search, CalendarClock } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { StatusPill } from "./statusPill";
import { KV } from "./Queue";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import BookAppointmentModal from "./BookAppointmentModal";
import { formatDate } from "../lib/date";

export default function AppointmentQueue() {
    const invalidate = useInvalidate();
    const [q, setQ] = useState("");
    const [status, setStatus] = useState("requested");
    const [sel, setSel] = useState(null);
    const [cdate, setCdate] = useState("");
    const [ctime, setCtime] = useState("");
    const [cdisplay, setCdisplay] = useState("");
    const [staffNote, setStaffNote] = useState("");
    const [offerMode, setOfferMode] = useState(false);
    const [chosen, setChosen] = useState([]); // slot objects
    const [busy, setBusy] = useState(false);
    const [reschedOpen, setReschedOpen] = useState(false);
    const [linkOpen, setLinkOpen] = useState(false);
    const [linkQ, setLinkQ] = useState("");
    const [linkResults, setLinkResults] = useState([]);
    const [linkBusy, setLinkBusy] = useState(false);

    const list = useQuery({
        queryKey: ["queue", "/internal/appointments", q, status],
        queryFn: async () => (await api.get("/internal/appointments", { params: { q: q || undefined, status: status || undefined } })).data,
    });
    const slotsQ = useQuery({
        queryKey: ["slots"],
        queryFn: async () => (await api.get("/availability/slots", { params: { days: 28 } })).data,
        enabled: offerMode,
    });
    const slots = slotsQ.data?.slots || [];

    const open = (i) => {
        setSel(i); setOfferMode(false); setChosen([]); setStaffNote("");
        setLinkOpen(false); setLinkQ(""); setLinkResults([]);
        const o1 = (i.preferred_options || [])[0] || {};
        setCdate(o1.date || ""); setCtime(o1.time || ""); setCdisplay(o1.display || "");
    };
    const close = () => setSel(null);

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
            invalidate(); list.refetch(); close();
        } catch (e) { toast.error(formatErr(e)); } finally { setLinkBusy(false); }
    };

    const applyOption = (o) => { setCdate(o.date); setCtime(o.time); setCdisplay(o.display); };

    const toggleSlot = (s) => {
        setChosen((prev) => {
            const exists = prev.find((x) => x.date === s.date && x.time === s.time);
            if (exists) return prev.filter((x) => !(x.date === s.date && x.time === s.time));
            if (prev.length >= 3) { toast.error("You can offer up to 3 times."); return prev; }
            return [...prev, s];
        });
    };

    const act = async (body) => {
        setBusy(true);
        try {
            await api.patch(`/internal/appointments/${sel.id}`, body);
            toast.success("Appointment updated.");
            invalidate(); list.refetch(); close();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const items = list.data || [];
    const chips = [["requested", "Requested"], ["", "All"], ["alternatives_offered", "Awaiting Patient"], ["confirmed", "Confirmed"], ["declined", "Declined"]];

    return (
        <div className="animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Appointment Requests</h1>
            <p className="text-sm text-slate-500 mb-3">Approve a requested time or offer available alternatives.</p>

            <div className="flex flex-wrap items-center gap-2 mb-3">
                <div className="relative">
                    <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                    <Input data-testid="queue-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search patient, reason, APT-…" className="pl-8 h-9 w-64 bg-white" />
                </div>
                <div className="flex gap-1 flex-wrap">
                    {chips.map(([v, l]) => (
                        <button key={l} data-testid={`filter-${l.toLowerCase().replace(/ /g, "-")}`} onClick={() => setStatus(v)}
                            className={`px-2.5 py-1 rounded-sm text-xs font-medium border ${status === v ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-300"}`}>{l}</button>
                    ))}
                </div>
            </div>

            <div className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="bg-slate-100 text-left text-xs uppercase tracking-wider text-slate-600">
                            <th className="px-3 py-2 font-medium">Ref</th><th className="px-3 py-2 font-medium">Patient</th>
                            <th className="px-3 py-2 font-medium">Reason</th><th className="px-3 py-2 font-medium">Preferred #1</th>
                            <th className="px-3 py-2 font-medium">Status</th><th />
                        </tr>
                    </thead>
                    <tbody>
                        {items.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-400">No appointment requests.</td></tr>}
                        {items.map((i) => (
                            <tr key={i.id} data-testid="queue-row" onClick={() => open(i)} className="border-b border-slate-200 even:bg-slate-50/60 hover:bg-visita-bg cursor-pointer">
                                <td className="px-3 py-2 text-slate-500">{i.ref_number}</td>
                                <td className="px-3 py-2 font-semibold">{i.patient_name}</td>
                                <td className="px-3 py-2">{i.reason}</td>
                                <td className="px-3 py-2">{(i.preferred_options || [])[0] ? `${formatDate((i.preferred_options || [])[0].date)} · ${(i.preferred_options || [])[0].label || (i.preferred_options || [])[0].time}` : "—"}</td>
                                <td className="px-3 py-2"><StatusPill status={i.status} /></td>
                                <td className="px-3 py-2 text-right"><Button size="sm" variant="ghost" className="h-7 text-visita-green" data-testid="queue-open">Open</Button></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <Dialog open={!!sel} onOpenChange={(o) => !o && close()}>
                <DialogContent className="max-w-lg font-plex max-h-[90vh] overflow-y-auto">
                    {sel && (
                        <>
                            <DialogHeader><DialogTitle>{sel.ref_number} · {sel.patient_name}</DialogTitle></DialogHeader>
                            {sel.patient_link_required && (
                                <div className="bg-amber-50 border border-amber-200 rounded-sm p-2 mb-1" data-testid="patient-link-required">
                                    <div className="flex items-center justify-between gap-2">
                                        <div className="text-xs text-amber-800">
                                            <span className="font-bold">PATIENT LINK REQUIRED</span>
                                            <div>Imported as: <span className="font-semibold">{sel.original_imported_name || sel.patient_name}</span></div>
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
                                                            <div className="font-semibold text-slate-800">{r.last_name}, {r.first_name}</div>
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
                                <KV label="Reason">{sel.reason}</KV>
                                {sel.status === "confirmed" && (
                                    <div className="bg-emerald-50 border border-emerald-200 rounded-sm p-2" data-testid="appt-confirmed-block">
                                        <div className="text-emerald-800 font-semibold">Confirmed: {`${formatDate(sel.confirmed_date)} · ${sel.confirmed_time}`}</div>
                                        {sel.booked_from && <div className="text-xs text-emerald-700">Booked from {sel.booked_from.source_type} {sel.booked_from.source_ref}</div>}
                                        <div className="flex gap-2 mt-2 flex-wrap">
                                            <Button size="sm" variant="outline" data-testid="appt-reschedule" onClick={() => setReschedOpen(true)}>
                                                <CalendarClock className="w-4 h-4 mr-1" /> Reschedule
                                            </Button>
                                            <Button size="sm" variant="outline" data-testid="appt-complete" disabled={busy}
                                                onClick={() => act({ action: "complete" })}>Completed</Button>
                                            <Button size="sm" variant="outline" className="text-amber-700 border-amber-200" data-testid="appt-noshow" disabled={busy}
                                                onClick={() => act({ action: "no_show" })}>No Show</Button>
                                            <Button size="sm" variant="outline" className="text-red-600 border-red-200" data-testid="appt-cancel"
                                                disabled={busy} onClick={() => act({ action: "cancel", staff_note: staffNote || undefined })}>
                                                Cancel
                                            </Button>
                                        </div>
                                        <div className="flex gap-2 mt-2 flex-wrap items-center border-t border-emerald-200 pt-2" data-testid="late-fee-controls">
                                            {sel.late_fee?.status === "outstanding" ? (
                                                <>
                                                    <span className="text-xs font-semibold text-red-700" data-testid="fee-status">Late fee ${sel.late_fee.amount} — Outstanding</span>
                                                    <Button size="sm" variant="outline" data-testid="appt-fee-paid" disabled={busy}
                                                        onClick={() => act({ action: "mark_fee_paid" })}>Mark Fee Paid</Button>
                                                    <Button size="sm" variant="outline" data-testid="appt-fee-waive" disabled={busy}
                                                        onClick={() => act({ action: "waive_fee" })}>Waive Fee</Button>
                                                </>
                                            ) : sel.late_fee ? (
                                                <span className="text-xs font-semibold text-slate-600" data-testid="fee-status">
                                                    Late fee ${sel.late_fee.amount} — {sel.late_fee.status === "paid" ? "Paid" : "Waived"}
                                                </span>
                                            ) : (
                                                <Button size="sm" variant="outline" className="text-amber-700 border-amber-200" data-testid="appt-record-fee"
                                                    disabled={busy} onClick={() => act({ action: "record_fee" })}>Record $40 Late Fee</Button>
                                            )}
                                        </div>
                                    </div>
                                )}
                                <div>
                                    <div className="text-slate-500 mb-1">Preferred options</div>
                                    <div className="space-y-1">
                                        {(sel.preferred_options || []).map((o, idx) => (
                                            <button key={o.display || `${o.date}-${o.time}`} onClick={() => applyOption(o)} data-testid={`use-option-${idx}`}
                                                className="w-full text-left px-2 py-1 rounded-sm border border-slate-200 hover:bg-visita-greenLight text-slate-800">
                                                {idx + 1}. {`${formatDate(o.date)} · ${o.label || o.time}`}
                                            </button>
                                        ))}
                                        {(sel.preferred_options || []).length === 0 && <span className="text-slate-400">None provided</span>}
                                    </div>
                                </div>
                                <KV label="Patient note">{sel.patient_note}</KV>

                                {!offerMode && (
                                    <>
                                        <div className="grid grid-cols-2 gap-2 pt-1">
                                            <div><Label className="text-xs">Confirmed date</Label><Input type="date" value={cdate} onChange={(e) => { setCdate(e.target.value); setCdisplay(""); }} data-testid="appt-confirm-date" /></div>
                                            <div><Label className="text-xs">Confirmed time</Label><Input type="time" value={ctime} onChange={(e) => { setCtime(e.target.value); setCdisplay(""); }} data-testid="appt-confirm-time" /></div>
                                        </div>
                                        <div className="flex flex-wrap gap-2 pt-2">
                                            <Button disabled={busy} onClick={() => act({ action: "approve", confirmed_date: cdate, confirmed_time: ctime, confirmed_display: cdisplay || undefined })} data-testid="appt-approve" className="bg-visita-green hover:bg-visita-greenDark text-white">Approve</Button>
                                            <Button disabled={busy} variant="outline" onClick={() => setOfferMode(true)} data-testid="appt-offer"><CalendarClock className="w-4 h-4 mr-1" /> Offer Available Times</Button>
                                            <Button disabled={busy} variant="outline" onClick={() => act({ action: "more_info", staff_note: staffNote || undefined })} data-testid="appt-more-info">Request More Info</Button>
                                            <Button disabled={busy} variant="outline" onClick={() => act({ action: "decline", staff_note: staffNote || undefined })} data-testid="appt-decline" className="text-red-600 border-red-200">Decline</Button>
                                        </div>
                                        <div className="pt-1"><Label className="text-xs">Note to patient (for more-info / decline)</Label><Textarea rows={2} value={staffNote} onChange={(e) => setStaffNote(e.target.value)} data-testid="appt-staff-note" /></div>
                                    </>
                                )}

                                {offerMode && (
                                    <div className="pt-1" data-testid="offer-selector">
                                        <div className="flex items-center justify-between mb-1">
                                            <Label className="text-xs">Select up to 3 available times ({chosen.length}/3)</Label>
                                            <button className="text-xs text-slate-500 underline" onClick={() => setOfferMode(false)}>Cancel</button>
                                        </div>
                                        {slotsQ.isLoading && <p className="text-slate-400 text-xs">Loading slots…</p>}
                                        <div className="max-h-56 overflow-y-auto border border-slate-200 rounded-sm divide-y">
                                            {slots.map((s, idx) => {
                                                const on = chosen.find((x) => x.date === s.date && x.time === s.time);
                                                return (
                                                    <button key={s.display || `${s.date}-${s.time}`} data-testid={`slot-${idx}`} onClick={() => toggleSlot(s)}
                                                        className={`w-full text-left px-2 py-1.5 text-sm ${on ? "bg-visita-greenLight font-semibold" : "hover:bg-slate-50"}`}>
                                                        {on ? "✓ " : ""}{s.display}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                        <Button disabled={busy || chosen.length === 0} onClick={() => act({ action: "offer", offered_slots: chosen })} data-testid="send-options"
                                            className="mt-2 w-full bg-visita-green hover:bg-visita-greenDark text-white">Send Options to Patient</Button>
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </DialogContent>
            </Dialog>

            {sel && (
                <BookAppointmentModal
                    open={reschedOpen}
                    onClose={() => setReschedOpen(false)}
                    onDone={() => { invalidate(); list.refetch(); close(); }}
                    mode="reschedule"
                    source={sel}
                />
            )}
        </div>
    );
}
