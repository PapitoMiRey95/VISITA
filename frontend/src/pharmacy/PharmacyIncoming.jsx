import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Inbox, ArrowLeft, FileText, Stethoscope, User, Pill, CheckCircle2, Clock, Eye } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";

function StatusPill({ status }) {
    const map = {
        SENT: { icon: Clock, cls: "bg-amber-100 text-amber-800" },
        VIEWED: { icon: Eye, cls: "bg-sky-100 text-sky-800" },
        ACKNOWLEDGED: { icon: CheckCircle2, cls: "bg-emerald-100 text-emerald-800" },
    };
    const { icon: Icon, cls } = map[status] || map.SENT;
    return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`}><Icon className="w-3 h-3" /> {status}</span>;
}

export default function PharmacyIncoming() {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [detail, setDetail] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try { const { data } = await api.get("/pharmacy/incoming"); setItems(data.items || []); }
        catch (err) { toast.error(formatErr(err)); } finally { setLoading(false); }
    }, []);

    useEffect(() => { load(); }, [load]);

    const open = async (id) => {
        try { const { data } = await api.get(`/pharmacy/incoming/${id}`); setDetail(data); load(); }
        catch (err) { toast.error(formatErr(err)); }
    };

    const acknowledge = async () => {
        try { const { data } = await api.post(`/pharmacy/incoming/${detail.id}/acknowledge`); setDetail(data); load(); toast.success("Prescription acknowledged."); }
        catch (err) { toast.error(formatErr(err)); }
    };

    if (detail) {
        return (
            <div className="animate-fade-in">
                <div className="flex items-center gap-3 mb-4">
                    <Button variant="ghost" size="sm" onClick={() => setDetail(null)} data-testid="incoming-back"><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Prescription {detail.ref_number}</h1>
                    <StatusPill status={detail.status} />
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="bg-white border border-slate-300 rounded-sm p-4">
                        <div className="flex items-center gap-2 text-slate-700 font-semibold mb-2"><User className="w-4 h-4" /> Patient</div>
                        <div className="text-sm space-y-1">
                            <div className="font-bold">{detail.patient_name}</div>
                            <div className="text-slate-500">DOB {formatDate(detail.patient_dob)}{detail.visita_patient_id ? ` · PIN ${detail.visita_patient_id}` : ""}</div>
                        </div>
                        <div className="flex items-center gap-2 text-slate-700 font-semibold mt-4 mb-2"><Stethoscope className="w-4 h-4" /> Prescriber</div>
                        <div className="text-sm space-y-1">
                            <div className="font-semibold">{detail.physician_name}</div>
                            <div className="text-slate-500">{detail.clinic_name}</div>
                            <div className="text-slate-400 text-xs">Sent {formatDateTime(detail.sent_at)}</div>
                        </div>
                    </div>

                    <div className="bg-white border border-slate-300 rounded-sm p-4">
                        <div className="flex items-center gap-2 text-slate-700 font-semibold mb-2"><Pill className="w-4 h-4" /> Prescription</div>
                        {(detail.medications || []).length > 0 ? (
                            <ul className="space-y-2 text-sm">
                                {detail.medications.map((m, i) => (
                                    <li key={i} className="border border-slate-100 rounded-sm p-2" data-testid="incoming-med">
                                        <div className="font-semibold">{[m.drug, m.strength, m.form].filter(Boolean).join(" ")}</div>
                                        {m.sig && <div className="text-slate-600">SIG: {m.sig}</div>}
                                        <div className="text-slate-500 text-xs">
                                            {m.quantity ? `Qty ${m.quantity}` : ""}{m.refills ? ` · Refills ${m.refills}` : ""}
                                        </div>
                                        {m.note && <div className="text-slate-400 text-xs">Note: {m.note}</div>}
                                    </li>
                                ))}
                            </ul>
                        ) : <div className="text-slate-400 text-sm">No structured medications — see the attached PDF.</div>}

                        {detail.physician_note && <div className="mt-3 text-sm"><span className="text-xs text-slate-400 uppercase">Note from physician</span><div className="text-slate-700">{detail.physician_note}</div></div>}

                        {detail.has_attachment && (
                            <div className="mt-4">
                                <div className="text-xs text-slate-400 uppercase mb-1">Attachment</div>
                                <Button variant="outline" size="sm" data-testid="incoming-view-pdf"
                                    onClick={async () => { try { await openAttachment(`/pharmacy/incoming/${detail.id}/attachment`); } catch (err) { toast.error(formatErr(err)); } }}>
                                    <FileText className="w-4 h-4 mr-1" /> View Rx PDF
                                </Button>
                            </div>
                        )}

                        {detail.status !== "ACKNOWLEDGED" && (
                            <Button className="mt-4 bg-visita-green hover:bg-visita-greenDark text-white" onClick={acknowledge} data-testid="incoming-acknowledge">
                                <CheckCircle2 className="w-4 h-4 mr-1" /> Acknowledge
                            </Button>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="animate-fade-in">
            <div className="mb-4">
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Incoming Prescriptions</h1>
                <p className="text-sm text-slate-500">Prescriptions sent to your pharmacy by the clinic.</p>
            </div>

            <div className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                {loading ? (
                    <div className="px-4 py-8 text-center text-slate-400 text-sm">Loading…</div>
                ) : items.length === 0 ? (
                    <div className="px-4 py-10 text-center text-slate-400 text-sm">
                        <Inbox className="w-8 h-8 mx-auto mb-2 opacity-50" /> No incoming prescriptions yet.
                    </div>
                ) : (
                    <table className="w-full text-sm">
                        <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                            <tr>
                                <th className="text-left px-3 py-2">Patient</th>
                                <th className="text-left px-3 py-2">Physician</th>
                                <th className="text-left px-3 py-2">Sent</th>
                                <th className="text-left px-3 py-2">Rx</th>
                                <th className="text-left px-3 py-2">PDF</th>
                                <th className="text-left px-3 py-2">Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((t) => (
                                <tr key={t.id} data-testid="incoming-row" className="border-t border-slate-100 cursor-pointer hover:bg-slate-50" onClick={() => open(t.id)}>
                                    <td className="px-3 py-2 font-semibold">{t.patient_name}</td>
                                    <td className="px-3 py-2">{t.physician_name}</td>
                                    <td className="px-3 py-2 text-slate-500 text-xs">{formatDateTime(t.sent_at)}</td>
                                    <td className="px-3 py-2 text-slate-600">{t.medication_summary}</td>
                                    <td className="px-3 py-2">{t.has_attachment ? <FileText className="w-4 h-4 text-indigo-600" /> : "—"}</td>
                                    <td className="px-3 py-2"><StatusPill status={t.status} /></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
