import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Microscope, Plus, Send, Eye, Stethoscope, UserPlus, Search, X, FileText, Loader2, CheckCircle2, ShieldCheck, Lock, Upload } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { formatDateTime } from "../lib/date";
import { formatCombinedName } from "../lib/name";
import { RESULT_TAXONOMY } from "../lib/resultTaxonomy";

const FILTERS = [
    { value: "", label: "All" },
    { value: "LABORATORY", label: "Laboratory" },
    { value: "DIAGNOSTIC_IMAGING", label: "Imaging" },
    { value: "CARDIAC_TESTS", label: "Cardiac" },
    { value: "PULMONARY_SLEEP", label: "Pulmonary / Sleep" },
    { value: "PATHOLOGY_CYTOLOGY", label: "Pathology / Cytology" },
    { value: "SCREENING", label: "Screening" },
    { value: "OTHER_REPORTS", label: "Other" },
];

const TABS = [
    { key: "requests", label: "Requests" },
    { key: "RECEIVED", label: "Results Received" },
    { key: "READY_FOR_PHYSICIAN", label: "Ready for Physician" },
    { key: "REVIEWED", label: "Reviewed" },
    { key: "NEEDS_PATIENT_MATCH", label: "Needs Patient Match" },
];

function TypeTag({ category, subtype }) {
    return (
        <div>
            <div className="font-semibold text-slate-800">{subtype || category || "Result"}</div>
            {category && subtype && <div className="text-xs text-slate-400">{category}</div>}
        </div>
    );
}

function PatientSearch({ onPick }) {
    const [q, setQ] = useState("");
    const [res, setRes] = useState([]);
    const [busy, setBusy] = useState(false);
    const run = async () => {
        if (!q.trim()) return;
        setBusy(true);
        try {
            const { data } = await api.get("/internal/patient-lookup", { params: { q, include_pin: false } });
            setRes(data || []);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <div>
            <div className="flex gap-2">
                <Input data-testid="exam-patient-search" value={q} onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && run()} placeholder="Search patient name…" />
                <Button size="sm" variant="outline" onClick={run} disabled={busy} data-testid="exam-patient-search-btn">
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                </Button>
            </div>
            {res.length > 0 && (
                <div className="mt-2 max-h-40 overflow-auto border border-slate-200 rounded divide-y divide-slate-100">
                    {res.map((p) => (
                        <button key={p.patient_id || p.directory_id} data-testid="exam-patient-option"
                            onClick={() => onPick(p)} className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50">
                            {formatCombinedName(`${p.last_name}, ${p.first_name}`)} {p.date_of_birth ? `· ${p.date_of_birth}` : ""}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

export default function ExamsResults() {
    const { user } = useAuth();
    const isPhysician = ["physician", "admin"].includes(user?.role);
    const [tab, setTab] = useState(user?.role === "physician" ? "READY_FOR_PHYSICIAN" : "requests");
    const [category, setCategory] = useState("");
    const [q, setQ] = useState("");
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState("");
    const [addOpen, setAddOpen] = useState(false);
    const [reviewTarget, setReviewTarget] = useState(null);
    const [matchTarget, setMatchTarget] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            if (tab === "requests") {
                const { data } = await api.get("/internal/exams/requests", { params: { category: category || undefined, q: q || undefined } });
                setRows(data || []);
            } else {
                const { data } = await api.get("/internal/exams/results", { params: { status: tab, category: category || undefined, q: q || undefined } });
                setRows(data || []);
            }
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, [tab, category, q]);

    useEffect(() => { load(); }, [load]);

    const act = async (id, fn, msg) => {
        setBusy(id);
        try { await fn(); if (msg) toast.success(msg); await load(); }
        catch (e) { toast.error(formatErr(e)); } finally { setBusy(""); }
    };

    const sendToPhysician = (r) => act(r.id, () => api.post(`/internal/exams/results/${r.id}/send-to-physician`), "Sent to physician for review.");
    const viewPdf = async (r) => { try { await openAttachment(`/internal/exams/results/${r.id}/pdf`); } catch (e) { toast.error(formatErr(e)); } };
    const releasePdf = (r) => act(r.id, () => api.post(`/internal/exams/results/${r.id}/release`), "PDF released to patient.");
    const keepInternal = (r) => act(r.id, () => api.post(`/internal/exams/results/${r.id}/keep-internal`), "Kept internal.");

    return (
        <div className="space-y-4" data-testid="exams-results-page">
            <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                    <Microscope className="w-5 h-5 text-visita-green" />
                    <h1 className="text-xl font-bold text-slate-900">Exams &amp; Results</h1>
                </div>
                {!isPhysician || user?.role === "admin" ? (
                    <Button size="sm" data-testid="exam-add-result-btn" onClick={() => setAddOpen(true)}
                        className="bg-visita-green hover:bg-visita-greenDark text-white">
                        <Plus className="w-4 h-4 mr-1" /> Add Result
                    </Button>
                ) : null}
            </div>

            <div className="flex gap-1 border-b border-slate-200 overflow-x-auto">
                {TABS.map((t) => (
                    <button key={t.key} data-testid={`exam-tab-${t.key}`} onClick={() => setTab(t.key)}
                        className={`px-3 py-2 text-sm font-semibold whitespace-nowrap border-b-2 transition ${tab === t.key ? "border-visita-green text-visita-greenDark" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
                        {t.label}
                    </button>
                ))}
            </div>

            <div className="flex items-center gap-2 flex-wrap">
                {FILTERS.map((f) => (
                    <button key={f.value} data-testid={`exam-filter-${f.value || "all"}`} onClick={() => setCategory(f.value)}
                        className={`px-2.5 py-1 rounded-full text-xs font-semibold border transition ${category === f.value ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-200 hover:border-visita-green"}`}>
                        {f.label}
                    </button>
                ))}
                <Input data-testid="exam-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" className="ml-auto max-w-xs h-8" />
            </div>

            {loading ? (
                <div className="text-sm text-slate-400 py-8 text-center">Loading…</div>
            ) : rows.length === 0 ? (
                <div className="text-sm text-slate-400 py-10 text-center border border-dashed border-slate-200 rounded" data-testid="exams-empty">Nothing here yet.</div>
            ) : (
                <div className="border border-slate-200 rounded divide-y divide-slate-100 bg-white" data-testid="exams-list">
                    {rows.map((r) => (
                        <div key={r.id} className="px-4 py-3 flex items-center justify-between gap-3" data-testid="exam-row">
                            <div className="flex items-center gap-3 min-w-0">
                                <span className="text-xs text-slate-400 w-20 shrink-0">{r.ref_number || r.source_ref}</span>
                                <div className="min-w-0">
                                    <div className="font-semibold text-slate-800 truncate">{formatCombinedName(r.patient_name) || <span className="text-amber-600">Unmatched patient</span>}</div>
                                    <div className="text-xs text-slate-500 flex items-center gap-2 flex-wrap">
                                        <span>{r.subtype || r.category_label}{r.detail ? ` · ${r.detail}` : ""}</span>
                                        {r.category_label && <span className="text-slate-300">·</span>}
                                        <span className="text-slate-400">{r.category_label}</span>
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                                {tab === "requests" && <span className="text-xs text-slate-400 capitalize">{(r.status || "").replace(/_/g, " ")}</span>}

                                {tab === "NEEDS_PATIENT_MATCH" && (
                                    <Button size="sm" variant="outline" data-testid="exam-match-btn" onClick={() => setMatchTarget(r)}>
                                        <UserPlus className="w-3.5 h-3.5 mr-1" /> Match patient
                                    </Button>
                                )}

                                {tab === "RECEIVED" && (
                                    <>
                                        {r.attachment_id && <Button size="sm" variant="outline" data-testid="exam-view-pdf" onClick={() => viewPdf(r)}><Eye className="w-3.5 h-3.5" /></Button>}
                                        <Button size="sm" disabled={busy === r.id} data-testid="exam-send-physician" onClick={() => sendToPhysician(r)}
                                            className="bg-visita-green hover:bg-visita-greenDark text-white">
                                            <Send className="w-3.5 h-3.5 mr-1" /> Send to Physician
                                        </Button>
                                    </>
                                )}

                                {tab === "READY_FOR_PHYSICIAN" && (
                                    <Button size="sm" data-testid="exam-review-btn" disabled={!isPhysician} onClick={() => setReviewTarget(r)}
                                        className="bg-visita-green hover:bg-visita-greenDark text-white">
                                        <Stethoscope className="w-3.5 h-3.5 mr-1" /> Review
                                    </Button>
                                )}

                                {tab === "REVIEWED" && (
                                    <>
                                        {r.shared_with_patient
                                            ? <span className="inline-flex items-center gap-1 text-xs text-emerald-600 font-semibold" data-testid="exam-released-badge"><ShieldCheck className="w-3.5 h-3.5" /> Released</span>
                                            : <span className="inline-flex items-center gap-1 text-xs text-slate-500" data-testid="exam-internal-badge"><Lock className="w-3.5 h-3.5" /> Internal</span>}
                                        {r.patient_notified && <span className="text-xs text-sky-600">Notified</span>}
                                        {r.access_requested && !r.shared_with_patient && <span className="text-xs font-bold text-amber-600" data-testid="exam-access-requested">Access requested</span>}
                                        <Button size="sm" variant="outline" data-testid="exam-view-pdf" onClick={() => viewPdf(r)}><Eye className="w-3.5 h-3.5" /></Button>
                                        {isPhysician && !r.shared_with_patient && (
                                            <>
                                                <Button size="sm" disabled={busy === r.id} data-testid="exam-release-btn" onClick={() => releasePdf(r)} className="bg-visita-green hover:bg-visita-greenDark text-white">Release PDF</Button>
                                                {r.access_requested && <Button size="sm" variant="outline" data-testid="exam-keep-internal-btn" disabled={busy === r.id} onClick={() => keepInternal(r)}>Keep Internal</Button>}
                                            </>
                                        )}
                                    </>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {addOpen && <AddResultModal onClose={() => setAddOpen(false)} onDone={() => { setAddOpen(false); load(); }} />}
            {matchTarget && <MatchModal target={matchTarget} onClose={() => setMatchTarget(null)} onDone={() => { setMatchTarget(null); load(); }} />}
            {reviewTarget && <ReviewModal target={reviewTarget} onView={() => viewPdf(reviewTarget)} onClose={() => setReviewTarget(null)} onDone={() => { setReviewTarget(null); load(); }} />}
        </div>
    );
}

function AddResultModal({ onClose, onDone }) {
    const [patient, setPatient] = useState(null);
    const [category, setCategory] = useState("");
    const [subtype, setSubtype] = useState("");
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);
    const cat = RESULT_TAXONOMY.find((c) => c.value === category);

    const submit = async (send) => {
        if (!category) { toast.error("Select a category."); return; }
        if (!file) { toast.error("Attach the result PDF."); return; }
        setBusy(true);
        try {
            const { data: created } = await api.post("/internal/exams/results", {
                patient_id: patient?.patient_id || null,
                category: cat?.label || category, subtype: subtype || null, source_type: "manual",
            });
            const fd = new FormData();
            fd.append("file", file);
            await api.post(`/internal/exams/results/${created.id}/attachment`, fd, { headers: { "Content-Type": "multipart/form-data" } });
            if (send) {
                if (!patient) { toast.error("Match a patient before sending to the physician."); setBusy(false); return; }
                await api.post(`/internal/exams/results/${created.id}/send-to-physician`);
                toast.success("Result added and sent to physician.");
            } else {
                toast.success(patient ? "Result added to Results Received." : "Result added to Needs Patient Match.");
            }
            onDone();
        } catch (e) { toast.error(formatErr(e)); setBusy(false); }
    };

    return (
        <Modal title="Add Result" onClose={onClose} testid="add-result-modal">
            <label className="block text-xs font-semibold text-slate-600 mb-1">Patient</label>
            {patient ? (
                <div className="flex items-center justify-between bg-slate-50 border border-slate-200 rounded px-3 py-2 mb-3 text-sm" data-testid="add-result-patient">
                    {formatCombinedName(`${patient.last_name}, ${patient.first_name}`)}
                    <button onClick={() => setPatient(null)} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
                </div>
            ) : (
                <div className="mb-3"><PatientSearch onPick={setPatient} /><p className="text-[11px] text-slate-400 mt-1">Leave empty to send to Needs Patient Match.</p></div>
            )}

            <label className="block text-xs font-semibold text-slate-600 mb-1">Category</label>
            <select data-testid="add-result-category" value={category} onChange={(e) => { setCategory(e.target.value); setSubtype(""); }}
                className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm mb-3">
                <option value="">Select category…</option>
                {RESULT_TAXONOMY.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            {cat && (
                <>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Subtype</label>
                    <select data-testid="add-result-subtype" value={subtype} onChange={(e) => setSubtype(e.target.value)}
                        className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm mb-3">
                        <option value="">(Optional)…</option>
                        {cat.subtypes.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                </>
            )}

            <label className="block text-xs font-semibold text-slate-600 mb-1">Result PDF</label>
            <input type="file" accept=".pdf,.jpg,.jpeg,.png" data-testid="add-result-file"
                onChange={(e) => setFile(e.target.files?.[0] || null)} className="w-full text-sm mb-4" />

            <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" onClick={onClose}>Cancel</Button>
                <Button size="sm" variant="outline" disabled={busy} data-testid="add-result-save" onClick={() => submit(false)}>
                    {busy && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />} Save to Received
                </Button>
                <Button size="sm" disabled={busy} data-testid="add-result-send" onClick={() => submit(true)}
                    className="bg-visita-green hover:bg-visita-greenDark text-white">
                    <Send className="w-3.5 h-3.5 mr-1" /> Save &amp; Send
                </Button>
            </div>
        </Modal>
    );
}

function MatchModal({ target, onClose, onDone }) {
    const [busy, setBusy] = useState(false);
    const pick = async (p) => {
        setBusy(true);
        try { await api.post(`/internal/exams/results/${target.id}/match`, { patient_id: p.patient_id }); toast.success("Patient matched."); onDone(); }
        catch (e) { toast.error(formatErr(e)); setBusy(false); }
    };
    return (
        <Modal title="Match patient" onClose={onClose} testid="match-modal">
            <p className="text-sm text-slate-500 mb-3">Select the correct patient for <b>{target.subtype || target.category_label}</b> ({target.ref_number}). Do not match by name alone if unsure.</p>
            <PatientSearch onPick={(p) => { if (!busy) pick(p); }} />
        </Modal>
    );
}

function ReviewModal({ target, onView, onClose, onDone }) {
    const [notify, setNotify] = useState(true);
    const [release, setRelease] = useState(false);
    const [busy, setBusy] = useState(false);
    const sign = async () => {
        setBusy(true);
        try { await api.post(`/internal/exams/results/${target.id}/review`, { notify, release }); toast.success("Signed & completed."); onDone(); }
        catch (e) { toast.error(formatErr(e)); setBusy(false); }
    };
    return (
        <Modal title="Review result" onClose={onClose} testid="review-modal">
            <div className="text-sm space-y-1 mb-3">
                <div><span className="text-slate-400">Patient:</span> <b>{formatCombinedName(target.patient_name)}</b></div>
                <div><span className="text-slate-400">Type:</span> {target.subtype || target.category_label} <span className="text-slate-400">({target.category_label})</span></div>
                {target.source_ref && <div><span className="text-slate-400">Source request:</span> {target.source_ref}</div>}
            </div>
            <Button size="sm" variant="outline" data-testid="review-view-pdf" onClick={onView} className="mb-4"><FileText className="w-3.5 h-3.5 mr-1" /> View PDF</Button>
            <div className="space-y-2 mb-4 border-t border-slate-100 pt-3">
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" data-testid="review-notify" checked={notify} onChange={(e) => setNotify(e.target.checked)} /> Notify patient that result has been reviewed</label>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" data-testid="review-release" checked={release} onChange={(e) => setRelease(e.target.checked)} /> Allow patient to view/download PDF <span className="text-[11px] text-slate-400">(off by default)</span></label>
            </div>
            <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" onClick={onClose}>Cancel</Button>
                <Button size="sm" disabled={busy} data-testid="review-sign-complete" onClick={sign} className="bg-visita-green hover:bg-visita-greenDark text-white">
                    {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <CheckCircle2 className="w-3.5 h-3.5 mr-1" />} Sign &amp; Complete
                </Button>
            </div>
        </Modal>
    );
}

function Modal({ title, onClose, children, testid }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" data-testid={testid}
            onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
            <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-4 max-h-[90vh] overflow-auto">
                <div className="flex items-center justify-between mb-3">
                    <h3 className="font-bold text-slate-900 text-sm">{title}</h3>
                    <button onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="modal-close"><X className="w-4 h-4" /></button>
                </div>
                {children}
            </div>
        </div>
    );
}
