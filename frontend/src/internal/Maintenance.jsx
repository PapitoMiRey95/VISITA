import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Database, GitCommit, ShieldAlert, Wrench, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { formatDateTime } from "../lib/date";

const Pill = ({ ok, children }) => (
    <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-bold ${ok ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{children}</span>
);

function Section({ icon: Icon, title, children, testid }) {
    return (
        <section className="bg-white border border-slate-200 rounded-sm p-4" data-testid={testid}>
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2 mb-3"><Icon className="w-4 h-4 text-visita-green" /> {title}</h2>
            {children}
        </section>
    );
}

// Write-capable tool: dry-run is free; apply requires MAINTENANCE_TOKEN + typed confirmation.
function Tool({ title, description, path, body = {}, applyKey = "apply", token, onDone, testid, render }) {
    const [result, setResult] = useState(null);
    const [busy, setBusy] = useState(false);
    const [confirm, setConfirm] = useState("");
    const run = async (apply) => {
        if (!token) { toast.error("Enter the maintenance token first."); return; }
        if (apply && confirm !== "APPLY") { toast.error('Type APPLY to confirm the write operation.'); return; }
        setBusy(true);
        try {
            const r = await api.post(path, { ...body, token, ...(applyKey ? { [applyKey]: apply } : {}) });
            setResult(r.data);
            toast.success(apply ? `${title}: applied` : `${title}: dry-run complete`);
            if (apply) { setConfirm(""); onDone?.(); }
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <div className="border border-slate-200 rounded-sm p-3 space-y-2" data-testid={testid}>
            <div className="font-semibold text-sm">{title}</div>
            <p className="text-xs text-slate-500">{description}</p>
            <div className="flex flex-wrap items-center gap-2">
                {applyKey && <Button size="sm" variant="outline" disabled={busy} onClick={() => run(false)} data-testid={`${testid}-dry-run`}>Dry-run</Button>}
                <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder='Type APPLY to enable' className="h-8 w-44 text-xs" data-testid={`${testid}-confirm`} />
                <Button size="sm" disabled={busy || confirm !== "APPLY"} onClick={() => run(true)} className="bg-amber-600 hover:bg-amber-700 text-white" data-testid={`${testid}-apply`}>Apply (audited)</Button>
            </div>
            {result && <div className="text-xs bg-slate-50 border rounded-sm p-2" data-testid={`${testid}-result`}>{render ? render(result) : <pre className="whitespace-pre-wrap">{JSON.stringify(result, null, 1)}</pre>}</div>}
        </div>
    );
}

const CatalogTable = ({ results }) => (
    <table className="w-full text-xs"><thead><tr className="text-left text-slate-500"><th>Catalog</th><th>SOURCE</th><th>EXISTS</th><th>MISSING</th><th>INSERTED</th><th>FAILED</th></tr></thead>
        <tbody>{Object.entries(results || {}).map(([k, v]) => <tr key={k}><td className="font-semibold">{k}</td><td>{v.SOURCE}</td><td>{v.EXISTS}</td><td>{v.MISSING}</td><td>{v.INSERTED}</td><td>{v.FAILED}</td></tr>)}</tbody></table>
);

export default function Maintenance() {
    const [token, setToken] = useState("");
    const q = useQuery({ queryKey: ["maintenance-status"], queryFn: async () => (await api.get("/internal/maintenance/status")).data, refetchInterval: 30000 });
    const d = q.data;
    return (
        <div className="p-4 sm:p-6 space-y-4 max-w-5xl" data-testid="maintenance-page">
            <div className="flex items-center justify-between">
                <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2"><Wrench className="w-5 h-5 text-visita-green" /> Internal Maintenance</h1>
                <Button size="sm" variant="outline" onClick={() => q.refetch()} data-testid="maintenance-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1" /> Refresh</Button>
            </div>
            {q.isLoading && <div className="text-sm text-slate-400">Loading diagnostics…</div>}
            {q.error && <div className="text-sm text-red-700" data-testid="maintenance-error">{formatErr(q.error)}</div>}
            {d && (
                <>
                    <div className="grid md:grid-cols-2 gap-4">
                        <Section icon={Activity} title="Health / readiness" testid="maint-health">
                            <div className="flex flex-wrap gap-2 mb-2">
                                <Pill ok={d.health.ready}>{d.health.ready ? "READY" : "NOT READY"}</Pill>
                                <Pill ok={d.health.bootstrap === "complete"}>bootstrap: {d.health.bootstrap}</Pill>
                                <span className="text-xs text-slate-500">attempts {d.health.attempts}</span>
                            </div>
                            <div className="flex flex-wrap gap-1">{Object.entries(d.health.steps || {}).map(([k, v]) => <Pill key={k} ok={v === "ok"}>{k}: {v}</Pill>)}</div>
                        </Section>
                        <Section icon={GitCommit} title="Release / build" testid="maint-release">
                            <dl className="text-xs grid grid-cols-[120px_1fr] gap-y-1">
                                <dt className="text-slate-500">Environment</dt><dd className="font-semibold uppercase" data-testid="maint-env">{d.release.environment}</dd>
                                <dt className="text-slate-500">Commit</dt><dd className="font-mono">{d.release.commit || "n/a"}</dd>
                                <dt className="text-slate-500">Process started</dt><dd>{formatDateTime(d.release.started_at)}</dd>
                                <dt className="text-slate-500">Database</dt><dd className="font-mono">{d.release.db_name}</dd>
                                <dt className="text-slate-500">Python</dt><dd>{d.release.python}</dd>
                            </dl>
                        </Section>
                        <Section icon={ShieldAlert} title="Safety flags" testid="maint-flags">
                            <div className="flex flex-wrap gap-1">
                                <Pill ok={!d.flags.ALLOW_DEMO_SEEDING}>ALLOW_DEMO_SEEDING: {String(d.flags.ALLOW_DEMO_SEEDING)}</Pill>
                                <Pill ok={!d.flags.ALLOW_DATA_MIGRATIONS}>ALLOW_DATA_MIGRATIONS: {String(d.flags.ALLOW_DATA_MIGRATIONS)}</Pill>
                                <Pill ok={d.flags.MAINTENANCE_TOKEN_configured}>MAINTENANCE_TOKEN: {d.flags.MAINTENANCE_TOKEN_configured ? "configured" : "missing"}</Pill>
                                <Pill ok>PORTAL_AUTO_CONFIRM: {String(d.flags.PORTAL_AUTO_CONFIRM)}</Pill>
                                <Pill ok={d.flags.ENCOUNTER_PILOT_USERS.length > 0}>Encounter pilot: {d.flags.ENCOUNTER_PILOT_USERS.join(", ") || "unrestricted"}</Pill>
                            </div>
                        </Section>
                        <Section icon={Database} title="Reference catalogs & indexes" testid="maint-catalogs">
                            <div className="flex flex-wrap gap-1 mb-2">{Object.entries(d.catalogs).map(([k, v]) => <Pill key={k} ok={v > 0 || k === "audit_logs"}>{k}: {v}</Pill>)}</div>
                            <div className="flex flex-wrap gap-1">{d.audit_indexes.map((i) => <Pill key={i.name} ok={i.status === "EXISTS"}>{i.name}: {i.status}</Pill>)}</div>
                            <div className="text-xs text-slate-500 mt-2">Synthetic test patients: {d.synthetic_patients}</div>
                        </Section>
                    </div>

                    <Section icon={Wrench} title="Maintenance tools (token-gated, audited)" testid="maint-tools">
                        <div className="mb-3">
                            <label className="text-xs text-slate-500">MAINTENANCE_TOKEN (kept in memory only, never stored)</label>
                            <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Maintenance token" className="max-w-md" data-testid="maint-token" />
                        </div>
                        <div className="grid md:grid-cols-2 gap-3">
                            <Tool title="Reference catalog import" testid="tool-catalog-import" token={token} onDone={q.refetch}
                                description="Insert-missing-only import of soap_helpers / diagnosis_catalog / service_catalog from the approved packages. Never overwrites or deletes."
                                path="/internal/admin/maintenance/catalog-import" render={(r) => <><div className="font-semibold mb-1">{r.mode}</div><CatalogTable results={r.results} /></>} />
                            <Tool title="audit_logs performance indexes" testid="tool-audit-indexes" token={token} onDone={q.refetch}
                                description="Builds only the 6 approved, missing audit_logs indexes. Non-critical; never drops or alters existing indexes."
                                path="/internal/admin/maintenance/audit-indexes" render={(r) => <ul>{r.results.map((x) => <li key={x.name}>{x.name}: <b>{x.status}</b>{x.error ? ` — ${x.error}` : ""}</li>)}</ul>} />
                            <Tool title="Synthetic test patients" testid="tool-synthetic" token={token} onDone={q.refetch} applyKey={null}
                                description="Create-if-missing the two approved synthetic patients (TEST-F-001, TEST-M-001). Directory-only; all external side effects blocked."
                                path="/internal/admin/synthetic-test-patients" render={(r) => <ul>{r.patients.map((p) => <li key={p.id}>{p.visita_patient_id}: <b>{p.created ? "CREATED" : "EXISTS"}</b></li>)}</ul>} />
                        </div>
                    </Section>

                    <Section icon={Activity} title="Recent maintenance audit" testid="maint-audit">
                        {d.recent_maintenance_audit.length === 0 && <div className="text-xs text-slate-400">No maintenance operations recorded.</div>}
                        <ul className="text-xs space-y-1">{d.recent_maintenance_audit.map((a, i) => (
                            <li key={`${a.created_at}-${i}`} className="flex flex-wrap gap-2"><span className="text-slate-500 w-36">{formatDateTime(a.created_at)}</span><b>{a.action}</b><span className="text-slate-600">{a.actor?.name || a.actor}</span><span className="text-slate-500">{a.meta?.mode || ""}</span></li>
                        ))}</ul>
                    </Section>
                </>
            )}
        </div>
    );
}
