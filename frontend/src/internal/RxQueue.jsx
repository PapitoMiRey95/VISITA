import { Link, useNavigate } from "react-router-dom";
import { Plus, Paperclip, FilePlus2 } from "lucide-react";
import { toast } from "sonner";
import Queue, { KV } from "./Queue";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";
import { formatDate, formatDateTime } from "../lib/date";
import { formatCombinedName } from "../lib/name";
import { openAttachment, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";

const STATUSES = [
    { label: "Received", value: "received" },
    { label: "Under Review", value: "under_review" },
    { label: "Waiting Physician", value: "waiting_physician" },
    { label: "Approved (VISITA)", value: "approved_process_visita" },
    { label: "Prescription Sent", value: "prescription_sent" },
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
    { header: "Patient", cell: (i) => <span className="font-semibold">{formatCombinedName(i.patient_name)}</span> },
    { header: "PIN", cell: (i) => <span className="font-mono text-slate-700" data-testid="rx-row-pin">{i.visita_patient_id || "—"}</span> },
    { header: "Detail", cell: (i) => (i.source === "pharmacy" ? (i.pharmacy || "") : `${i.requested_months || ""} mo`) },
    { header: "Status", cell: (i) => <StatusPill status={i.internal_status} /> },
];

export default function RxQueue() {
    const { user } = useAuth();
    const physician = user?.role === "physician";
    const navigate = useNavigate();

    const convertToPrescription = (i) => {
        // Creates a DRAFT only — nothing is confirmed until the physician SENDS.
        const payload = {
            source_request_id: i.id,
            patient_ref: i.directory_id || i.patient_id,
            pharmacy_id: i.pharmacy_id,
            pharmacy_name: i.pharmacy,
            ref_number: i.ref_number,
            medications_structured: i.medications_structured || [],
        };
        try { sessionStorage.setItem("visita_rx_convert", JSON.stringify(payload)); } catch { /* ignore */ }
        navigate("/internal/send-rx");
    };

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
                            {(i.patient_snapshot && (i.patient_snapshot.date_of_birth || i.patient_snapshot.health_card_number || i.patient_snapshot.address)) && (
                                <div className="mt-1 mb-2 border border-slate-200 rounded p-2 bg-slate-50/60 space-y-1" data-testid="rx-patient-snapshot">
                                    <div className="text-[11px] uppercase text-slate-400 font-medium">Patient information (as sent)</div>
                                    <KV label="DOB">{formatDate(i.patient_snapshot.date_of_birth)}</KV>
                                    {i.patient_snapshot.visita_patient_id && <KV label="VIen PIN">{i.patient_snapshot.visita_patient_id}</KV>}
                                    <KV label="Address">{[[i.patient_snapshot.address, i.patient_snapshot.unit && `#${i.patient_snapshot.unit}`].filter(Boolean).join(" "), i.patient_snapshot.city, i.patient_snapshot.province, i.patient_snapshot.postal_code].filter(Boolean).join(", ")}</KV>
                                    <KV label="Cell">{i.patient_snapshot.cell_phone}</KV>
                                    <KV label="Home">{i.patient_snapshot.home_phone}</KV>
                                    <KV label="OHIP">{i.patient_snapshot.health_card_number ? `${i.patient_snapshot.health_card_number}${i.patient_snapshot.health_card_version ? ` ${i.patient_snapshot.health_card_version}` : ""}${i.patient_snapshot.health_card_expiry_date ? ` · exp ${formatDate(i.patient_snapshot.health_card_expiry_date)}` : ""}` : ""}</KV>
                                </div>
                            )}
                            {(i.medications_structured || []).length > 0 ? (
                                <div className="space-y-1.5" data-testid="rx-structured-meds">
                                    <div className="text-[11px] uppercase text-slate-400 font-medium">Requested medications</div>
                                    {(i.medications_structured || []).map((m, idx) => (
                                        <div key={idx} data-testid="rx-structured-med" className="border border-slate-200 rounded px-2 py-1.5 text-sm">
                                            <div className="font-semibold text-slate-800">{idx + 1}. {[m.drug, m.strength].filter(Boolean).join(" ")}{m.form ? <span className="font-normal text-slate-500"> — {m.form}</span> : null}</div>
                                            {m.sig && <div className="text-slate-600 text-xs">{m.sig}</div>}
                                            {(m.quantity || m.days_supply || m.requested_duration) && <div className="text-slate-500 text-xs">{[m.quantity && `Qty ${m.quantity}${m.quantity_unit ? ` ${m.quantity_unit}` : ""}`, m.days_supply && `${m.days_supply} days`, m.requested_duration && `Renew: ${m.requested_duration}`].filter(Boolean).join(" · ")}</div>}
                                            {(m.existing_rx_number || m.last_filled_date || m.manufacturer || m.current_refills) && <div className="text-slate-400 text-[11px]">{[m.existing_rx_number && `Rx# ${m.existing_rx_number}`, m.last_filled_date && `Last filled ${m.last_filled_date}`, m.current_refills && `Refills left ${m.current_refills}`, m.manufacturer && `Mfr ${m.manufacturer}`].filter(Boolean).join(" · ")}</div>}
                                            {m.pharmacy_note && <div className="text-slate-500 text-[11px]">Note: {m.pharmacy_note}</div>}
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <KV label="Requested medication(s)">{(i.medications || []).join("; ")}</KV>
                            )}
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
                            {i.linked_transmission_ref ? (
                                <div className="mt-2 border border-emerald-200 bg-emerald-50/60 rounded p-2" data-testid="rx-converted-banner">
                                    <div className="text-xs text-emerald-700 font-medium">Prescription sent from this request</div>
                                    <KV label="Prescription">{i.linked_transmission_ref}</KV>
                                    <KV label="Sent at">{formatDateTime(i.prescription_sent_at)}</KV>
                                </div>
                            ) : (physician && (i.medications_structured || []).length > 0 && (
                                <div className="mt-2 pt-2 border-t border-slate-200">
                                    <Button size="sm" variant="outline" data-testid="rx-convert-to-prescription"
                                        onClick={() => convertToPrescription(i)}
                                        className="border-visita-green text-visita-greenDark hover:bg-visita-greenLight">
                                        <FilePlus2 className="w-3.5 h-3.5 mr-1" /> Convert to Prescription
                                    </Button>
                                    <div className="text-[11px] text-slate-400 mt-1">Creates an editable draft. Nothing is confirmed until you review and Send.</div>
                                </div>
                            ))}
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
