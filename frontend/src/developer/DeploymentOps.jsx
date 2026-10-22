import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Rocket, Activity, History, Megaphone } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { formatDateTime } from "../lib/date";

const STATE_STYLE = {
    NORMAL: "bg-emerald-500 text-slate-950 border-emerald-500", UPDATING: "bg-sky-500 text-slate-950 border-sky-500",
    MAINTENANCE: "bg-amber-400 text-slate-950 border-amber-400", SERVICE_ISSUE: "bg-red-500 text-white border-red-500",
};
const DIM = { NORMAL: "border-emerald-500/40 text-emerald-300", UPDATING: "border-sky-500/40 text-sky-300", MAINTENANCE: "border-amber-500/40 text-amber-300", SERVICE_ISSUE: "border-red-500/40 text-red-300" };
const RESULT_STYLE = { SUCCEEDED: "bg-emerald-500/15 text-emerald-300", RECOVERED: "bg-amber-500/15 text-amber-300", RESOLVED: "bg-emerald-500/15 text-emerald-300", ROLLED_BACK: "bg-amber-500/15 text-amber-300", TIMEOUT: "bg-red-500/15 text-red-300", MANUAL_ISSUE: "bg-red-500/15 text-red-300" };
const GOOD = new Set(["ONLINE", "CONNECTED", "READY"]);
const bundleHash = () => (Array.from(document.scripts).map((s) => s.src.match(/main\.([a-z0-9]+)\.js/)?.[1]).find(Boolean)) || "dev";
const dur = (a, b) => { if (!a || !b) return "—"; const s = Math.round((new Date(b) - new Date(a)) / 1000); return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`; };

function Card({ icon: Icon, title, children, testid, className = "" }) {
    return (
        <section className={`bg-slate-900/70 border border-slate-800 rounded-md p-5 ${className}`} data-testid={testid}>
            <h2 className="text-sm font-bold text-slate-200 flex items-center gap-2 mb-3"><Icon className="w-4 h-4 text-emerald-400" /> {title}</h2>
            {children}
        </section>
    );
}
const Row = ({ label, children, testid }) => (
    <div className="flex items-center justify-between gap-3 border-b border-slate-800 py-1.5 text-sm" data-testid={testid}><span className="text-slate-400">{label}</span><span className="text-slate-100 text-right">{children}</span></div>
);
const Pill = ({ value, cls }) => <span className={`text-xs font-bold px-2 py-0.5 rounded-sm ${cls || (GOOD.has(value) ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/20 text-amber-300")}`}>{value}</span>;

function StateStrip({ d, onChanged }) {
    const dep = d.deployment; const v = dep.verification;
    const [kind, setKind] = useState("CODE");
    const [note, setNote] = useState("");
    const [commit, setCommit] = useState("");
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState(false);
    const run = async (fn, ok) => { setBusy(true); try { await fn(); toast.success(ok); setConfirm(""); onChanged(); } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); } };
    const begin = () => run(() => api.post("/developer/deployment/begin-update", { kind, note, expected_commit: commit || null }), "Soft Update started — managed notice is live");
    const verify = () => run(() => api.post("/developer/deployment/verify"), "Health check recorded");
    const issue = () => run(() => api.post("/developer/deployment/service-issue", { confirm, note }), "SERVICE_ISSUE entered — outage notice is live");
    const resolve = (rolled_back) => run(() => api.post("/developer/deployment/resolve", { confirm, note, rolled_back }), rolled_back ? "Marked rolled back — NORMAL" : "Resolved — NORMAL");
    const st = dep.state;
    return (
        <Card icon={Rocket} title="Deployment & Maintenance" testid="dep-state-strip">
            <div className="flex items-center gap-2 flex-wrap" data-testid="dep-state-row">
                {["NORMAL", "UPDATING", "MAINTENANCE", "SERVICE_ISSUE"].map((s) => (
                    <span key={s} className={`px-3 py-1.5 rounded-sm text-xs font-bold border ${st === s ? STATE_STYLE[s] : DIM[s]}`} data-testid={`dep-state-${s.toLowerCase()}`} data-active={st === s}>{s}</span>
                ))}
                <span className="text-xs text-slate-400 ml-2" data-testid="dep-state-since">{st} {dep.since ? `since ${formatDateTime(dep.since)}` : ""}{dep.by?.name ? ` · by ${dep.by.name}` : ""}{dep.kind ? ` · ${dep.kind}` : ""}</span>
            </div>
            <div className="grid md:grid-cols-4 gap-3 text-xs mt-4">
                <div className="rounded-sm border border-slate-800 bg-slate-950/60 p-3"><div className="text-slate-500">Flow</div><div className="mt-1 text-slate-200 font-mono">NORMAL → UPDATING → verify → NORMAL</div><div className="text-slate-500 mt-1">no recovery in {d.timeout_min} min → SERVICE_ISSUE</div></div>
                <div className="rounded-sm border border-slate-800 bg-slate-950/60 p-3"><div className="text-slate-500">Soft Update</div><div className="mt-1 text-slate-200">App stays accessible · managed notice · auto-clears after {d.required_ok} consecutive healthy checks</div></div>
                <div className="rounded-sm border border-slate-800 bg-slate-950/60 p-3"><div className="text-slate-500">Full Maintenance</div><div className="mt-1 text-slate-200">Writes stopped (503 for non-operators) · branded screen · typed ENTER / EXIT (card below)</div></div>
                <div className="rounded-sm border border-slate-800 bg-slate-950/60 p-3"><div className="text-slate-500">Verification</div><div className="mt-1 text-slate-200">CODE / HOTFIX: expected build when supplied · RESOURCE: same build valid, readiness only</div></div>
            </div>
            <div className="mt-4 flex flex-wrap items-end gap-2" data-testid="dep-actions">
                {st !== "MAINTENANCE" && st !== "UPDATING" && (<>
                    <label className="text-xs text-slate-400">Kind
                        <select value={kind} onChange={(e) => setKind(e.target.value)} className="block mt-1 h-8 rounded-sm bg-slate-950 border border-slate-700 text-slate-100 text-xs px-2" data-testid="dep-kind">
                            {(d.kinds || []).map((k) => <option key={k} value={k}>{k === "CODE" ? "CODE deploy" : k === "RESOURCE" ? "RESOURCE-only republish" : "HOTFIX / redeploy"}</option>)}
                        </select>
                    </label>
                    <label className="text-xs text-slate-400">Expected build (commit){kind === "RESOURCE" ? " — ignored" : ""}
                        <Input value={commit} onChange={(e) => setCommit(e.target.value)} disabled={kind === "RESOURCE"} placeholder={d.release?.commit || "e.g. cacb15e"} className="mt-1 h-8 w-40 text-xs font-mono bg-slate-950 border-slate-700 text-slate-100" data-testid="dep-expected-commit" />
                    </label>
                </>)}
                <label className="text-xs text-slate-400 flex-1 min-w-[200px]">Note
                    <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What ships / why" className="mt-1 h-8 text-xs bg-slate-950 border-slate-700 text-slate-100" data-testid="dep-note" />
                </label>
                {st !== "MAINTENANCE" && st !== "UPDATING" && <Button size="sm" disabled={busy} onClick={begin} className="bg-sky-500 hover:bg-sky-400 text-slate-950" data-testid="dep-begin-update">Begin Soft Update</Button>}
                <Button size="sm" variant="outline" disabled={busy} onClick={verify} className="border-slate-600 text-slate-200" data-testid="dep-verify-now">Run health check</Button>
                {(st === "UPDATING" || st === "SERVICE_ISSUE") && (<>
                    <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={st === "UPDATING" ? "ISSUE or RESOLVE" : "Type RESOLVE"} className="h-8 w-36 text-xs bg-slate-950 border-slate-700 text-slate-100" data-testid="dep-confirm" />
                    {st === "UPDATING" && <Button size="sm" disabled={busy || confirm !== "ISSUE"} onClick={issue} className="bg-red-600 hover:bg-red-500 text-white" data-testid="dep-enter-issue">Enter SERVICE_ISSUE</Button>}
                    <Button size="sm" disabled={busy || confirm !== "RESOLVE"} onClick={() => resolve(false)} className="bg-emerald-500 hover:bg-emerald-400 text-slate-950" data-testid="dep-resolve">Resolve → NORMAL</Button>
                    <Button size="sm" disabled={busy || confirm !== "RESOLVE"} onClick={() => resolve(true)} variant="outline" className="border-amber-500/60 text-amber-300" data-testid="dep-rolled-back">Rolled back → NORMAL</Button>
                </>)}
            </div>
            {(st === "UPDATING" || st === "SERVICE_ISSUE") && (
                <div className="mt-3 text-xs text-slate-300" data-testid="dep-verification-line">
                    Verification <span className="font-mono text-slate-100" data-testid="dep-streak">{v.streak} / {v.required}</span> consecutive OK
                    {v.deadline_at && st === "UPDATING" && <> · deadline {formatDateTime(v.deadline_at)}</>}
                    {v.last_check_at && <> · last check {formatDateTime(v.last_check_at)} {v.checks?.[0] && (v.checks[0].ok ? <span className="text-emerald-300">OK</span> : <span className="text-red-300">failed: {v.checks[0].reasons.join(", ")}</span>)}</>}
                    {st === "SERVICE_ISSUE" && v.streak >= v.required && <span className="text-emerald-300"> · service healthy again — type RESOLVE</span>}
                </div>
            )}
        </Card>
    );
}

function BuildCard({ d, onChanged }) {
    const dep = d.deployment; const last = d.history?.[0];
    const [tier, setTier] = useState(dep.build?.tier || "");
    const save = async () => { try { await api.put("/developer/deployment/build-info", { tier }); toast.success("Resource tier noted"); onChanged(); } catch (e) { toast.error(formatErr(e)); } };
    return (
        <Card icon={Rocket} title={`${d.environment === "production" ? "Production" : "Preview"} build`} testid="dep-build">
            <Row label="Version" testid="dep-build-version"><span className="font-mono">{d.release?.commit || "n/a"} · main.{bundleHash()}</span></Row>
            <Row label="Resource tier" testid="dep-build-tier">
                <span className="flex items-center gap-1"><Input value={tier} onChange={(e) => setTier(e.target.value)} placeholder="e.g. Launch · 0.5 vCPU / 2 GB" className="h-7 w-52 text-xs bg-slate-950 border-slate-700 text-slate-100" data-testid="dep-tier-input" /><Button size="sm" variant="ghost" onClick={save} className="h-7 px-2 text-xs text-slate-300" data-testid="dep-tier-save">Save</Button></span>
            </Row>
            <Row label="Deployment status" testid="dep-build-status">{last ? <Pill value={last.result || last.status} cls={RESULT_STYLE[last.result] || (last.status === "IN_PROGRESS" ? "bg-sky-500/15 text-sky-300" : "bg-slate-700 text-slate-200")} /> : "—"}</Row>
            <Row label="Started"><span className="font-mono">{last ? formatDateTime(last.started_at) : "—"}</span></Row>
            <Row label="Completed"><span className="font-mono">{last?.completed_at ? `${formatDateTime(last.completed_at)} · ${dur(last.started_at, last.completed_at)}` : "—"}</span></Row>
            <Row label="Last successful health check" testid="dep-last-ok"><span className="font-mono">{dep.verification?.last_ok_at ? formatDateTime(dep.verification.last_ok_at) : "—"}</span></Row>
            <Row label="Rollback target"><span className="font-mono">{last?.rollback_target || "—"}</span></Row>
            <p className="text-[11px] text-slate-500 mt-2">Build timings are recorded by VIen (Begin Soft Update → verification), not read from the hosting pipeline. Tier is operator-noted.</p>
        </Card>
    );
}

function ReadinessCard({ d }) {
    const p = d.probe || {}; const v = d.deployment.verification;
    return (
        <Card icon={Activity} title="Readiness" testid="dep-readiness">
            <Row label="Application / API"><Pill value={p.api} /></Row>
            <Row label="Database"><Pill value={p.database} /></Row>
            <Row label="Storage"><Pill value={p.storage} /></Row>
            <Row label="Readiness"><Pill value={p.readiness} /></Row>
            <Row label="Verification streak" testid="dep-readiness-streak"><span className="font-mono">{v.streak} / {v.required}</span></Row>
            <div className="mt-3 text-[11px] text-slate-500">Platform cron verifies every minute; results feed the state machine. Nothing here touches clinical data.</div>
            {!!v.checks?.length && <ul className="mt-2 space-y-0.5 text-[11px] font-mono" data-testid="dep-checks">{v.checks.slice(0, 5).map((c, i) => <li key={i} className={c.ok ? "text-emerald-300" : "text-red-300"}>{formatDateTime(c.at)} · {c.source} · {c.ok ? "OK" : c.reasons.join(", ")}</li>)}</ul>}
        </Card>
    );
}

function NoticePreview({ d, announcement }) {
    const st = d.deployment.state;
    const managed = st === "UPDATING" ? "VIen is being updated. Some services may be briefly unavailable. Please try again if something does not load."
        : st === "SERVICE_ISSUE" || st === "MAINTENANCE" ? "VIen is temporarily unavailable. We’re completing a brief system update. Please try again shortly." : null;
    return (
        <Card icon={Megaphone} title="User-facing preview" testid="dep-notice-preview">
            <div className="text-xs text-slate-400 mb-2">Managed notice ({st}) renders above the manual Global message on portal, internal, login and registration pages. The manual message is kept, not replaced.</div>
            <div className="rounded-sm border border-slate-700 overflow-hidden">
                {managed ? <div className="bg-[#0b2545] text-white text-[13px] px-4 py-2 flex items-center gap-2" data-testid="dep-preview-managed"><span className="w-2 h-2 rounded-full bg-sky-300" />{managed}</div>
                    : <div className="bg-slate-950 text-slate-500 text-[12px] px-4 py-2 italic" data-testid="dep-preview-managed-none">No managed notice (NORMAL)</div>}
                {announcement?.active && <div className="bg-sky-700 text-white text-[13px] px-4 py-1.5 text-center font-semibold" data-testid="dep-preview-manual">{announcement.type} · {announcement.message}</div>}
                <div className="bg-white p-3 text-slate-400 text-xs">(page content continues normally)</div>
            </div>
        </Card>
    );
}

function HistoryCard({ d }) {
    return (
        <Card icon={History} title="Recent deployments" testid="dep-history" className="md:col-span-3">
            <div className="overflow-x-auto"><table className="w-full text-xs">
                <thead><tr className="text-slate-500 text-left"><th className="py-1 pr-3">Started</th><th className="pr-3">Kind</th><th className="pr-3">Mode</th><th className="pr-3">Operator</th><th className="pr-3">Build</th><th className="pr-3">Duration</th><th className="pr-3">Verification</th><th className="pr-3">Result</th><th>Rollback target</th></tr></thead>
                <tbody className="text-slate-200">
                    {(d.history || []).map((h) => (
                        <tr key={h.id} className="border-t border-slate-800" data-testid={`dep-history-row-${h.id}`}>
                            <td className="py-1.5 pr-3 font-mono">{formatDateTime(h.started_at)}</td><td className="pr-3">{h.kind}{h.note ? <span className="text-slate-500"> · {h.note}</span> : null}</td>
                            <td className="pr-3"><span className={`px-1.5 py-0.5 rounded-sm font-bold ${h.mode === "FULL" ? "bg-amber-500/15 text-amber-300" : "bg-sky-500/15 text-sky-300"}`}>{h.mode}</span></td>
                            <td className="pr-3">{h.operator?.name}</td><td className="pr-3 font-mono">{h.build_from || "—"}{h.build_to && h.build_to !== h.build_from ? ` → ${h.build_to}` : ""}{h.expected_commit ? <span className="text-slate-500"> (exp {h.expected_commit})</span> : null}</td>
                            <td className="pr-3">{dur(h.started_at, h.completed_at)}</td><td className="pr-3">{h.verification ? `${h.verification.ok} ok / ${h.verification.failed} failed` : "—"}</td>
                            <td className="pr-3"><Pill value={h.result || h.status} cls={RESULT_STYLE[h.result] || (h.status === "IN_PROGRESS" ? "bg-sky-500/15 text-sky-300" : h.status === "SERVICE_ISSUE" ? "bg-red-500/15 text-red-300" : "bg-slate-700 text-slate-200")} /></td>
                            <td className="font-mono">{h.rollback_target || "—"}</td>
                        </tr>
                    ))}
                    {!d.history?.length && <tr><td colSpan={9} className="py-3 text-slate-500 italic">No deployments recorded yet.</td></tr>}
                </tbody>
            </table></div>
        </Card>
    );
}

export function DeploymentOps({ announcement, onChanged }) {
    const q = useQuery({ queryKey: ["developer-deployment"], queryFn: async () => (await api.get("/developer/deployment")).data, refetchInterval: 15000 });
    const d = q.data;
    const changed = () => { q.refetch(); onChanged(); };
    if (q.error) return <div className="text-sm text-red-400">{formatErr(q.error)}</div>;
    if (!d) return <div className="text-sm text-slate-500" data-testid="dep-loading">Loading…</div>;
    return (
        <div className="space-y-5" data-testid="dep-ops">
            <StateStrip d={d} onChanged={changed} />
            <div className="grid md:grid-cols-3 gap-5">
                <BuildCard d={d} onChanged={changed} />
                <ReadinessCard d={d} />
                <NoticePreview d={d} announcement={announcement} />
                <HistoryCard d={d} />
            </div>
        </div>
    );
}
