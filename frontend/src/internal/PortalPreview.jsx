import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Eye, ArrowLeft } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";

// Forced light palette: the preview must look like the patient's portal regardless of the viewer's dark theme.
const Card = ({ title, children, testid }) => (
    <section className="rounded-xl border p-4" style={{ background: "#fff", borderColor: "#e2e8f0", color: "#0f172a" }} data-testid={testid}><h2 className="text-sm font-extrabold mb-2" style={{ color: "#0b2545" }}>{title}</h2>{children}</section>
);
const Empty = ({ text }) => <div className="text-xs text-slate-400 italic">{text}</div>;

/* ADMIN PREVIEW: read-only rendering of what the linked patient currently sees. Computed with the viewer's session — not impersonation. */
export default function PortalPreview() {
    const { patientId } = useParams();
    const q = useQuery({ queryKey: ["portal-preview", patientId], queryFn: async () => (await api.get(`/internal/patients/${patientId}/portal-preview`)).data });
    const d = q.data;
    return (
        <div className="min-h-full" style={{ background: "#f4f7fb", color: "#0f172a", colorScheme: "light" }} data-testid="portal-preview">
            <div className="bg-amber-400 text-slate-900 text-xs font-bold px-4 py-2 flex items-center justify-between" data-testid="portal-preview-banner">
                <span className="inline-flex items-center gap-2"><Eye className="w-4 h-4" /> ADMIN PREVIEW — This is what the patient can currently see. Read-only; no patient actions can be performed here.</span>
                <Link to={`/internal/patients?patient_ref=patient:${patientId}`} className="inline-flex items-center gap-1 underline" data-testid="portal-preview-back"><ArrowLeft className="w-3.5 h-3.5" /> Back to patient</Link>
            </div>
            <div className="max-w-5xl mx-auto p-5 space-y-4">
                {q.error && <div className="text-sm text-red-600">{formatErr(q.error)}</div>}
                {d && !d.linked && <Card title="Patient Portal" testid="portal-preview-unlinked"><Empty text={d.message} /></Card>}
                {d?.linked && (<>
                    <div className="text-xl font-extrabold" style={{ color: "#0f172a" }} data-testid="portal-preview-name">{d.patient.first_name} {d.patient.last_name} <span className="text-sm font-normal text-slate-500">· PIN {d.patient.visita_patient_id || "—"}</span></div>
                    <div className="grid md:grid-cols-2 gap-4">
                        <Card title="Your Medicines" testid="portal-preview-meds">
                            {d.medications?.medications?.length ? <ul className="text-sm space-y-1">{d.medications.medications.map((m) => <li key={m.id} data-testid="portal-preview-med"><b>{m.drug}</b> {m.strength_display || m.strength} <span className="text-slate-500 text-xs">{m.sig}</span></li>)}</ul> : <Empty text="No medicines are shown to the patient." />}
                            {d.medications?.previously_prescribed?.length > 0 && <div className="text-[11px] text-slate-400 mt-2">{d.medications.previously_prescribed.length} previously prescribed (shown under refill selection)</div>}
                        </Card>
                        <Card title="Appointments" testid="portal-preview-appts">
                            {d.overview?.appointments?.length ? <ul className="text-sm space-y-1">{d.overview.appointments.slice(0, 6).map((a) => <li key={a.id}>{a.confirmed_display || a.requested_display || (a.slot_date ? `${formatDate(a.slot_date)} ${a.slot_time || ""}` : "—")} · {a.reason} <span className="text-xs text-slate-500">{a.status}</span></li>)}</ul> : <Empty text="No appointments." />}
                        </Card>
                        <Card title="Prescription requests" testid="portal-preview-rx">
                            {d.overview?.requests?.filter((r) => r.type === "Prescription").length ? <ul className="text-sm space-y-1">{d.overview.requests.filter((r) => r.type === "Prescription").slice(0, 6).map((r) => <li key={r.id}>{r.ref_number} · {r.summary} <span className="text-xs text-slate-500">{r.status}</span></li>)}</ul> : <Empty text="No prescription requests." />}
                        </Card>
                        <Card title="Referrals" testid="portal-preview-referrals">
                            {d.overview?.referrals?.length ? <ul className="text-sm space-y-1">{d.overview.referrals.map((r) => <li key={r.id}>{r.specialty} <span className="text-xs text-slate-500">{r.status}</span></li>)}</ul> : <Empty text="No referrals." />}
                        </Card>
                        <Card title="Documents & results" testid="portal-preview-docs">
                            {d.documents?.length ? <ul className="text-sm space-y-1">{d.documents.map((x) => <li key={x.id}>{x.title || x.original_filename} <span className="text-xs text-slate-500">{String(x.shared_at || x.uploaded_at || x.created_at || "").slice(0, 10)}</span></li>)}</ul> : <Empty text="No shared documents." />}
                        </Card>
                        <Card title="Profile information" testid="portal-preview-profile">
                            <div className="text-sm space-y-0.5"><div>{d.patient.email || "—"}</div><div>{d.patient.phone || "—"}</div><div>DOB {d.patient.date_of_birth || "—"}</div>{d.patient.profile_completion && <div className="text-xs text-slate-500">Profile completion: {d.patient.profile_completion.status || JSON.stringify(d.patient.profile_completion)}</div>}</div>
                        </Card>
                    </div>
                </>)}
            </div>
        </div>
    );
}
