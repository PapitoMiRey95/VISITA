import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { Search, Pill, User, ArrowLeft, Send, ClipboardList, Wand2, X, AlertTriangle } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatLastFirst } from "../lib/name";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

const RECEIVED = ["fax", "phone", "other"];
const DEFAULT_PHARMACY = "1670 Dufferin Drug Mart";

function medDisplay(m) {
    const head = [m.drug, m.strength, m.form].filter(Boolean).join(" ").trim();
    return head || (m.original_text || "").trim();
}

export default function PharmacyIntake() {
    const nav = useNavigate();
    const [query, setQuery] = useState("");
    const [pin, setPin] = useState("");
    const [pinSearching, setPinSearching] = useState(false);
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [snap, setSnap] = useState(null); // selected patient snapshot
    const [selectedActive, setSelectedActive] = useState([]);
    const [busy, setBusy] = useState(false);
    const [pharmacies, setPharmacies] = useState([]);
    const [pasteText, setPasteText] = useState("");
    const [organizing, setOrganizing] = useState(false);
    const [parsedMeds, setParsedMeds] = useState([]);
    const [parseWarnings, setParseWarnings] = useState([]);
    const [f, setF] = useState({ pharmacy: "", meds_text: "", duration_qty: "", pharmacy_note: "", received_via: "fax", internal_note: "" });
    const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

    // Pharmacy dropdown options: portal pharmacies (future) + the default 1670 DDM.
    useEffect(() => {
        api.get("/internal/pharmacies").then(({ data }) => setPharmacies(data || [])).catch(() => setPharmacies([]));
    }, []);
    const pharmacyOptions = (() => {
        const names = (pharmacies || []).map((p) => p.pharmacy_name).filter(Boolean);
        return Array.from(new Set([DEFAULT_PHARMACY, ...names]));
    })();

    const search = async (e) => {
        e?.preventDefault();
        if (!query.trim()) return;
        setSearching(true);
        try {
            const { data } = await api.get("/internal/patient-lookup", { params: { q: query.trim() } });
            setResults(data);
        } catch (err) { toast.error(formatErr(err)); } finally { setSearching(false); }
    };

    const searchPin = async (e) => {
        e?.preventDefault();
        const p = pin.trim();
        if (!p) return;
        if (!/^\d+$/.test(p)) { toast.error("PIN must be numbers only."); return; }
        setPinSearching(true);
        try {
            const { data } = await api.get("/internal/patient-lookup", { params: { q: p } });
            const exact = data.filter((r) => String(r.visita_patient_id || "") === p);
            setResults(exact.length ? exact : data);
            if (data.length === 0) toast.error("No patient found for that PIN.");
        } catch (err) { toast.error(formatErr(err)); } finally { setPinSearching(false); }
    };

    const selectPatient = async (id) => {
        try {
            const { data } = await api.get(`/internal/patient-snapshot/${id}`);
            setSnap(data);
            setF((s) => ({ ...s, pharmacy: data.current_pharmacy || s.pharmacy || DEFAULT_PHARMACY }));
            setSelectedActive([]);
        } catch (err) { toast.error(formatErr(err)); }
    };

    const toggleActive = (med) =>
        setSelectedActive((s) => (s.includes(med) ? s.filter((m) => m !== med) : [...s, med]));

    // Smart tool: paste raw Rx text -> Organize -> structured medication cards.
    const organize = async () => {
        if (!pasteText.trim()) { toast.error("Paste the prescription text first."); return; }
        setOrganizing(true);
        try {
            const { data } = await api.post("/internal/rx/parse", {
                text: pasteText, patient_ref: snap?.directory_id || snap?.patient_id || null,
            });
            const meds = data.medications || [];
            if (meds.length === 0) { toast.error("No medications recognised. Check the pasted text."); }
            setParsedMeds(meds);
            setParseWarnings(data.warnings || []);
            if (data.months && !f.duration_qty) set("duration_qty", `${data.months} months`);
            if (meds.length) toast.success(`Organized ${meds.length} medication${meds.length > 1 ? "s" : ""}.`);
        } catch (err) { toast.error(formatErr(err)); } finally { setOrganizing(false); }
    };

    const removeParsed = (idx) => setParsedMeds((s) => s.filter((_, i) => i !== idx));

    const submit = async () => {
        const manual = f.meds_text.split("\n").map((x) => x.trim()).filter(Boolean);
        const organized = parsedMeds.map(medDisplay).filter(Boolean);
        const medications = [...selectedActive, ...organized, ...manual];
        if (!f.pharmacy.trim()) { toast.error("Select a pharmacy."); return; }
        if (medications.length === 0) { toast.error("Add at least one requested medication (paste & organize, pick from active, or type manually)."); return; }
        setBusy(true);
        try {
            await api.post("/internal/pharmacy-rx", {
                directory_id: snap.directory_id, patient_id: snap.patient_id, pharmacy: f.pharmacy, medications,
                medications_structured: parsedMeds, selected_active_meds: selectedActive, duration_qty: f.duration_qty || null,
                pharmacy_note: f.pharmacy_note || null, received_via: f.received_via,
                internal_note: f.internal_note || null,
            });
            toast.success("Sent to physician Rx queue.");
            nav("/internal/rx");
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center gap-3 mb-4">
                <Button asChild variant="ghost" size="sm"><Link to="/internal/rx"><ArrowLeft className="w-4 h-4 mr-1" /> Rx</Link></Button>
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Rx Request / Refill Intake</h1>
                    <p className="text-sm text-slate-500">Log an Rx request or refill — from a pharmacy, or a patient who called in — and send it to the physician.</p>
                </div>
            </div>

            {!snap && (
                <div className="bg-white border border-slate-300 rounded-sm p-5 max-w-xl">
                    <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Step 1 — Find patient</div>
                    <form onSubmit={search} className="flex gap-2">
                        <div className="relative flex-1">
                            <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                            <Input data-testid="intake-search" value={query}
                                onChange={(e) => {
                                    const v = e.target.value;
                                    setQuery(v);
                                    if (!v.trim()) setResults([]);
                                }}
                                placeholder="Patient name or VISITA Patient ID / PIN" className="pl-8" />
                        </div>
                        <Button type="submit" disabled={searching} data-testid="intake-search-btn">{searching ? "…" : "Search"}</Button>
                    </form>

                    <div className="my-3 flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-400">
                        <span className="flex-1 border-t border-slate-200" />or search by PIN<span className="flex-1 border-t border-slate-200" />
                    </div>
                    <form onSubmit={searchPin} className="flex gap-2">
                        <div className="relative flex-1">
                            <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                            <Input data-testid="intake-pin-search" value={pin} inputMode="numeric"
                                onChange={(e) => {
                                    const v = e.target.value.replace(/[^\d]/g, "");
                                    setPin(v);
                                    if (!v) setResults([]);
                                }}
                                placeholder="VISITA PIN (numbers only)" className="pl-8" />
                        </div>
                        <Button type="submit" variant="outline" disabled={pinSearching} data-testid="intake-pin-search-btn">{pinSearching ? "…" : "Find by PIN"}</Button>
                    </form>
                    <div className="mt-3 divide-y border border-slate-200 rounded-sm max-h-80 overflow-y-auto">
                        {results.length === 0 && <div className="px-3 py-4 text-slate-400 text-sm">Search VISITA patients (directory + portal accounts) by name, DOB, phone or VISITA PIN.</div>}
                        {results.map((r) => (
                            <button key={r.id} data-testid="intake-result" onClick={() => selectPatient(r.id)}
                                className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex justify-between">
                                <span className="font-semibold">{formatLastFirst(r.last_name, r.first_name)}</span>
                                <span className="text-slate-500 text-xs">DOB {formatDate(r.date_of_birth)} · {r.visita_patient_id ? `#${r.visita_patient_id}` : r.patient_status}</span>
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {snap && (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    {/* LEFT — Active medications */}
                    <div className="bg-white border border-slate-300 rounded-sm p-4">
                        <div className="flex items-center gap-2 mb-2 text-slate-700 font-semibold"><Pill className="w-4 h-4" /> Current / Active Medications</div>
                        {(snap.medications || []).length === 0 ? (
                            <p className="text-xs text-slate-400 leading-relaxed">
                                No synchronized medications yet. Read-only medication history will appear here once VISITA
                                integration is enabled. Enter the requested medication(s) manually in the centre panel.
                            </p>
                        ) : (
                            <div className="space-y-1.5">
                                {snap.medications.map((m, idx) => {
                                    const label = typeof m === "string" ? m : `${m.name || ""} ${m.strength || ""} — ${m.directions || ""}`;
                                    const on = selectedActive.includes(label);
                                    return (
                                        <label key={idx} data-testid="active-med" className={`flex items-start gap-2 text-sm px-2 py-1.5 rounded-sm cursor-pointer ${on ? "bg-visita-greenLight" : "hover:bg-slate-50"}`}>
                                            <input type="checkbox" checked={on} onChange={() => toggleActive(label)} className="mt-1" />
                                            <span>{label}</span>
                                        </label>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    {/* CENTER — Rx request / refill */}
                    <div className="bg-white border border-slate-300 rounded-sm p-4 space-y-3">
                        <div className="flex items-center gap-2 text-slate-700 font-semibold"><ClipboardList className="w-4 h-4" /> Rx Request / Refill</div>
                        <div>
                            <Label className="text-xs">Pharmacy</Label>
                            <select data-testid="intake-pharmacy" value={f.pharmacy || ""} onChange={(e) => set("pharmacy", e.target.value)}
                                className="w-full h-9 border border-slate-300 rounded-sm px-2 text-sm bg-white">
                                <option value="" disabled>Select a pharmacy…</option>
                                {pharmacyOptions.map((name) => <option key={name} value={name}>{name}</option>)}
                            </select>
                            <p className="text-[11px] text-slate-400 mt-1">More pharmacies appear here as they are added to the system.</p>
                        </div>

                        {/* Smart paste & organize */}
                        <div className="border border-indigo-200 bg-indigo-50/40 rounded-sm p-2.5 space-y-2">
                            <div className="flex items-center gap-1.5 text-xs font-semibold text-indigo-800"><Wand2 className="w-3.5 h-3.5" /> Smart Rx — paste &amp; organize</div>
                            <Textarea data-testid="intake-paste" value={pasteText} onChange={(e) => setPasteText(e.target.value)} rows={4}
                                placeholder={"Paste the full prescription here, e.g.\nRamipril 10 mg — 1 tab daily, Qty 90\nMetformin 500 mg BID\nNumber of months: 3"} />
                            <Button type="button" size="sm" variant="outline" data-testid="intake-organize" disabled={organizing}
                                onClick={organize} className="border-indigo-400 text-indigo-700 hover:bg-indigo-100">
                                <Wand2 className="w-3.5 h-3.5 mr-1" /> {organizing ? "Organizing…" : "Organize"}
                            </Button>

                            {parseWarnings.length > 0 && (
                                <div className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded p-1.5" data-testid="intake-parse-warnings">
                                    {parseWarnings.map((w, i) => <div key={i} className="flex items-start gap-1"><AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />{w}</div>)}
                                </div>
                            )}

                            {parsedMeds.length > 0 && (
                                <div className="space-y-1.5" data-testid="intake-parsed-meds">
                                    <div className="text-[11px] uppercase text-slate-400 font-medium">Organized medications ({parsedMeds.length})</div>
                                    {parsedMeds.map((m, idx) => (
                                        <div key={idx} data-testid="intake-parsed-med" className="border border-slate-200 bg-white rounded px-2 py-1.5 text-sm relative">
                                            <button type="button" onClick={() => removeParsed(idx)} data-testid="intake-parsed-remove"
                                                className="absolute top-1.5 right-1.5 text-slate-300 hover:text-red-500"><X className="w-3.5 h-3.5" /></button>
                                            <div className="font-semibold text-slate-800 pr-5">{idx + 1}. {medDisplay(m)}</div>
                                            {m.sig && <div className="text-slate-600 text-xs">{m.sig}</div>}
                                            {(m.quantity || m.refills || m.additional_instructions) && (
                                                <div className="text-slate-500 text-[11px]">{[m.quantity && `Qty ${m.quantity}`, m.refills != null && `${m.refills} refills`, m.additional_instructions].filter(Boolean).join(" · ")}</div>
                                            )}
                                            {(m.needs_review || []).length > 0 && <div className="text-amber-600 text-[11px]">Needs review: {m.needs_review.join(", ")}</div>}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div>
                            <Label className="text-xs">Or type medication(s) manually {selectedActive.length > 0 && <span className="text-visita-greenDark">(+{selectedActive.length} from active list)</span>}</Label>
                            <Textarea data-testid="intake-meds" value={f.meds_text} onChange={(e) => set("meds_text", e.target.value)} placeholder="One medication per line, e.g.&#10;Ramipril 10 mg&#10;Metformin 500 mg" rows={2} />
                        </div>
                        <div><Label className="text-xs">Requested refill duration / quantity (if known)</Label><Input data-testid="intake-duration" value={f.duration_qty} onChange={(e) => set("duration_qty", e.target.value)} placeholder="e.g. 3 months" /></div>
                        <div><Label className="text-xs">Note (pharmacy or patient)</Label><Textarea value={f.pharmacy_note} onChange={(e) => set("pharmacy_note", e.target.value)} rows={2} /></div>
                        <div>
                            <Label className="text-xs">Received via</Label>
                            <div className="flex gap-2 mt-1">
                                {RECEIVED.map((r) => (
                                    <button key={r} type="button" data-testid={`intake-via-${r}`} onClick={() => set("received_via", r)}
                                        className={`flex-1 py-1.5 rounded-sm border text-sm capitalize ${f.received_via === r ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-300"}`}>
                                        {r}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <div><Label className="text-xs">Internal note (optional)</Label><Input data-testid="intake-note" value={f.internal_note} onChange={(e) => set("internal_note", e.target.value)} /></div>
                        <Button data-testid="intake-send" onClick={submit} disabled={busy} className="w-full bg-visita-green hover:bg-visita-greenDark text-white">
                            <Send className="w-4 h-4 mr-1" /> Send to Physician
                        </Button>
                    </div>

                    {/* RIGHT — Patient snapshot */}
                    <div className="bg-white border border-slate-300 rounded-sm p-4">
                        <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2 text-slate-700 font-semibold"><User className="w-4 h-4" /> Patient Snapshot</div>
                            <button className="text-xs text-slate-400 hover:text-slate-600" onClick={() => setSnap(null)} data-testid="intake-change-patient">Change</button>
                        </div>
                        <div className="text-sm space-y-1">
                            <Row label="Name">{formatLastFirst(snap.last_name, snap.first_name)}</Row>
                            <Row label="VISITA PIN / ID">{snap.visita_patient_id || "—"}</Row>
                            <Row label="DOB">{formatDate(snap.date_of_birth)}</Row>
                            <Row label="Age">{snap.age != null ? `${snap.age} y` : "—"}</Row>
                            <Row label="Phone">{snap.phone || "—"}</Row>
                            <Row label="Last visit">{snap.last_visit_date ? formatDate(snap.last_visit_date) : "—"}</Row>
                            <Row label="Last visit plan">{snap.last_visit_plan || "—"}</Row>
                            <Row label="Current pharmacy">{snap.current_pharmacy || "—"}</Row>
                            <Row label="Directory status">{snap.patient_status}</Row>
                        </div>
                        <p className="text-[11px] text-slate-400 mt-3 leading-relaxed">
                            Quick physician context only. Clinical medication and visit data remain in VISITA (read-only sync pending).
                        </p>
                    </div>
                </div>
            )}
        </div>
    );
}

function Row({ label, children }) {
    return (
        <div className="flex justify-between gap-2 border-b border-slate-100 py-1">
            <span className="text-slate-400 text-xs uppercase tracking-wide">{label}</span>
            <span className="text-slate-700 text-right">{children}</span>
        </div>
    );
}
