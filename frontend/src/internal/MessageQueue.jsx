import Queue, { KV } from "./Queue";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";

const STATUSES = [
    { label: "New", value: "new" },
    { label: "Open", value: "open" },
    { label: "Waiting Physician", value: "waiting_physician" },
    { label: "Completed", value: "completed" },
];

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
            title="Patient Messages"
            subtitle="Messages from patients"
            endpoint="/internal/messages"
            patchBase="/internal/messages"
            searchPlaceholder="Search patient, subject, MSG-…"
            statuses={physician ? [] : STATUSES}
            replyEnabled
            enableBooking
            sourceType="message"
            columns={[
                { header: "Ref", cell: (i) => <span className="text-slate-500">{i.ref_number}</span> },
                { header: "Patient", cell: (i) => <span className="font-semibold">{i.patient_name}</span> },
                { header: "Category", cell: (i) => i.category },
                { header: "Subject", cell: (i) => i.subject || "—" },
                { header: "Status", cell: (i) => <StatusPill status={i.status} /> },
            ]}
            detail={(i) => (
                <div className="space-y-2">
                    <KV label="Category">{i.category}</KV>
                    <div className="space-y-1.5">
                        {(i.thread || []).map((t, idx) => (
                            <div key={idx} className={`rounded p-2 ${t.from === "patient" ? "bg-slate-100" : "bg-visita-greenLight"}`}>
                                <b>{t.from === "patient" ? "Patient" : "Clinic"}:</b> {t.body}
                            </div>
                        ))}
                    </div>
                </div>
            )}
            actions={actions}
        />
    );
}
