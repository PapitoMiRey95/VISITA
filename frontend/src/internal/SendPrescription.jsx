import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
    Search, Plus, Trash2, Upload, FileText, X, Send, Pill, Truck, Building2,
    UserCheck, CheckCircle2, Clock, Eye, ArrowLeft, Paperclip,
} from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

const EMPTY_MED = { drug: "", strength: "", form: "", sig: "", quantity: "", refills: "", note: "" };

function StatusPill({ status }) {
    const map = {
        SENT: { icon: Clock, cls: "bg-amber-100 text-amber-800" },
        VIEWED: { icon: Eye, cls: "bg-sky-100 text-sky-800" },
        ACKNOWLEDGED: { icon: CheckCircle2, cls: "bg-emerald-100 text-emerald-800" },
    };
    const { icon: Icon, cls } = map[status] || map.SENT;
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`} data-testid="rxtx-status">
            <Icon className="w-3 h-3" /> {status}
        </span>
    );
}

export default function SendPrescription() {
    const [patient, setPatient] = useState(null);          // snapshot
    const [pharmacies, setPharmacies] = useState([]);
    const [pharmacyId, setPharmacyId] = useState("");
    const [meds, setMeds] = useState([{ ...EMPTY_MED }]);
    const [note, setNote] = useState("");
    const [file, setFile] = useState(null);
    const [confirmed, setConfirmed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [history, setHistory] = useState([]);

    // patient search state
    const [query, setQuery] = useState("");
    const [pin, setPin] = useState("");
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);

    const loadHistory = useCallback(async () => {
        try { const { data } = await api.get("/internal/send-rx"); setHistory(data); }
        catch (err) { /* non-blocking */ }
    }, []);

    useEffect(() => {
        api.get("/internal/pharmacies").then(({ data }) => setPharmacies(data)).catch(() => {});
        loadHistory();
    }, [loadHistory]);

    const runSearch = async (e, byPin = false) => {
        e?.preventDefault();
        const term = (byPin ? pin : query).trim();
        if (byPin && !/^\d+$/.test(term)) { toast.error("PIN must be numbers only."); return; }
        if (!term) return;
        setSearching(true);
        try {
            const url = byPin ? "/internal/patient-lookup/pin" : "/internal/patient-lookup";
            const params = byPin ? { pin: term } : { q: term };
            const { data } = await api.get(url, { params });
            setResults(data);
            if (data.length === 0) toast.error("No matching patient found.");
        } catch (err) { toast.error(formatErr(err)); } finally { setSearching(false); }
    };

    const selectPatient = async (id) => {
        try {
            const { data } = await api.get(`/internal/patient-snapshot/${id}`);
            setPatient(data);
            setResults([]); setQuery(""); setPin("");
            // preselect the patient's current pharmacy if it maps to a portal account
            const cur = (data.current_pharmacy || "").toLowerCase();
            const match = cur ? pharmacies.find((p) => (p.pharmacy_name || "").toLowerCase().includes(cur) || cur.includes((p.pharmacy_name || "").toLowerCase())) : null;
            setPharmacyId(match ? match.pharmacy_id : (pharmacies.length === 1 ? pharmacies[0].pharmacy_id : ""));
        } catch (err) { toast.error(formatErr(err)); }
    };

    const setMed = (i, k, v) => setMeds((s) => s.map((m, idx) => (idx === i ? { ...m, [k]: v } : m)));
    const addMed = () => setMeds((s) => [...s, { ...EMPTY_MED }]);
    const removeMed = (i) => setMeds((s) => (s.length === 1 ? s : s.filter((_, idx) => idx !== i)));

    const pickPdf = (f) => {
        if (!f) return;
        const okPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name);
        if (!okPdf) { toast.error("Only PDF files are accepted."); return; }
        if (f.size > 15 * 1024 * 1024) { toast.error("File too large. Maximum size is 15 MB."); return; }
        setFile(f);
    };

    const filledMeds = meds.filter((m) => m.drug.trim());
    const selectedPharmacy = pharmacies.find((p) => p.pharmacy_id === pharmacyId);
    const canSend = !!patient && !!pharmacyId && (filledMeds.length > 0 || !!file) && confirmed && !busy;

    const reset = () => {
        setPatient(null); setPharmacyId(""); setMeds([{ ...EMPTY_MED }]); setNote(""); setFile(null); setConfirmed(false);
    };

    const send = async () => {
        if (!canSend) return;
        setBusy(true);
        try {
            const fd = new FormData();
            fd.append("patient_ref", patient.directory_id || patient.patient_id);
            fd.append("pharmacy_id", pharmacyId);
            fd.append("medications", JSON.stringify(filledMeds));
            fd.append("physician_note", note.trim());
            fd.append("confirm", "true");
            if (file) fd.append("file", file);
            await api.post("/internal/send-rx", fd, { headers: { "Content-Type": "multipart/form-data" } });
            toast.success("Prescription sent to the pharmacy.");
            reset();
            loadHistory();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    return (
        <div className="animate-fade-in max-w-5xl">
            <div className="flex items-center gap-3 mb-1">
                <Truck className="w-6 h-6 text-visita-greenDark" />
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Send Prescription</h1>
            </div>
            <p className="text-sm text-slate-500 mb-5">Send a prescription securely to a patient's pharmacy.</p>

            {/* STEP 1 — FIND PATIENT */}
            <section className="bg-white border border-slate-300 rounded-sm p-5 mb-4">
                <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Step 1 — Find patient</div>
                {!patient ? (
                    <>
                        <form onSubmit={(e) => runSearch(e, false)} className="flex gap-2">
                            <div className="relative flex-1">
                                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                                <Input data-testid="sendrx-search" value={query}
                                    onChange={(e) => { setQuery(e.target.value); if (!e.target.value.trim()) setResults([]); }}
                                    placeholder="Patient name, VIen / VISITA Patient ID, DOB or phone" className="pl-8" />
                            </div>
                            <Button type="submit" disabled={searching} data-testid="sendrx-search-btn">{searching ? "…" : "Search"}</Button>
                        </form>
                        <div className="my-3 flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-400">
                            <span className="flex-1 border-t border-slate-200" />or search by PIN<span className="flex-1 border-t border-slate-200" />
                        </div>
                        <form onSubmit={(e) => runSearch(e, true)} className="flex gap-2">
                            <div className="relative flex-1">
                                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                                <Input data-testid="sendrx-pin" value={pin} inputMode="numeric"
                                    onChange={(e) => { const v = e.target.value.replace(/[^\d]/g, ""); setPin(v); if (!v) setResults([]); }}
                                    placeholder="VISITA PIN (numbers only)" className="pl-8" />
                            </div>
                            <Button type="submit" variant="outline" disabled={searching} data-testid="sendrx-pin-btn">Find by PIN</Button>
                        </form>
                        <div className="mt-3 divide-y border border-slate-200 rounded-sm max-h-72 overflow-y-auto">
                            {results.length === 0 && <div className="px-3 py-4 text-slate-400 text-sm">Search the patient directory by name, ID, PIN, DOB or phone.</div>}
                            {results.map((r) => (
                                <button key={r.id} data-testid="sendrx-result" onClick={() => selectPatient(r.id)}
                                    className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex justify-between gap-2">
                                    <span className="font-semibold">{`${r.last_name || ""}, ${r.first_name || ""}`.replace(/^, |, $/, "")}</span>
                                    <span className="text-slate-500 text-xs">{r.visita_patient_id ? `PIN ${r.visita_patient_id}` : (r.patient_status || "")} · DOB {formatDate(r.date_of_birth)}</span>
                                </button>
                            ))}
                        </div>
                    </>
                ) : (
                    <div className="flex items-start justify-between gap-3 bg-slate-50 border border-slate-200 rounded-sm p-3" data-testid="sendrx-patient-card">
                        <div className="flex items-start gap-2">
                            <UserCheck className="w-5 h-5 text-visita-greenDark mt-0.5" />
                            <div className="text-sm">
                                <div className="font-bold text-slate-900">{`${patient.last_name || ""}, ${patient.first_name || ""}`.replace(/^, |, $/, "")}</div>
                                <div className="text-slate-500 text-xs mt-0.5">
                                    DOB {formatDate(patient.date_of_birth)}
                                    {patient.visita_patient_id ? ` · PIN ${patient.visita_patient_id}` : ""}
                                    {patient.phone ? ` · ${patient.phone}` : ""}
                                </div>
                                {patient.current_pharmacy && <div className="text-slate-400 text-xs mt-0.5">Default pharmacy: {patient.current_pharmacy}</div>}
                            </div>
                        </div>
                        <button className="text-xs text-slate-400 hover:text-slate-600" onClick={reset} data-testid="sendrx-change-patient">Change</button>
                    </div>
                )}
            </section>

            {patient && (
                <>
                    {/* STEP 2 — SELECT PHARMACY */}
                    <section className="bg-white border border-slate-300 rounded-sm p-5 mb-4">
                        <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Step 2 — Send to pharmacy</div>
                        {pharmacies.length === 0 ? (
                            <p className="text-sm text-amber-700">No pharmacy portal accounts are available. Portal delivery is unavailable.</p>
                        ) : (
                            <div className="space-y-2">
                                <Label className="text-xs">Pharmacy</Label>
                                <select data-testid="sendrx-pharmacy" value={pharmacyId} onChange={(e) => setPharmacyId(e.target.value)}
                                    className="w-full border border-slate-200 rounded-sm h-10 px-2 bg-white text-sm">
                                    <option value="">Select a pharmacy…</option>
                                    {pharmacies.map((p) => (
                                        <option key={p.pharmacy_id} value={p.pharmacy_id}>{p.pharmacy_name}</option>
                                    ))}
                                </select>
                                {selectedPharmacy && (
                                    <div className="text-xs text-slate-500 flex flex-wrap gap-x-4 gap-y-0.5 pt-1">
                                        <span className="inline-flex items-center gap-1"><Building2 className="w-3.5 h-3.5" /> {selectedPharmacy.pharmacy_name}</span>
                                        {selectedPharmacy.address && <span>{selectedPharmacy.address}</span>}
                                        {selectedPharmacy.phone && <span>Tel: {selectedPharmacy.phone}</span>}
                                        {selectedPharmacy.fax && <span>Fax: {selectedPharmacy.fax}</span>}
                                        <span className="text-emerald-600">Portal delivery available</span>
                                    </div>
                                )}
                            </div>
                        )}
                    </section>

                    {/* STEP 3 — PRESCRIPTION */}
                    <section className="bg-white border border-slate-300 rounded-sm p-5 mb-4">
                        <div className="text-xs uppercase tracking-wide text-slate-400 mb-3">Step 3 — Prescription</div>
                        <div className="flex items-center gap-2 text-slate-700 font-semibold mb-2"><Pill className="w-4 h-4" /> Enter prescription in VIen EMR</div>
                        <div className="space-y-3">
                            {meds.map((m, i) => (
                                <div key={i} className="border border-slate-200 rounded-sm p-3" data-testid="sendrx-med-line">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-xs font-semibold text-slate-500">Medication {i + 1}</span>
                                        {meds.length > 1 && (
                                            <button onClick={() => removeMed(i)} data-testid="sendrx-remove-med" className="text-slate-400 hover:text-red-600 inline-flex items-center gap-1 text-xs">
                                                <Trash2 className="w-3.5 h-3.5" /> Remove
                                            </button>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                        <div><Label className="text-xs">Medication / Drug</Label><Input data-testid="sendrx-drug" value={m.drug} onChange={(e) => setMed(i, "drug", e.target.value)} placeholder="e.g. Ramipril" /></div>
                                        <div><Label className="text-xs">Strength</Label><Input value={m.strength} onChange={(e) => setMed(i, "strength", e.target.value)} placeholder="e.g. 10 mg" /></div>
                                        <div><Label className="text-xs">Dosage form</Label><Input value={m.form} onChange={(e) => setMed(i, "form", e.target.value)} placeholder="e.g. tablet" /></div>
                                        <div><Label className="text-xs">Directions / SIG</Label><Input value={m.sig} onChange={(e) => setMed(i, "sig", e.target.value)} placeholder="e.g. 1 tab PO daily" /></div>
                                        <div><Label className="text-xs">Quantity</Label><Input value={m.quantity} onChange={(e) => setMed(i, "quantity", e.target.value)} placeholder="e.g. 90" /></div>
                                        <div><Label className="text-xs">Refills</Label><Input value={m.refills} onChange={(e) => setMed(i, "refills", e.target.value)} placeholder="e.g. 3" /></div>
                                    </div>
                                    <div className="mt-2"><Label className="text-xs">Physician note (optional)</Label><Input value={m.note} onChange={(e) => setMed(i, "note", e.target.value)} /></div>
                                </div>
                            ))}
                            <Button variant="outline" size="sm" onClick={addMed} data-testid="sendrx-add-med"><Plus className="w-4 h-4 mr-1" /> Add Medication</Button>
                        </div>

                        <div className="mt-4">
                            <div className="flex items-center gap-2 text-slate-700 font-semibold mb-2"><Upload className="w-4 h-4" /> Upload Rx PDF (optional)</div>
                            <input id="sendrx-pdf-input" type="file" accept="application/pdf,.pdf" className="hidden"
                                data-testid="sendrx-pdf-input" onChange={(e) => pickPdf(e.target.files?.[0])} />
                            {!file ? (
                                <Button variant="outline" onClick={() => document.getElementById("sendrx-pdf-input").click()} data-testid="sendrx-upload-pdf">
                                    <Upload className="w-4 h-4 mr-1" /> Upload Rx PDF
                                </Button>
                            ) : (
                                <div className="border border-slate-200 rounded-sm p-3 flex items-center gap-3" data-testid="sendrx-pdf-preview">
                                    <FileText className="w-8 h-8 text-slate-400" />
                                    <div className="flex-1 min-w-0">
                                        <div className="text-sm font-medium text-slate-800 truncate">{file.name}</div>
                                        <div className="text-xs text-slate-400">{(file.size / 1024).toFixed(0)} KB · PDF</div>
                                    </div>
                                    <button onClick={() => document.getElementById("sendrx-pdf-input").click()} className="text-xs text-slate-500 hover:underline" data-testid="sendrx-replace-pdf">Replace</button>
                                    <button onClick={() => { setFile(null); document.getElementById("sendrx-pdf-input").value = ""; }} className="text-slate-400 hover:text-red-600" data-testid="sendrx-remove-pdf"><X className="w-4 h-4" /></button>
                                </div>
                            )}
                        </div>

                        <div className="mt-4">
                            <Label className="text-xs">Message / note to pharmacy (optional)</Label>
                            <Textarea data-testid="sendrx-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
                        </div>
                    </section>

                    {/* STEP 4 — REVIEW & SEND */}
                    <section className="bg-white border border-slate-300 rounded-sm p-5 mb-6">
                        <div className="text-xs uppercase tracking-wide text-slate-400 mb-3">Step 4 — Review & send</div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                            <div><div className="text-xs text-slate-400 uppercase">Patient</div><div className="font-semibold">{`${patient.last_name || ""}, ${patient.first_name || ""}`.replace(/^, |, $/, "")}</div></div>
                            <div><div className="text-xs text-slate-400 uppercase">Pharmacy</div><div className="font-semibold">{selectedPharmacy?.pharmacy_name || "—"}</div></div>
                            <div className="sm:col-span-2">
                                <div className="text-xs text-slate-400 uppercase">Prescription</div>
                                {filledMeds.length > 0 ? (
                                    <ul className="list-disc pl-5 text-slate-700">
                                        {filledMeds.map((m, i) => (
                                            <li key={i}>{[m.drug, m.strength, m.form].filter(Boolean).join(" ")}{m.sig ? ` — ${m.sig}` : ""}{m.quantity ? ` · Qty ${m.quantity}` : ""}{m.refills ? ` · Refills ${m.refills}` : ""}</li>
                                        ))}
                                    </ul>
                                ) : <div className="text-slate-400">No manual medications</div>}
                            </div>
                            <div className="sm:col-span-2"><div className="text-xs text-slate-400 uppercase">Attachment</div><div className="text-slate-700">{file ? file.name : "None"}</div></div>
                        </div>
                        <label className="flex items-start gap-2 mt-4 text-sm cursor-pointer">
                            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} data-testid="sendrx-confirm" className="mt-1" />
                            <span>I confirm this prescription is intended for the selected patient and pharmacy.</span>
                        </label>
                        <Button data-testid="sendrx-send" onClick={send} disabled={!canSend} className="mt-4 bg-visita-green hover:bg-visita-greenDark text-white">
                            <Send className="w-4 h-4 mr-1" /> Send Prescription
                        </Button>
                    </section>
                </>
            )}

            {/* RECENTLY SENT */}
            <section className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-200 text-sm font-semibold text-slate-700">Recently Sent</div>
                {history.length === 0 ? (
                    <div className="px-4 py-8 text-center text-slate-400 text-sm">No prescriptions sent yet.</div>
                ) : (
                    <table className="w-full text-sm">
                        <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                            <tr>
                                <th className="text-left px-3 py-2">Patient</th>
                                <th className="text-left px-3 py-2">Pharmacy</th>
                                <th className="text-left px-3 py-2">Sent</th>
                                <th className="text-left px-3 py-2">Rx</th>
                                <th className="text-left px-3 py-2">Status</th>
                                <th className="px-3 py-2"></th>
                            </tr>
                        </thead>
                        <tbody>
                            {history.map((t) => (
                                <tr key={t.id} data-testid="rxtx-row" className="border-t border-slate-100">
                                    <td className="px-3 py-2 font-semibold">{t.patient_name}</td>
                                    <td className="px-3 py-2">{t.pharmacy_name}</td>
                                    <td className="px-3 py-2 text-slate-500 text-xs">{formatDateTime(t.sent_at)}</td>
                                    <td className="px-3 py-2 text-slate-600">{t.medication_summary}</td>
                                    <td className="px-3 py-2"><StatusPill status={t.status} /></td>
                                    <td className="px-3 py-2 text-right">
                                        {t.has_attachment && (
                                            <button data-testid="rxtx-attachment"
                                                onClick={async () => { try { await openAttachment(`/internal/send-rx/${t.id}/attachment`); } catch (err) { toast.error(formatErr(err)); } }}
                                                className="inline-flex items-center gap-1 text-indigo-600 hover:underline text-xs">
                                                <Paperclip className="w-3.5 h-3.5" /> PDF
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
}
