import { Link } from "react-router-dom";
import { Plus, Paperclip } from "lucide-react";
import { toast } from "sonner";
import Queue, { KV } from "./Queue";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";
import { formatDateTime } from "../lib/date";
import { openAttachment, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";

const STATUSES = [
    { label: "Received", value: "received" },
    { label: "Under Review", value: "under_review" },
    { label: "Waiting Physician", value: "waiting_physician" },
    { label: "Approved (VISITA)", value: "approved_process_visita" },
    { label: "Completed", value: "completed" },
    { label: "Voided / Archived", value: "voided" },
];

function SourceBadge({ source }) {
    const pharmacy = source === "pharmacy";
    return (
        <span className={`inline-block px-2 py-0.5 rounded-sm text-[10px] font-bold tracking-wide ${pharmacy ? "bg-indigo-100 text-indigo-700" : "bg-slate-100 text-slate-600"}`}>
            {pharmacy ? "PHARMACY" : "PATIENT"}
        </span>
    );
}

const COLUMNS = [
    { header: "Source", cell: (i) => <SourceBadge source={i.source} /> },
    { header: "Ref", cell: (i) => <span className="text-slate-500">{i.ref_number}</span> },
    { header: "Patient", cell: (i) => <span className="font-semibold">{i.patient_name}</span> },
    { header: "Medication", cell: (i) => `${i.medication_name || ""} ${i.strength || ""}`.trim() },
    { header: "Detail", cell: (i) => (i.source === "pharmacy" ? (i.pharmacy || "") : `${i.requested_months || ""} mo`) },
    { header: "Status", cell: (i) => <StatusPill status={i.internal_status} /> },
];

export default function RxQueue() {
    const { user } = useAuth();
    const physician = user?.role === "physician";

    const actions = (item) => {
        if (physician) {
            return [
                { label: "Approve", testid: "act-approve", body: { action: "approve" } },
                { label: "Modify", testid: "act-modify", variant: "outline", body: { action: "modify" } },
                { label: "Appointment Required", testid: "act-appt-req", variant: "outline", body: { action: "appointment_required" } },
                { label: "Request More Info", testid: "act-more-info", variant: "outline", body: { action: "more_info" } },
                { label: "Decline", testid: "act-decline", variant: "outline", body: { action: "decline" } },
            ];
        }
        const base = [];
        if (item.internal_status === "received") base.push({ label: "Mark Under Review", testid: "act-review", variant: "outline", body: { action: "review" } });
        if (item.internal_status !== "waiting_physician") base.push({ label: "Send to Physician", testid: "act-send-physician", variant: "outline", body: { action: "send_to_physician" } });
        base.push({ label: "Mark Completed", testid: "act-complete", body: { action: "complete" } });
        base.push({ label: "Appointment Required", testid: "act-appt-req", variant: "outline", body: { action: "appointment_required" } });
        return base;
    };

    return (
        <Queue
            title="Prescription Requests"
            subtitle="Actionable prescription requests — patient and pharmacy"
            endpoint="/internal/prescriptions"
            patchBase="/internal/prescriptions"
            searchPlaceholder="Search patient, medication, RX-…"
            statuses={physician ? [] : STATUSES}
            enableBooking
            enableVoid
            sourceType="prescription"
            headerAction={
                physician ? null : (
                    <Button asChild size="sm" className="bg-visita-green hover:bg-visita-greenDark text-white" data-testid="pharmacy-refill-btn">
                        <Link to="/internal/pharmacy-intake"><Plus className="w-4 h-4 mr-1" /> Request Intake</Link>
                    </Button>
                )
            }
            columns={COLUMNS}
            detail={(i) => (
                <div className="space-y-1.5">
                    <KV label="Source">{i.source === "pharmacy" ? "PHARMACY REQUEST" : "PATIENT REQUEST"}</KV>
                    {i.source === "pharmacy" ? (
                        <>
                            <KV label="Pharmacy">{i.pharmacy}</KV>
                            <KV label="Requested medication(s)">{(i.medications || []).join("; ")}</KV>
                            <KV label="Active meds referenced">{(i.selected_active_meds || []).join("; ")}</KV>
                            <KV label="Duration / quantity">{i.duration_qty}</KV>
                            <KV label="Received via">{i.received_via}</KV>
                            <KV label="Pharmacy note">{i.pharmacy_note}</KV>
                            {i.message_to_physician && <KV label="Message to physician">{i.message_to_physician}</KV>}
                            {i.attachment && (
                                <KV label="Attachment">
                                    <button
                                        data-testid="rx-attachment-view"
                                        onClick={async () => {
                                            try { await openAttachment(`/internal/prescriptions/${i.id}/attachment`); }
                                            catch (err) { toast.error(formatErr(err)); }
                                        }}
                                        className="inline-flex items-center gap-1 text-indigo-600 hover:underline">
                                        <Paperclip className="w-3.5 h-3.5" /> {i.attachment.original_filename || "View file"}
                                    </button>
                                </KV>
                            )}
                            <KV label="Intake by">{i.intake_by}</KV>
                        </>
                    ) : (
                        <>
                            <KV label="Medication">{i.medication_name} {i.strength}</KV>
                            <KV label="Directions">{i.directions}</KV>
                            <KV label="Supply">{i.requested_months} month(s)</KV>
                            <KV label="Delivery">{i.delivery_method === "pharmacy" ? "Send to pharmacy" : "Pickup"}</KV>
                            <KV label="New pharmacy">{i.new_pharmacy_details}</KV>
                            <KV label="Patient note">{i.patient_note}</KV>
                        </>
                    )}
                    {i.physician_note && <KV label="Physician modification">{i.physician_note}</KV>}
                    <KV label="Staff note">{i.staff_note}</KV>
                    <KV label="Requested">{formatDateTime(i.created_at)}</KV>
                    {i.internal_status === "voided" && (
                        <div className="mt-2 border border-red-200 bg-red-50/60 rounded p-2 space-y-1" data-testid="voided-banner">
                            <div className="text-xs uppercase text-red-600 font-medium">Voided / Archived</div>
                            <KV label="Void reason">{i.void_reason}</KV>
                            <KV label="Voided by">{i.voided_by}</KV>
                            <KV label="Voided at">{formatDateTime(i.voided_at)}</KV>
                        </div>
                    )}
                </div>
            )}
            actions={actions}
        />
    );
}
