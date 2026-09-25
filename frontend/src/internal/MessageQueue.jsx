import { Paperclip } from "lucide-react";
import { toast } from "sonner";
import Queue, { KV } from "./Queue";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";
import { openAttachment, formatErr } from "../lib/api";
import { formatCombinedName } from "../lib/name";

const STATUSES = [
    { label: "New", value: "new" },
    { label: "Open", value: "open" },
    { label: "Waiting Physician", value: "waiting_physician" },
    { label: "Completed", value: "completed" },
];

function SourceBadge({ source }) {
    const pharmacy = source === "pharmacy";
    return (
        <span className={`inline-block px-2 py-0.5 rounded-sm text-[10px] font-bold tracking-wide ${pharmacy ? "bg-indigo-100 text-indigo-700" : "bg-slate-100 text-slate-600"}`}>
            {pharmacy ? "PHARMACY" : "PATIENT"}
        </span>
    );
}

function senderLabel(from) {
    if (from === "pharmacy") return "Pharmacy";
    if (from === "clinic") return "Clinic";
    return "Patient";
}

export default function MessageQueue() {
    const { user } = useAuth();
    const physician = user?.role === "physician";

    const actions = () => {
        const base = [];
        if (!physician) base.push({ label: "Send to Physician", testid: "act-send-physician", variant: "outline", body: { action: "send_to_physician" } });
        base.push({ label: "Mark Completed", testid: "act-complete", body: { action: "complete" } });
        return base;
    };

    return (
        <Queue
            title="Messages"
            subtitle="Messages from patients and partner pharmacies"
            endpoint="/internal/messages"
            patchBase="/internal/messages"
            searchPlaceholder="Search patient, pharmacy, subject, MSG-…"
            statuses={physician ? [] : STATUSES}
            replyEnabled
            enableBooking
            sourceType="message"
            attachmentEntity="message"
            columns={[
                { header: "Source", cell: (i) => <SourceBadge source={i.source} /> },
                { header: "Ref", cell: (i) => <span className="text-slate-500">{i.ref_number}</span> },
                { header: "From", cell: (i) => (
                    i.source === "pharmacy"
                        ? <span className="font-semibold text-indigo-700">{i.pharmacy_name}</span>
                        : <span className="font-semibold">{formatCombinedName(i.patient_name)}</span>
                ) },
                { header: "Subject", cell: (i) => i.subject || "—" },
                { header: "Status", cell: (i) => <StatusPill status={i.status} /> },
            ]}
            detail={(i) => (
                <div className="space-y-2">
                    {i.source === "pharmacy" && (
                        <div className="rounded-sm bg-indigo-50 border border-indigo-100 px-2 py-1.5 text-xs text-indigo-700">
                            <b>PHARMACY</b> — {i.pharmacy_name}
                            {i.patient_name && i.patient_name !== i.pharmacy_name && <> · Patient: {formatCombinedName(i.patient_name)}</>}
                            {i.linked_rx_ref && <> · Rx: {i.linked_rx_ref}</>}
                        </div>
                    )}
                    <KV label="Category">{i.category}</KV>
                    <div className="space-y-1.5">
                        {(i.thread || []).map((t, idx) => (
                            <div key={idx} className={`rounded p-2 ${t.from === "pharmacy" ? "bg-indigo-50" : t.from === "patient" ? "bg-slate-100" : "bg-visita-greenLight"}`}>
                                <b>{senderLabel(t.from)}:</b> {t.body}
                                {t.attachment && (
                                    <button
                                        data-testid="msg-attachment-view"
                                        onClick={async () => {
                                            try { await openAttachment(`/internal/messages/${i.id}/attachment/${idx}`); }
                                            catch (err) { toast.error(formatErr(err)); }
                                        }}
                                        className="mt-1 flex items-center gap-1 text-indigo-600 hover:underline text-xs">
                                        <Paperclip className="w-3.5 h-3.5" /> {t.attachment.original_filename || "View file"}
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}
            actions={actions}
        />
    );
}
