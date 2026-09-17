import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

const ROUTES = [
    { key: "Appointment", to: "/portal/appointments" },
    { key: "Prescription", to: "/portal/prescriptions" },
    { key: "New Referral", to: "/portal/referrals" },
    { key: "Referral Status", to: "/portal/referrals" },
    { key: "X-Ray / Ultrasound", to: "/portal/imaging" },
];

export default function PortalMessages() {
    const nav = useNavigate();
    const { overview, cfg, refetch } = usePortal();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const list = overview.data?.messages || [];
    const intro = cfg.data?.templates?.smart_routing_intro || "What can we help you with?";
    const [freeText, setFreeText] = useState(false);
    const [f, setF] = useState({ category: "Message for Doctor", subject: "", body: "" });
    const [busy, setBusy] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await api.post("/portal/messages", f);
            toast.success("Message sent to the clinic.");
            setF({ category: "Message for Doctor", subject: "", body: "" });
            setFreeText(false);
            refetch();
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Message the Clinic</h1>
            <EmergencyNotice />
            {p && <PendingBanner status={p.verification_status} />}

            {verified && !freeText && (
                <Card>
                    <h2 className="font-bold text-slate-800 mb-3">{intro}</h2>
                    <div className="space-y-2">
                        {ROUTES.map((r) => (
                            <button key={r.key} data-testid={`route-${r.key}`} onClick={() => nav(r.to)}
                                className="w-full text-left px-4 py-3 rounded-xl border border-slate-200 font-semibold text-slate-700 hover:border-portal-blue hover:bg-portal-blue/5 transition">
                                {r.key}
                            </button>
                        ))}
                        <button data-testid="route-doctor" onClick={() => { setF({ ...f, category: "Message for Doctor" }); setFreeText(true); }}
                            className="w-full text-left px-4 py-3 rounded-xl border border-slate-200 font-semibold text-slate-700 hover:border-portal-blue hover:bg-portal-blue/5 transition">
                            Message for Doctor
                        </button>
                        <button data-testid="route-other" onClick={() => { setF({ ...f, category: "Other" }); setFreeText(true); }}
                            className="w-full text-left px-4 py-3 rounded-xl border border-slate-200 font-semibold text-slate-700 hover:border-portal-blue hover:bg-portal-blue/5 transition">
                            Other
                        </button>
                    </div>
                </Card>
            )}

            {verified && freeText && (
                <Card>
                    <form onSubmit={submit} className="space-y-4" data-testid="message-form">
                        <div className="text-sm font-semibold text-portal-blueDark">{f.category}</div>
                        <div><Label className="font-semibold text-slate-700">Subject</Label><Input className="mt-1" value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} data-testid="msg-subject" /></div>
                        <div><Label className="font-semibold text-slate-700">Message</Label><Textarea className="mt-1" required rows={4} value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} data-testid="msg-body" /></div>
                        <div className="flex gap-2">
                            <Button type="button" variant="outline" onClick={() => setFreeText(false)} className="flex-1">Back</Button>
                            <Button type="submit" disabled={busy} data-testid="msg-submit" className="flex-1 bg-portal-blue hover:bg-portal-blueDark text-white">{busy ? "Sending…" : "Send"}</Button>
                        </div>
                    </form>
                </Card>
            )}

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">Your messages</h2>
                {list.length === 0 && <p className="text-slate-500 text-sm">No messages yet.</p>}
                {list.map((m) => (
                    <Card key={m.ref_number} className="p-4">
                        <div className="flex justify-between items-start gap-2 mb-2">
                            <div className="font-bold text-slate-800">{m.subject || m.category}</div>
                            <StatusPill status={m.status} />
                        </div>
                        <div className="space-y-1.5">
                            {(m.thread || []).map((t, i) => (
                                <div key={i} className={`text-sm rounded-lg px-3 py-2 ${t.from === "patient" ? "bg-slate-100 text-slate-700" : "bg-portal-blue/10 text-slate-800"}`}>
                                    <span className="font-bold">{t.from === "patient" ? "You" : "Clinic"}: </span>{t.body}
                                </div>
                            ))}
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
}
