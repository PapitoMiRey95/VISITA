import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { UserCheck, UserX, History, Link2, ShieldCheck, Search, GitMerge, Building2, GitCompare, UserPlus, AlertTriangle } from "lucide-react";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "../components/ui/alert-dialog";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { formatDate, formatDateTime } from "../lib/date";
import { formatPatientName } from "../lib/name";
import MatchComparison from "./MatchComparison";

const TYPE = { ohip: "OHIP", private: "Private / Uninsured", tourist: "Tourist / Visitor", uninsured: "Private / Uninsured" };

const REL_STYLE = {
    active: "bg-emerald-100 text-emerald-700",
    applicant: "bg-sky-100 text-sky-700",
    former: "bg-amber-100 text-amber-700",
    inactive: "bg-slate-100 text-slate-600",
};

function RelationshipBadges({ rel }) {
    if (!rel) return null;
    const own = rel.own;
    const others = rel.others || [];
    if (!own && others.length === 0) return null;
    return (
        <div className="flex flex-wrap items-center gap-1.5 mt-1" data-testid="relationship-badges">
            {own && (
                <span data-testid="relationship-own" className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold ${REL_STYLE[own.status] || REL_STYLE.inactive}`}>
                    <Building2 className="w-3 h-3" /> This practice: {own.label}
                </span>
            )}
            {others.map((o, i) => (
                <span key={i} data-testid="relationship-other" className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs ${REL_STYLE[o.status] || REL_STYLE.inactive}`}>
                    {o.practice_name}: {o.label}
                </span>
            ))}
        </div>
    );
}

const IDENTITY_STATE = {
    LINK_PENDING: ["Existing patient matched — verify & link", "bg-emerald-100 text-emerald-700"],
    IDENTITY_REVIEW_REQUIRED: ["Existing patient candidate — identity review required", "bg-amber-100 text-amber-800"],
    NEW_PATIENT_CANDIDATE: ["No existing patient match detected", "bg-slate-100 text-slate-600"],
};

const HISTORY_STATE = {
    LINKED_EXISTING: ["Linked to existing patient", "bg-emerald-100 text-emerald-700", Link2],
    NEW_PATIENT: ["New patient", "bg-sky-100 text-sky-700", UserPlus],
    IDENTITY_REVIEW: ["Identity review", "bg-amber-100 text-amber-800", AlertTriangle],
};

function CandidateLine({ c, onLink, linking }) {
    return (
        <div data-testid="identity-candidate" className="text-xs text-slate-700 bg-emerald-50 border border-emerald-100 rounded-sm px-2 py-1.5 mb-1 flex items-center justify-between gap-2">
            <div>
                <span className="font-semibold">{formatPatientName(c)}</span>
                {" · "}DOB {formatDate(c.date_of_birth)} · HC {c.health_card_masked || "—"}
                {c.visita_patient_id ? <> · <span className="font-semibold">VISITA #{c.visita_patient_id}</span></> : ""}
                {c.city ? ` · ${c.city}` : ""} {c.province || ""}
                {c.linked_patient_id ? <span className="ml-1 text-amber-700">(already linked)</span> : ""}
                {c.match_kind === "POSSIBLE_IDENTITY_REVIEW" && <span className="ml-1 px-1 rounded-sm bg-amber-100 text-amber-800 font-semibold" data-testid="candidate-review-only">possible — same DOB, name contained · review only</span>}
            </div>
            <Button size="sm" disabled={linking || !!c.linked_patient_id} data-testid={`identity-link-${c.id}`}
                onClick={() => onLink(c.id)} className="h-7 bg-visita-green hover:bg-visita-greenDark text-white shrink-0">
                <Link2 className="w-3.5 h-3.5 mr-1" /> Link
            </Button>
        </div>
    );
}

function IdentitySearchLink({ patientId, onLinked, canDecide }) {
    const [q, setQ] = useState("");
    const [results, setResults] = useState(null);
    const [busy, setBusy] = useState(false);
    const search = async () => {
        if (!q.trim()) return;
        setBusy(true);
        try {
            const { data } = await api.get("/internal/directory", { params: { q: q.trim() } });
            setResults(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    if (!canDecide) return null;
    return (
        <div className="mt-2 border-t border-slate-200 pt-2">
            <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Find another canonical record</div>
            <div className="flex gap-2">
                <div className="relative flex-1">
                    <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                    <Input data-testid={`identity-search-${patientId}`} value={q} onChange={(e) => setQ(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && search()} placeholder="Search name, HC, VISITA #…" className="pl-8 h-9 bg-white" />
                </div>
                <Button size="sm" variant="outline" disabled={busy} onClick={search} data-testid={`identity-search-btn-${patientId}`}>Search</Button>
            </div>
            {results && results.length === 0 && <p className="text-xs text-slate-400 mt-1">No directory records found.</p>}
            {results && results.length > 0 && (
                <div className="mt-1.5">
                    {results.map((c) => <CandidateLine key={c.id} c={c} linking={false} onLink={(did) => onLinked(did)} />)}
                </div>
            )}
        </div>
    );
}

function IdentityLinks({ canDecide }) {
    const invalidate = useInvalidate();
    const [linkingId, setLinkingId] = useState(null);
    const q = useQuery({ queryKey: ["queue", "/internal/identity-links"], queryFn: async () => (await api.get("/internal/identity-links")).data });
    const items = q.data || [];

    const link = async (patientId, directoryId) => {
        if (!window.confirm("Link this portal account to the selected canonical patient? The canonical VISITA PIN will be preserved and future activity will use it. No clinical records are merged.")) return;
        setLinkingId(patientId);
        try {
            const { data } = await api.post(`/internal/patients/${patientId}/link-directory`, { directory_id: directoryId });
            toast.success(`Linked to canonical patient${data.visita_patient_id ? ` · VISITA #${data.visita_patient_id}` : ""}.`);
            invalidate(); q.refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setLinkingId(null); }
    };

    return (
        <div className="space-y-2" data-testid="identity-links">
            <p className="text-sm text-slate-500">Portal accounts with a possible existing VISITA record. Linking preserves the canonical PIN and never merges clinical history or overwrites demographics. Ambiguous matches are resolved manually here.</p>
            {items.length === 0 && <p className="text-slate-400 text-sm">No accounts awaiting identity review.</p>}
            {items.map((p) => (
                <div key={p.id} data-testid="identity-item" className="bg-white border border-slate-300 rounded-sm p-4">
                    <div className="grid md:grid-cols-2 gap-4">
                        <div className="text-sm space-y-0.5">
                            <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Portal registration</div>
                            <div className="font-bold text-slate-800 text-base" data-testid="identity-portal-name">{formatPatientName(p)}</div>
                            <div className="text-slate-600">DOB: {formatDate(p.date_of_birth)} · {TYPE[p.patient_type] || p.patient_type}</div>
                            <div className="text-slate-600">Phone: {p.phone} · Email: {p.email}</div>
                            {p.health_card_masked && <div className="text-slate-600">Health Card: {p.health_card_masked}</div>}
                            <div className="text-slate-500 text-xs">
                                {p.verification_status === "verified" ? "Verified portal account" : "Pending verification"}
                                {p.visita_patient_id ? ` · current PIN ${p.visita_patient_id}` : " · no PIN"}
                            </div>
                            <RelationshipBadges rel={p.relationship} />
                        </div>
                        <div className="text-sm">
                            <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">
                                Suggested canonical record{(p.candidates.length > 1) ? "s" : ""}{p.strength ? ` · ${p.strength} match` : ""}
                            </div>
                            {p.candidates.map((c) => (
                                <CandidateLine key={c.id} c={c} linking={linkingId === p.id} onLink={(did) => link(p.id, did)} />
                            ))}
                            <IdentitySearchLink patientId={p.id} canDecide={canDecide} onLinked={(did) => link(p.id, did)} />
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
}

function VerifiedHistory() {
    const q = useQuery({ queryKey: ["queue", "/internal/verifications/history"], queryFn: async () => (await api.get("/internal/verifications/history")).data });
    const items = q.data || [];
    return (
        <div className="space-y-2" data-testid="verification-history">
            {items.length === 0 && <p className="text-slate-400 text-sm">No verified patients yet.</p>}
            {items.map((p) => {
                const rejected = p.verification_status === "rejected";
                return (
                    <div key={p.id} data-testid="verification-history-item" className="bg-white border border-slate-300 rounded-sm p-3 flex items-start justify-between gap-3 flex-wrap">
                        <div className="text-sm space-y-0.5">
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold ${rejected ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}`}>
                                    {rejected ? <UserX className="w-3.5 h-3.5" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                                    {rejected ? "Rejected" : "Verified"}
                                </span>
                                {!rejected && HISTORY_STATE[p.identity_state] && (() => { const [lbl, cls, Icon] = HISTORY_STATE[p.identity_state]; return (
                                    <span data-testid={`history-identity-${p.identity_state}`} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold uppercase tracking-wide ${cls}`}><Icon className="w-3 h-3" /> {lbl}</span>
                                ); })()}
                                <span className="font-bold text-slate-800 text-base" data-testid="history-name">{p.canonical_full_name || formatPatientName(p)}</span>
                                {p.canonical_full_name && p.canonical_full_name !== formatPatientName(p) && <span className="text-xs text-slate-400">portal: {formatPatientName(p)}</span>}
                            </div>
                            <div className="text-slate-600">
                                Patient registration · {TYPE[p.patient_type] || p.patient_type}
                                {p.visita_patient_id ? <> · <span className="font-semibold">VISITA #{p.visita_patient_id}</span></> : ""}
                            </div>
                            <div className="text-slate-500 text-xs">
                                By {p.verified_by || "—"} · {formatDateTime(p.verified_at)}
                            </div>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

export default function Verifications() {
    const invalidate = useInvalidate();
    const { user } = useAuth();
    const canDecide = ["staff", "admin"].includes(user?.role);
    const [tab, setTab] = useState("identity");
    const [visitaIds, setVisitaIds] = useState({});
    const [cmps, setCmps] = useState({});
    const [confirmNew, setConfirmNew] = useState(null);
    const autoLoaded = useRef(new Set());
    const list = useQuery({ queryKey: ["queue", "/internal/verifications"], queryFn: async () => (await api.get("/internal/verifications")).data });
    const items = list.data || [];

    const loadCompare = async (patientId, candidateId) => {
        const key = `${patientId}:${candidateId}`;
        setCmps((prev) => ({ ...prev, [key]: { data: prev[key]?.data || null, loading: true } }));
        try {
            const { data } = await api.get(`/internal/verifications/${patientId}/compare`, { params: { candidate_id: candidateId } });
            setCmps((prev) => ({ ...prev, [key]: { data, loading: false } }));
        } catch (e) { toast.error(formatErr(e)); setCmps((prev) => { const n = { ...prev }; delete n[key]; return n; }); }
    };

    const compare = (patientId, candidateId) => {
        const key = `${patientId}:${candidateId}`;
        if (cmps[key]) { setCmps((prev) => { const n = { ...prev }; delete n[key]; return n; }); return; }
        loadCompare(patientId, candidateId);
    };

    // Auto-expand the comparison when a verification has exactly ONE candidate (read-only, still collapsible).
    useEffect(() => {
        items.forEach((p) => {
            const cands = p.directory_match?.candidates || [];
            if (cands.length === 1) {
                const key = `${p.id}:${cands[0].id}`;
                if (!autoLoaded.current.has(key)) {
                    autoLoaded.current.add(key);
                    loadCompare(p.id, cands[0].id);
                }
            }
        });
    }, [items]);

    const decide = async (id, decision, opts = {}) => {
        try {
            await api.post(`/internal/verifications/${id}`, { decision, visita_patient_id: visitaIds[id] || undefined, ...opts });
            toast.success(decision === "verified" ? (opts.confirm_new_patient ? "Verified as new patient." : "Patient verified and linked to existing record.") : "Patient rejected.");
            invalidate(); list.refetch();
        } catch (e) {
            const code = e?.response?.data?.detail?.code;
            if (code === "IDENTITY_LINK_REQUIRED") { toast.warning("Existing patient may match — resolve in Identity Link Review first."); invalidate(); setTab("identity"); return; }
            toast.error(formatErr(e));
        }
    };

    return (
        <div className="animate-fade-in max-w-4xl">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Patient Verifications</h1>
            <p className="text-sm text-slate-500 mb-4">Manually verify new portal accounts and match them to VISITA patient records.</p>

            <div className="flex gap-1 mb-4 border-b border-slate-200">
                <button data-testid="verif-tab-identity" onClick={() => setTab("identity")}
                    title="Match recently registered portal applicants to their VISITA patient record"
                    className={`px-3 py-2 text-sm font-semibold -mb-px border-b-2 inline-flex items-center gap-1 ${tab === "identity" ? "border-visita-green text-visita-greenDark" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
                    <GitMerge className="w-4 h-4" /> Identity Link Review
                </button>
                <button data-testid="verif-tab-pending" onClick={() => setTab("pending")}
                    className={`px-3 py-2 text-sm font-semibold -mb-px border-b-2 ${tab === "pending" ? "border-visita-green text-visita-greenDark" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
                    Pending{items.length ? ` (${items.length})` : ""}
                </button>
                <button data-testid="verif-tab-history" onClick={() => setTab("history")}
                    className={`px-3 py-2 text-sm font-semibold -mb-px border-b-2 inline-flex items-center gap-1 ${tab === "history" ? "border-visita-green text-visita-greenDark" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
                    <History className="w-4 h-4" /> Recently Verified
                </button>
            </div>
            {tab === "identity" && (
                <p className="text-xs text-slate-500 -mt-2 mb-3" data-testid="verif-identity-hint">
                    Start here: match patients who recently applied for portal access to their existing VISITA record before verifying.
                </p>
            )}

            {tab === "identity" ? <IdentityLinks canDecide={canDecide} /> : tab === "history" ? <VerifiedHistory /> : (
            <div className="space-y-2">
                {items.length === 0 && <p className="text-slate-400 text-sm">No pending verifications.</p>}
                {items.map((p) => (
                    <div key={p.id} data-testid="verification-item" className="bg-white border border-slate-300 rounded-sm p-4">
                        <div className="flex items-start justify-between gap-3 flex-wrap">
                            <div className="text-sm space-y-0.5">
                                {IDENTITY_STATE[p.identity_state] && (
                                    <span data-testid={`verification-identity-${p.identity_state}`} className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold mb-1 ${IDENTITY_STATE[p.identity_state][1]}`}>
                                        {IDENTITY_STATE[p.identity_state][0]}
                                    </span>
                                )}
                                <div className="font-bold text-slate-800 text-base" data-testid="verification-name">{formatPatientName(p)}</div>
                                <div className="text-slate-600">DOB: {formatDate(p.date_of_birth)} · {TYPE[p.patient_type] || p.patient_type}</div>
                                <RelationshipBadges rel={p.relationship} />
                                <div className="text-slate-600">Phone: {p.phone} · Email: {p.email}</div>
                                {p.health_card_masked && <div className="text-slate-600">Health Card: {p.health_card_masked}</div>}
                                {p.province && <div className="text-slate-600">Province: {p.province}</div>}
                                {p.country && <div className="text-slate-600">Country: {p.country}</div>}
                                {p.extra_info && <div className="text-slate-600">Note: {p.extra_info}</div>}

                                {(() => { const cands = p.live_candidates?.length ? p.live_candidates : (p.directory_match?.candidates || []); const strength = p.live_candidates?.length ? p.live_strength : p.directory_match?.strength; return cands.length > 0 && (
                                    <div className="mt-2 border-t border-slate-200 pt-1.5">
                                        <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">
                                            Suggested VISITA record{(cands.length > 1) ? "s" : ""} · {strength} match
                                        </div>
                                        {cands.map((c) => {
                                            const key = `${p.id}:${c.id}`;
                                            const entry = cmps[key];
                                            const open = !!entry;
                                            return (
                                                <div key={c.id}>
                                                    <div data-testid="verification-candidate" className="text-xs text-slate-600 bg-emerald-50 rounded-sm px-2 py-1 mb-1 flex items-center justify-between gap-2">
                                                        <span>
                                                            {formatPatientName(c)} · DOB {formatDate(c.date_of_birth)} · HC {c.health_card_masked || "—"}
                                                            {c.visita_patient_id ? ` · VISITA #${c.visita_patient_id}` : ""} · {c.city || ""} {c.province || ""}
                                                        </span>
                                                        <button type="button" data-testid={`verif-compare-${c.id}`} onClick={() => compare(p.id, c.id)}
                                                            className="shrink-0 inline-flex items-center gap-1 text-visita-greenDark font-semibold hover:underline">
                                                            <GitCompare className="w-3.5 h-3.5" /> {open ? "Hide" : "Compare"}
                                                        </button>
                                                    </div>
                                                    {open && <MatchComparison cmp={entry.data} loading={entry.loading} />}
                                                </div>
                                            );
                                        })}
                                    </div>
                                ); })()}
                            </div>
                            <div className="flex flex-col gap-2 items-end">
                                {canDecide ? (
                                    <>
                                        <div>
                                            <Label className="text-xs">VISITA Patient ID (optional)</Label>
                                            <Input className="h-8 w-44" value={visitaIds[p.id] || ""} onChange={(e) => setVisitaIds({ ...visitaIds, [p.id]: e.target.value })} data-testid="visita-id-input" />
                                        </div>
                                        <div className="flex gap-2 flex-wrap justify-end">
                                            {p.identity_state === "IDENTITY_REVIEW_REQUIRED" && (
                                                <Button size="sm" onClick={() => setTab("identity")} data-testid="verify-review-link" className="bg-amber-500 hover:bg-amber-600 text-white"><GitMerge className="w-4 h-4 mr-1" /> Review / Link Existing Patient</Button>
                                            )}
                                            {p.identity_state === "LINK_PENDING" && (
                                                <Button size="sm" onClick={() => decide(p.id, "verified")} data-testid="verify-link-existing" className="bg-visita-green hover:bg-visita-greenDark text-white"><Link2 className="w-4 h-4 mr-1" /> Verify & Link Existing Patient</Button>
                                            )}
                                            {p.identity_state === "NEW_PATIENT_CANDIDATE" && (
                                                <Button size="sm" onClick={() => setConfirmNew(p)} data-testid="verify-as-new" className="bg-visita-green hover:bg-visita-greenDark text-white"><UserPlus className="w-4 h-4 mr-1" /> Verify as New Patient</Button>
                                            )}
                                            <Button size="sm" variant="outline" onClick={() => decide(p.id, "rejected")} data-testid="verify-reject" className="text-red-600 border-red-200"><UserX className="w-4 h-4 mr-1" /> Reject</Button>
                                        </div>
                                        {p.identity_state === "IDENTITY_REVIEW_REQUIRED" && (
                                            <p className="text-[11px] text-amber-800 max-w-[260px] text-right" data-testid="verify-blocked-note">Verify as new patient is blocked until the existing-patient candidate is reviewed in Identity Link Review.</p>
                                        )}
                                    </>
                                ) : (
                                    <span className="text-xs text-slate-400 italic">View only</span>
                                )}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
            )}
            <AlertDialog open={!!confirmNew} onOpenChange={(o) => !o && setConfirmNew(null)}>
                <AlertDialogContent data-testid="confirm-new-patient-dialog">
                    <AlertDialogHeader>
                        <AlertDialogTitle>Verify as a new patient?</AlertDialogTitle>
                        <AlertDialogDescription asChild>
                            <div className="space-y-2 text-sm">
                                <p className="font-semibold text-slate-800">{confirmNew ? formatPatientName(confirmNew) : ""} · DOB {confirmNew ? formatDate(confirmNew.date_of_birth) : ""}</p>
                                <p>No existing canonical patient match requiring review was identified.</p>
                                <p>A new VIen patient identity / VISITA PIN may be created. If this person is already a clinic patient, cancel and link them in Identity Link Review instead.</p>
                            </div>
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel data-testid="confirm-new-cancel">Cancel</AlertDialogCancel>
                        <AlertDialogAction data-testid="confirm-new-accept" className="bg-visita-green hover:bg-visita-greenDark"
                            onClick={() => { const id = confirmNew.id; setConfirmNew(null); decide(id, "verified", { confirm_new_patient: true }); }}>
                            Verify as New Patient
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
