import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { StatusPill } from "./statusPill";
import { KV } from "./Queue";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

export default function AppointmentQueue() {
    const invalidate = useInvalidate();
    const [q, setQ] = useState("");
    const [status, setStatus] = useState("requested");
    const [sel, setSel] = useState(null);
    const [date, setDate] = useState("");
    const [time, setTime] = useState("");
    const [staffNote, setStaffNote] = useState("");
    const [busy, setBusy] = useState(false);

    const list = useQuery({
        queryKey: ["queue", "/internal/appointments", q, status],
        queryFn: async () => (await api.get("/internal/appointments", { params: { q: q || undefined, status: status || undefined } })).data,
    });

    const open = (i) => { setSel(i); setDate(i.approved_date || i.preferred_date || ""); setTime(i.approved_time || i.preferred_time || ""); setStaffNote(""); };

    const act = async (action) => {
        setBusy(true);
        try {
            const body = { action, staff_note: staffNote || undefined };
            if (action === "approve") { body.approved_date = date; body.approved_time = time; }
            await api.patch(`/internal/appointments/${sel.id}`, body);
            toast.success("Appointment updated.");
            invalidate(); list.refetch(); setSel(null);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const items = list.data || [];
    const chips = [["requested", "Requested"], ["", "All"], ["confirmed", "Confirmed"], ["declined", "Declined"]];

    return (
        <div className="animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Appointment Requests</h1>
            <p className="text-sm text-slate-500 mb-3">Requests awaiting clinic action</p>

            <div className="flex flex-wrap items-center gap-2 mb-3">
                <div className="relative">
                    <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                    <Input data-testid="queue-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search patient, reason, APT-…" className="pl-8 h-9 w-64 bg-white" />
                </div>
                <div className="flex gap-1">
                    {chips.map(([v, l]) => (
                        <button key={l} data-testid={`filter-${l.toLowerCase()}`} onClick={() => setStatus(v)}
                            className={`px-2.5 py-1 rounded-sm text-xs font-medium border ${status === v ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-300"}`}>{l}</button>
                    ))}
                </div>
            </div>

            <div className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="bg-slate-100 text-left text-xs uppercase tracking-wider text-slate-600">
                            <th className="px-3 py-2 font-medium">Ref</th><th className="px-3 py-2 font-medium">Patient</th>
                            <th className="px-3 py-2 font-medium">Reason</th><th className="px-3 py-2 font-medium">Preferred</th>
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
                                <td className="px-3 py-2">{i.preferred_date} {i.preferred_time}</td>
                                <td className="px-3 py-2"><StatusPill status={i.status} /></td>
                                <td className="px-3 py-2 text-right"><Button size="sm" variant="ghost" className="h-7 text-visita-green" data-testid="queue-open">Open</Button></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <Dialog open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
                <DialogContent className="max-w-lg font-plex">
                    {sel && (
                        <>
                            <DialogHeader><DialogTitle>{sel.ref_number} · {sel.patient_name}</DialogTitle></DialogHeader>
                            <div className="space-y-1.5 text-sm">
                                <KV label="Reason">{sel.reason}</KV>
                                <KV label="Preferred">{sel.preferred_date} {sel.preferred_time}</KV>
                                <KV label="Alternative">{sel.alternative_date} {sel.alternative_time}</KV>
                                <KV label="Patient note">{sel.patient_note}</KV>
                                <KV label="Requested">{new Date(sel.created_at).toLocaleString()}</KV>
                            </div>
                            <div className="grid grid-cols-2 gap-2 mt-2">
                                <div><Label className="text-xs">Confirm date</Label><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="appt-approve-date" /></div>
                                <div><Label className="text-xs">Confirm time</Label><Input value={time} onChange={(e) => setTime(e.target.value)} placeholder="10:00 AM" data-testid="appt-approve-time" /></div>
                            </div>
                            <div><Label className="text-xs">Note to patient (optional)</Label><Textarea rows={2} value={staffNote} onChange={(e) => setStaffNote(e.target.value)} data-testid="appt-staff-note" /></div>
                            <div className="flex flex-wrap gap-2 pt-1">
                                <Button disabled={busy} onClick={() => act("approve")} data-testid="appt-approve" className="bg-visita-green hover:bg-visita-greenDark text-white">Approve</Button>
                                <Button disabled={busy} variant="outline" onClick={() => act("suggest")} data-testid="appt-suggest">Suggest Another Time</Button>
                                <Button disabled={busy} variant="outline" onClick={() => act("more_info")} data-testid="appt-more-info">Request More Info</Button>
                                <Button disabled={busy} variant="outline" onClick={() => act("decline")} data-testid="appt-decline" className="text-red-600 border-red-200">Decline</Button>
                            </div>
                        </>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}
