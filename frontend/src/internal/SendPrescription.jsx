import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
    Search, Plus, Trash2, Upload, FileText, X, Send, Truck, Building2,
    UserCheck, CheckCircle2, Clock, Eye, ClipboardPaste, RotateCw, Pencil, AlertTriangle, Paperclip,
} from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

const EMPTY_MED = { drug: "", strength: "", unit: "", form: "", attributes: [], sig: "", quantity: "", refills: "", note: "", original_text: "", needs_review: [], _editing: true };

function StatusPill({ status }) {
    const map = {
        SENT: { icon: Clock, cls: "bg-amber-100 text-amber-800" },
        VIEWED: { icon: Eye, cls: "bg-sky-100 text-sky-800" },
        ACKNOWLEDGED: { icon: CheckCircle2, cls: "bg-emerald-100 text-emerald-800" },
    };
    const { icon: Icon, cls } = map[status] || map.SENT;
    return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`} data-testid="rxtx-status"><Icon className="w-3 h-3" /> {status}</span>;
}

export default function SendPrescription() {
    const [patient, setPatient] = useState(null);
    const [pharmacies, setPharmacies] = useState([]);
    const [pharmacyId, setPharmacyId] = useState("");
    const [prevMeds, setPrevMeds] = useState([]);

    const [meds, setMeds] = useState([]);
    const [rx, setRx] = useState({ months: "", refills: "", note: "", _editing: false });
    const [sourceText, setSourceText] = useState("");
    const [paste, setPaste] = useState("");
    const [warnings, setWarnings] = useState([]);
    const [ackMismatch, setAckMismatch] = useState(false);
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);
    const [parsing, setParsing] = useState(false);
    const [history, setHistory] = useState([]);

    const [query, setQuery] = useState("");
    const [pin, setPin] = useState("");
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);

    const loadHistory = useCallback(() => api.get("/internal/send-rx").then(({ data }) => setHistory(data)).catch(() => {}), []);

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
            const cur = (data.current_pharmacy || "").toLowerCase();
            const match = cur ? pharmacies.find((p) => (p.pharmacy_name || "").toLowerCase().includes(cur) || cur.includes((p.pharmacy_name || "").toLowerCase())) : null;
            setPharmacyId(match ? match.pharmacy_id : (pharmacies.length === 1 ? pharmacies[0].pharmacy_id : ""));
            const ref = data.directory_id || data.patient_id || id;
            api.get(`/internal/patients/${ref}/medications`).then(({ data: pm }) => setPrevMeds(pm)).catch(() => setPrevMeds([]));
        } catch (err) { toast.error(formatErr(err)); }
    };

    const resetRxDraft = () => { setMeds([]); setRx({ months: "", refills: "", note: "", _editing: false }); setSourceText(""); setPaste(""); setWarnings([]); setAckMismatch(false); setFile(null); };
    const resetAll = () => { setPatient(null); setPharmacyId(""); setPrevMeds([]); resetRxDraft(); };

    const repeatRx = (pm) => {
        setMeds((s) => [...s, {
            drug: pm.drug || "", strength: pm.strength || "", unit: pm.unit || "", form: pm.form || "",
            attributes: pm.attributes || [], sig: pm.sig || "", quantity: "", refills: "",
            note: pm.note || "", original_text: pm.original_text || "", needs_review: [], _editing: false,
        }]);
        setRx((r) => ({ ...r, months: pm.months ?? r.months, refills: pm.refills ?? r.refills }));
        toast.success("Added to prescription. Review and send.");
    };

    const organize = async () => {
        if (!paste.trim()) { toast.error("Paste the prescription text first."); return; }
        setParsing(true);
        try {
            const ref = patient ? (patient.directory_id || patient.patient_id) : null;
            const { data } = await api.post("/internal/rx/parse", { text: paste, patient_ref: ref });
            const parsed = (data.medications || []).map((m) => ({ ...EMPTY_MED, ...m, attributes: m.attributes || [], _editing: false }));
            if (parsed.length === 0 && !data.note) toast.error("No medications could be identified. You can add one manually.");
            setMeds((s) => [...s, ...parsed]);
            setRx((r) => ({ months: data.months ?? r.months, refills: data.refills ?? r.refills, note: data.note || r.note, _editing: false }));
            setSourceText((t) => (t ? `${t}\n${paste}` : paste));
            setWarnings(data.warnings || []);
            setAckMismatch(false);
            setPaste("");
            toast.success(`Organized ${parsed.length} medication(s).`);
        } catch (err) { toast.error(formatErr(err)); } finally { setParsing(false); }
    };

    const setMed = (i, k, v) => setMeds((s) => s.map((m, idx) => (idx === i ? { ...m, [k]: v } : m)));
    const toggleEdit = (i) => setMeds((s) => s.map((m, idx) => (idx === i ? { ...m, _editing: !m._editing } : m)));
    const removeMed = (i) => setMeds((s) => s.filter((_, idx) => idx !== i));
    const addManual = () => setMeds((s) => [...s, { ...EMPTY_MED }]);

    const pickPdf = (f) => {
        if (!f) return;
        if (!(f.type === "application/pdf" || /\.pdf$/i.test(f.name))) { toast.error("Only PDF files are accepted."); return; }
        if (f.size > 15 * 1024 * 1024) { toast.error("File too large. Maximum size is 15 MB."); return; }
        setFile(f);
    };

    const filledMeds = meds.filter((m) => (m.drug || "").trim());
    const selectedPharmacy = pharmacies.find((p) => p.pharmacy_id === pharmacyId);
    const mismatchBlocked = warnings.length > 0 && !ackMismatch;
    const canSend = !!patient && !!pharmacyId && (filledMeds.length > 0 || !!file) && !mismatchBlocked && !busy;

    const send = async () => {
        if (!canSend) return;
        setBusy(true);
        try {
            const fd = new FormData();
            fd.append("patient_ref", patient.directory_id || patient.patient_id);
            fd.append("pharmacy_id", pharmacyId);
            fd.append("medications", JSON.stringify(filledMeds.map(({ _editing, needs_review, ...m }) => m)));
            fd.append("physician_note", rx.note || "");
            if (rx.months !== "" && rx.months != null) fd.append("months", String(rx.months));
            if (rx.refills !== "" && rx.refills != null) fd.append("refills", String(rx.refills));
            if (sourceText) fd.append("source_text", sourceText);
            if (file) fd.append("file", file);
            await api.post("/internal/send-rx", fd, { headers: { "Content-Type": "multipart/form-data" } });
            toast.success("Prescription sent to the pharmacy.");
            const keepPatient = patient, keepPharm = pharmacyId, keepRef = patient.directory_id || patient.patient_id;
            resetRxDraft();
            setPatient(keepPatient); setPharmacyId(keepPharm);
            api.get(`/internal/patients/${keepRef}/medications`).then(({ data: pm }) => setPrevMeds(pm)).catch(() => {});
            loadHistory();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const patientName = (p) => `${p.last_name || ""}, ${p.first_name || ""}`.replace(/^, |, $/g, "");

    return (
        <div className="animate-fade-in max-w-5xl">
            <div className="flex items-center gap-3 mb-1">
                <Truck className="w-6 h-6 text-visita-greenDark" />
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Send Prescription</h1>
            </div>
            <p className="text-sm text-slate-500 mb-5">Send a prescription securely to a patient's pharmacy.</p>

            <section className="bg-white border border-slate-300 rounded-sm p-5 mb-4">
                <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Step 1 — Find patient</div>
                {!patient ? (
                    <>
                        <form onSubmit={(e) => runSearch(e, false)} className="flex gap-2">
                            <div className="relative flex-1">
                                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                                <Input data-testid="sendrx-search" value={query} onChange={(e) => { setQuery(e.target.value); if (!e.target.value.trim()) setResults([]); }} placeholder="Patient name, VIen / VISITA Patient ID, DOB or phone" className="pl-8" />
                            </div>
                            <Button type="submit" disabled={searching} data-testid="sendrx-search-btn">{searching ? "…" : "Search"}</Button>
                        </form>
                        <div className="my-3 flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-400"><span className="flex-1 border-t border-slate-200" />or search by PIN<span className="flex-1 border-t border-slate-200" /></div>
                        <form onSubmit={(e) => runSearch(e, true)} className="flex gap-2">
                            <div className="relative flex-1">
                                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                                <Input data-testid="sendrx-pin" value={pin} inputMode="numeric" onChange={(e) => { const v = e.target.value.replace(/[^\d]/g, ""); setPin(v); if (!v) setResults([]); }} placeholder="VISITA PIN (numbers only)" className="pl-8" />
                            </div>
                            <Button type="submit" variant="outline" disabled={searching} data-testid="sendrx-pin-btn">Find by PIN</Button>
                        </form>
                        <div className="mt-3 divide-y border border-slate-200 rounded-sm max-h-72 overflow-y-auto">
                            {results.length === 0 && <div className="px-3 py-4 text-slate-400 text-sm">Search the patient directory by name, ID, PIN, DOB or phone.</div>}
                            {results.map((r) => (
                                <button key={r.id} data-testid="sendrx-result" onClick={() => selectPatient(r.id)} className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex justify-between gap-2">
                                    <span className="font-semibold">{patientName(r)}</span>
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
                                <div className="font-bold text-slate-900">{patientName(patient)}</div>
                                <div className="text-slate-500 text-xs mt-0.5">DOB {formatDate(patient.date_of_birth)}{patient.visita_patient_id ? ` · PIN ${patient.visita_patient_id}` : ""}{patient.phone ? ` · ${patient.phone}` : ""}</div>
                                {patient.current_pharmacy && <div className="text-slate-400 text-xs mt-0.5">Default pharmacy: {patient.current_pharmacy}</div>}
                            </div>
                        </div>
                        <button className="text-xs text-slate-400 hover:text-slate-600" onClick={resetAll} data-testid="sendrx-change-patient">Change</button>
                    </div>
                )}
            </section>

            {patient && (
                <>
                    <section className="bg-white border border-slate-300 rounded-sm p-5 mb-4">
                        <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Step 2 — Send to pharmacy</div>
                        {pharmacies.length === 0 ? (
                            <p className="text-sm text-amber-700">No pharmacy portal accounts are available. Portal delivery is unavailable.</p>
                        ) : (
                            <div className="space-y-2">
                                <select data-testid="sendrx-pharmacy" value={pharmacyId} onChange={(e) => setPharmacyId(e.target.value)} className="w-full border border-slate-200 rounded-sm h-10 px-2 bg-white text-sm">
                                    <option value="">Select a pharmacy…</option>
                                    {pharmacies.map((p) => (<option key={p.pharmacy_id} value={p.pharmacy_id}>{p.pharmacy_name}</option>))}
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

                    <section className="bg-white border border-slate-300 rounded-sm p-5 mb-4 space-y-5">
                        <div className="text-xs uppercase tracking-wide text-slate-400">Step 3 — Prescription</div>

                        <div>
                            <div className="text-sm font-semibold text-slate-700 mb-2">Previous / Current Prescriptions</div>
                            {prevMeds.length === 0 ? (
                                <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-sm px-3 py-2" data-testid="sendrx-no-history">No medication history has been recorded in VIen yet. Paste from Access below to get started.</div>
                            ) : (
                                <div className="space-y-2">
                                    {prevMeds.map((pm) => (
                                        <div key={pm.id} data-testid="sendrx-prevmed" className="flex items-start justify-between gap-3 border border-slate-200 rounded-sm px-3 py-2">
                                            <div className="text-sm">
                                                <div className="font-semibold text-slate-800">{[pm.drug, pm.strength].filter(Boolean).join(" ")}</div>
                                                <div className="text-slate-500 text-xs">{[pm.form, ...(pm.attributes || [])].filter(Boolean).join(" · ")}</div>
                                                {pm.sig && <div className="text-slate-600 text-xs mt-0.5">{pm.sig}</div>}
                                                <div className="text-slate-400 text-[11px] mt-0.5">Last prescribed: {formatDate(pm.last_prescribed_at)}</div>
                                            </div>
                                            <Button size="sm" variant="outline" data-testid="sendrx-repeat" onClick={() => repeatRx(pm)}><RotateCw className="w-3.5 h-3.5 mr-1" /> Repeat Rx</Button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div>
                            <div className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-1"><ClipboardPaste className="w-4 h-4" /> Paste from Access EMR</div>
                            <p className="text-xs text-slate-500 mb-2">Copy the prescription from Access and paste it here. VIen will organize the medication details for you.</p>
                            <Textarea data-testid="sendrx-paste" value={paste} onChange={(e) => setPaste(e.target.value)} rows={4} placeholder={"Candesartan cilexetil 16 mg tablet film-coated scored: 1 tablet HS\nNumber of months: 3\nNumber of refills: 0"} />
                            <Button size="sm" className="mt-2" onClick={organize} disabled={parsing} data-testid="sendrx-organize"><ClipboardPaste className="w-4 h-4 mr-1" /> {parsing ? "Organizing…" : "Organize Prescription"}</Button>
                        </div>

                        {warnings.length > 0 && (
                            <div className="border border-amber-300 bg-amber-50 rounded-sm p-3" data-testid="sendrx-mismatch">
                                <div className="flex items-center gap-2 text-amber-800 font-semibold text-sm"><AlertTriangle className="w-4 h-4" /> Patient information in the pasted prescription may not match the selected patient.</div>
                                <ul className="list-disc pl-6 text-xs text-amber-700 mt-1">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
                                <label className="flex items-center gap-2 text-xs text-amber-800 mt-2 cursor-pointer">
                                    <input type="checkbox" checked={ackMismatch} onChange={(e) => setAckMismatch(e.target.checked)} data-testid="sendrx-ack-mismatch" />
                                    I have verified this prescription is for {patientName(patient)}.
                                </label>
                            </div>
                        )}

                        {meds.length > 0 && (
                            <div>
                                <div className="text-sm font-semibold text-slate-700 mb-2">VIen understood</div>
                                <div className="space-y-2">
                                    {meds.map((m, i) => (
                                        <div key={i} data-testid="sendrx-med-card" className="border border-slate-200 rounded-sm p-3">
                                            {!m._editing ? (
                                                <div className="flex items-start justify-between gap-3">
                                                    <div className="text-sm">
                                                        <div className="font-semibold text-slate-800">{[m.drug || "(medication?)", m.strength].filter(Boolean).join(" ")}</div>
                                                        <div className="text-slate-500 text-xs">{[m.form, ...(m.attributes || [])].filter(Boolean).join(" · ") || "—"}</div>
                                                        {m.sig ? <div className="text-slate-700 text-xs mt-1"><span className="text-slate-400">SIG</span> {m.sig}</div> : null}
                                                        {(m.needs_review || []).length > 0 && <div className="text-amber-600 text-[11px] mt-1 inline-flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> Review: {m.needs_review.join(", ")}</div>}
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <button onClick={() => toggleEdit(i)} data-testid="sendrx-edit-med" className="text-xs text-slate-500 hover:underline inline-flex items-center gap-1"><Pencil className="w-3.5 h-3.5" /> Edit</button>
                                                        <button onClick={() => removeMed(i)} className="text-slate-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
                                                    </div>
                                                </div>
                                            ) : (
                                                <div className="space-y-2">
                                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                                        <div><Label className="text-xs">Medication / Drug</Label><Input data-testid="sendrx-drug" value={m.drug} onChange={(e) => setMed(i, "drug", e.target.value)} /></div>
                                                        <div><Label className="text-xs">Strength</Label><Input value={m.strength} onChange={(e) => setMed(i, "strength", e.target.value)} /></div>
                                                        <div><Label className="text-xs">Dosage form</Label><Input value={m.form} onChange={(e) => setMed(i, "form", e.target.value)} /></div>
                                                        <div><Label className="text-xs">Directions / SIG</Label><Input value={m.sig} onChange={(e) => setMed(i, "sig", e.target.value)} /></div>
                                                    </div>
                                                    <div><Label className="text-xs">Physician note (optional)</Label><Input value={m.note} onChange={(e) => setMed(i, "note", e.target.value)} /></div>
                                                    {m.original_text && <div className="text-[11px] text-slate-400">Original: {m.original_text}</div>}
                                                    <div className="flex justify-end gap-2">
                                                        <button onClick={() => removeMed(i)} className="text-xs text-red-600 inline-flex items-center gap-1"><Trash2 className="w-3.5 h-3.5" /> Remove</button>
                                                        <Button size="sm" variant="outline" onClick={() => toggleEdit(i)}>Done</Button>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>

                                <div className="border border-slate-200 rounded-sm p-3 mt-2" data-testid="sendrx-rxlevel">
                                    {!rx._editing ? (
                                        <div className="flex items-center justify-between">
                                            <div className="text-sm text-slate-700"><span className="text-slate-400 text-xs uppercase mr-2">Prescription</span>{rx.months !== "" && rx.months != null ? `${rx.months} month(s)` : "Duration not set"} · {rx.refills !== "" && rx.refills != null ? `${rx.refills} refill(s)` : "Refills not set"}</div>
                                            <button onClick={() => setRx((r) => ({ ...r, _editing: true }))} data-testid="sendrx-edit-rx" className="text-xs text-slate-500 hover:underline inline-flex items-center gap-1"><Pencil className="w-3.5 h-3.5" /> Edit Prescription Details</button>
                                        </div>
                                    ) : (
                                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 items-end">
                                            <div><Label className="text-xs">Number of months</Label><Input inputMode="numeric" value={rx.months} onChange={(e) => setRx((r) => ({ ...r, months: e.target.value.replace(/[^\d]/g, "") }))} /></div>
                                            <div><Label className="text-xs">Number of refills</Label><Input inputMode="numeric" value={rx.refills} onChange={(e) => setRx((r) => ({ ...r, refills: e.target.value.replace(/[^\d]/g, "") }))} /></div>
                                            <Button size="sm" variant="outline" onClick={() => setRx((r) => ({ ...r, _editing: false }))}>Done</Button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        <div>
                            <div className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2"><Upload className="w-4 h-4" /> Upload existing Rx PDF</div>
                            <input id="sendrx-pdf-input" type="file" accept="application/pdf,.pdf" className="hidden" data-testid="sendrx-pdf-input" onChange={(e) => pickPdf(e.target.files?.[0])} />
                            {!file ? (
                                <Button variant="outline" size="sm" onClick={() => document.getElementById("sendrx-pdf-input").click()} data-testid="sendrx-upload-pdf"><Upload className="w-4 h-4 mr-1" /> Upload PDF</Button>
                            ) : (
                                <div className="border border-slate-200 rounded-sm p-3 flex items-center gap-3" data-testid="sendrx-pdf-preview">
                                    <FileText className="w-8 h-8 text-slate-400" />
                                    <div className="flex-1 min-w-0"><div className="text-sm font-medium text-slate-800 truncate">{file.name}</div><div className="text-xs text-slate-400">{(file.size / 1024).toFixed(0)} KB · PDF</div></div>
                                    <button onClick={() => document.getElementById("sendrx-pdf-input").click()} className="text-xs text-slate-500 hover:underline" data-testid="sendrx-replace-pdf">Replace</button>
                                    <button onClick={() => { setFile(null); document.getElementById("sendrx-pdf-input").value = ""; }} className="text-slate-400 hover:text-red-600" data-testid="sendrx-remove-pdf"><X className="w-4 h-4" /></button>
                                </div>
                            )}
                        </div>

                        <div>
                            <Button variant="ghost" size="sm" onClick={addManual} data-testid="sendrx-add-manual" className="text-slate-500"><Plus className="w-4 h-4 mr-1" /> Add Medication Manually</Button>
                        </div>
                    </section>

                    <section className="bg-white border border-slate-300 rounded-sm p-5 mb-6">
                        <div className="text-xs uppercase tracking-wide text-slate-400 mb-3">Step 4 — Review & send</div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                            <div><div className="text-xs text-slate-400 uppercase">Patient</div><div className="font-semibold">{patientName(patient)}</div></div>
                            <div><div className="text-xs text-slate-400 uppercase">Pharmacy</div><div className="font-semibold">{selectedPharmacy?.pharmacy_name || "—"}</div></div>
                            <div className="sm:col-span-2">
                                <div className="text-xs text-slate-400 uppercase">Prescription</div>
                                {filledMeds.length > 0 ? (
                                    <ul className="list-disc pl-5 text-slate-700">
                                        {filledMeds.map((m, i) => (<li key={i}>{[m.drug, m.strength, m.form].filter(Boolean).join(" ")}{m.sig ? ` — ${m.sig}` : ""}</li>))}
                                    </ul>
                                ) : <div className="text-slate-400">No manual medications</div>}
                                {(rx.months || rx.refills) && <div className="text-slate-500 text-xs mt-1">{rx.months ? `${rx.months} month(s)` : ""}{rx.months && rx.refills ? " · " : ""}{rx.refills ? `${rx.refills} refill(s)` : ""}</div>}
                            </div>
                            <div className="sm:col-span-2"><div className="text-xs text-slate-400 uppercase">Attachment</div><div className="text-slate-700">{file ? file.name : "None"}</div></div>
                        </div>
                        <Button data-testid="sendrx-send" onClick={send} disabled={!canSend} className="mt-4 bg-visita-green hover:bg-visita-greenDark text-white"><Send className="w-4 h-4 mr-1" /> Send Prescription</Button>
                        {mismatchBlocked && <div className="text-xs text-amber-700 mt-2">Resolve the patient-match warning above before sending.</div>}
                    </section>
                </>
            )}

            <section className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-200 text-sm font-semibold text-slate-700">Recently Sent</div>
                {history.length === 0 ? (
                    <div className="px-4 py-8 text-center text-slate-400 text-sm">No prescriptions sent yet.</div>
                ) : (
                    <table className="w-full text-sm">
                        <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                            <tr><th className="text-left px-3 py-2">Patient</th><th className="text-left px-3 py-2">Pharmacy</th><th className="text-left px-3 py-2">Sent</th><th className="text-left px-3 py-2">Rx</th><th className="text-left px-3 py-2">Status</th><th className="px-3 py-2"></th></tr>
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
                                            <button data-testid="rxtx-attachment" onClick={async () => { try { await openAttachment(`/internal/send-rx/${t.id}/attachment`); } catch (err) { toast.error(formatErr(err)); } }} className="inline-flex items-center gap-1 text-indigo-600 hover:underline text-xs"><Paperclip className="w-3.5 h-3.5" /> PDF</button>
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
