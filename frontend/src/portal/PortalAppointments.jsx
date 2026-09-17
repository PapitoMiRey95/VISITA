import { useState } from "react";
import { toast } from "sonner";
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
    const [f, setF] = useState({ reason: "", preferred_date: "", preferred_time: "", alternative_date: "", alternative_time: "", patient_note: "" });
    const [busy, setBusy] = useState(false);
    const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await api.post("/portal/appointments", f);
            toast.success("Appointment requested. The clinic will review and confirm.");
            setF({ reason: "", preferred_date: "", preferred_time: "", alternative_date: "", alternative_time: "", patient_note: "" });
            refetch();
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
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
                            <Input className="mt-1" required value={f.reason} onChange={set("reason")} data-testid="appt-reason" />
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <Label className="font-semibold text-slate-700">Preferred date</Label>
                                <Input type="date" className="mt-1" value={f.preferred_date} onChange={set("preferred_date")} data-testid="appt-date" />
                            </div>
                            <div>
                                <Label className="font-semibold text-slate-700">Preferred time</Label>
                                <Input className="mt-1" placeholder="Morning / 2pm" value={f.preferred_time} onChange={set("preferred_time")} data-testid="appt-time" />
                            </div>
                            <div>
                                <Label className="font-semibold text-slate-700">Alternative date</Label>
                                <Input type="date" className="mt-1" value={f.alternative_date} onChange={set("alternative_date")} />
                            </div>
                            <div>
                                <Label className="font-semibold text-slate-700">Alternative time</Label>
                                <Input className="mt-1" placeholder="Optional" value={f.alternative_time} onChange={set("alternative_time")} />
                            </div>
                        </div>
                        <div>
                            <Label className="font-semibold text-slate-700">Short note (optional)</Label>
                            <Textarea className="mt-1" value={f.patient_note} onChange={set("patient_note")} />
                        </div>
                        <Button type="submit" disabled={busy} data-testid="appt-submit"
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
                    <Card key={a.ref_number} className="p-4">
                        <div className="flex justify-between items-start gap-2">
                            <div>
                                <div className="font-bold text-slate-800">{a.reason}</div>
                                <div className="text-sm text-slate-500">{a.ref_number} · Preferred {a.preferred_date || "—"}</div>
                                {a.approved_date && <div className="text-sm text-emerald-700 font-semibold mt-1">Confirmed: {a.approved_date} {a.approved_time}</div>}
                                {a.staff_note && <div className="text-sm text-slate-600 mt-1">Note: {a.staff_note}</div>}
                            </div>
                            <StatusPill status={a.status} />
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
}
