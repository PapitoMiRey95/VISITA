import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Calendar, Pill, FileText, ClipboardList, Download, Plus } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import MedicationRefill from "./MedicationRefill";

export default function ManagedPortal() {
    const { patientId } = useParams();
    const nav = useNavigate();
    const [data, setData] = useState(null);
    const [err, setErr] = useState(null);
    const [showRx, setShowRx] = useState(false);
    const [showAppt, setShowAppt] = useState(false);

    const load = useCallback(() => {
        api.get(`/portal/managed/${patientId}/summary`, { params: { on_behalf_of: patientId } })
            .then(({ data }) => { setData(data); setErr(null); })
            .catch((e) => setErr(formatErr(e)));
    }, [patientId]);
    useEffect(() => { load(); }, [load]);

    const can = (p) => data?.permissions?.includes(p);

    const download = async (att) => {
        try {
            const { data: blob } = await api.get(`/portal/documents/${att.id}/download`, { params: { on_behalf_of: patientId }, responseType: "blob" });
            const url = URL.createObjectURL(blob); const a = document.createElement("a");
            a.href = url; a.download = att.filename || "document"; a.click(); URL.revokeObjectURL(url);
        } catch (e) { toast.error(formatErr(e)); }
    };

    if (err) return (
        <div data-testid="managed-portal-error" className="p-5 rounded-md border border-amber-200 bg-amber-50">
            <p className="text-slate-700 font-semibold">This account isn't available</p>
            <p className="text-sm text-slate-600 mt-1">{err}</p>
            <Button variant="outline" className="mt-3" onClick={() => nav("/portal/people")}><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
        </div>
    );
    if (!data) return <p className="text-slate-400 text-sm" data-testid="managed-portal-loading">Loading…</p>;

    return (
        <div data-testid="managed-portal-page">
            <div data-testid="managed-banner" className="sticky top-[57px] z-10 -mx-4 px-4 py-2.5 bg-portal-blue text-white flex items-center justify-between">
                <span className="text-sm font-semibold">You are managing {data.patient_name}'s account</span>
                <button data-testid="return-to-my-account" onClick={() => nav("/portal")} className="text-xs underline flex items-center gap-1"><ArrowLeft className="w-3 h-3" /> Return to my account</button>
            </div>

            <h1 className="text-xl font-bold text-portal-blueDark mt-4">{data.patient_name}</h1>
            <p className="text-xs text-slate-500 mb-4">{data.relationship} · you can: {data.permissions.join(", ")}</p>

            {can("APPOINTMENTS") && (
                <Section icon={Calendar} title="Appointments" testid="managed-appointments"
                    action={<Button size="sm" variant="outline" data-testid="managed-request-appt" onClick={() => setShowAppt((v) => !v)}><Plus className="w-4 h-4 mr-1" /> Request</Button>}>
                    {showAppt && <ApptForm patientId={patientId} onDone={() => { setShowAppt(false); load(); }} />}
                    {(data.appointments || []).length === 0 ? <Empty /> : data.appointments.map((a, i) => (
                        <Line key={i} title={a.reason || "Appointment"} sub={a.confirmed_display || `${a.preferred_date || ""} ${a.preferred_time || ""}`} status={a.status} />
                    ))}
                </Section>
            )}

            {can("RX_REQUESTS") && (
                <Section icon={Pill} title="Prescription renewals" testid="managed-rx"
                    action={<Button size="sm" variant="outline" data-testid="managed-request-rx" onClick={() => setShowRx((v) => !v)}><Plus className="w-4 h-4 mr-1" /> Refill</Button>}>
                    {showRx && <MedicationRefill onBehalfOf={patientId} onSubmitted={() => { setShowRx(false); load(); }} />}
                    {!showRx && <p className="text-xs text-slate-400">Submit a refill request on behalf of {data.patient_name}.</p>}
                </Section>
            )}

            {can("DOCUMENTS") && (
                <Section icon={FileText} title="Released documents" testid="managed-documents">
                    {(data.documents || []).length === 0 ? <Empty /> : data.documents.map((d) => (
                        <div key={d.id} className="flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0">
                            <span className="text-sm text-slate-700">{d.filename || d.title || "Document"}</span>
                            <button data-testid="managed-doc-download" onClick={() => download(d)} className="text-portal-blue"><Download className="w-4 h-4" /></button>
                        </div>
                    ))}
                </Section>
            )}

            {can("REQUEST_STATUS") && (
                <Section icon={ClipboardList} title="Request & referral status" testid="managed-requests">
                    {(data.requests || []).length === 0 ? <Empty /> : data.requests.map((r, i) => (
                        <Line key={i} title={`${r.type} · ${r.ref_number || ""}`} status={r.status} />
                    ))}
                </Section>
            )}
        </div>
    );
}

const Empty = () => <p className="text-xs text-slate-400">Nothing to show.</p>;
const Line = ({ title, sub, status }) => (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0">
        <div><div className="text-sm text-slate-700">{title}</div>{sub && <div className="text-xs text-slate-400">{sub}</div>}</div>
        {status && <span className="text-xs font-semibold text-portal-blue">{status}</span>}
    </div>
);
const Section = ({ icon: Icon, title, testid, action, children }) => (
    <div data-testid={testid} className="bg-white rounded-xl border border-slate-200 p-4 mb-3">
        <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-1.5"><Icon className="w-4 h-4 text-portal-blue" /> {title}</h2>
            {action}
        </div>
        {children}
    </div>
);

function ApptForm({ patientId, onDone }) {
    const [reason, setReason] = useState(""); const [date, setDate] = useState(""); const [time, setTime] = useState(""); const [busy, setBusy] = useState(false);
    const submit = async () => {
        if (!reason.trim() || !date || !time) return toast.error("Enter reason, date and time.");
        setBusy(true);
        try {
            await api.post(`/portal/appointments?on_behalf_of=${patientId}`, { reason, options: [{ date, time }] });
            toast.success("Appointment request submitted."); onDone();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <div className="mb-3 space-y-2" data-testid="managed-appt-form">
            <Input data-testid="managed-appt-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for visit" />
            <div className="flex gap-2">
                <Input data-testid="managed-appt-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
                <Input data-testid="managed-appt-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
            </div>
            <Button data-testid="managed-appt-submit" disabled={busy} onClick={submit} className="bg-portal-blue text-white">{busy ? "Submitting…" : "Request appointment"}</Button>
        </div>
    );
}
