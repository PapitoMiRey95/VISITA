import { useState, useCallback, useEffect } from "react";
import { toast } from "sonner";
import { Stethoscope, Pill, FileText, CalendarDays, Plus, Check, Pencil, Ban, ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { MedEditPanel } from "./MedEditPanel";

const EMPTY_MED = { drug: "", strength: "", form: "", action: "", sig: "", attributes: [], quantity: "", quantity_unit: "", refills: "", note: "", additional_instructions: "" };

function medLabel(m) {
    return [m.drug, m.strength_display || m.strength, m.form].filter(Boolean).join(" · ");
}

export default function MedicalRecord({ patientId }) {
    const [open, setOpen] = useState(false);
    const [rec, setRec] = useState(null);
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState("");
    const [addMode, setAddMode] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [med, setMed] = useState(EMPTY_MED);
    const [drugOptions, setDrugOptions] = useState([]);
    const [fieldSuggest, setFieldSuggest] = useState({});

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get(`/internal/patients/${patientId}/medical-record`);
            setRec(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, [patientId]);

    useEffect(() => { if (open && !rec) load(); }, [open, rec, load]);

    const loadDrugs = useCallback(async () => {
        try {
            const { data } = await api.get("/internal/rx/suggest", { params: { patient_ref: patientId } });
            setDrugOptions(data.drugs || []);
        } catch { /* suggestions are best-effort */ }
    }, [patientId]);

    const ensureDrugSuggest = useCallback(async (drugKey) => {
        if (!drugKey || fieldSuggest[drugKey]) return;
        try {
            const { data } = await api.get("/internal/rx/suggest", { params: { patient_ref: patientId, drug: drugKey } });
            setFieldSuggest((p) => ({ ...p, [drugKey]: data.fields || {} }));
        } catch { /* ignore */ }
    }, [patientId, fieldSuggest]);

    const startAdd = () => { setMed({ ...EMPTY_MED }); setEditingId(null); setAddMode(true); loadDrugs(); };
    const startEdit = (m) => {
        setMed({
            drug: m.drug || "", strength: m.strength || "", form: m.form || "", action: m.action || "",
            sig: m.sig || "", attributes: m.attributes || [], quantity: m.quantity || "",
            quantity_unit: m.quantity_unit || "", refills: m.refills ?? "", route: m.route || "",
            duration_value: m.duration_value || "", duration_unit: m.duration_unit || "",
            note: m.note || "", additional_instructions: m.additional_instructions || "",
        });
        setEditingId(m.id); setAddMode(false); loadDrugs();
    };
    const cancelForm = () => { setAddMode(false); setEditingId(null); setMed(EMPTY_MED); };

    const setMedField = (_i, k, v) => setMed((prev) => ({ ...prev, [k]: v }));

    const saveAdd = async () => {
        if (!(med.drug || "").trim()) { toast.error("Enter a medication name."); return; }
        setBusy("add");
        try {
            await api.post(`/internal/patients/${patientId}/medications`, med);
            toast.success("Medication added to the active list.");
            cancelForm(); setRec(null); await load();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(""); }
    };
    const saveEdit = async () => {
        setBusy("edit");
        try {
            await api.patch(`/internal/patients/${patientId}/medications/${editingId}`, { ...med, action_type: "edit" });
            toast.success("Medication updated.");
            cancelForm(); setRec(null); await load();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(""); }
    };
    const [stopId, setStopId] = useState(null);
    const [stopNote, setStopNote] = useState("");
    const medAction = async (id, action_type, label, note = "") => {
        setBusy(id + action_type);
        try {
            await api.patch(`/internal/patients/${patientId}/medications/${id}`, { action_type, ...(note ? { note } : {}) });
            toast.success(label);
            setRec(null); await load();
        } catch (e) { toast.error(formatErr(e)); setBusy(""); }
    };

    const active = rec?.medications?.active || [];
    const discontinued = rec?.medications?.discontinued || [];
    const encounters = rec?.encounters || [];
    const documents = rec?.documents || [];
    const summary = rec?.summary || {};

    return (
        <div className="mt-6 pt-4 border-t border-slate-200" data-testid="medical-record-section">
            <button type="button" onClick={() => setOpen((o) => !o)} data-testid="medical-record-toggle"
                className="flex items-center gap-2 text-sm font-bold text-slate-900 hover:text-visita-green">
                {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                <Stethoscope className="w-4 h-4 text-visita-green" /> Medical Record
            </button>

            {open && (
                <div className="mt-3" data-testid="medical-record-body">
                    {loading && !rec ? (
                        <div className="text-sm text-slate-400">Loading medical record…</div>
                    ) : (
                        <div className="space-y-5">
                            {/* Summary */}
                            <section data-testid="mr-summary">
                                <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-1">Patient Summary</div>
                                <div className="text-sm text-slate-700 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1">
                                    <div><span className="text-slate-400">DOB:</span> {formatDate(summary.date_of_birth) || "—"}</div>
                                    <div><span className="text-slate-400">Age:</span> {summary.age ?? "—"}</div>
                                    <div><span className="text-slate-400">PIN:</span> {summary.visita_patient_id || "—"}</div>
                                    <div className="col-span-2 sm:col-span-3"><span className="text-slate-400">Health Card:</span> {summary.health_card_display || "—"}</div>
                                </div>
                            </section>

                            {/* Encounters */}
                            <section data-testid="mr-encounters">
                                <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-1 flex items-center gap-1"><CalendarDays className="w-3.5 h-3.5" /> Encounters</div>
                                {encounters.length === 0 ? (
                                    <div className="text-sm text-slate-400">No encounters recorded.</div>
                                ) : (
                                    <div className="divide-y divide-slate-100 border border-slate-200 rounded-sm">
                                        {encounters.map((e) => (
                                            <div key={e.id} className="px-3 py-2 text-sm flex justify-between gap-3" data-testid="mr-encounter-row">
                                                <div>
                                                    <div className="font-medium text-slate-800">{e.label || e.reason || "Appointment"}</div>
                                                    <div className="text-xs text-slate-500">{e.reason && e.label ? e.reason : ""}</div>
                                                </div>
                                                <div className="text-right text-xs text-slate-500 whitespace-nowrap">
                                                    <div>{e.date ? formatDate(e.date) : formatDate(e.created_at)}{e.time ? ` · ${e.time}` : ""}</div>
                                                    <div className="capitalize">{(e.status || "").replace(/_/g, " ")}</div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </section>

                            {/* Medications */}
                            <section data-testid="mr-medications">
                                <div className="flex items-center justify-between mb-1">
                                    <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400 flex items-center gap-1"><Pill className="w-3.5 h-3.5" /> Medications</div>
                                    {!addMode && !editingId && (
                                        <Button size="sm" variant="outline" data-testid="mr-add-med-btn" onClick={startAdd}>
                                            <Plus className="w-3.5 h-3.5 mr-1" /> Add medication
                                        </Button>
                                    )}
                                </div>

                                {(addMode || editingId) && (
                                    <div className="border border-slate-700 bg-slate-800 text-slate-100 rounded-sm p-3 mb-3" data-testid="mr-med-form">
                                        <div className="text-xs font-bold text-slate-100 mb-2">{editingId ? "Edit medication" : "Add medication"}</div>
                                        <MedEditPanel m={med} i={0} setMed={setMedField} removeMed={cancelForm} toggleEdit={cancelForm}
                                            fieldSuggest={fieldSuggest} drugOptions={drugOptions} ensureDrugSuggest={ensureDrugSuggest} />
                                        <div className="flex justify-end gap-2 mt-2">
                                            <Button size="sm" variant="outline" onClick={cancelForm}>Cancel</Button>
                                            <Button size="sm" disabled={!!busy} data-testid="mr-med-save"
                                                onClick={editingId ? saveEdit : saveAdd}
                                                className="bg-visita-green hover:bg-visita-greenDark text-white">
                                                {editingId ? "Save changes" : "Add to list"}
                                            </Button>
                                        </div>
                                    </div>
                                )}

                                {active.length === 0 ? (
                                    <div className="text-sm text-slate-400">No active medications.</div>
                                ) : (
                                    <div className="divide-y divide-slate-100 border border-slate-200 rounded-sm" data-testid="mr-active-meds">
                                        {active.map((m) => (
                                            <div key={m.id} className="px-3 py-2.5 flex items-center justify-between gap-3" data-testid="mr-med-row">
                                                <div className="min-w-0">
                                                    <div className="font-semibold text-slate-800 text-sm">{medLabel(m)}</div>
                                                    {m.sig && <div className="text-xs text-slate-500 truncate">{m.sig}</div>}
                                                    {m.coverage_days && m.last_prescribed_at && <div className="text-[11px] text-slate-400" data-testid="mr-med-coverage">Last sent {String(m.last_prescribed_at).slice(0, 10)} · ~{m.coverage_days} days supply{m.physician_name ? ` · ${m.physician_name}` : ""}</div>}
                                                </div>
                                                {stopId === m.id ? (
                                                    <div className="flex items-center gap-1.5 shrink-0" data-testid="mr-med-stop-confirm">
                                                        <Input value={stopNote} onChange={(e) => setStopNote(e.target.value)} placeholder="Reason (optional)" className="h-8 w-40 text-xs" data-testid="mr-med-stop-note" />
                                                        <Button size="sm" disabled={!!busy} data-testid="mr-med-stop-confirm-btn" className="h-8 bg-red-600 hover:bg-red-700 text-white"
                                                            onClick={async () => { await medAction(m.id, "discontinue", "Medication marked as stopped — removed from the patient's current list and blister pack.", stopNote); setStopId(null); setStopNote(""); }}>Stop</Button>
                                                        <Button size="sm" variant="ghost" className="h-8" onClick={() => { setStopId(null); setStopNote(""); }}>Cancel</Button>
                                                    </div>
                                                ) : (
                                                <div className="flex gap-1.5 shrink-0">
                                                    <Button size="sm" variant="outline" disabled={!!busy} data-testid="mr-med-continue"
                                                        onClick={() => medAction(m.id, "continue", "Medication continued.")} title="Continue">
                                                        <Check className="w-3.5 h-3.5" />
                                                    </Button>
                                                    <Button size="sm" variant="outline" disabled={!!busy} data-testid="mr-med-edit"
                                                        onClick={() => startEdit(m)} title="Edit">
                                                        <Pencil className="w-3.5 h-3.5" />
                                                    </Button>
                                                    <Button size="sm" variant="outline" disabled={!!busy} data-testid="mr-med-stop"
                                                        onClick={() => setStopId(m.id)}
                                                        className="border-red-200 text-red-600 hover:bg-red-50" title="Stop / Discontinue">
                                                        <Ban className="w-3.5 h-3.5 mr-1" /> Stop
                                                    </Button>
                                                </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {discontinued.length > 0 && (
                                    <div className="mt-2" data-testid="mr-discontinued-meds">
                                        <div className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">Discontinued (history preserved)</div>
                                        <div className="divide-y divide-slate-100 border border-slate-200 rounded-sm">
                                            {discontinued.map((m) => (
                                                <div key={m.id} className="px-3 py-2 flex items-center justify-between gap-3 text-slate-500">
                                                    <div className="min-w-0">
                                                        <div className="text-sm line-through">{medLabel(m)}</div>
                                                        <div className="text-[11px]">Stopped {m.discontinued_at ? formatDate(m.discontinued_at) : ""}{m.discontinued_by ? ` by ${m.discontinued_by}` : ""}</div>
                                                    </div>
                                                    <Button size="sm" variant="outline" disabled={!!busy} data-testid="mr-med-resume"
                                                        onClick={() => medAction(m.id, "continue", "Medication resumed.")} title="Resume">
                                                        <RotateCcw className="w-3.5 h-3.5" />
                                                    </Button>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </section>

                            {/* Documents */}
                            <section data-testid="mr-documents">
                                <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-1 flex items-center gap-1"><FileText className="w-3.5 h-3.5" /> Documents / Results</div>
                                {documents.length === 0 ? (
                                    <div className="text-sm text-slate-400">No documents shared.</div>
                                ) : (
                                    <div className="divide-y divide-slate-100 border border-slate-200 rounded-sm">
                                        {documents.map((d, idx) => (
                                            <div key={d.id || d.att_id || idx} className="px-3 py-2 text-sm flex justify-between gap-3" data-testid="mr-doc-row">
                                                <span className="text-slate-800 truncate">{d.filename || d.name || d.title || d.label || "Document"}</span>
                                                <span className="text-xs text-slate-500 whitespace-nowrap">{formatDate(d.shared_at || d.created_at) || ""}</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </section>

                            <p className="text-[11px] text-slate-400">Physician-authoritative view. Medication changes update the patient's "Your Medicines" immediately. All actions are audited.</p>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
