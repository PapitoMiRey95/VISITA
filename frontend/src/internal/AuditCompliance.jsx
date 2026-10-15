import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck, Search, ChevronLeft, ChevronRight, Lock, Clock, FileSignature } from "lucide-react";
import { api } from "../lib/api";
import { formatDateTime } from "../lib/date";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../components/ui/sheet";

/* Settings → Audit & Compliance. READ-ONLY viewer over existing audit_logs. ZERO mutation controls by design. */
const TABS = [["audit_log", "Audit Log"], ["signed_visits", "Signed Visits"], ["exports", "Exports"]];
const STATUS = { SIGNED: "bg-visita-ribbon text-white", STOPPED_UNSIGNED: "bg-amber-100 text-amber-900", READY_TO_SIGN: "bg-amber-100 text-amber-900", IN_PROGRESS: "bg-emerald-100 text-emerald-800", COMPLETED: "bg-slate-200 text-slate-700" };
const statusLabel = (s) => ({ READY_TO_SIGN: "STOPPED_UNSIGNED", COMPLETED: "COMPLETED (LEGACY)" }[s] || s || "—");
const EMPTY = { date_from: "", date_to: "", patient: "", visit_ref: "", actor: "", action: "", module: "", visit_status: "" };

export default function AuditCompliance() {
    const [tab, setTab] = useState("audit_log");
    const [f, setF] = useState(EMPTY);
    const [applied, setApplied] = useState(EMPTY);
    const [page, setPage] = useState(1);
    const [data, setData] = useState(null);
    const [sel, setSel] = useState(null);
    const [timeline, setTimeline] = useState(null);

    const load = useCallback(() => {
        const params = { page, page_size: 50 };
        Object.entries(applied).forEach(([k, v]) => { if (v) params[k === "patient" ? "patient_ref" : k] = v; });
        api.get("/internal/audit", { params }).then(({ data: d }) => setData(d)).catch(() => setData({ items: [], total: 0 }));
    }, [applied, page]);
    useEffect(() => { load(); }, [load]);

    const openEvent = (row) => {
        setSel(row); setTimeline(null);
        if (row.entity_type === "visit") api.get(`/internal/audit/visit/${row.entity_id}`).then(({ data: d }) => setTimeline(d)).catch(() => setTimeline(null));
    };
    const Field = ({ k, label, type = "text", placeholder }) => (
        <label className="flex flex-col gap-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}
            <input type={type} value={f[k]} placeholder={placeholder} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`audit-filter-${k}`}
                className="h-8 px-2 text-xs font-normal normal-case tracking-normal rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500" />
        </label>
    );
    const pages = data ? Math.max(1, Math.ceil(data.total / 50)) : 1;

    return (
        <div className="animate-fade-in" data-testid="audit-compliance">
            <div className="flex items-start gap-3 mb-3">
                <ShieldCheck className="w-7 h-7 text-visita-ribbon mt-1" />
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Audit &amp; Compliance</h1>
                    <p className="text-sm text-slate-500">Immutable record of clinical and lifecycle activity for this practice. Read-only — audit entries can never be edited or deleted.</p>
                </div>
                <Link to="/internal/settings" className="ml-auto text-xs text-visita-ribbon hover:underline" data-testid="audit-back-settings">← Settings</Link>
            </div>
            <nav className="flex gap-0 border-b border-slate-300 mb-3" data-testid="audit-tabs">
                {TABS.map(([k, l]) => (
                    <button key={k} type="button" onClick={() => setTab(k)} data-testid={`audit-tab-${k}`} disabled={k !== "audit_log"}
                        className={`px-3 h-8 text-xs font-bold border-b-2 -mb-px ${tab === k ? "border-visita-ribbon text-visita-ribbon" : "border-transparent text-slate-500"} disabled:opacity-50`}>{l}{k !== "audit_log" && <span className="ml-1 font-normal text-[9px]">(next phase)</span>}</button>
                ))}
            </nav>
            <div className="bg-white border border-slate-300 rounded-sm p-3 mb-3" data-testid="audit-filters">
                <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2">
                    <Field k="date_from" label="From" type="date" /><Field k="date_to" label="To" type="date" />
                    <Field k="patient" label="Patient ref" placeholder="directory:… / patient:…" /><Field k="visit_ref" label="Visit ref" placeholder="VIS-000090" />
                    <Field k="actor" label="Actor" placeholder="name or id" /><Field k="action" label="Event" placeholder="visit_signed" />
                    <Field k="module" label="Module" placeholder="Visit / Patient" />
                    <label className="flex flex-col gap-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-500">Visit status
                        <select value={f.visit_status} onChange={(e) => setF({ ...f, visit_status: e.target.value })} data-testid="audit-filter-visit_status" className="h-8 px-1 text-xs font-normal normal-case tracking-normal rounded-sm border border-slate-300 bg-white">
                            <option value="">Any</option><option>IN_PROGRESS</option><option>STOPPED_UNSIGNED</option><option value="READY_TO_SIGN">STOPPED_UNSIGNED (legacy value)</option><option>SIGNED</option><option>COMPLETED</option>
                        </select>
                    </label>
                </div>
                <div className="flex gap-2 mt-2">
                    <button type="button" onClick={() => { setPage(1); setApplied(f); }} data-testid="audit-apply" className="inline-flex items-center gap-1 h-8 px-3 rounded-sm bg-visita-ribbon text-white text-xs font-bold"><Search className="w-3.5 h-3.5" /> Apply filters</button>
                    <button type="button" onClick={() => { setF(EMPTY); setApplied(EMPTY); setPage(1); }} data-testid="audit-reset" className="h-8 px-3 rounded-sm border border-slate-300 text-xs">Clear</button>
                    <span className="ml-auto text-xs text-slate-500 self-center" data-testid="audit-total">{data ? `${data.total} events` : "Loading…"}</span>
                </div>
            </div>
            <div className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                <table className="w-full text-xs" data-testid="audit-table">
                    <thead className="bg-slate-100 text-[10px] uppercase tracking-wide text-slate-500">
                        <tr>{["Date / Time", "Patient", "Visit Ref", "Actor", "Role", "Event", "Module", "Status"].map((h) => <th key={h} className="text-left px-2 py-1.5 font-bold">{h}</th>)}</tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                        {data?.items?.map((r) => (
                            <tr key={r.id} onClick={() => openEvent(r)} data-testid={`audit-row-${r.id}`} className="hover:bg-visita-bg cursor-pointer">
                                <td className="px-2 py-1 whitespace-nowrap font-mono text-[11px]">{formatDateTime(r.created_at)}</td>
                                <td className="px-2 py-1">{r.patient_name ? <>{r.patient_name}{r.patient_pin && <span className="ml-1 text-slate-500">PIN {r.patient_pin}</span>}</> : <span className="text-slate-400">—</span>}</td>
                                <td className="px-2 py-1 font-mono">{r.visit_ref || "—"}</td>
                                <td className="px-2 py-1">{r.actor_name || "—"}</td>
                                <td className="px-2 py-1 capitalize">{r.actor_role || "—"}</td>
                                <td className="px-2 py-1 font-mono">{r.action}</td>
                                <td className="px-2 py-1">{r.module}</td>
                                <td className="px-2 py-1">{r.new_status ? <span className={`px-1.5 py-px rounded-sm text-[10px] font-bold ${STATUS[r.new_status] || "bg-slate-100"}`}>{statusLabel(r.new_status)}</span> : "—"}</td>
                            </tr>
                        ))}
                        {data && !data.items.length && <tr><td colSpan={8} className="px-2 py-4 text-center text-slate-400 italic" data-testid="audit-empty">No audit events match.</td></tr>}
                    </tbody>
                </table>
                <div className="flex items-center gap-2 px-2 py-1.5 border-t border-slate-200 text-xs">
                    <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="audit-prev" className="h-7 px-2 border rounded-sm disabled:opacity-40"><ChevronLeft className="w-3.5 h-3.5" /></button>
                    <span data-testid="audit-page">Page {page} / {pages}</span>
                    <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)} data-testid="audit-next" className="h-7 px-2 border rounded-sm disabled:opacity-40"><ChevronRight className="w-3.5 h-3.5" /></button>
                    <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-slate-500"><Lock className="w-3 h-3" /> Read-only · immutable</span>
                </div>
            </div>
            <Sheet open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
                <SheetContent className="w-[560px] sm:max-w-[560px] overflow-y-auto" data-testid="audit-detail">
                    {sel && <EventDetail row={sel} timeline={timeline} />}
                </SheetContent>
            </Sheet>
        </div>
    );
}

function KV({ k, v, mono }) {
    return v === undefined || v === null || v === "" ? null : (
        <div className="grid grid-cols-[140px_1fr] gap-2 py-0.5 border-b border-slate-100 text-xs"><span className="text-slate-500">{k}</span><span className={`break-all ${mono ? "font-mono text-[11px]" : ""}`}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</span></div>
    );
}

function EventDetail({ row, timeline }) {
    const signed = timeline?.signed;
    return (
        <>
            <SheetHeader>
                <SheetTitle className="font-mono text-base">{row.action}</SheetTitle>
                <SheetDescription>{formatDateTime(row.created_at)} · {row.actor_name} ({row.actor_role})</SheetDescription>
            </SheetHeader>
            <div className="mt-3" data-testid="audit-detail-fields">
                <KV k="Server timestamp" v={row.created_at} mono /><KV k="Practice" v={row.practice_id} mono /><KV k="Actor id" v={row.actor_id} mono /><KV k="Actor" v={row.actor_name} /><KV k="Role" v={row.actor_role} />
                <KV k="Patient" v={row.patient_name} /><KV k="Patient PIN" v={row.patient_pin} /><KV k="patient_ref" v={row.patient_ref} mono />
                <KV k="Entity" v={row.entity_type} /><KV k="Entity id" v={row.entity_id} mono /><KV k="Visit ref" v={row.visit_ref} mono />
                <KV k="Old status" v={row.old_status} /><KV k="New / resulting status" v={row.new_status} />
                {Object.entries(row.meta || {}).filter(([k]) => !["patient_ref", "practice_id", "ref_number", "resulting_status", "actor_id", "actor_name", "actor_role", "server_time", "visit_id"].includes(k))
                    .map(([k, v]) => <KV key={k} k={`meta.${k}`} v={v} mono={typeof v !== "string" || k.includes("hash")} />)}
            </div>
            {signed && (
                <div className="mt-3 border border-visita-ribbon/30 rounded-sm p-2 text-xs bg-visita-ribbon/5" data-testid="audit-signed-integrity">
                    <div className="flex items-center gap-1 font-bold text-visita-ribbon"><FileSignature className="w-3.5 h-3.5" /> SIGNED</div>
                    <div>{signed.signed_by?.physician_name} · {formatDateTime(signed.signed_at)}</div>
                    <div>Snapshot v{signed.version}</div>
                    <div className="font-mono text-[10px] break-all">SHA-256: {signed.hash}</div>
                    <div className="text-[10px] text-slate-500 mt-1">Hash = integrity reference of the signed snapshot; the signature is the authenticated physician identity above.</div>
                </div>
            )}
            {timeline && (
                <div className="mt-3" data-testid="audit-visit-timeline">
                    <div className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide text-slate-500 mb-1"><Clock className="w-3 h-3" /> Visit timeline · {timeline.visit.ref_number}
                        <span className={`ml-auto px-1.5 py-px rounded-sm ${STATUS[timeline.visit.status] || "bg-slate-100"}`}>{statusLabel(timeline.visit.status)}</span></div>
                    <ol className="border-l-2 border-slate-200 pl-3 space-y-1.5">
                        {timeline.items.filter((i) => i.action !== "visit_read").map((i) => (
                            <li key={i.id} className="text-xs relative" data-testid={`timeline-${i.action}`}>
                                <span className={`absolute -left-[17px] top-1 w-2.5 h-2.5 rounded-full ${i.action === "visit_signed" ? "bg-visita-ribbon" : i.action === "visit_stopped" ? "bg-red-500" : i.action === "visit_started" ? "bg-emerald-500" : "bg-slate-300"}`} />
                                <span className="font-mono text-[11px] text-slate-500">{formatDateTime(i.created_at)}</span> <span className="font-semibold">{i.action.replace(/_/g, " ")}</span> <span className="text-slate-600">· {i.actor_name}</span>
                                {i.after_stop && <span className="ml-1 text-[10px] text-amber-800 font-semibold">documentation after encounter ended</span>}
                            </li>
                        ))}
                    </ol>
                </div>
            )}
        </>
    );
}
