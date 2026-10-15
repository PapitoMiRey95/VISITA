import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Link2, Wrench, AlertTriangle, ShieldCheck, ArrowLeft, Check, Users, Stethoscope } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { Button } from "../components/ui/button";
import { formatDate } from "../lib/date";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "../components/ui/alert-dialog";

const CLASS = {
    SAFE_LINK_CANDIDATE: ["Safe link candidate", "bg-emerald-100 text-emerald-700"],
    POSSIBLE_MATCH_REVIEW: ["Possible match — review", "bg-amber-100 text-amber-800"],
    IDENTITY_CONFLICT: ["Identity conflict — review required", "bg-red-100 text-red-700"],
    HALF_LINK: ["Half link", "bg-orange-100 text-orange-800"],
    DIRECTORY_ALREADY_LINKED: ["Directory already linked", "bg-slate-200 text-slate-700"],
    MULTIPLE_PORTAL_ACCOUNTS: ["Multiple portal accounts", "bg-purple-100 text-purple-800"],
    CLINICAL_HISTORY_REVIEW_REQUIRED: ["Clinical history review required", "bg-red-100 text-red-700"],
    NO_MATCH: ["No match / possible true new patient", "bg-slate-100 text-slate-600"],
    LINKED_RECONCILE_DEMOGRAPHICS: ["Linked — reconcile demographics", "bg-sky-100 text-sky-700"],
};
const EV = {
    EXACT_HCN: ["Exact HCN", "bg-emerald-100 text-emerald-800"], EXACT_DOB: ["Exact DOB", "bg-emerald-100 text-emerald-800"], EXACT_NAME: ["Exact name", "bg-emerald-100 text-emerald-800"],
    SHORTENED_NAME: ["Shortened name", "bg-amber-100 text-amber-800"], DIFFERENT_HCN: ["Different HCN", "bg-red-100 text-red-700"], DIFFERENT_DOB: ["Different DOB", "bg-red-100 text-red-700"],
    NAME_INCOMPATIBLE: ["Name incompatible", "bg-red-100 text-red-700"], HALF_LINK_PORTAL_SIDE: ["Half-link (portal side only)", "bg-orange-100 text-orange-800"],
    HALF_LINK_DIRECTORY_SIDE: ["Half-link (directory side only)", "bg-orange-100 text-orange-800"], EXISTING_DIRECTORY_LINK: ["Existing directory link", "bg-purple-100 text-purple-800"],
    DUPLICATE_PORTAL_HCN: ["Duplicate portal account — same HCN", "bg-purple-100 text-purple-800"], DUPLICATE_PORTAL_NAME_DOB: ["Duplicate portal account — same name + DOB", "bg-purple-100 text-purple-800"],
};
const STATE = { MATCH: "bg-emerald-50 text-emerald-700", CANONICAL_ONLY: "bg-slate-100 text-slate-600", PORTAL_ONLY: "bg-sky-100 text-sky-700", CONFLICT: "bg-red-100 text-red-700", EMPTY: "text-slate-300" };
const DEP_KEYS = ["visits", "prescriptions", "imaging", "bloodwork", "results", "referrals", "medications", "conditions", "surgeries", "allergies", "rx_transmissions", "appointments"];

const Badge = ({ map, k, testid }) => { const [l, c] = map[k] || [k, "bg-slate-100 text-slate-600"]; return <span data-testid={testid} className={`inline-flex px-1.5 py-0.5 rounded-sm text-[10px] font-bold uppercase tracking-wide ${c}`}>{l}</span>; };

function Deps({ label, dep }) {
    if (!dep) return null;
    const items = DEP_KEYS.filter((k) => dep[k]).map((k) => `${k} ${dep[k]}`);
    return (
        <div className="text-[11px] text-slate-600" data-testid={`deps-${label}`}>
            <span className="font-semibold">{label}:</span> {items.length ? items.join(" · ") : "no clinical references"}
            {dep.has_clinical && <span className="ml-1 text-red-700 font-semibold">(clinical history present)</span>}
        </div>
    );
}

function Side({ title, d, pin, status, testid }) {
    return (
        <div className="border border-slate-300 rounded-sm p-3 bg-white text-sm" data-testid={testid}>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">{title}</div>
            {!d ? <div className="text-slate-400 italic">No canonical record identified.</div> : (
                <>
                    <div className="font-bold text-slate-900 text-base">{d.full_name}</div>
                    <div className="text-slate-600">DOB {formatDate(d.date_of_birth)} · HC {d.health_card_masked || "—"} · PIN <span className="font-semibold">{pin || "none"}</span></div>
                    <div className="text-xs text-slate-500">{status}</div>
                </>
            )}
        </div>
    );
}

function FieldTable({ c, selections, setSelections, linked }) {
    const rows = c.fields.filter((r) => r.state !== "EMPTY");
    return (
        <table className="w-full text-xs border border-slate-200" data-testid="reconcile-table">
            <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500">
                <tr><th className="text-left p-1.5">Field</th><th className="text-left p-1.5">Canonical</th><th className="text-left p-1.5">Portal</th><th className="p-1.5">State</th><th className="text-left p-1.5">Action</th></tr>
            </thead>
            <tbody>
                {rows.map((r) => {
                    const sel = selections[r.field] || "KEEP_CANONICAL";
                    const actionable = linked && (r.state === "PORTAL_ONLY" || r.state === "CONFLICT");
                    return (
                        <tr key={r.field} className="border-t border-slate-100" data-testid={`reconcile-row-${r.field}`}>
                            <td className="p-1.5 font-semibold text-slate-700">{r.label}{r.identity_critical && <span className="ml-1 text-[9px] text-red-600 font-bold">ID</span>}</td>
                            <td className="p-1.5 text-slate-800">{r.canonical ?? "—"}</td>
                            <td className="p-1.5 text-slate-800">{r.portal ?? "—"}</td>
                            <td className="p-1.5 text-center"><span className={`px-1 py-px rounded-sm font-bold ${STATE[r.state]}`}>{r.state.replace("_", " ")}</span></td>
                            <td className="p-1.5">
                                {!actionable ? <span className="text-slate-400">{r.state === "MATCH" ? "no action" : r.state === "CANONICAL_ONLY" ? "keep canonical" : "—"}</span> : (
                                    <div className="flex gap-1">
                                        <button type="button" data-testid={`keep-${r.field}`} onClick={() => setSelections({ ...selections, [r.field]: "KEEP_CANONICAL" })}
                                            className={`px-1.5 py-0.5 rounded-sm border text-[10px] font-semibold ${sel === "KEEP_CANONICAL" ? "bg-slate-700 text-white border-slate-700" : "bg-white border-slate-300"}`}>Keep canonical</button>
                                        <button type="button" data-testid={`use-${r.field}`} onClick={() => setSelections({ ...selections, [r.field]: "USE_PORTAL" })}
                                            className={`px-1.5 py-0.5 rounded-sm border text-[10px] font-semibold ${sel === "USE_PORTAL" ? "bg-sky-700 text-white border-sky-700" : "bg-white border-slate-300"}`}>
                                            {r.state === "PORTAL_ONLY" ? "Add to canonical" : "Use portal value"}</button>
                                    </div>
                                )}
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
}

function Case({ item, onBack }) {
    const invalidate = useInvalidate();
    const pid = item.portal.id;
    const did = item.canonical?.id;
    const q = useQuery({ queryKey: ["identity-cleanup-case", pid, did], queryFn: async () => (await api.get(`/internal/identity-cleanup/${pid}`, { params: did ? { directory_id: did } : {} })).data });
    const c = q.data;
    const [selections, setSelections] = useState({});
    const [confirm, setConfirm] = useState(null); // "link" | "apply"
    const [busy, setBusy] = useState(false);
    const refresh = () => { q.refetch(); invalidate(); };
    const run = async (fn, ok) => { setBusy(true); try { await fn(); toast.success(ok); refresh(); } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); setConfirm(null); } };
    if (!c) return <div className="text-sm text-slate-400">Loading case…</div>;
    const linked = c.link_state === "LINKED";
    const chosen = Object.entries(selections).filter(([, v]) => v === "USE_PORTAL").map(([f]) => f);
    const critical = chosen.filter((f) => c.fields.find((r) => r.field === f)?.identity_critical);
    return (
        <div className="space-y-3" data-testid="cleanup-case">
            <div className="flex items-center gap-2 flex-wrap">
                <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-xs text-slate-600 hover:underline" data-testid="cleanup-back"><ArrowLeft className="w-3.5 h-3.5" /> Queue</button>
                <Badge map={CLASS} k={c.class} testid="case-class" />
                {c.evidence.map((e) => <Badge key={e} map={EV} k={e} testid={`evidence-${e}`} />)}
                <span className="ml-auto text-[10px] font-bold text-slate-500" data-testid="case-link-state">LINK: {c.link_state}</span>
            </div>
            <div className="grid md:grid-cols-2 gap-3">
                <Side title="Canonical patient (patient_directory)" d={c.canonical} pin={c.canonical?.visita_patient_id} status={c.canonical ? `Directory ${c.canonical.patient_status} · ${c.canonical.linked_patient_id ? (c.canonical.linked_patient_id === pid ? "linked to this portal account" : "linked to ANOTHER portal account") : "no portal link"}` : ""} testid="side-canonical" />
                <Side title="Portal registration (patients)" d={c.portal} pin={c.portal.historical_visita_patient_id ? `${c.portal.visita_patient_id} · historical portal PIN ${c.portal.historical_visita_patient_id} (retained, not recycled)` : c.portal.visita_patient_id ? `${c.portal.visita_patient_id}${c.canonical?.visita_patient_id && c.portal.visita_patient_id !== c.canonical.visita_patient_id ? " (duplicate/historical portal PIN)" : ""}` : null} status={`${c.portal.verification_status} · portal ${c.portal.portal_status || "—"} · ${c.portal.matched_directory_id ? "matched_directory set" : "unlinked"}`} testid="side-portal" />
            </div>
            {c.other_portal && (
                <div className="border border-purple-200 bg-purple-50 rounded-sm p-2 text-xs" data-testid="other-portal">
                    <Users className="w-3.5 h-3.5 inline mr-1" /><span className="font-semibold">Multiple portal accounts:</span> directory already linked to <span className="font-semibold">{c.other_portal.full_name || c.other_portal.id}</span>{c.other_portal.visita_patient_id ? ` (PIN ${c.other_portal.visita_patient_id})` : ""}. Candidate account: {c.portal.full_name}. Explicit portal-account reconciliation required — nothing is changed here.
                </div>
            )}
            <div className="border border-slate-200 rounded-sm p-2 space-y-0.5 bg-slate-50">
                <div className="text-[10px] uppercase tracking-wide text-slate-500 flex items-center gap-1"><Stethoscope className="w-3 h-3" /> Clinical dependency check</div>
                <Deps label="Portal side" dep={c.dependencies.portal} />
                <Deps label="Canonical side" dep={c.dependencies.canonical} />
            </div>
            {c.blocked_reason && !linked && (
                <div className="border border-red-200 bg-red-50 text-red-800 rounded-sm p-2 text-xs font-semibold flex items-center gap-1" data-testid="blocked-banner">
                    <AlertTriangle className="w-3.5 h-3.5" /> {CLASS[c.blocked_reason]?.[0] || c.blocked_reason} — routine link is not permitted for this case.
                </div>
            )}
            <div className="flex gap-2 flex-wrap">
                {c.can_link && <Button size="sm" disabled={busy} onClick={() => setConfirm("link")} data-testid="cleanup-link-btn" className="bg-visita-green hover:bg-visita-greenDark text-white"><Link2 className="w-4 h-4 mr-1" /> Link to Existing Patient</Button>}
                {c.can_repair && <Button size="sm" disabled={busy} onClick={() => setConfirm("repair")} data-testid="cleanup-repair-btn" className="bg-orange-600 hover:bg-orange-700 text-white"><Wrench className="w-4 h-4 mr-1" /> Repair Link</Button>}
                {linked && <Button size="sm" variant="outline" disabled={busy} onClick={() => run(() => api.post(`/internal/identity-cleanup/${pid}/complete`, { outcome: "completed" }), "Case completed.")} data-testid="cleanup-complete-btn"><Check className="w-4 h-4 mr-1" /> Complete</Button>}
                {!linked && c.class === "IDENTITY_CONFLICT" && <Button size="sm" variant="outline" disabled={busy} onClick={() => run(() => api.post(`/internal/identity-cleanup/${pid}/complete`, { outcome: "conflict_noted" }), "Conflict recorded for review.")} data-testid="cleanup-conflict-btn" className="text-red-700 border-red-300"><AlertTriangle className="w-4 h-4 mr-1" /> Record conflict</Button>}
            </div>
            {c.canonical && (
                <div className="space-y-2">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">Demographic reconciliation {linked ? "" : "(preview — link first to apply)"}</div>
                    <FieldTable c={c} selections={selections} setSelections={setSelections} linked={linked} />
                    {linked && (
                        <div className="flex items-center gap-2">
                            <Button size="sm" disabled={busy || !chosen.length} onClick={() => setConfirm("apply")} data-testid="cleanup-apply-btn" className="bg-sky-700 hover:bg-sky-800 text-white">Apply {chosen.length || ""} selected update{chosen.length === 1 ? "" : "s"}</Button>
                            {critical.length > 0 && <span className="text-[11px] text-red-700 font-semibold" data-testid="critical-warning">Includes identity-critical field(s): {critical.join(", ")} — stricter confirmation required.</span>}
                        </div>
                    )}
                </div>
            )}
            <AlertDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)}>
                <AlertDialogContent data-testid={`confirm-${confirm}`}>
                    <AlertDialogHeader>
                        <AlertDialogTitle>{confirm === "link" ? "Link portal account to existing patient?" : confirm === "repair" ? "Repair half-link?" : "Apply selected demographic updates?"}</AlertDialogTitle>
                        <AlertDialogDescription asChild>
                            <div className="text-sm space-y-1">
                                {confirm === "link" && <>
                                    <p><span className="font-semibold">{c.portal.full_name}</span> → <span className="font-semibold">{c.canonical?.full_name}</span></p>
                                    <ul className="list-disc pl-4 text-xs"><li>Existing canonical PIN <b>{c.canonical?.visita_patient_id || "—"}</b> is preserved; no new PIN is issued.</li><li>The portal account attaches to that canonical patient.</li><li>No clinical history is merged or rewritten.</li><li>Demographic reconciliation follows as a separate step.</li></ul>
                                </>}
                                {confirm === "repair" && <p className="text-xs">Restores a consistent two-way link between <b>{c.portal.full_name}</b> and <b>{c.canonical?.full_name}</b> (PIN {c.canonical?.visita_patient_id || "—"}). Nothing else changes. Audited.</p>}
                                {confirm === "apply" && <>
                                    <p className="text-xs">Canonical record will be updated for: <b>{chosen.join(", ")}</b>. Source: portal registration. Each field change is audited.</p>
                                    {critical.length > 0 && <p className="text-xs text-red-700 font-semibold">Identity-critical change ({critical.join(", ")}): confirm you have verified this against source documents.</p>}
                                </>}
                            </div>
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel data-testid="confirm-cancel">Cancel</AlertDialogCancel>
                        <AlertDialogAction data-testid="confirm-accept" className={confirm === "apply" && critical.length ? "bg-red-700 hover:bg-red-800" : "bg-visita-green hover:bg-visita-greenDark"} onClick={() => {
                            if (confirm === "link") run(() => api.post(`/internal/identity-cleanup/${pid}/link`, { directory_id: did }), "Linked to existing patient. PIN preserved.");
                            else if (confirm === "repair") run(() => api.post(`/internal/identity-cleanup/${pid}/repair-half-link`, { directory_id: did }), "Link repaired.");
                            else run(async () => { const { data } = await api.post(`/internal/identity-cleanup/${pid}/apply-fields`, { directory_id: did, selections: chosen.map((f) => ({ field: f, action: "USE_PORTAL" })), confirm_identity_critical: critical.length > 0 }); setSelections({}); if (data.skipped?.length) toast.message(`Skipped: ${data.skipped.map((s) => `${s.field} (${s.reason})`).join(", ")}`); }, "Canonical record updated.");
                        }}>{confirm === "link" ? "Link to Existing Patient" : confirm === "repair" ? "Repair Link" : critical.length ? "Confirm identity-critical update" : "Apply updates"}</AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}

export default function IdentityCleanup() {
    const q = useQuery({ queryKey: ["queue", "/internal/identity-cleanup"], queryFn: async () => (await api.get("/internal/identity-cleanup")).data });
    const [open, setOpen] = useState(null);
    const items = q.data || [];
    if (open) return <Case item={open} onBack={() => { setOpen(null); q.refetch(); }} />;
    return (
        <div className="space-y-2" data-testid="identity-cleanup">
            <p className="text-sm text-slate-500 flex items-center gap-1"><ShieldCheck className="w-4 h-4" /> Historical portal registrations reviewed one case at a time. Loading this queue changes nothing.</p>
            {q.isLoading && <p className="text-slate-400 text-sm">Building queue…</p>}
            {!q.isLoading && items.length === 0 && <p className="text-slate-400 text-sm">No historical identity cases.</p>}
            {items.map((it) => (
                <button key={it.portal.id} type="button" onClick={() => setOpen(it)} data-testid={`cleanup-item-${it.class}`}
                    className="w-full text-left bg-white border border-slate-300 rounded-sm p-3 hover:bg-slate-50">
                    <div className="flex items-center gap-2 flex-wrap">
                        <Badge map={CLASS} k={it.class} />
                        {it.evidence.map((e) => <Badge key={e} map={EV} k={e} />)}
                    </div>
                    <div className="mt-1 grid md:grid-cols-2 gap-x-4 text-sm">
                        <div><span className="text-[10px] uppercase text-slate-400 mr-1">Portal</span><span className="font-semibold">{it.portal.full_name}</span> <span className="text-xs text-slate-500">DOB {formatDate(it.portal.date_of_birth)} · {it.portal.verification_status} · PIN {it.portal.visita_patient_id || "none"}</span></div>
                        <div><span className="text-[10px] uppercase text-slate-400 mr-1">Canonical</span>{it.canonical ? <><span className="font-semibold">{it.canonical.full_name}</span> <span className="text-xs text-slate-500">DOB {formatDate(it.canonical.date_of_birth)} · PIN {it.canonical.visita_patient_id || "—"}</span></> : <span className="text-slate-400 italic">none identified</span>}</div>
                    </div>
                </button>
            ))}
        </div>
    );
}
