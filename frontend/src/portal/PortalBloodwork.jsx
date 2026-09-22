import { useState } from "react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

export default function PortalBloodwork() {
    const { overview, refetch } = usePortal();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const list = overview.data?.bloodwork || [];
    const [f, setF] = useState({ reason: "", patient_note: "" });
    const [busy, setBusy] = useState(false);
    const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await api.post("/portal/bloodwork", f);
            toast.success("Bloodwork request received.");
            setF({ reason: "", patient_note: "" });
            refetch();
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Bloodwork Request</h1>
            <EmergencyNotice />
            {p && <PendingBanner status={p.verification_status} />}

            {verified && (
                <Card>
                    <form onSubmit={submit} className="space-y-4" data-testid="bloodwork-form">
                        <div>
                            <Label className="font-semibold text-slate-700">Reason for bloodwork request</Label>
                            <select className="mt-1 w-full h-11 border border-slate-300 rounded-md px-3 text-sm bg-white"
                                required value={f.reason} onChange={(e) => set("reason", e.target.value)} data-testid="bld-reason">
                                <option value="" disabled>Select a reason…</option>
                                <option value="Routine / Annual bloodwork">Routine / Annual bloodwork</option>
                                <option value="Follow-up / Repeat bloodwork">Follow-up / Repeat bloodwork</option>
                                <option value="New symptoms or health concern">New symptoms or health concern</option>
                                <option value="Other">Other</option>
                            </select>
                        </div>
                        <div>
                            <Label className="font-semibold text-slate-700">Additional note (optional)</Label>
                            <Textarea className="mt-1" value={f.patient_note} onChange={(e) => set("patient_note", e.target.value)} data-testid="bld-note" />
                        </div>
                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
                            You do not need to choose specific tests. Dr. Aguayo decides whether bloodwork is appropriate
                            and which tests to order. Your request will be reviewed by the physician.
                        </div>
                        <Button type="submit" disabled={busy} data-testid="bld-submit" className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">{busy ? "Submitting…" : "Submit Request"}</Button>
                    </form>
                </Card>
            )}

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">Your bloodwork requests</h2>
                {list.length === 0 && <p className="text-slate-500 text-sm">No requests yet.</p>}
                {list.map((i) => (
                    <Card key={i.ref_number} className="p-4 flex justify-between items-start gap-2">
                        <div>
                            <div className="font-bold text-slate-800">{i.reason || "Bloodwork"}</div>
                            <div className="text-sm text-slate-500">{i.ref_number}</div>
                        </div>
                        <StatusPill status={i.status} />
                    </Card>
                ))}
            </div>
        </div>
    );
}
