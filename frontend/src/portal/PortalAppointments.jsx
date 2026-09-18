import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, CheckCircle2 } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

export default function PortalAppointments() {
    const { overview, refetch } = usePortal();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const list = overview.data?.appointments || [];

    const slotsQ = useQuery({
        queryKey: ["slots"],
        queryFn: async () => (await api.get("/availability/slots", { params: { days: 28 } })).data,
        enabled: verified,
    });
    const slots = slotsQ.data?.slots || [];

    const [reason, setReason] = useState("");
    const [note, setNote] = useState("");
    const [picks, setPicks] = useState(["", "", ""]); // indices into slots
    const [busy, setBusy] = useState(false);
    const [selecting, setSelecting] = useState({}); // apptId -> index

    const setPick = (i, v) => setPicks((s) => s.map((x, idx) => (idx === i ? v : x)));

    const submit = async (e) => {
        e.preventDefault();
        const options = picks.filter((v) => v !== "").map((v) => slots[Number(v)]).filter(Boolean);
        if (options.length === 0) return toast.error("Please choose at least Preferred Option 1.");
        setBusy(true);
        try {
            await api.post("/portal/appointments", { reason, patient_note: note, options });
            toast.success("Appointment requested. The clinic will confirm a time.");
            setReason(""); setNote(""); setPicks(["", "", ""]);
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

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Request an Appointment</h1>
            <EmergencyNotice />
            {p && <PendingBanner status={p.verification_status} />}

            {verified && (
                <Card>
                    <form onSubmit={submit} className="space-y-4" data-testid="appointment-form">
                        <div>
                            <Label className="font-semibold text-slate-700">Reason for appointment</Label>
                            <Input className="mt-1" required value={reason} onChange={(e) => setReason(e.target.value)} data-testid="appt-reason" />
                        </div>
                        <div>
                            <Label className="font-semibold text-slate-700">Choose up to 3 preferred times</Label>
                            <p className="text-xs text-slate-500 mb-2">These are Dr. Aguayo's available times. Ranking a few options helps us confirm faster.</p>
                            {slotsQ.isLoading && <p className="text-sm text-slate-400">Loading available times…</p>}
                            {!slotsQ.isLoading && slots.length === 0 && <p className="text-sm text-amber-700">No available times right now — please message the clinic.</p>}
                            {slots.length > 0 && [0, 1, 2].map((i) => (
                                <div key={i} className="mb-2">
                                    <Label className="text-xs text-slate-500">Preferred Option {i + 1}{i === 0 ? " (required)" : ""}</Label>
                                    <select data-testid={`appt-option-${i + 1}`} value={picks[i]} onChange={(e) => setPick(i, e.target.value)}
                                        className="w-full border border-slate-200 rounded-xl h-11 px-2 mt-1 bg-white">
                                        <option value="">— Select a time —</option>
                                        {slots.map((s, idx) => <option key={idx} value={idx}>{s.display}</option>)}
                                    </select>
                                </div>
                            ))}
                        </div>
                        <div><Label className="font-semibold text-slate-700">Short note (optional)</Label><Textarea className="mt-1" value={note} onChange={(e) => setNote(e.target.value)} /></div>
                        <Button type="submit" disabled={busy || slots.length === 0} data-testid="appt-submit"
                            className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                            {busy ? "Submitting…" : "Request Appointment"}
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

                        {a.raw_status === "confirmed" && a.confirmed_display && (
                            <div className="mt-2 flex items-center gap-2 text-emerald-700 font-semibold text-sm">
                                <CheckCircle2 className="w-4 h-4" /> {a.confirmed_display}
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
