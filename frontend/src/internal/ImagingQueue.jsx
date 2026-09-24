import Queue, { KV } from "./Queue";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";
import { formatDateTime } from "../lib/date";
import { formatCombinedName } from "../lib/name";

const STATUSES = [
    { label: "New", value: "new" },
    { label: "Under Review", value: "under_review" },
    { label: "Waiting Physician", value: "waiting_physician" },
    { label: "Completed", value: "completed" },
];

export default function ImagingQueue() {
    const { user } = useAuth();
    const physician = user?.role === "physician";

    const actions = (item) => {
        if (physician) {
            return [
                { label: "Mark Completed", testid: "act-complete", body: { action: "complete" } },
                { label: "Appointment Required", testid: "act-appt-req", variant: "outline", body: { action: "appointment_required" } },
            ];
        }
        return [
            { label: "Mark Under Review", testid: "act-review", variant: "outline", body: { action: "review" } },
            { label: "Send to Physician", testid: "act-send-physician", variant: "outline", body: { action: "send_to_physician" } },
            { label: "Mark Completed", testid: "act-complete", body: { action: "complete" } },
            { label: "Appointment Required", testid: "act-appt-req", variant: "outline", body: { action: "appointment_required" } },
        ];
    };

    return (
        <Queue
            title="Imaging Requests"
            subtitle="X-Ray and Ultrasound requests"
            endpoint="/internal/imaging"
            patchBase="/internal/imaging"
            searchPlaceholder="Search patient, body part, IMG-…"
            statuses={physician ? [] : STATUSES}
            enableBooking
            sourceType="imaging"
            columns={[
                { header: "Ref", cell: (i) => <span className="text-slate-500">{i.ref_number}</span> },
                { header: "Patient", cell: (i) => <span className="font-semibold">{formatCombinedName(i.patient_name)}</span> },
                { header: "Type", cell: (i) => <span className="capitalize">{i.imaging_type}</span> },
                { header: "Body Part", cell: (i) => i.body_part },
                { header: "Status", cell: (i) => <StatusPill status={i.internal_status} /> },
            ]}
            detail={(i) => (
                <div className="space-y-1.5">
                    <KV label="Type">{i.imaging_type}</KV>
                    <KV label="Body part">{i.body_part}</KV>
                    <KV label="Reason">{i.reason}</KV>
                    <KV label="Patient note">{i.patient_note}</KV>
                    <KV label="Requested">{formatDateTime(i.created_at)}</KV>
                </div>
            )}
            actions={actions}
        />
    );
}
