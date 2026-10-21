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

// Display origin: pharmacy-portal submissions = PHARMACY; clinic staff/admin intake (fax/phone) = ADMIN; portal = PATIENT.
// Stored `source` stays "pharmacy" for scoping — this is presentation only.
const originOf = (i) => (i.source === "pharmacy" ? (i.received_via === "pharmacy_portal" ? "PHARMACY" : "ADMIN") : "PATIENT");
const ORIGIN_TONE = { PHARMACY: "bg-indigo-100 text-indigo-700", ADMIN: "bg-amber-100 text-amber-800", PATIENT: "bg-slate-100 text-slate-600" };
function SourceBadge({ item }) {
    const o = originOf(item);
    return (
        <span data-testid="rx-source-badge" className={`inline-block px-2 py-0.5 rounded-sm text-[10px] font-bold tracking-wide ${ORIGIN_TONE[o]}`}>
            {o}
        </span>
    );
}

function ManualReviewBadge({ item }) {
    if (!(item?.medication_entry_source === "MANUAL" || item?.requires_medication_review)) return null;
    return (
        <span data-testid="manual-entry-badge" className="inline-block px-2 py-0.5 rounded-sm text-[10px] font-bold tracking-wide bg-amber-100 text-amber-800 border border-amber-300">
            MANUAL ENTRY — REVIEW REQUIRED
        </span>
    );
}

const COLUMNS = [
    { header: "Source", cell: (i) => <SourceBadge item={i} /> },
    { header: "Ref", cell: (i) => <span className="text-slate-500">{i.ref_number}</span> },
    { header: "Patient", cell: (i) => <span className="font-semibold">{formatCombinedName(i.patient_name)}</span> },
    { header: "PIN", cell: (i) => <span className="font-mono text-slate-700" data-testid="rx-row-pin">{i.visita_patient_id || "—"}</span> },
    { header: "Medication", cell: (i) => (<span className="flex flex-col gap-1"><span>{i.medication_name || "—"}</span><ManualReviewBadge item={i} /></span>) },
    { header: "Status", cell: (i) => <StatusPill status={i.internal_status} /> },
];

// Physician triage view: no medication text in the list — only a compact count
// (+ the safety badge). Full Rx details appear after Open.
const medCount = (i) => (i.medications_structured || []).length || (i.medications || []).length || (i.medication_name ? 1 : 0);
const PHYSICIAN_COLUMNS = [
    COLUMNS[0], COLUMNS[1], COLUMNS[2], COLUMNS[3],
    { header: "Status", cell: (i) => (
        <span className="flex flex-col gap-1">
            <StatusPill status={i.internal_status} />
            <span className="text-[11px] text-slate-500" data-testid="rx-row-med-count">{medCount(i)} medication{medCount(i) === 1 ? "" : "s"}</span>
            <ManualReviewBadge item={i} />
        </span>
    ) },
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
            columns={physician ? PHYSICIAN_COLUMNS : COLUMNS}
            wide
            footerActions={(i) => (!i.linked_transmission_ref && physician && (i.medications_structured || []).length > 0 ? (
                <Button size="sm" data-testid="rx-convert-to-prescription" onClick={() => convertToPrescription(i)}
                    className="bg-visita-green hover:bg-visita-greenDark text-white" title="Creates an editable draft. Nothing is confirmed until you review and Send.">
                    <FilePlus2 className="w-3.5 h-3.5 mr-1" /> Convert to Prescription
                </Button>
            ) : null)}
            detail={(i) => (
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,340px)]" data-testid="rx-detail-grid">
                  <div className="space-y-2 min-w-0" data-testid="rx-detail-main">
                    {i.source === "pharmacy" ? (
                        <>
                            {(i.medications_structured || []).length > 0 ? (
                                <div className="space-y-1.5" data-testid="rx-structured-meds">
                                    <div className="text-[11px] uppercase text-slate-400 font-medium">Requested medications ({i.medications_structured.length})</div>
                                    <div className={`grid gap-2 ${i.medications_structured.length > 1 ? "md:grid-cols-2" : ""}`}>
                                    {(i.medications_structured || []).map((m, idx) => (
                                        <div key={idx} data-testid="rx-structured-med" className="border border-slate-200 rounded px-2.5 py-2 text-sm min-w-0 break-words">
                                            <div className="font-semibold text-slate-800">{idx + 1}. {[m.drug, m.strength].filter(Boolean).join(" ")}{m.form ? <span className="font-normal text-slate-500"> — {m.form}</span> : null}</div>
                                            {m.sig && <div className="text-slate-600 text-sm">{m.sig}</div>}
                                            {(m.quantity || m.days_supply || m.requested_duration) && <div className="text-slate-500 text-xs">{[m.quantity && `Qty ${m.quantity}${m.quantity_unit ? ` ${m.quantity_unit}` : ""}`, m.days_supply && `${m.days_supply} days`, m.requested_duration && `Renew: ${m.requested_duration}`].filter(Boolean).join(" · ")}</div>}
                                            {(m.existing_rx_number || m.last_filled_date || m.manufacturer || m.current_refills) && <div className="text-slate-400 text-[11px]">{[m.existing_rx_number && `Rx# ${m.existing_rx_number}`, m.last_filled_date && `Last filled ${m.last_filled_date}`, m.current_refills && `Refills left ${m.current_refills}`, m.manufacturer && `Mfr ${m.manufacturer}`].filter(Boolean).join(" · ")}</div>}
                                            {m.pharmacy_note && <div className="text-slate-500 text-[11px]">Note: {m.pharmacy_note}</div>}
                                        </div>
                                    ))}
                                    </div>
                                </div>
                            ) : (
                                <KV label="Requested medication(s)">{(i.medications || []).join("; ")}</KV>
                            )}
                            <KV label="Duration / quantity">{i.duration_qty}</KV>
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
                            {i.linked_transmission_ref && (
                                <div className="mt-2 border border-emerald-200 bg-emerald-50/60 rounded p-2" data-testid="rx-converted-banner">
                                    <div className="text-xs text-emerald-700 font-medium">Prescription sent from this request</div>
                                    <KV label="Prescription">{i.linked_transmission_ref}</KV>
                                    <KV label="Sent at">{formatDateTime(i.prescription_sent_at)}</KV>
                                </div>
                            )}
                        </>
                    ) : (
                        <>
                            <KV label="Medication">{i.medication_name} {i.strength}</KV>
                            {(i.medication_entry_source === "MANUAL" || i.requires_medication_review) && (
                                <div data-testid="manual-entry-detail-badge" className="my-1 inline-flex items-center gap-1.5 px-2 py-1 rounded bg-amber-100 text-amber-800 border border-amber-300 text-[11px] font-bold">
                                    ⚠ MANUAL ENTRY — REVIEW REQUIRED
                                </div>
                            )}
                            <KV label="Directions">{i.directions}</KV>
                            <KV label="Supply">{i.requested_months} month(s)</KV>
                            <KV label="Patient note">{i.patient_note}</KV>
                        </>
                    )}
                    {i.physician_note && <KV label="Physician modification">{i.physician_note}</KV>}
                    {i.internal_status === "voided" && (
                        <div className="mt-2 border border-red-200 bg-red-50/60 rounded p-2 space-y-1" data-testid="voided-banner">
                            <div className="text-xs uppercase text-red-600 font-medium">Voided / Archived</div>
                            <KV label="Void reason">{i.void_reason}</KV>
                            <KV label="Voided by">{i.voided_by}</KV>
                            <KV label="Voided at">{formatDateTime(i.voided_at)}</KV>
                        </div>
                    )}
                  </div>
                  <div className="space-y-1.5 min-w-0 lg:border-l lg:border-slate-200 lg:pl-4" data-testid="rx-detail-context">
                    <KV label="Source">{{ PHARMACY: "PHARMACY REQUEST", ADMIN: "ADMIN INTAKE (ON BEHALF OF PHARMACY)", PATIENT: "PATIENT REQUEST" }[originOf(i)]}</KV>
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
                            <KV label="Received via">{i.received_via}</KV>
                            <KV label="Delivery">{i.delivery_method === "pickup" ? "Pick up at pharmacy" : i.delivery_method === "pharmacy" ? "Delivery" : ""}</KV>
                            <KV label="Pharmacy note">{i.pharmacy_note}</KV>
                            <KV label="Intake by">{i.intake_by}</KV>
                        </>
                    ) : (
                        <>
                            <KV label="Delivery">{i.delivery_method === "pharmacy" ? "Send to pharmacy" : "Pickup"}</KV>
                            <KV label="New pharmacy">{i.new_pharmacy_details}</KV>
                        </>
                    )}
                    <KV label="Staff note">{i.staff_note}</KV>
                    <KV label="Requested">{formatDateTime(i.created_at)}</KV>
                  </div>
                </div>
            )}
            actions={actions}
        />
    );
}
