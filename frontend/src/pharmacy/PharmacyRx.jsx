import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Plus, ArrowLeft, Send, Pill, Paperclip, ClipboardList } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { PatientSearch, IdentityCard, AttachmentPicker } from "./shared";

const EMPTY = { medication_name: "", strength: "", duration_qty: "", pharmacy_note: "", message_to_physician: "" };

export default function PharmacyRx() {
    const [mode, setMode] = useState("list"); // list | new
    const [requests, setRequests] = useState([]);
    const [loading, setLoading] = useState(true);

    const [patient, setPatient] = useState(null);
    const [f, setF] = useState(EMPTY);
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);
    const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

    const load = useCallback(async () => {
        setLoading(true);
        try { const { data } = await api.get("/pharmacy/rx"); setRequests(data); }
        catch (err) { toast.error(formatErr(err)); } finally { setLoading(false); }
    }, []);

    useEffect(() => { load(); }, [load]);

    const startNew = () => { setPatient(null); setF(EMPTY); setFile(null); setMode("new"); };

    const submit = async () => {
        if (!patient) { toast.error("Select a patient first."); return; }
        if (!f.medication_name.trim()) { toast.error("Enter the medication name."); return; }
        setBusy(true);
        try {
            const fd = new FormData();
            fd.append("directory_id", patient.id);
            fd.append("medication_name", f.medication_name.trim());
            fd.append("strength", f.strength.trim());
            fd.append("duration_qty", f.duration_qty.trim());
            fd.append("pharmacy_note", f.pharmacy_note.trim());
            fd.append("message_to_physician", f.message_to_physician.trim());
            if (file) fd.append("file", file);
            await api.post("/pharmacy/rx", fd, { headers: { "Content-Type": "multipart/form-data" } });
            toast.success("Rx request sent to Dr. Aguayo's office.");
            setMode("list");
            load();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    if (mode === "list") {
        return (
            <div className="animate-fade-in">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Rx Requests</h1>
                        <p className="text-sm text-slate-500">Prescription / refill requests sent to Dr. Aguayo's office.</p>
                    </div>
                    <Button onClick={startNew} className="bg-visita-green hover:bg-visita-greenDark text-white" data-testid="new-rx-btn">
                        <Plus className="w-4 h-4 mr-1" /> New Rx Request
                    </Button>
                </div>

                <div className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                    {loading ? (
                        <div className="px-4 py-8 text-center text-slate-400 text-sm">Loading…</div>
                    ) : requests.length === 0 ? (
                        <div className="px-4 py-10 text-center text-slate-400 text-sm">
                            <ClipboardList className="w-8 h-8 mx-auto mb-2 opacity-50" />
                            No Rx requests yet. Click <b>New Rx Request</b> to send one.
                        </div>
                    ) : (
                        <table className="w-full text-sm">
                            <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                                <tr>
                                    <th className="text-left px-3 py-2">Ref</th>
                                    <th className="text-left px-3 py-2">Patient</th>
                                    <th className="text-left px-3 py-2">Medication</th>
                                    <th className="text-left px-3 py-2">Status</th>
                                    <th className="text-left px-3 py-2">Sent</th>
                                    <th className="px-3 py-2"></th>
                                </tr>
                            </thead>
                            <tbody>
                                {requests.map((r) => (
                                    <tr key={r.id} data-testid="rx-row" className="border-t border-slate-100">
                                        <td className="px-3 py-2 text-slate-500">{r.ref_number}</td>
                                        <td className="px-3 py-2 font-semibold">{r.patient_name}</td>
                                        <td className="px-3 py-2">{`${r.medication_name || ""} ${r.strength || ""}`.trim()}</td>
                                        <td className="px-3 py-2"><span className="inline-block px-2 py-0.5 rounded-sm bg-visita-greenLight text-visita-greenDark text-xs">{r.status_label}</span></td>
                                        <td className="px-3 py-2 text-slate-500 text-xs">{formatDateTime(r.created_at)}</td>
                                        <td className="px-3 py-2 text-right">
                                            {r.attachment && (
                                                <button data-testid="rx-row-attachment"
                                                    onClick={async () => { try { await openAttachment(`/pharmacy/rx/${r.id}/attachment`); } catch (err) { toast.error(formatErr(err)); } }}
                                                    className="inline-flex items-center gap-1 text-indigo-600 hover:underline text-xs">
                                                    <Paperclip className="w-3.5 h-3.5" /> File
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>
        );
    }

    // NEW REQUEST
    return (
        <div className="animate-fade-in">
            <div className="flex items-center gap-3 mb-4">
                <Button variant="ghost" size="sm" onClick={() => setMode("list")} data-testid="rx-back"><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">New Rx Request</h1>
            </div>

            {!patient ? (
                <div className="bg-white border border-slate-300 rounded-sm p-5 max-w-xl">
                    <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Step 1 — Find patient</div>
                    <PatientSearch onSelect={setPatient} testidPrefix="rx" />
                </div>
            ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="space-y-4">
                        <IdentityCard p={patient} />
                        <button className="text-xs text-slate-400 hover:text-slate-600" onClick={() => setPatient(null)} data-testid="rx-change-patient">← Choose a different patient</button>
                    </div>

                    <div className="bg-white border border-slate-300 rounded-sm p-4 space-y-3">
                        <div className="flex items-center gap-2 text-slate-700 font-semibold"><Pill className="w-4 h-4" /> Medication request</div>
                        <div><Label className="text-xs">Medication name *</Label><Input data-testid="rx-med-name" value={f.medication_name} onChange={(e) => set("medication_name", e.target.value)} placeholder="e.g. Ramipril" /></div>
                        <div><Label className="text-xs">Strength</Label><Input data-testid="rx-strength" value={f.strength} onChange={(e) => set("strength", e.target.value)} placeholder="e.g. 10 mg" /></div>
                        <div><Label className="text-xs">Requested refill duration / quantity</Label><Input data-testid="rx-duration" value={f.duration_qty} onChange={(e) => set("duration_qty", e.target.value)} placeholder="e.g. 3 months" /></div>
                        <div><Label className="text-xs">Pharmacy note</Label><Textarea data-testid="rx-pharmacy-note" value={f.pharmacy_note} onChange={(e) => set("pharmacy_note", e.target.value)} rows={2} /></div>
                        <div><Label className="text-xs">Message to physician (optional)</Label><Textarea data-testid="rx-message" value={f.message_to_physician} onChange={(e) => set("message_to_physician", e.target.value)} rows={2} /></div>
                        <div>
                            <Label className="text-xs">Attachment (prescription / refill request)</Label>
                            <div className="mt-1"><AttachmentPicker file={file} onChange={setFile} testidPrefix="rx" /></div>
                        </div>
                        <Button data-testid="rx-send" onClick={submit} disabled={busy} className="w-full bg-visita-green hover:bg-visita-greenDark text-white">
                            <Send className="w-4 h-4 mr-1" /> Send Rx Request
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}
