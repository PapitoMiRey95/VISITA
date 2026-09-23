import { useState, useRef, useEffect } from "react";
import { toast } from "sonner";
import { UserSearch, Search, MapPin, Phone, IdCard, Building2, Lock, RefreshCw, Pencil, ShieldCheck, X } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { useAuth } from "../context/AuthContext";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Button } from "../components/ui/button";

const HC_BADGE = {
    VALID: "bg-emerald-100 text-emerald-700",
    EXPIRING_SOON: "bg-amber-100 text-amber-800",
    EXPIRED: "bg-red-100 text-red-700",
    INCOMPLETE: "bg-slate-100 text-slate-500",
};
const HC_LABEL = { VALID: "VALID", EXPIRING_SOON: "EXPIRING SOON", EXPIRED: "EXPIRED", INCOMPLETE: "INCOMPLETE" };

// Display names as "LASTNAMES, First Names" (last names ALWAYS uppercase, first names Title Case).
const titleCaseName = (s) =>
    (s || "").trim().toLowerCase().replace(/(^|[\s'\-])([\p{L}])/gu, (_, sep, ch) => sep + ch.toUpperCase());
function formatPatientName(p) {
    if (!p) return "—";
    const last = (p.last_name || "").trim().toUpperCase();
    const first = titleCaseName(p.first_name || "");
    if (last && first) return `${last}, ${first}`;
    return last || first || p.full_name || "—";
}

function statusLabel(s) {
    if (!s) return "—";
    if (s === "PORTAL_PATIENT") return "VERIFIED — PORTAL PATIENT";
    return String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function Row({ label, children, testid }) {
    return (
        <div className="flex justify-between gap-4 border-b border-slate-100 py-2">
            <span className="text-slate-400 text-xs uppercase tracking-wide whitespace-nowrap">{label}</span>
            <span data-testid={testid} className="text-slate-800 text-right text-sm font-medium">{children || "—"}</span>
        </div>
    );
}

export default function Patients() {
    const [query, setQuery] = useState("");
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [searched, setSearched] = useState(false);
    const [showResults, setShowResults] = useState(false);
    const [selected, setSelected] = useState(null);
    const [editing, setEditing] = useState(false);
    const [form, setForm] = useState({});
    const [busy, setBusy] = useState(false);
    const { user } = useAuth();
    const canEdit = ["admin", "staff", "physician"].includes(user?.role) && selected?.source === "portal";
    const searchRef = useRef(null);

    const reloadSelected = async () => {
        if (!selected) return;
        const q = selected.visita_patient_id || selected.full_name;
        try {
            const { data } = await api.get("/internal/patient-lookup", { params: { q } });
            const fresh = data.find((r) => (r.patient_id && r.patient_id === selected.patient_id) || r.id === selected.id);
            if (fresh) setSelected(fresh);
        } catch { /* noop */ }
    };

    const startEdit = () => {
        setForm({
            phone: selected.cell_phone || "",
            health_card_number: selected.health_card_number || "",
            health_card_version: selected.health_card_version_code || "",
            health_card_issue_date: selected.health_card_issue_date || "",
            health_card_expiry_date: selected.health_card_expiry_date || "",
            visita_patient_id: selected.visita_patient_id || "",
        });
        setEditing(true);
    };

    const saveEdit = async () => {
        setBusy(true);
        try {
            await api.patch(`/internal/patients/${selected.patient_id}`, form);
            toast.success("Patient information updated.");
            setEditing(false); await reloadSelected();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const reviewHc = async (action) => {
        setBusy(true);
        try {
            await api.post(`/internal/patients/${selected.patient_id}/health-card/${action}`);
            toast.success(action === "approve" ? "Health Card update approved." : "Health Card update rejected.");
            await reloadSelected();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    // Close the results list when clicking outside the search area.
    useEffect(() => {
        function onDocClick(e) {
            if (searchRef.current && !searchRef.current.contains(e.target)) setShowResults(false);
        }
        document.addEventListener("mousedown", onDocClick);
        return () => document.removeEventListener("mousedown", onDocClick);
    }, []);

    const run = async (e) => {
        e?.preventDefault();
        const q = query.trim();
        if (q.length < 2) { toast.error("Enter at least 2 characters."); return; }
        setSearching(true);
        try {
            const { data } = await api.get("/internal/patient-lookup", { params: { q } });
            setResults(data);
            setSearched(true);
            if (data.length === 1) {
                setSelected(data[0]);
                setShowResults(false);
            } else {
                setShowResults(true);
            }
        } catch (err) { toast.error(formatErr(err)); } finally { setSearching(false); }
    };

    const pick = (r) => { setSelected(r); setShowResults(false); };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center gap-2 mb-1">
                <UserSearch className="w-5 h-5 text-visita-green" />
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Patients</h1>
            </div>
            <p className="text-sm text-slate-500 mb-4 flex items-center gap-1">
                <Lock className="w-3.5 h-3.5" /> Read-only lookup — search by name, VISITA PIN / ID, health card number, or phone.
            </p>

            <div ref={searchRef} className="relative max-w-xl mb-4">
                <form onSubmit={run} className="flex gap-2">
                    <div className="relative flex-1">
                        <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                        <Input data-testid="patient-lookup-search" value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            onFocus={() => { if (results.length) setShowResults(true); }}
                            placeholder="Name, VISITA PIN, health card #, or phone" className="pl-8" />
                    </div>
                    <Button type="submit" disabled={searching} data-testid="patient-lookup-search-btn">
                        {searching ? "…" : "Search"}
                    </Button>
                </form>

                {showResults && searched && (
                    <div data-testid="patient-lookup-results"
                        className="absolute z-20 mt-1 w-full bg-white border border-slate-300 rounded-sm shadow-lg divide-y max-h-[calc(100vh-13rem)] overflow-y-auto">
                        {results.length === 0 ? (
                            <div className="px-3 py-4 text-slate-400 text-sm">No matching patients found.</div>
                        ) : (
                            <>
                                <div className="px-3 py-1.5 text-[11px] uppercase tracking-wide text-slate-400 bg-slate-50">
                                    {results.length} match{results.length === 1 ? "" : "es"}
                                </div>
                                {results.map((r) => (
                                    <button key={r.id} data-testid="patient-lookup-result" onClick={() => pick(r)}
                                        className={`w-full text-left px-3 py-2.5 hover:bg-slate-50 ${selected?.id === r.id ? "bg-visita-greenLight" : ""}`}>
                                        <div className="font-semibold text-slate-800">{formatPatientName(r)}</div>
                                        <div className="text-xs text-slate-500">
                                            {r.visita_patient_id ? `PIN ${r.visita_patient_id}` : "PIN Not assigned"} · DOB {formatDate(r.date_of_birth)} · {statusLabel(r.patient_status)}
                                        </div>
                                    </button>
                                ))}
                            </>
                        )}
                    </div>
                )}
            </div>

            {!selected ? (
                <div className="bg-white border border-dashed border-slate-300 rounded-sm px-4 py-16 text-center text-slate-400 text-sm max-w-3xl">
                    Search above and select a patient to view their snapshot.
                </div>
            ) : (
                <div className="bg-white border border-slate-300 rounded-sm p-5 max-w-3xl" data-testid="patient-snapshot">
                    <div className="flex items-center justify-between mb-3">
                        <div>
                            <h2 className="text-lg font-bold text-slate-900" data-testid="patient-name">{formatPatientName(selected)}</h2>
                            <span className={`inline-block mt-1 px-2 py-0.5 rounded-sm text-xs ${selected.source === "portal" ? "bg-emerald-100 text-emerald-800 font-semibold" : "bg-slate-100 text-slate-600"}`}>{statusLabel(selected.patient_status)}</span>
                        </div>
                        <div className="flex items-center gap-3">
                            {canEdit && !editing && (
                                <Button variant="outline" size="sm" data-testid="patient-edit-btn" onClick={startEdit}>
                                    <Pencil className="w-3.5 h-3.5 mr-1" /> Edit Patient Information
                                </Button>
                            )}
                            {!canEdit && <span className="text-xs text-slate-400 flex items-center gap-1"><Lock className="w-3.5 h-3.5" /> Read-only</span>}
                            <Button variant="outline" size="sm" data-testid="patient-change-btn"
                                onClick={() => { setShowResults(results.length > 0); searchRef.current?.querySelector("input")?.focus(); }}>
                                <RefreshCw className="w-3.5 h-3.5 mr-1" /> Change Patient
                            </Button>
                        </div>
                    </div>

                    {selected.health_card_update_pending && selected.pending_health_card && (
                        <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3" data-testid="hc-pending-panel">
                            <div className="flex items-center gap-2 text-amber-900 font-bold text-sm"><ShieldCheck className="w-4 h-4" /> HEALTH CARD UPDATE PENDING</div>
                            <div className="text-sm text-slate-700 mt-1">Proposed: <span className="font-semibold tracking-wide">{selected.pending_health_card.display}</span>
                                {selected.pending_health_card.health_card_expiry_date ? ` · Expiry ${formatDate(selected.pending_health_card.health_card_expiry_date)}` : ""}</div>
                            <div className="text-xs text-slate-500">Current verified card stays active until approved.</div>
                            {canEdit && (
                                <div className="flex gap-2 mt-2">
                                    <Button size="sm" disabled={busy} data-testid="hc-approve" onClick={() => reviewHc("approve")} className="bg-visita-green hover:bg-visita-greenDark text-white">Approve</Button>
                                    <Button size="sm" variant="outline" disabled={busy} data-testid="hc-reject" onClick={() => reviewHc("reject")}>Reject</Button>
                                </div>
                            )}
                        </div>
                    )}

                    {editing ? (
                        <div className="space-y-3" data-testid="patient-edit-form">
                            <div className="grid grid-cols-3 gap-2">
                                <div className="col-span-3"><Label className="text-xs">Cell Phone</Label><Input data-testid="edit-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
                                <div className="col-span-2"><Label className="text-xs">Health Card Number (10 digits)</Label><Input data-testid="edit-hcn" value={form.health_card_number} onChange={(e) => setForm({ ...form, health_card_number: e.target.value })} /></div>
                                <div><Label className="text-xs">Version</Label><Input data-testid="edit-hcv" value={form.health_card_version} maxLength={2} onChange={(e) => setForm({ ...form, health_card_version: e.target.value.toUpperCase() })} /></div>
                                <div><Label className="text-xs">Issue Date</Label><Input type="date" data-testid="edit-hc-issue" value={form.health_card_issue_date || ""} onChange={(e) => setForm({ ...form, health_card_issue_date: e.target.value })} /></div>
                                <div><Label className="text-xs">Expiry Date</Label><Input type="date" data-testid="edit-hc-expiry" value={form.health_card_expiry_date || ""} onChange={(e) => setForm({ ...form, health_card_expiry_date: e.target.value })} /></div>
                                <div><Label className="text-xs">VISITA PIN</Label><Input data-testid="edit-pin" value={form.visita_patient_id} onChange={(e) => setForm({ ...form, visita_patient_id: e.target.value })} /></div>
                            </div>
                            <div className="flex gap-2">
                                <Button disabled={busy} data-testid="edit-save" onClick={saveEdit} className="bg-visita-green hover:bg-visita-greenDark text-white">Save changes</Button>
                                <Button variant="outline" onClick={() => setEditing(false)}><X className="w-4 h-4 mr-1" /> Cancel</Button>
                            </div>
                            <p className="text-[11px] text-slate-400">Staff/Admin edits apply immediately and are recorded in the audit history.</p>
                        </div>
                    ) : (
                    <>
                    <Row label="Full Name" testid="snap-name">{selected.full_name}</Row>
                    <Row label="VISITA PIN / ID" testid="snap-pin"><span className="inline-flex items-center gap-1"><IdCard className="w-3.5 h-3.5 text-slate-400" />{selected.visita_patient_id || "Not assigned"}</span></Row>
                    <Row label="DOB" testid="snap-dob">{formatDate(selected.date_of_birth)}</Row>
                    <Row label="Age" testid="snap-age">{selected.age != null ? `${selected.age}` : "—"}</Row>
                    <Row label="Home Phone" testid="snap-home">{selected.home_phone ? <span className="inline-flex items-center gap-1"><Phone className="w-3.5 h-3.5 text-slate-400" />{selected.home_phone}</span> : null}</Row>
                    <Row label="Cell Phone" testid="snap-cell">{selected.cell_phone ? <span className="inline-flex items-center gap-1"><Phone className="w-3.5 h-3.5 text-slate-400" />{selected.cell_phone}</span> : null}</Row>
                    <Row label="Address" testid="snap-address">{selected.address_full ? <span className="inline-flex items-center gap-1 text-right"><MapPin className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />{selected.address_full}</span> : null}</Row>
                    <Row label="Health Card" testid="snap-hcn">
                        {selected.health_card_display ? (
                            <span className="inline-flex items-center gap-2">
                                <span className="tracking-wide">{selected.health_card_display}</span>
                                {selected.health_card_status && <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${HC_BADGE[selected.health_card_status]}`} data-testid="snap-hc-badge">{HC_LABEL[selected.health_card_status]}</span>}
                            </span>
                        ) : null}
                    </Row>
                    <Row label="HC Issue Date" testid="snap-hc-issue">{selected.health_card_issue_date ? formatDate(selected.health_card_issue_date) : null}</Row>
                    <Row label="HC Expiry Date" testid="snap-hc-expiry">{selected.health_card_expiry_date ? formatDate(selected.health_card_expiry_date) : null}</Row>
                    <Row label="Directory Status" testid="snap-status">{statusLabel(selected.patient_status)}</Row>
                    <Row label="Current Pharmacy" testid="snap-pharmacy">{selected.current_pharmacy ? <span className="inline-flex items-center gap-1"><Building2 className="w-3.5 h-3.5 text-slate-400" />{selected.current_pharmacy}</span> : null}</Row>

                    <p className="text-xs text-slate-400 mt-4 leading-relaxed">
                        Demographic &amp; contact information only. Medication list and other approved VISITA information will appear here later.
                    </p>
                    </>
                    )}
                </div>
            )}
        </div>
    );
}
