import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, CheckCircle2, X, Clock, Info, Send } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { formatDate } from "../lib/date";

const NOTE_MAX = 300;

// Private/uninsured evenings run 5:30–9:00 PM, any day (Mon–Sun), in fixed
// 30-minute windows. Value stored = window start (HH:MM).
const TIME_WINDOWS = [
    { v: "17:30", label: "5:30 – 6:00 PM" },
    { v: "18:00", label: "6:00 – 6:30 PM" },
    { v: "18:30", label: "6:30 – 7:00 PM" },
    { v: "19:00", label: "7:00 – 7:30 PM" },
    { v: "19:30", label: "7:30 – 8:00 PM" },
    { v: "20:00", label: "8:00 – 8:30 PM" },
    { v: "20:30", label: "8:30 – 9:00 PM" },
];

// Cascading Reason-for-Visit selector driven by the backend taxonomy.
function ReasonCascade({ taxonomy, value, onChange }) {
    // value = array of selected codes (root..leaf)
    const levels = useMemo(() => {
        const out = [];
        let node = taxonomy;
        for (let i = 0; i <= value.length; i++) {
            if (!node || Object.keys(node).length === 0) break;
            out.push(node);
            const code = value[i];
            node = code && node[code] ? node[code].children : null;
        }
        return out;
    }, [taxonomy, value]);

    return (
        <div className="space-y-2" data-testid="reason-cascade">
            {levels.map((options, idx) => (
                <select key={idx} data-testid={`reason-level-${idx}`}
                    value={value[idx] || ""} className="w-full border border-slate-200 rounded-xl h-11 px-2 bg-white"
                    onChange={(e) => {
                        const next = value.slice(0, idx);
                        if (e.target.value) next.push(e.target.value);
                        onChange(next);
                    }}>
                    <option value="">{idx === 0 ? "Select a reason…" : "Select…"}</option>
                    {Object.entries(options).map(([code, node]) => (
                        <option key={code} value={code}>{node.label}</option>
                    ))}
                </select>
            ))}
        </div>
    );
}

function Thread({ pr, onSend }) {
    const [msg, setMsg] = useState("");
    return (
        <div className="mt-3 border-t border-slate-100 pt-3">
            <div className="text-xs font-semibold text-slate-600 mb-1.5">Conversation</div>
            <div className="space-y-1.5 max-h-52 overflow-y-auto mb-2">
                {(pr.thread || []).length === 0 && <div className="text-xs text-slate-400">No messages yet.</div>}
                {(pr.thread || []).map((m, i) => (
                    <div key={i} className={`text-sm rounded-lg px-2.5 py-1.5 ${m.from === "patient" ? "bg-sky-50 ml-6" : "bg-slate-100 mr-6"}`}>
                        <div className="text-[10px] uppercase tracking-wide text-slate-400">{m.from === "patient" ? "You" : "Clinic"}</div>
                        {m.message}
                    </div>
                ))}
            </div>
            <div className="flex gap-2">
                <Input data-testid={`pr-msg-input-${pr.id}`} value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Write a message…" />
                <Button size="sm" data-testid={`pr-msg-send-${pr.id}`} disabled={!msg.trim()}
                    onClick={async () => { await onSend(pr.id, msg.trim()); setMsg(""); }}
                    className="bg-portal-blue hover:bg-portal-blueDark text-white"><Send className="w-4 h-4" /></Button>
            </div>
        </div>
    );
}

export default function PortalPrivateAppointments() {
    const { refetch } = usePortal();
    const [taxonomy, setTaxonomy] = useState({});
    const [config, setConfig] = useState({ private_hours: "" });
    const [mode, setMode] = useState("SPECIFIC");
    const [date, setDate] = useState("");
    const [time, setTime] = useState("");
    const [reasonCodes, setReasonCodes] = useState([]);
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);

    const listQ = useQuery({ queryKey: ["private-requests"], queryFn: async () => (await api.get("/portal/private-requests")).data });
    const list = listQ.data || [];

    useEffect(() => {
        api.get("/config/reasons").then(({ data }) => setTaxonomy(data)).catch(() => {});
        api.get("/config/private").then(({ data }) => setConfig(data)).catch(() => {});
    }, []);

    const isLeaf = useMemo(() => {
        let node = taxonomy;
        for (const c of reasonCodes) { node = node?.[c]?.children; if (node === undefined) return false; }
        return reasonCodes.length > 0 && (node === null || node === undefined);
    }, [taxonomy, reasonCodes]);

    const submit = async (e) => {
        e.preventDefault();
        if (!isLeaf) return toast.error("Please choose a complete reason for your visit.");
        if (mode !== "NO_PREFERENCE" && (!date || !time)) return toast.error("Please provide your preferred date and time.");
        setBusy(true);
        try {
            await api.post("/portal/private-requests", {
                preference_mode: mode, preferred_date: mode === "NO_PREFERENCE" ? undefined : date,
                preferred_time: mode === "NO_PREFERENCE" ? undefined : time,
                reason_codes: reasonCodes, note: note || undefined,
            });
            toast.success("Your private appointment request was submitted.");
            setMode("SPECIFIC"); setDate(""); setTime(""); setReasonCodes([]); setNote("");
            listQ.refetch(); refetch();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const act = async (id, path, body) => {
        try { await api.post(`/portal/private-requests/${id}/${path}`, body || {}); toast.success("Done."); listQ.refetch(); refetch(); }
        catch (err) { toast.error(formatErr(err)); }
    };
    const sendMsg = async (id, message) => act(id, "messages", { message });

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Private Appointment Request</h1>
            <EmergencyNotice />

            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-900 flex gap-2" data-testid="private-badge-banner">
                <Info className="w-5 h-5 flex-shrink-0" />
                <div>
                    <p className="font-bold">PRIVATE / UNINSURED</p>
                    Dr. Aguayo generally sees private / uninsured patients in the evening: <span className="font-semibold">{config.private_hours || "any day, 5:30 PM–9:00 PM"}</span>, in 30-minute windows.
                    You are requesting a time only — the clinic will review your request. If it can be accommodated it may be accepted; otherwise another date and time will be offered to you.
                </div>
            </div>

            <Card>
                <form onSubmit={submit} className="space-y-4" data-testid="private-request-form">
                    <div>
                        <Label className="font-semibold text-slate-700">When would you prefer?</Label>
                        <div className="grid sm:grid-cols-3 gap-2 mt-2">
                            {[
                                { v: "SPECIFIC", title: "A specific evening", desc: "Pick a day & 30-min window" },
                                { v: "OTHER", title: "I'm flexible", desc: "Suggest one, clinic may adjust" },
                                { v: "NO_PREFERENCE", title: "No preference", desc: "Clinic may choose" },
                            ].map(({ v, title, desc }) => (
                                <button type="button" key={v} data-testid={`pref-mode-${v}`} onClick={() => setMode(v)}
                                    className={`text-left rounded-xl border p-3 transition-colors ${mode === v ? "border-portal-blue bg-sky-50 ring-1 ring-portal-blue" : "border-slate-200 bg-white hover:border-portal-blue"}`}>
                                    <div className="font-bold text-slate-800 text-sm">{title}</div>
                                    <div className="text-xs text-slate-500">{desc}</div>
                                </button>
                            ))}
                        </div>
                    </div>

                    {mode !== "NO_PREFERENCE" && (
                        <div className="grid grid-cols-2 gap-3" data-testid="pref-datetime">
                            <div>
                                <Label className="text-xs">Preferred date</Label>
                                <Input type="date" data-testid="pref-date" value={date} onChange={(e) => setDate(e.target.value)} />
                            </div>
                            <div>
                                <Label className="text-xs">Preferred time window</Label>
                                <select data-testid="pref-time" value={time} onChange={(e) => setTime(e.target.value)}
                                    className="w-full border border-slate-200 rounded-xl h-11 px-2 bg-white text-sm">
                                    <option value="">Select a 30-min window…</option>
                                    {TIME_WINDOWS.map(({ v, label }) => (
                                        <option key={v} value={v}>{label}</option>
                                    ))}
                                </select>
                            </div>
                        </div>
                    )}

                    <div>
                        <Label className="font-semibold text-slate-700">Reason for visit</Label>
                        <div className="mt-2"><ReasonCascade taxonomy={taxonomy} value={reasonCodes} onChange={setReasonCodes} /></div>
                    </div>

                    <div>
                        <div className="flex items-center justify-between">
                            <Label className="font-semibold text-slate-700">Optional note</Label>
                            <span className="text-xs text-slate-400">{note.length} / {NOTE_MAX}</span>
                        </div>
                        <Textarea data-testid="pref-note" value={note} maxLength={NOTE_MAX} onChange={(e) => setNote(e.target.value.slice(0, NOTE_MAX))} />
                    </div>

                    <Button type="submit" disabled={busy} data-testid="private-submit"
                        className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                        {busy ? "Submitting…" : "Submit Private Request"}
                    </Button>
                </form>
            </Card>

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">Your Private Requests</h2>
                {list.length === 0 && <p className="text-slate-500 text-sm">No private requests yet.</p>}
                {list.map((pr) => (
                    <Card key={pr.id} className="p-4" data-testid="private-request-card">
                        <div className="flex justify-between items-start gap-2">
                            <div>
                                <div className="font-bold text-slate-800">{pr.reason_label}</div>
                                <div className="text-sm text-slate-500">{pr.ref_number} · <span className="font-semibold text-amber-700">PRIVATE / UNINSURED</span></div>
                                {pr.preferred_date && <div className="text-xs text-slate-500 mt-1">Requested: {formatDate(pr.preferred_date)} · {pr.preferred_time}</div>}
                            </div>
                            <StatusPill status={pr.status} />
                        </div>

                        {(pr.status === "OFFERED" || pr.status === "AWAITING_PATIENT") && pr.offered_date && (
                            <div className="mt-3 bg-sky-50 border border-sky-200 rounded-xl p-3" data-testid={`pr-offer-${pr.id}`}>
                                <div className="flex items-center gap-2 text-sky-800 font-bold text-sm mb-2">
                                    <CalendarClock className="w-4 h-4" /> Offered: {formatDate(pr.offered_date)} · {pr.offered_label || pr.offered_time}
                                </div>
                                <div className="flex gap-2">
                                    <Button size="sm" data-testid={`pr-accept-${pr.id}`} onClick={() => act(pr.id, "accept")}
                                        className="bg-portal-blue hover:bg-portal-blueDark text-white"><CheckCircle2 className="w-4 h-4 mr-1" /> Accept</Button>
                                    <Button size="sm" variant="outline" className="text-red-600 border-red-200" data-testid={`pr-decline-${pr.id}`}
                                        onClick={() => act(pr.id, "decline")}><X className="w-4 h-4 mr-1" /> Decline</Button>
                                </div>
                            </div>
                        )}

                        {pr.status === "CONFIRMED" && (
                            <div className="mt-2 flex items-center gap-2 text-emerald-700 font-semibold text-sm">
                                <CheckCircle2 className="w-4 h-4" /> Confirmed{pr.offered_date ? `: ${formatDate(pr.offered_date)} · ${pr.offered_label || pr.offered_time}` : ` for ${formatDate(pr.preferred_date)} · ${pr.preferred_time}`}
                            </div>
                        )}

                        {!["CONFIRMED", "COMPLETED", "CANCELLED", "DECLINED"].includes(pr.status) && (
                            <div className="mt-2">
                                <Button size="sm" variant="ghost" className="text-red-600" data-testid={`pr-cancel-${pr.id}`} onClick={() => act(pr.id, "cancel")}>
                                    <X className="w-4 h-4 mr-1" /> Cancel request
                                </Button>
                            </div>
                        )}

                        <Thread pr={pr} onSend={sendMsg} />
                    </Card>
                ))}
            </div>
        </div>
    );
}
