import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

export default function PortalPrescriptions() {
    const { overview, refetch } = usePortal();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const list = overview.data?.prescriptions || [];
    const pharmacies = useQuery({ queryKey: ["pharmacies"], queryFn: async () => (await api.get("/portal/pharmacies")).data, enabled: verified });

    const [f, setF] = useState({ medication_name: "", strength: "", directions: "", requested_months: 1, delivery_method: "pickup", pharmacy_id: "", new_pharmacy_details: "", patient_note: "" });
    const [busy, setBusy] = useState(false);
    const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await api.post("/portal/prescriptions", f);
            toast.success("Prescription request received.");
            setF({ medication_name: "", strength: "", directions: "", requested_months: 1, delivery_method: "pickup", pharmacy_id: "", new_pharmacy_details: "", patient_note: "" });
            refetch();
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    const Choice = ({ active, onClick, children, testid }) => (
        <button type="button" data-testid={testid} onClick={onClick}
            className={`flex-1 py-2.5 rounded-xl border font-semibold text-sm transition ${active ? "bg-portal-blue text-white border-portal-blue" : "bg-white text-slate-600 border-slate-200"}`}>
            {children}
        </button>
    );

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Prescription Request</h1>
            {p && <PendingBanner status={p.verification_status} />}

            {verified && (
                <Card>
                    <form onSubmit={submit} className="space-y-4" data-testid="rx-form">
                        <div>
                            <Label className="font-semibold text-slate-700">Medication name</Label>
                            <Input className="mt-1" required value={f.medication_name} onChange={(e) => set("medication_name", e.target.value)} data-testid="rx-med" />
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <div><Label className="font-semibold text-slate-700">Strength</Label><Input className="mt-1" value={f.strength} onChange={(e) => set("strength", e.target.value)} placeholder="10 mg" /></div>
                            <div><Label className="font-semibold text-slate-700">Directions (if known)</Label><Input className="mt-1" value={f.directions} onChange={(e) => set("directions", e.target.value)} /></div>
                        </div>
                        <div>
                            <Label className="font-semibold text-slate-700">Requested supply</Label>
                            <div className="flex gap-2 mt-1">
                                {[1, 2, 3].map((m) => <Choice key={m} testid={`rx-months-${m}`} active={f.requested_months === m} onClick={() => set("requested_months", m)}>{m} month{m > 1 ? "s" : ""}</Choice>)}
                            </div>
                        </div>
                        <div>
                            <Label className="font-semibold text-slate-700">Delivery method</Label>
                            <div className="flex gap-2 mt-1">
                                <Choice testid="rx-pickup" active={f.delivery_method === "pickup"} onClick={() => set("delivery_method", "pickup")}>Pickup</Choice>
                                <Choice testid="rx-pharmacy" active={f.delivery_method === "pharmacy"} onClick={() => set("delivery_method", "pharmacy")}>Send to Pharmacy</Choice>
                            </div>
                        </div>
                        {f.delivery_method === "pharmacy" && (
                            <div className="space-y-2">
                                <Label className="font-semibold text-slate-700">Select saved pharmacy</Label>
                                <select className="w-full border border-slate-200 rounded-md h-10 px-2" value={f.pharmacy_id} onChange={(e) => set("pharmacy_id", e.target.value)} data-testid="rx-pharmacy-select">
                                    <option value="">— Choose —</option>
                                    {(pharmacies.data || []).map((ph) => <option key={ph.id} value={ph.id}>{ph.name}</option>)}
                                </select>
                                <Label className="font-semibold text-slate-700">Or enter a new pharmacy</Label>
                                <Input value={f.new_pharmacy_details} onChange={(e) => set("new_pharmacy_details", e.target.value)} placeholder="Name, address, fax" />
                            </div>
                        )}
                        <div><Label className="font-semibold text-slate-700">Patient note (optional)</Label><Textarea className="mt-1" value={f.patient_note} onChange={(e) => set("patient_note", e.target.value)} /></div>
                        <Button type="submit" disabled={busy} data-testid="rx-submit" className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                            {busy ? "Submitting…" : "Submit Prescription Request"}
                        </Button>
                    </form>
                </Card>
            )}

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">Your prescription requests</h2>
                {list.length === 0 && <p className="text-slate-500 text-sm">No requests yet.</p>}
                {list.map((r) => (
                    <Card key={r.ref_number} className="p-4 flex justify-between items-start gap-2">
                        <div>
                            <div className="font-bold text-slate-800">{r.medication_name} {r.strength}</div>
                            <div className="text-sm text-slate-500">{r.ref_number}</div>
                        </div>
                        <StatusPill status={r.status} />
                    </Card>
                ))}
            </div>
        </div>
    );
}
