import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import {
    Plus, ArrowLeft, Send, Paperclip, ClipboardList, ClipboardPaste, RotateCw,
    UserCheck, Pill, AlertTriangle, FileText,
} from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/date";
import { formatHealthCardWithVersion } from "../lib/healthCard";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { PatientSearch, AttachmentPicker } from "./shared";
import { PharmacyMedCard } from "./PharmacyMedCard";
import { useUnsavedGuard } from "../internal/unsavedGuard";

const EMPTY_MED = {
    drug: "", action: "", strength: "", form: "", attributes: [], sig: "",
    quantity: "", quantity_unit: "", requested_duration: "",
    existing_rx_number: "", last_filled_date: "", manufacturer: "", days_supply: "",
    current_refills: "", pharmacy_note: "",
    original_text: "", needs_review: [], _editing: true, _moreOpen: false,
};

function InfoRow({ label, children, testid }) {
    return (
        <div className="flex justify-between gap-3 border-b border-slate-100 py-1.5">
            <span className="text-slate-400 text-xs uppercase tracking-wide whitespace-nowrap">{label}</span>
            <span className="text-slate-800 text-right text-sm" data-testid={testid}>{children || "Not available"}</span>
        </div>
    );
}

function PatientInfoPanel({ p }) {
    const ohip = p.health_card_number
        ? `${formatHealthCardWithVersion(p.health_card_number, p.health_card_version || p.health_card_version_code)}${p.health_card_expiry_date ? ` · exp ${formatDate(p.health_card_expiry_date)}` : ""}`
        : null;
    return (
        <div className="bg-white border border-slate-300 rounded-sm p-4" data-testid="pharm-patient-info">
            <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Patient Information</div>
            <InfoRow label="Name" testid="pharm-patient-name">{p.full_name}</InfoRow>
            <InfoRow label="VIen PIN / ID" testid="pharm-patient-pin">{p.visita_patient_id}</InfoRow>
            <InfoRow label="DOB" testid="pharm-patient-dob">{formatDate(p.date_of_birth)}</InfoRow>
            <InfoRow label="Address" testid="pharm-patient-address">{p.address_full}</InfoRow>
            <InfoRow label="Cell" testid="pharm-patient-cell">{p.cell_phone}</InfoRow>
            <InfoRow label="Home" testid="pharm-patient-home">{p.home_phone}</InfoRow>
            <InfoRow label="OHIP / Health Card" testid="pharm-patient-ohip">{ohip}</InfoRow>
            {p.patient_type ? <InfoRow label="Patient type" testid="pharm-patient-type">{p.patient_type}</InfoRow> : null}
        </div>
    );
}

export default function PharmacyRx() {
    const [mode, setMode] = useState("list"); // list | new
    const [requests, setRequests] = useState([]);
    const [loading, setLoading] = useState(true);

    const [patient, setPatient] = useState(null);
    const [meds, setMeds] = useState([]);
    const [file, setFile] = useState(null);
    const [reqNote, setReqNote] = useState("");
    const [msgPhysician, setMsgPhysician] = useState("");
    const [paste, setPaste] = useState("");
    const [parsing, setParsing] = useState(false);
    const [busy, setBusy] = useState(false);

    const [drugOptions, setDrugOptions] = useState([]);
    const [fieldSuggest, setFieldSuggest] = useState({});
    const [priorRequests, setPriorRequests] = useState([]);
    const [storedDraft, setStoredDraft] = useState(null);
    const [changePending, setChangePending] = useState(false);
    const patientRefRef = useRef(null);
    const { setGuard } = useUnsavedGuard();

    const draftKey = (ref) => `visita_pharmacy_rx_draft_${ref}`;
    const clearStoredDraft = (ref) => { try { sessionStorage.removeItem(draftKey(ref || patientRefRef.current)); } catch { /* ignore */ } };

    const load = useCallback(async () => {
        setLoading(true);
        try { const { data } = await api.get("/pharmacy/rx"); setRequests(data); }
        catch (err) { toast.error(formatErr(err)); } finally { setLoading(false); }
    }, []);
    useEffect(() => { load(); }, [load]);

    const ensureDrugSuggest = useCallback((drug) => {
        const key = (drug || "").toLowerCase().trim();
        if (!key || fieldSuggest[key] !== undefined) return;
        setFieldSuggest((s) => ({ ...s, [key]: {} }));
        api.get("/pharmacy/rx/suggest", { params: { patient_ref: patientRefRef.current || undefined, drug } })
            .then(({ data }) => setFieldSuggest((s) => ({ ...s, [key]: data.fields || {} })))
            .catch(() => {});
    }, [fieldSuggest]);

    // --- unsaved-work safeguard ---------------------------------------------
    const dirty = !!patient && !busy && (
        meds.length > 0 || !!paste.trim() || !!file || reqNote.trim() !== "" || msgPhysician.trim() !== ""
    );
    const writeDraft = useCallback(() => {
        const ref = patientRefRef.current; if (!ref) return;
        try { sessionStorage.setItem(draftKey(ref), JSON.stringify({ meds, reqNote, msgPhysician, savedAt: new Date().toISOString() })); } catch { /* ignore */ }
    }, [meds, reqNote, msgPhysician]);
    const saveDraftForLater = useCallback(async () => { writeDraft(); return true; }, [writeDraft]);
    useEffect(() => {
        setGuard({ dirty, save: saveDraftForLater });
        return () => setGuard({ dirty: false, save: null });
    }, [dirty, saveDraftForLater, setGuard]);
    useEffect(() => {
        const h = (e) => { if (dirty) { writeDraft(); e.preventDefault(); e.returnValue = ""; } };
        window.addEventListener("beforeunload", h);
        return () => window.removeEventListener("beforeunload", h);
    }, [dirty, writeDraft]);

    const resetDraft = () => { setMeds([]); setFile(null); setReqNote(""); setMsgPhysician(""); setPaste(""); };
    const resetAll = () => { setPatient(null); setDrugOptions([]); setFieldSuggest({}); setPriorRequests([]); setStoredDraft(null); patientRefRef.current = null; resetDraft(); };

    const startNew = () => { resetAll(); setMode("new"); };

    const selectPatient = async (r) => {
        try {
            const { data } = await api.get(`/pharmacy/patients/${r.id}`);
            setPatient(data);
            const ref = data.id;
            patientRefRef.current = ref;
            setDrugOptions([]); setFieldSuggest({});
            try { const raw = sessionStorage.getItem(draftKey(ref)); setStoredDraft(raw ? JSON.parse(raw) : null); } catch { setStoredDraft(null); }
            api.get("/pharmacy/rx/suggest", { params: { patient_ref: ref } }).then(({ data: sg }) => setDrugOptions(sg.drugs || [])).catch(() => setDrugOptions([]));
            api.get(`/pharmacy/patients/${ref}/prior-requests`).then(({ data: pr }) => setPriorRequests(pr)).catch(() => setPriorRequests([]));
        } catch (err) { toast.error(formatErr(err)); }
    };

    const restoreDraft = () => {
        const d = storedDraft; if (!d) return;
        setMeds(d.meds || []); setReqNote(d.reqNote || ""); setMsgPhysician(d.msgPhysician || "");
        setStoredDraft(null); toast.success("Unsent Rx request restored.");
    };
    const discardStoredDraft = () => { clearStoredDraft(); setStoredDraft(null); };

    const attemptChangePatient = () => { if (dirty) setChangePending(true); else { clearStoredDraft(); resetAll(); } };
    const confirmChangePatient = () => { clearStoredDraft(); resetAll(); setChangePending(false); };

    const setMed = (i, k, v) => setMeds((s) => s.map((m, idx) => (idx === i ? { ...m, [k]: v } : m)));
    const toggleEdit = (i) => setMeds((s) => s.map((m, idx) => (idx === i ? { ...m, _editing: !m._editing } : m)));
    const removeMed = (i) => setMeds((s) => s.filter((_, idx) => idx !== i));
    const addManual = () => setMeds((s) => [...s, { ...EMPTY_MED }]);

    const organize = async () => {
        if (!paste.trim()) { toast.error("Paste the prescription or medication list first."); return; }
        setParsing(true);
        try {
            const { data } = await api.post("/pharmacy/rx/parse", { text: paste });
            const parsed = (data.medications || []).map((m) => ({ ...EMPTY_MED, ...m, attributes: m.attributes || [], _editing: false }));
            if (parsed.length === 0) { toast.error("No medications could be identified. You can add one manually."); }
            setMeds((s) => [...s, ...parsed]);
            setPaste("");
            toast.success(`Organized ${parsed.length} medication(s).`);
        } catch (err) { toast.error(formatErr(err)); } finally { setParsing(false); }
    };

    const repeatPrior = (pr) => {
        const copied = (pr.medications_structured || []).map((m) => ({ ...EMPTY_MED, ...m, attributes: m.attributes || [], needs_review: [], _editing: false }));
        if (copied.length === 0) { toast.error("No structured medications on that request to repeat."); return; }
        setMeds((s) => [...s, ...copied]);
        toast.success(`Added ${copied.length} medication(s) from a previous request. Review and send.`);
    };

    const filledMeds = meds.filter((m) => (m.drug || "").trim());
    const canSend = !!patient && (filledMeds.length > 0 || !!file) && !busy;

    const submit = async () => {
        if (!canSend) { toast.error("Add at least one medication or attach a document."); return; }
        setBusy(true);
        try {
            const fd = new FormData();
            fd.append("directory_id", patient.id);
            fd.append("medications", JSON.stringify(filledMeds.map(({ _editing, _moreOpen, needs_review, action, ...m }) => ({ ...m, action }))));
            fd.append("pharmacy_note", reqNote.trim());
            fd.append("message_to_physician", msgPhysician.trim());
            if (file) fd.append("file", file);
            await api.post("/pharmacy/rx", fd, { headers: { "Content-Type": "multipart/form-data" } });
            toast.success("Rx request sent to Dr. Aguayo's office.");
            clearStoredDraft(patient.id);
            resetAll();
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
                                    <th className="text-left px-3 py-2">Medication(s)</th>
                                    <th className="text-left px-3 py-2">Status</th>
                                    <th className="text-left px-3 py-2">Sent</th>
                                    <th className="px-3 py-2"></th>
                                </tr>
                            </thead>
                            <tbody>
                                {requests.map((r) => {
                                    const medCount = (r.medications || []).length;
                                    const medLabel = medCount > 1 ? `${medCount} medications` : (`${r.medication_name || ""} ${r.strength || ""}`.trim() || (r.medications || [])[0] || "—");
                                    return (
                                        <tr key={r.id} data-testid="rx-row" className="border-t border-slate-100">
                                            <td className="px-3 py-2 text-slate-500">{r.ref_number}</td>
                                            <td className="px-3 py-2 font-semibold">{r.patient_name}</td>
                                            <td className="px-3 py-2">{medLabel}</td>
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
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>
        );
    }

    // NEW REQUEST — smart builder
    return (
        <div className="animate-fade-in">
            <div className="flex items-center gap-3 mb-4">
                <Button variant="ghost" size="sm" onClick={() => { if (dirty) setChangePending(true); else { resetAll(); setMode("list"); } }} data-testid="rx-back"><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">New Rx Request</h1>
            </div>

            {!patient ? (
                <div className="bg-white border border-slate-300 rounded-sm p-5 max-w-xl">
                    <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Step 1 — Find patient</div>
                    <PatientSearch onSelect={selectPatient} testidPrefix="rx" />
                </div>
            ) : (
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 items-start">
                    <div className="lg:col-span-2 space-y-3 lg:sticky lg:top-2">
                        <PatientInfoPanel p={patient} />
                        <button className="text-xs text-slate-400 hover:text-slate-600" onClick={attemptChangePatient} data-testid="rx-change-patient">← Choose a different patient</button>
                    </div>

                    <div className="lg:col-span-3 space-y-4">
                        {storedDraft && meds.length === 0 && (
                            <div className="bg-amber-50 border border-amber-300 rounded-sm p-3 flex items-center justify-between gap-3" data-testid="rx-restore">
                                <div className="text-sm text-amber-800">You have an unsent Rx request in progress for this patient.</div>
                                <div className="flex gap-2 shrink-0">
                                    <Button size="sm" variant="outline" data-testid="rx-restore-btn" onClick={restoreDraft}>Restore</Button>
                                    <button className="text-xs text-slate-500 hover:underline" data-testid="rx-restore-discard" onClick={discardStoredDraft}>Discard</button>
                                </div>
                            </div>
                        )}

                        {priorRequests.length > 0 && (
                            <div className="bg-white border border-slate-300 rounded-sm p-4">
                                <div className="text-sm font-semibold text-slate-700 mb-2">Previous requests for this patient</div>
                                <div className="space-y-2">
                                    {priorRequests.slice(0, 5).map((pr) => (
                                        <div key={pr.id} data-testid="rx-prior" className="flex items-start justify-between gap-3 border border-slate-200 rounded-sm px-3 py-2 bg-slate-50/60">
                                            <div className="text-sm">
                                                <div className="text-slate-400 text-[11px] uppercase tracking-wide">{pr.ref_number || ""} · {formatDate(pr.created_at)}</div>
                                                <div className="text-slate-600 text-xs mt-0.5 truncate max-w-md">{(pr.medications || []).join(", ") || "—"}</div>
                                            </div>
                                            {(pr.medications_structured || []).length > 0 && (
                                                <Button size="sm" variant="outline" data-testid="rx-repeat-prior" onClick={() => repeatPrior(pr)}><RotateCw className="w-3.5 h-3.5 mr-1" /> Repeat</Button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="bg-white border border-slate-300 rounded-sm p-4 space-y-4">
                            <div className="flex items-center gap-2 text-slate-700 font-semibold"><Pill className="w-4 h-4" /> Rx Request</div>

                            <div>
                                <div className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-1"><ClipboardPaste className="w-4 h-4" /> Paste prescription / refill information</div>
                                <p className="text-xs text-slate-500 mb-2">Paste the prescription or medication list here. VIen will organize the medications for review.</p>
                                <Textarea data-testid="rx-paste" value={paste} onChange={(e) => setPaste(e.target.value)} rows={4} placeholder={"Amlodipine besylate 5 mg tablet: 1 tablet HS\nBisoprolol fumarate 5 mg tablet: 1 tablet HS\nRosuvastatin calcium 5 mg tablet: 1 tablet OD"} />
                                <Button size="sm" className="mt-2" onClick={organize} disabled={parsing} data-testid="rx-organize"><ClipboardPaste className="w-4 h-4 mr-1" /> {parsing ? "Organizing…" : "Organize Request"}</Button>
                            </div>

                            {meds.length > 0 && (
                                <div>
                                    <div className="text-sm font-semibold text-slate-700 mb-2">Medications</div>
                                    <div className="space-y-2">
                                        {meds.map((m, i) => (
                                            <PharmacyMedCard key={i} m={m} i={i} setMed={setMed} removeMed={removeMed} toggleEdit={toggleEdit}
                                                fieldSuggest={fieldSuggest} drugOptions={drugOptions} ensureDrugSuggest={ensureDrugSuggest} />
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div>
                                <Button variant="ghost" size="sm" onClick={addManual} data-testid="rx-add-manual" className="text-slate-500"><Plus className="w-4 h-4 mr-1" /> Add Medication</Button>
                            </div>

                            <div>
                                <Label className="text-xs">Upload photo / JPG / PNG / PDF (optional)</Label>
                                <div className="mt-1"><AttachmentPicker file={file} onChange={setFile} testidPrefix="rx" /></div>
                            </div>

                            <div><Label className="text-xs">Pharmacy note</Label><Textarea data-testid="rx-pharmacy-note" value={reqNote} onChange={(e) => setReqNote(e.target.value)} rows={2} /></div>
                            <div><Label className="text-xs">Message to physician (optional)</Label><Textarea data-testid="rx-message" value={msgPhysician} onChange={(e) => setMsgPhysician(e.target.value)} rows={2} /></div>
                        </div>

                        {/* Review before send */}
                        <div className="bg-white border border-slate-300 rounded-sm p-4">
                            <div className="text-xs uppercase tracking-wide text-slate-400 mb-3">Review & send</div>
                            <div className="text-sm mb-2"><span className="text-xs text-slate-400 uppercase mr-2">Patient</span><span className="font-semibold">{patient.full_name}</span>{patient.visita_patient_id ? <span className="text-slate-500"> · PIN {patient.visita_patient_id}</span> : null}<span className="text-slate-500"> · DOB {formatDate(patient.date_of_birth)}</span></div>
                            <div className="text-xs text-slate-400 uppercase mb-1">Medication requests</div>
                            {filledMeds.length > 0 ? (
                                <div className="space-y-2" data-testid="rx-review-meds">
                                    {filledMeds.map((m, i) => (
                                        <div key={i} data-testid="rx-review-med" className="border border-slate-200 rounded-sm px-3 py-2">
                                            <div className="flex items-center gap-2 flex-wrap text-sm">
                                                <span className="text-slate-400 text-xs font-semibold">{i + 1}.</span>
                                                <span className="font-semibold text-slate-800">{[m.drug, m.strength].filter(Boolean).join(" ")}</span>
                                                {m.form ? <span className="text-slate-500 text-xs">— {m.form}</span> : null}
                                            </div>
                                            {m.sig ? <div className="text-slate-700 text-xs mt-0.5">{m.sig}</div> : null}
                                            {(m.requested_duration || m.days_supply || m.quantity) ? (
                                                <div className="text-slate-500 text-xs mt-0.5">
                                                    {m.quantity ? `Qty ${m.quantity}${m.quantity_unit ? ` ${m.quantity_unit}` : ""}` : ""}
                                                    {m.quantity && (m.days_supply || m.requested_duration) ? " · " : ""}
                                                    {m.days_supply ? `${m.days_supply} days` : ""}
                                                    {m.days_supply && m.requested_duration ? " · " : ""}
                                                    {m.requested_duration ? `Renew: ${m.requested_duration}` : ""}
                                                </div>
                                            ) : null}
                                            {(m.existing_rx_number || m.last_filled_date || m.manufacturer) ? (
                                                <div className="text-slate-400 text-[11px] mt-0.5">{[m.existing_rx_number ? `Rx# ${m.existing_rx_number}` : "", m.last_filled_date ? `Last filled ${m.last_filled_date}` : "", m.manufacturer ? `Mfr ${m.manufacturer}` : ""].filter(Boolean).join(" · ")}</div>
                                            ) : null}
                                        </div>
                                    ))}
                                </div>
                            ) : file ? (
                                <div className="text-slate-500 text-sm inline-flex items-center gap-2" data-testid="rx-review-doconly"><FileText className="w-4 h-4" /> Document-only request</div>
                            ) : (
                                <div className="text-amber-600 text-sm inline-flex items-center gap-1"><AlertTriangle className="w-4 h-4" /> Add a medication or attach a document.</div>
                            )}
                            {reqNote.trim() && <div className="mt-2"><div className="text-xs text-slate-400 uppercase">Pharmacy note</div><div className="text-slate-600 text-xs">{reqNote}</div></div>}
                            <div className="mt-2"><span className="text-xs text-slate-400 uppercase mr-2">Attachment</span><span className="text-slate-700 text-sm">{file ? file.name : "None"}</span></div>

                            <Button data-testid="rx-send" onClick={submit} disabled={!canSend} className="mt-4 w-full bg-visita-green hover:bg-visita-greenDark text-white">
                                <Send className="w-4 h-4 mr-1" /> Send Rx Request
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {changePending && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" data-testid="rx-change-guard">
                    <div className="bg-white rounded-sm border border-slate-300 shadow-lg w-full max-w-sm p-5" role="dialog" aria-modal="true">
                        <div className="flex items-start gap-3">
                            <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                            <div>
                                <h3 className="font-semibold text-slate-900">Unsent Rx request</h3>
                                <p className="text-sm text-slate-500 mt-1">You have an unsent Rx request in progress. Leaving will discard it.</p>
                            </div>
                        </div>
                        <div className="flex items-center justify-end gap-2 mt-5">
                            <Button variant="ghost" data-testid="rx-change-stay" onClick={() => setChangePending(false)}>Stay on this page</Button>
                            <Button variant="outline" data-testid="rx-change-discard" onClick={() => { setChangePending(false); confirmChangePatient(); }} className="border-red-200 text-red-600 hover:bg-red-50">Leave and discard</Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
