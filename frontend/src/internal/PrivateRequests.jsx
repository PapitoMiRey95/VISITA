import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, CheckCircle2, X, Send, Stethoscope, Clock } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { StatusPill } from "./statusPill";
import { formatCombinedName } from "../lib/name";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function PrivateRequests() {
    const invalidate = useInvalidate();
    const [sel, setSel] = useState(null);
    const [offer, setOffer] = useState({ date: "", time: "", note: "" });
    const [msg, setMsg] = useState("");

    const list = useQuery({ queryKey: ["queue", "/internal/private-requests"], queryFn: async () => (await api.get("/internal/private-requests")).data });
    const items = list.data || [];

    const detailQ = useQuery({
        queryKey: ["private-detail", sel],
        queryFn: async () => (await api.get(`/internal/private-requests/${sel}`)).data,
        enabled: !!sel,
    });
    const pr = detailQ.data;

    const refresh = () => { list.refetch(); if (sel) detailQ.refetch(); invalidate(); };
    const act = async (path, body) => {
        try { await api.post(`/internal/private-requests/${sel}/${path}`, body || {}); toast.success("Done."); refresh(); }
        catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center gap-2 mb-1">
                <Stethoscope className="w-5 h-5 text-visita-greenDark" />
                <h1 className="text-2xl font-bold text-slate-900">Private / Uninsured Requests</h1>
            </div>
            <p className="text-sm text-slate-500 mb-4">Private appointment requests from private, uninsured, and visitor patients.</p>

            <div className="grid md:grid-cols-2 gap-4">
                <div className="space-y-2">
                    {items.length === 0 && <p className="text-slate-400 text-sm">No private requests.</p>}
                    {items.map((r) => (
                        <button key={r.id} data-testid={`pr-row-${r.id}`} onClick={() => setSel(r.id)}
                            className={`w-full text-left bg-white border rounded-lg p-3 ${sel === r.id ? "border-visita-green ring-1 ring-visita-green" : "border-slate-200"}`}>
                            <div className="flex items-center justify-between gap-2">
                                <span className="font-semibold text-slate-800">{formatCombinedName(r.patient_name)}</span>
                                <StatusPill status={r.status} />
                            </div>
                            <div className="text-xs text-slate-500 mt-0.5">
                                {r.ref_number} · <span className="font-semibold text-amber-700">PRIVATE / UNINSURED</span>
                            </div>
                            <div className="text-xs text-slate-600 mt-0.5">{r.reason_label}</div>
                            {r.preferred_date && <div className="text-xs text-slate-500">Requested: {formatDate(r.preferred_date)} · {r.preferred_time}</div>}
                            {r.preference_mode === "NO_PREFERENCE" && <div className="text-xs text-slate-400">No preference — clinic may choose</div>}
                        </button>
                    ))}
                </div>

                <div>
                    {!pr && <div className="text-slate-400 text-sm bg-white border border-slate-200 rounded-lg p-6 text-center">Select a request to review.</div>}
                    {pr && (
                        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3" data-testid="pr-detail">
                            <div className="flex items-center justify-between">
                                <div className="font-bold text-slate-800">{formatCombinedName(pr.patient_name)}</div>
                                <StatusPill status={pr.status} />
                            </div>
                            <div className="text-xs text-slate-500">{pr.ref_number} · <span className="font-semibold text-amber-700">PRIVATE / UNINSURED</span> · {pr.patient_type}</div>
                            <div className="text-sm"><span className="text-slate-500">Reason:</span> {(pr.reason_path || []).join(" › ")}</div>
                            {pr.preferred_date && <div className="text-sm"><span className="text-slate-500">Requested:</span> {formatDate(pr.preferred_date)} · {pr.preferred_time}</div>}
                            {pr.preference_mode === "NO_PREFERENCE" && <div className="text-sm text-slate-500">No preference — clinic may choose.</div>}
                            {pr.note && <div className="text-sm"><span className="text-slate-500">Note:</span> {pr.note}</div>}

                            {!["CONFIRMED", "COMPLETED", "CANCELLED", "DECLINED"].includes(pr.status) && (
                                <div className="space-y-3 border-t border-slate-100 pt-3">
                                    {pr.preference_mode === "SPECIFIC" && pr.preferred_date && (
                                        <Button size="sm" data-testid="pr-accept-requested" onClick={() => act("accept-requested")}
                                            className="bg-visita-green hover:bg-visita-greenDark text-white w-full">
                                            <CheckCircle2 className="w-4 h-4 mr-1" /> Accept requested time ({formatDate(pr.preferred_date)} · {pr.preferred_time})
                                        </Button>
                                    )}
                                    <div className="rounded-md bg-slate-50 border border-slate-100 p-2.5">
                                        <div className="text-xs font-semibold text-slate-600 mb-1.5 flex items-center gap-1"><CalendarClock className="w-3.5 h-3.5" /> Offer a different date / time</div>
                                        <div className="grid grid-cols-2 gap-2">
                                            <Input type="date" data-testid="pr-offer-date" value={offer.date} onChange={(e) => setOffer({ ...offer, date: e.target.value })} />
                                            <Input type="time" data-testid="pr-offer-time" value={offer.time} onChange={(e) => setOffer({ ...offer, time: e.target.value })} />
                                        </div>
                                        <Input className="mt-2" placeholder="Optional note to patient" data-testid="pr-offer-note" value={offer.note} onChange={(e) => setOffer({ ...offer, note: e.target.value })} />
                                        <Button size="sm" className="mt-2 bg-visita-green hover:bg-visita-greenDark text-white" data-testid="pr-offer-submit"
                                            disabled={!offer.date || !offer.time}
                                            onClick={() => act("offer", { date: offer.date, time: offer.time, note: offer.note || undefined }).then(() => setOffer({ date: "", time: "", note: "" }))}>
                                            <Clock className="w-4 h-4 mr-1" /> Send offer
                                        </Button>
                                    </div>
                                    <div className="flex gap-2">
                                        <Button size="sm" variant="outline" className="text-red-600 border-red-200" data-testid="pr-decline" onClick={() => act("decline")}>
                                            <X className="w-4 h-4 mr-1" /> Decline
                                        </Button>
                                        <Button size="sm" variant="ghost" className="text-red-600" data-testid="pr-cancel" onClick={() => act("cancel")}>Cancel</Button>
                                    </div>
                                </div>
                            )}

                            {pr.status === "CONFIRMED" && (
                                <div className="text-emerald-700 font-semibold text-sm flex items-center gap-2"><CheckCircle2 className="w-4 h-4" /> Confirmed — appears on the Calendar with a PRIVATE badge.</div>
                            )}

                            <div className="border-t border-slate-100 pt-3">
                                <Label className="text-xs text-slate-600">Conversation</Label>
                                <div className="space-y-1.5 max-h-52 overflow-y-auto my-2">
                                    {(pr.thread || []).length === 0 && <div className="text-xs text-slate-400">No messages yet.</div>}
                                    {(pr.thread || []).map((m, i) => (
                                        <div key={i} className={`text-sm rounded-lg px-2.5 py-1.5 ${m.from === "clinic" ? "bg-visita-greenLight ml-6" : "bg-slate-100 mr-6"}`}>
                                            <div className="text-[10px] uppercase tracking-wide text-slate-400">{m.from === "clinic" ? m.by : "Patient"}</div>
                                            {m.message}
                                        </div>
                                    ))}
                                </div>
                                <div className="flex gap-2">
                                    <Input data-testid="pr-msg-input" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Message the patient…" />
                                    <Button size="sm" data-testid="pr-msg-send" disabled={!msg.trim()}
                                        onClick={() => act("messages", { message: msg.trim() }).then(() => setMsg(""))}
                                        className="bg-visita-green hover:bg-visita-greenDark text-white"><Send className="w-4 h-4" /></Button>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
