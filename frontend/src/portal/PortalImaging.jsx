import { useState } from "react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

export default function PortalImaging() {
    const { overview, refetch } = usePortal();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const list = overview.data?.imaging || [];
    const [f, setF] = useState({ imaging_type: "xray", body_part: "", reason: "", patient_note: "" });
    const [busy, setBusy] = useState(false);
    const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await api.post("/portal/imaging", f);
            toast.success("Imaging request submitted for clinic review.");
            setF({ imaging_type: "xray", body_part: "", reason: "", patient_note: "" });
            refetch();
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">X-Ray / Ultrasound Request</h1>
            <EmergencyNotice />
            {p && <PendingBanner status={p.verification_status} />}

            {verified && (
                <Card>
                    <form onSubmit={submit} className="space-y-4" data-testid="imaging-form">
                        <div className="flex gap-2">
                            {[["xray", "X-Ray"], ["ultrasound", "Ultrasound"]].map(([v, l]) => (
                                <button key={v} type="button" data-testid={`img-type-${v}`} onClick={() => set("imaging_type", v)}
                                    className={`flex-1 py-2.5 rounded-xl border font-semibold text-sm ${f.imaging_type === v ? "bg-portal-blue text-white border-portal-blue" : "bg-white text-slate-600 border-slate-200"}`}>{l}</button>
                            ))}
                        </div>
                        <div><Label className="font-semibold text-slate-700">Body part / region</Label><Input className="mt-1" required value={f.body_part} onChange={(e) => set("body_part", e.target.value)} data-testid="img-bodypart" /></div>
                        <div><Label className="font-semibold text-slate-700">Reason for imaging request</Label>
                            <select className="mt-1 w-full h-11 border border-slate-300 rounded-md px-3 text-sm bg-white"
                                required value={f.reason} onChange={(e) => set("reason", e.target.value)} data-testid="img-reason">
                                <option value="" disabled>Select a reason…</option>
                                <option value="New symptoms / pain / injury">New symptoms / pain / injury</option>
                                <option value="Follow-up / Repeat imaging">Follow-up / Repeat imaging</option>
                                <option value="Other">Other</option>
                            </select>
                        </div>
                        <div><Label className="font-semibold text-slate-700">Patient note (optional)</Label><Textarea className="mt-1" value={f.patient_note} onChange={(e) => set("patient_note", e.target.value)} /></div>
                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
                            This does not authorize imaging. Your request will be reviewed by the clinic and physician.
                        </div>
                        <Button type="submit" disabled={busy} data-testid="img-submit" className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">{busy ? "Submitting…" : "Submit Request"}</Button>
                    </form>
                </Card>
            )}

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">Your imaging requests</h2>
                {list.length === 0 && <p className="text-slate-500 text-sm">No requests yet.</p>}
                {list.map((i) => (
                    <Card key={i.ref_number} className="p-4 flex justify-between items-start gap-2">
                        <div>
                            <div className="font-bold text-slate-800 capitalize">{i.imaging_type} — {i.body_part}</div>
                            <div className="text-sm text-slate-500">{i.ref_number}</div>
                        </div>
                        <StatusPill status={i.status} />
                    </Card>
                ))}
            </div>
        </div>
    );
}
