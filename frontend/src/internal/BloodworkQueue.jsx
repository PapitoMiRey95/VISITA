import Queue, { KV } from "./Queue";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";
import { formatDateTime } from "../lib/date";
import { formatCombinedName } from "../lib/name";

const STATUSES = [
    { label: "New", value: "new" },
    { label: "Under Review", value: "under_review" },
    { label: "Waiting Physician", value: "waiting_physician" },
    { label: "More Info", value: "more_info_required" },
    { label: "Completed", value: "completed" },
];

export default function BloodworkQueue() {
    const { user } = useAuth();
    const physician = user?.role === "physician";

    const actions = (item) => {
        if (physician) {
            return [
                { label: "Approve / Process", testid: "act-complete", body: { action: "complete" } },
                { label: "Appointment Required", testid: "act-appt-req", variant: "outline", body: { action: "appointment_required" } },
                { label: "Request More Info", testid: "act-more-info", variant: "outline", body: { action: "more_info" } },
                { label: "Decline", testid: "act-decline", variant: "outline", body: { action: "decline" } },
            ];
        }
        return [
            { label: "Mark Under Review", testid: "act-review", variant: "outline", body: { action: "review" } },
            { label: "Send to Physician", testid: "act-send-physician", variant: "outline", body: { action: "send_to_physician" } },
            { label: "Approve / Process", testid: "act-complete", body: { action: "complete" } },
            { label: "Appointment Required", testid: "act-appt-req", variant: "outline", body: { action: "appointment_required" } },
        ];
    };

    return (
        <Queue
            title="Bloodwork Requests"
            subtitle="Patient requests for bloodwork — physician decides appropriate tests"
            endpoint="/internal/bloodwork"
            patchBase="/internal/bloodwork"
            searchPlaceholder="Search patient, reason, BLD-…"
            statuses={physician ? [] : STATUSES}
            enableBooking
            sourceType="bloodwork"
            attachmentEntity="bloodwork"
            columns={[
                { header: "Ref", cell: (i) => <span className="text-slate-500">{i.ref_number}</span> },
                { header: "Patient", cell: (i) => <span className="font-semibold">{formatCombinedName(i.patient_name)}</span> },
                { header: "Reason", cell: (i) => i.reason },
                { header: "Status", cell: (i) => <StatusPill status={i.internal_status} /> },
            ]}
            detail={(i) => (
                <div className="space-y-1.5">
                    <KV label="Reason">{i.reason}</KV>
                    <KV label="Patient note">{i.patient_note}</KV>
                    <KV label="Requested">{formatDateTime(i.created_at)}</KV>
                </div>
            )}
            actions={actions}
        />
    );
}
