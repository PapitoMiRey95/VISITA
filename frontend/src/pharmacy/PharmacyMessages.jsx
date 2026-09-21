import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Plus, ArrowLeft, Send, MessageSquare, Paperclip } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { PatientSearch, AttachmentPicker } from "./shared";

function Bubble({ t, convId, idx }) {
    const pharmacy = t.from === "pharmacy";
    return (
        <div className={`rounded-lg p-2.5 text-sm max-w-[85%] ${pharmacy ? "bg-visita-greenLight ml-auto" : "bg-slate-100"}`}>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-0.5">{pharmacy ? "You (Pharmacy)" : t.from === "clinic" ? "Clinic" : "Patient"}</div>
            <div className="text-slate-800 whitespace-pre-wrap">{t.body}</div>
            {t.attachment && (
                <button data-testid="pharmacy-msg-attachment"
                    onClick={async () => { try { await openAttachment(`/pharmacy/messages/${convId}/attachment/${idx}`); } catch (err) { toast.error(formatErr(err)); } }}
                    className="mt-1 flex items-center gap-1 text-indigo-600 hover:underline text-xs">
                    <Paperclip className="w-3.5 h-3.5" /> {t.attachment.original_filename || "View file"}
                </button>
            )}
            <div className="text-[10px] text-slate-400 mt-1">{formatDateTime(t.at)}</div>
        </div>
    );
}

export default function PharmacyMessages() {
    const [mode, setMode] = useState("list"); // list | thread | compose
    const [convos, setConvos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [active, setActive] = useState(null);

    // compose state
    const [subject, setSubject] = useState("");
    const [body, setBody] = useState("");
    const [linkPatient, setLinkPatient] = useState(null);
    const [rxRef, setRxRef] = useState("");
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);

    // reply state
    const [reply, setReply] = useState("");
    const [replyFile, setReplyFile] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/pharmacy/messages");
            setConvos(data);
            setActive((cur) => (cur ? data.find((c) => c.id === cur.id) || cur : cur));
        } catch (err) { toast.error(formatErr(err)); } finally { setLoading(false); }
    }, []);

    useEffect(() => { load(); }, [load]);

    const openThread = (c) => { setActive(c); setReply(""); setReplyFile(null); setMode("thread"); };

    const startCompose = () => { setSubject(""); setBody(""); setLinkPatient(null); setRxRef(""); setFile(null); setMode("compose"); };

    const sendNew = async () => {
        if (!body.trim()) { toast.error("Enter a message."); return; }
        setBusy(true);
        try {
            const fd = new FormData();
            fd.append("body", body.trim());
            fd.append("subject", subject.trim());
            if (linkPatient) fd.append("patient_directory_id", linkPatient.id);
            if (rxRef.trim()) fd.append("rx_ref", rxRef.trim());
            if (file) fd.append("file", file);
            const { data } = await api.post("/pharmacy/messages", fd, { headers: { "Content-Type": "multipart/form-data" } });
            toast.success("Message sent to the clinic.");
            await load();
            openThread(data);
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const sendReply = async () => {
        if (!reply.trim()) { toast.error("Enter a reply."); return; }
        setBusy(true);
        try {
            const fd = new FormData();
            fd.append("body", reply.trim());
            if (replyFile) fd.append("file", replyFile);
            const { data } = await api.post(`/pharmacy/messages/${active.id}/reply`, fd, { headers: { "Content-Type": "multipart/form-data" } });
            setReply(""); setReplyFile(null);
            setActive(data);
            load();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    if (mode === "compose") {
        return (
            <div className="animate-fade-in max-w-xl">
                <div className="flex items-center gap-3 mb-4">
                    <Button variant="ghost" size="sm" onClick={() => setMode("list")} data-testid="msg-back"><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">New Message</h1>
                </div>
                <div className="bg-white border border-slate-300 rounded-sm p-4 space-y-3">
                    <div><Label className="text-xs">Subject</Label><Input data-testid="msg-subject" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject" /></div>
                    <div><Label className="text-xs">Message *</Label><Textarea data-testid="msg-body" value={body} onChange={(e) => setBody(e.target.value)} rows={4} placeholder="Type your message to the clinic…" /></div>
                    <div>
                        <Label className="text-xs">Link a patient (optional)</Label>
                        {linkPatient ? (
                            <div className="flex items-center justify-between border border-slate-200 rounded-sm px-3 py-2 text-sm">
                                <span className="font-semibold">{linkPatient.full_name} <span className="text-slate-400 font-normal">· PIN {linkPatient.visita_patient_id || "—"}</span></span>
                                <button className="text-xs text-slate-400 hover:text-red-600" onClick={() => setLinkPatient(null)} data-testid="msg-unlink-patient">Remove</button>
                            </div>
                        ) : (
                            <div className="mt-1"><PatientSearch onSelect={setLinkPatient} testidPrefix="msg" /></div>
                        )}
                    </div>
                    <div><Label className="text-xs">Related Rx ref (optional)</Label><Input data-testid="msg-rx-ref" value={rxRef} onChange={(e) => setRxRef(e.target.value)} placeholder="e.g. RX-000123" /></div>
                    <div>
                        <Label className="text-xs">Attachment (optional)</Label>
                        <div className="mt-1"><AttachmentPicker file={file} onChange={setFile} testidPrefix="msg" /></div>
                    </div>
                    <Button data-testid="msg-send" onClick={sendNew} disabled={busy} className="w-full bg-visita-green hover:bg-visita-greenDark text-white">
                        <Send className="w-4 h-4 mr-1" /> Send Message
                    </Button>
                </div>
            </div>
        );
    }

    if (mode === "thread" && active) {
        return (
            <div className="animate-fade-in max-w-2xl">
                <div className="flex items-center gap-3 mb-3">
                    <Button variant="ghost" size="sm" onClick={() => setMode("list")} data-testid="msg-back"><ArrowLeft className="w-4 h-4 mr-1" /> Messages</Button>
                    <div className="min-w-0">
                        <h1 className="text-lg font-bold text-slate-900 truncate">{active.subject}</h1>
                        <p className="text-xs text-slate-500">
                            {active.ref_number}
                            {active.patient_name && active.patient_name !== active.pharmacy_name && <> · Patient: {active.patient_name}</>}
                            {active.linked_rx_ref && <> · Rx: {active.linked_rx_ref}</>}
                        </p>
                    </div>
                </div>

                <div className="bg-white border border-slate-300 rounded-sm p-4 space-y-2 mb-3" data-testid="msg-thread">
                    {(active.thread || []).map((t, idx) => <Bubble key={idx} t={t} convId={active.id} idx={idx} />)}
                </div>

                <div className="bg-white border border-slate-300 rounded-sm p-3 space-y-2">
                    <Textarea data-testid="msg-reply-body" value={reply} onChange={(e) => setReply(e.target.value)} rows={2} placeholder="Write a reply…" />
                    <AttachmentPicker file={replyFile} onChange={setReplyFile} testidPrefix="msg-reply" />
                    <Button data-testid="msg-reply-send" onClick={sendReply} disabled={busy} className="bg-visita-green hover:bg-visita-greenDark text-white">
                        <Send className="w-4 h-4 mr-1" /> Send Reply
                    </Button>
                </div>
            </div>
        );
    }

    // LIST
    return (
        <div className="animate-fade-in">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Messages</h1>
                    <p className="text-sm text-slate-500">Secure messages with Dr. Aguayo's office.</p>
                </div>
                <Button onClick={startCompose} className="bg-visita-green hover:bg-visita-greenDark text-white" data-testid="new-message-btn">
                    <Plus className="w-4 h-4 mr-1" /> New Message
                </Button>
            </div>

            <div className="bg-white border border-slate-300 rounded-sm divide-y">
                {loading ? (
                    <div className="px-4 py-8 text-center text-slate-400 text-sm">Loading…</div>
                ) : convos.length === 0 ? (
                    <div className="px-4 py-10 text-center text-slate-400 text-sm">
                        <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        No messages yet. Click <b>New Message</b> to start a conversation.
                    </div>
                ) : (
                    convos.map((c) => {
                        const last = (c.thread || [])[c.thread.length - 1];
                        return (
                            <button key={c.id} data-testid="msg-row" onClick={() => openThread(c)}
                                className="w-full text-left px-4 py-3 hover:bg-slate-50 flex justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="font-semibold text-slate-800 truncate">{c.subject}</div>
                                    <div className="text-xs text-slate-500 truncate">
                                        {last ? `${last.from === "pharmacy" ? "You: " : last.from === "clinic" ? "Clinic: " : ""}${last.body}` : ""}
                                    </div>
                                </div>
                                <div className="text-xs text-slate-400 whitespace-nowrap">{formatDateTime(c.updated_at)}</div>
                            </button>
                        );
                    })
                )}
            </div>
        </div>
    );
}
