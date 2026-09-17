import Queue, { KV } from "./Queue";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";

const STATUSES = [
    { label: "Received", value: "received" },
    { label: "Under Review", value: "under_review" },
    { label: "Waiting Physician", value: "waiting_physician" },
    { label: "Completed", value: "completed" },
];

const COLUMNS = [
    { header: "Ref", cell: (i) => <span className="text-slate-500">{i.ref_number}</span> },
    { header: "Patient", cell: (i) => <span className="font-semibold">{i.patient_name}</span> },
    { header: "Medication", cell: (i) => `${i.medication_name} ${i.strength || ""}` },
    { header: "Supply", cell: (i) => `${i.requested_months} mo` },
    { header: "Delivery", cell: (i) => (i.delivery_method === "pharmacy" ? "Pharmacy" : "Pickup") },
    { header: "Status", cell: (i) => <StatusPill status={i.internal_status} /> },
];

export default function RxQueue() {
    const { user } = useAuth();
    const physician = user?.role === "physician";

    const actions = (item) => {
        if (physician) {
            return [
                { label: "Mark Completed", testid: "act-complete", body: { action: "complete" } },
                { label: "Appointment Required", testid: "act-appt-req", variant: "outline", body: { action: "appointment_required" } },
            ];
        }
        const base = [];
        if (item.internal_status === "received") base.push({ label: "Mark Under Review", testid: "act-review", variant: "outline", body: { action: "review" } });
        base.push({ label: "Send to Physician", testid: "act-send-physician", variant: "outline", body: { action: "send_to_physician" } });
        base.push({ label: "Mark Completed", testid: "act-complete", body: { action: "complete" } });
        base.push({ label: "Appointment Required", testid: "act-appt-req", variant: "outline", body: { action: "appointment_required" } });
        return base;
    };

    return (
        <Queue
            title="Prescription Requests"
            subtitle="Actionable prescription requests"
            endpoint="/internal/prescriptions"
            patchBase="/internal/prescriptions"
            searchPlaceholder="Search patient, medication, RX-…"
            statuses={physician ? [] : STATUSES}
            columns={COLUMNS}
            detail={(i) => (
                <div className="space-y-1.5">
                    <KV label="Medication">{i.medication_name} {i.strength}</KV>
                    <KV label="Directions">{i.directions}</KV>
                    <KV label="Supply">{i.requested_months} month(s)</KV>
                    <KV label="Delivery">{i.delivery_method === "pharmacy" ? "Send to pharmacy" : "Pickup"}</KV>
                    <KV label="New pharmacy">{i.new_pharmacy_details}</KV>
                    <KV label="Patient note">{i.patient_note}</KV>
                    <KV label="Requested">{new Date(i.created_at).toLocaleString()}</KV>
                    <KV label="Assigned to">{i.assigned_to}</KV>
                </div>
            )}
            actions={actions}
        />
    );
}
