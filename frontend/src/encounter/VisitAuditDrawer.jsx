import { useEffect, useState } from "react";
import { Clock, FileSignature, Lock } from "lucide-react";
import { api } from "../lib/api";
import { formatDateTime } from "../lib/date";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../components/ui/sheet";

/* Visit Hx → View Audit. READ-ONLY drawer over GET /internal/audit/visit/{id}. Zero mutation controls. */
const STATUS = { SIGNED: "bg-visita-ribbon text-white", STOPPED_UNSIGNED: "bg-amber-100 text-amber-900", READY_TO_SIGN: "bg-amber-100 text-amber-900", IN_PROGRESS: "bg-emerald-100 text-emerald-800", COMPLETED: "bg-slate-200 text-slate-700" };
const statusLabel = (s) => ({ READY_TO_SIGN: "STOPPED_UNSIGNED", COMPLETED: "COMPLETED (LEGACY)" }[s] || s || "—");
const HIDE_META = ["patient_ref", "practice_id", "ref_number", "resulting_status", "actor_id", "actor_name", "actor_role", "server_time", "visit_id"];
const dot = (a) => (a === "visit_signed" ? "bg-visita-ribbon" : a === "visit_stopped" ? "bg-red-500" : a === "visit_started" ? "bg-emerald-500" : "bg-slate-300");

export function VisitAuditDrawer({ visitId, open, onClose }) {
    const [tl, setTl] = useState(null);
    const [err, setErr] = useState(false);
    useEffect(() => {
        if (!open || !visitId) return;
        setTl(null); setErr(false);
        api.get(`/internal/audit/visit/${visitId}`).then(({ data }) => setTl(data)).catch(() => setErr(true));
    }, [open, visitId]);
    const items = (tl?.items || []).filter((i) => i.action !== "visit_read");
    return (
        <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
            <SheetContent className="w-[520px] sm:max-w-[520px] overflow-y-auto" data-testid="visit-hx-audit-drawer">
                <SheetHeader>
                    <SheetTitle className="text-base flex items-center gap-2">Visit audit · <span className="font-mono">{tl?.visit?.ref_number || "…"}</span>
                        {tl && <span className={`px-1.5 py-px rounded-sm text-[10px] font-bold ${STATUS[tl.visit.status] || "bg-slate-100"}`} data-testid="visit-hx-audit-status">{statusLabel(tl.visit.status)}</span>}
                    </SheetTitle>
                    <SheetDescription className="flex items-center gap-1"><Lock className="w-3 h-3" /> Read-only · immutable audit trail for this Visit only.</SheetDescription>
                </SheetHeader>
                {err && <div className="mt-3 text-xs text-red-700" data-testid="visit-hx-audit-error">Audit trail unavailable.</div>}
                {tl?.signed && (
                    <div className="mt-3 border border-visita-ribbon/30 rounded-sm p-2 text-xs bg-visita-ribbon/5" data-testid="visit-hx-audit-signed">
                        <div className="flex items-center gap-1 font-bold text-visita-ribbon"><FileSignature className="w-3.5 h-3.5" /> SIGNED</div>
                        <div>{tl.signed.signed_by?.physician_name} · {formatDateTime(tl.signed.signed_at)}</div>
                        {tl.signed.version != null && <div>Snapshot v{tl.signed.version}</div>}
                        {tl.signed.hash && <div className="font-mono text-[10px] break-all">SHA-256: {tl.signed.hash}</div>}
                        <div className="text-[10px] text-slate-500 mt-1">Hash = integrity reference of the signed snapshot; the signature is the authenticated physician identity above.</div>
                    </div>
                )}
                {tl && !tl.signed && (
                    <div className="mt-3 text-[11px] text-slate-500" data-testid="visit-hx-audit-unsigned">
                        {tl.visit.status === "COMPLETED" ? "Legacy visit — no digital signing metadata on record." : "No digital signature recorded for this Visit."}
                    </div>
                )}
                {tl && (
                    <div className="mt-3" data-testid="visit-hx-audit-timeline">
                        <div className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide text-slate-500 mb-1"><Clock className="w-3 h-3" /> Timeline · {items.length} events</div>
                        {!items.length && <div className="text-xs text-slate-400 italic" data-testid="visit-hx-audit-empty">No audit events recorded for this Visit.</div>}
                        <ol className="border-l-2 border-slate-200 pl-3 space-y-2">
                            {items.map((i) => {
                                const meta = Object.entries(i.meta || {}).filter(([k]) => !HIDE_META.includes(k));
                                return (
                                    <li key={i.id} className="text-xs relative" data-testid={`visit-hx-audit-${i.action}`}>
                                        <span className={`absolute -left-[17px] top-1 w-2.5 h-2.5 rounded-full ${dot(i.action)}`} />
                                        <div><span className="font-mono text-[11px] text-slate-500">{formatDateTime(i.created_at)}</span> <span className="font-semibold">{i.action.replace(/_/g, " ")}</span> <span className="text-slate-600">· {i.actor_name || "—"}{i.actor_role ? ` (${i.actor_role})` : ""}</span>
                                            {i.after_stop && <span className="ml-1 text-[10px] text-amber-800 font-semibold">documentation after encounter ended</span>}</div>
                                        {(i.old_status || i.new_status) && <div className="text-[10px] text-slate-500">{i.old_status || "—"} → {i.new_status || "—"}</div>}
                                        {meta.length > 0 && (
                                            <div className="mt-0.5 grid grid-cols-[110px_1fr] gap-x-2 text-[10px] text-slate-600">
                                                {meta.map(([k, v]) => <div key={k} className="contents"><span className="text-slate-400">{k}</span><span className={`break-all ${typeof v !== "string" || k.includes("hash") ? "font-mono" : ""}`}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</span></div>)}
                                            </div>
                                        )}
                                    </li>
                                );
                            })}
                        </ol>
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}
