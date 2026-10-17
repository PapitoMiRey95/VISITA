import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, Search, ShieldAlert, Trash2, Lock, UserX } from "lucide-react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { formatDateTime } from "../lib/date";
import { saveDraft, PublishBar } from "./platformConfig";

const Panel = ({ title, icon: Icon, children, testid, tone = "slate" }) => (
    <section className={`rounded-md p-5 border ${tone === "danger" ? "bg-red-950/30 border-red-900/60" : "bg-slate-900/70 border-slate-800"}`} data-testid={testid}>
        <h2 className="text-sm font-bold text-slate-200 flex items-center gap-2 mb-3"><Icon className={`w-4 h-4 ${tone === "danger" ? "text-red-400" : "text-emerald-400"}`} /> {title}</h2>
        {children}
    </section>
);

const Chip = ({ children, tone = "slate", testid }) => (
    <span data-testid={testid} className={`inline-block text-[10px] font-bold px-1.5 py-0.5 rounded-sm uppercase ${tone === "green" ? "bg-emerald-500/20 text-emerald-300" : tone === "red" ? "bg-red-500/20 text-red-300" : tone === "amber" ? "bg-amber-500/20 text-amber-300" : "bg-slate-700 text-slate-200"}`}>{children}</span>
);

function ModePanel({ status, cfg, onChanged }) {
    const [confirm, setConfirm] = useState("");
    const live = status?.data_mode;
    const draftMode = cfg?.draft?.config?.operations?.data_mode;
    const switchDraft = async () => {
        try { await saveDraft("operations", { data_mode: "LIVE_CLINICAL" }); toast.success("Draft set to LIVE_CLINICAL — publish to apply (one-way)."); setConfirm(""); onChanged(); }
        catch (e) { toast.error(formatErr(e)); }
    };
    return (
        <Panel title="Platform data mode" icon={Lock} testid="dataops-mode">
            <div className="flex items-center gap-3 mb-2">
                <Chip tone={live === "PRELAUNCH_TEST" ? "amber" : "green"} testid="dataops-mode-live">{live || "…"}</Chip>
                <span className="text-xs text-slate-400">live (config v{status?.version ?? 0})</span>
                {draftMode && draftMode !== live && <Chip tone="green" testid="dataops-mode-draft">draft → {draftMode}</Chip>}
            </div>
            <p className="text-xs text-slate-400 mb-3">Test-data tools below work only while the installation is explicitly in <span className="font-mono">PRELAUNCH_TEST</span>. Switching to <span className="font-mono">LIVE_CLINICAL</span> is permanent: every destructive tool fails closed and can never erase clinical records.</p>
            {live === "PRELAUNCH_TEST" && !draftMode && (
                <div className="flex flex-wrap items-center gap-2">
                    <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Type LIVE_CLINICAL" className="h-8 w-52 text-xs bg-slate-950 border-slate-700 text-slate-100" data-testid="dataops-mode-confirm" />
                    <Button size="sm" disabled={confirm !== "LIVE_CLINICAL"} onClick={switchDraft} className="bg-emerald-500 hover:bg-emerald-400 text-slate-900" data-testid="dataops-mode-switch">Prepare one-way switch (draft)</Button>
                </div>
            )}
            {cfg && <div className="mt-3"><PublishBar cfg={cfg} onChanged={onChanged} /></div>}
        </Panel>
    );
}

function Deps({ deps }) {
    const keys = Object.keys(deps || {});
    if (!keys.length) return <div className="text-xs text-slate-400" data-testid="dataops-deps-none">No dependent documents.</div>;
    return <div className="flex flex-wrap gap-1.5" data-testid="dataops-deps">{keys.map((k) => <Chip key={k}>{k}: {deps[k]}</Chip>)}</div>;
}

function ResetPatient({ pid, onDone }) {
    const [reason, setReason] = useState("");
    const [confirm, setConfirm] = useState("");
    const [includeDir, setIncludeDir] = useState(false);
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null);
    const q = useQuery({ queryKey: ["dataops-preview", pid], queryFn: async () => (await api.get(`/developer/data-ops/patient/${pid}/preview`)).data, enabled: !!pid });
    const pv = q.data;
    const ready = reason.trim().length >= 5 && confirm.trim() === "RESET TEST PATIENT";
    const run = async () => {
        if (!window.confirm(`Permanently delete test patient ${pv?.patient?.name} (PIN ${pv?.patient?.pin || "—"}) and ${pv?.total_dependency_docs} dependent documents? This cannot be undone.`)) return;
        setBusy(true);
        try {
            const { data } = await api.post(`/developer/data-ops/patient/${pid}/reset`, { reason: reason.trim(), confirm_text: confirm.trim(), include_directory: includeDir });
            setResult(data); toast.success(`Test patient removed — ${data.total} documents deleted`); onDone();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    if (q.isLoading) return <div className="text-xs text-slate-400">Loading dependency preview…</div>;
    if (q.error) return <div className="text-xs text-red-400">{formatErr(q.error)}</div>;
    if (result) return (
        <div className="rounded-sm border border-emerald-700/60 bg-emerald-500/10 p-3 text-xs text-emerald-200" data-testid="dataops-reset-result">
            <div className="font-bold">Removed. {result.total} documents deleted.</div>
            <div className="mt-1 flex flex-wrap gap-1.5">{Object.entries(result.deleted).map(([k, v]) => <Chip key={k} tone="green">{k}: {v}</Chip>)}</div>
            {result.released_emails?.length > 0 && <div className="mt-1">Released login email(s): <span className="font-mono">{result.released_emails.join(", ")}</span></div>}
        </div>
    );
    return (
        <div className="space-y-3" data-testid="dataops-reset-panel">
            <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1 text-xs text-slate-300">
                <div><span className="text-slate-400">Patient</span> · <span className="font-semibold text-white" data-testid="dataops-pv-name">{pv.patient.name}</span></div>
                <div><span className="text-slate-400">PIN</span> · <span className="font-mono" data-testid="dataops-pv-pin">{pv.patient.pin || "—"}</span></div>
                <div><span className="text-slate-400">ID</span> · <span className="font-mono">{pv.patient.id}</span></div>
                <div><span className="text-slate-400">Created</span> · {formatDateTime(pv.patient.created_at)}</div>
                <div className="sm:col-span-2"><span className="text-slate-400">Logins</span> · {pv.logins.length ? pv.logins.map((l) => <span key={l.id} className="font-mono mr-2">{l.email} <Chip tone={l.active ? "green" : "red"}>{l.role}{l.active ? "" : " · disabled"}</Chip></span>) : "none"}</div>
                <div className="sm:col-span-2"><span className="text-slate-400">Directory</span> · {pv.directory.length ? pv.directory.map((d) => <span key={d.id} className="font-mono mr-2">{d.visita_patient_id || d.id.slice(0, 8)} ({d.patient_status})</span>) : "no directory record"}</div>
            </div>
            <div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">Dependencies ({pv.total_dependency_docs} docs{pv.grants_as_delegate ? ` · ${pv.grants_as_delegate} caregiver grant(s) as delegate` : ""})</div>
                <Deps deps={pv.dependencies} />
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-300">
                <input type="checkbox" checked={includeDir} onChange={(e) => setIncludeDir(e.target.checked)} data-testid="dataops-include-directory" disabled={!pv.directory.length} />
                Also delete the canonical directory record(s) and PIN (otherwise the directory record is kept and unlinked)
            </label>
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required) — e.g. confirmed owner-created test record" className="bg-slate-950 border-slate-700 text-slate-100 text-xs" data-testid="dataops-reset-reason" />
            <div className="flex flex-wrap items-center gap-2">
                <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Type RESET TEST PATIENT" className="h-8 w-60 text-xs bg-slate-950 border-slate-700 text-slate-100" data-testid="dataops-reset-confirm" />
                <Button size="sm" disabled={!ready || busy} onClick={run} className="bg-red-600 hover:bg-red-500 text-white" data-testid="dataops-reset-btn"><Trash2 className="w-3.5 h-3.5 mr-1" /> RESET TEST PATIENT</Button>
            </div>
        </div>
    );
}

function DeleteUser({ uid, onDone }) {
    const [reason, setReason] = useState("");
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null);
    const q = useQuery({ queryKey: ["dataops-user", uid], queryFn: async () => (await api.get(`/developer/data-ops/user/${uid}/preview`)).data, enabled: !!uid });
    const pv = q.data;
    if (q.isLoading) return <div className="text-xs text-slate-400">Loading…</div>;
    if (q.error) return <div className="text-xs text-red-400">{formatErr(q.error)}</div>;
    if (result) return <div className="rounded-sm border border-emerald-700/60 bg-emerald-500/10 p-3 text-xs text-emerald-200" data-testid="dataops-user-result">Deleted. Released <span className="font-mono">{result.released_email}</span>.</div>;
    const run = async () => {
        if (!window.confirm(`Permanently delete login identity ${pv.email}?`)) return;
        setBusy(true);
        try { const { data } = await api.post(`/developer/data-ops/user/${uid}/delete`, { reason: reason.trim(), confirm_text: confirm.trim() }); setResult(data); toast.success("Test user deleted"); onDone(); }
        catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <div className="space-y-3" data-testid="dataops-user-panel">
            <div className="text-xs text-slate-300">
                <span className="font-semibold text-white">{pv.name || "—"}</span> · <span className="font-mono">{pv.email}</span> · <Chip tone={pv.protected ? "red" : "slate"}>{pv.role}</Chip> {pv.username && <span className="font-mono">@{pv.username}</span>}
                {pv.patient_id && <div className="text-amber-300 mt-1">Attached to patient {pv.patient_id} — use RESET TEST PATIENT instead.</div>}
                {pv.protected && <div className="text-red-300 mt-1">Operator identities cannot be deleted here.</div>}
            </div>
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" className="bg-slate-950 border-slate-700 text-slate-100 text-xs" data-testid="dataops-user-reason" />
            <div className="flex flex-wrap items-center gap-2">
                <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Type DELETE TEST USER" className="h-8 w-56 text-xs bg-slate-950 border-slate-700 text-slate-100" data-testid="dataops-user-confirm" />
                <Button size="sm" disabled={busy || pv.protected || !!pv.patient_id || reason.trim().length < 5 || confirm.trim() !== "DELETE TEST USER"} onClick={run} className="bg-red-600 hover:bg-red-500 text-white" data-testid="dataops-user-delete-btn"><UserX className="w-3.5 h-3.5 mr-1" /> DELETE TEST USER</Button>
            </div>
        </div>
    );
}

export function DataOperations({ cfg, onChanged }) {
    const [q, setQ] = useState("");
    const [results, setResults] = useState(null);
    const [sel, setSel] = useState(null);
    const st = useQuery({ queryKey: ["dataops-status"], queryFn: async () => (await api.get("/developer/data-ops/status")).data });
    const live = st.data?.data_mode === "PRELAUNCH_TEST";
    const search = async (e, keepSel = false) => {
        e?.preventDefault();
        try { const { data } = await api.get("/developer/data-ops/search", { params: { q } }); setResults(data.results); if (!keepSel) setSel(null); }
        catch (err) { toast.error(formatErr(err)); }
    };
    const refresh = () => { st.refetch(); onChanged(); };
    return (
        <div className="space-y-5" data-testid="dev-data-ops">
            <ModePanel status={st.data} cfg={cfg} onChanged={refresh} />
            {!live ? (
                <Panel title="Test-data tools disabled" icon={ShieldAlert} testid="dataops-locked">
                    <p className="text-xs text-slate-300">The installation is in <span className="font-mono">LIVE_CLINICAL</span> mode. Search, reset and delete tools are permanently unavailable.</p>
                </Panel>
            ) : (
                <>
                    <Panel title="Find test record" icon={Search} testid="dataops-search">
                        <form onSubmit={search} className="flex gap-2">
                            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, VISITA PIN, email or internal ID" className="h-9 bg-slate-950 border-slate-700 text-slate-100" data-testid="dataops-search-input" />
                            <Button type="submit" size="sm" className="bg-emerald-500 hover:bg-emerald-400 text-slate-900 h-9" data-testid="dataops-search-btn">Search</Button>
                        </form>
                        {results && (
                            <ul className="mt-3 divide-y divide-slate-800" data-testid="dataops-results">
                                {!results.length && <li className="text-xs text-slate-400 py-2">No matches.</li>}
                                {results.map((r) => (
                                    <li key={r.type + r.id} className="py-2 flex items-center justify-between gap-3 text-xs" data-testid="dataops-result-row">
                                        <div className="min-w-0">
                                            <Chip tone={r.type === "patient" ? "amber" : r.type === "user" ? "slate" : "green"}>{r.type}</Chip>
                                            <span className="ml-2 font-semibold text-white">{r.name || "—"}</span>
                                            {r.pin && <span className="ml-2 font-mono text-slate-300">PIN {r.pin}</span>}
                                            {r.email && <span className="ml-2 font-mono text-slate-300">{r.email}</span>}
                                            {r.role && <span className="ml-2 text-slate-400">{r.role}{r.active === false ? " · disabled" : ""}</span>}
                                            {r.type === "patient" && <span className="ml-2 text-slate-400">{r.logins.length} login(s){r.record_status ? ` · ${r.record_status}` : ""}</span>}
                                            <div className="font-mono text-[10px] text-slate-500 truncate">{r.id}</div>
                                        </div>
                                        {r.type === "patient" && <Button size="sm" variant="outline" className="border-red-800 text-red-300 hover:bg-red-950" onClick={() => setSel(r)} data-testid="dataops-pick-patient">Preview / reset</Button>}
                                        {r.type === "user" && <Button size="sm" variant="outline" className="border-slate-600 text-slate-200" disabled={r.protected} onClick={() => setSel(r)} data-testid="dataops-pick-user">Preview / delete</Button>}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </Panel>
                    {sel?.type === "patient" && <Panel title={`Reset test patient — ${sel.name}`} icon={Database} tone="danger" testid="dataops-reset"><ResetPatient key={sel.id} pid={sel.id} onDone={() => search(null, true)} /></Panel>}
                    {sel?.type === "user" && <Panel title={`Delete test user identity — ${sel.email}`} icon={UserX} tone="danger" testid="dataops-delete-user"><DeleteUser key={sel.id} uid={sel.id} onDone={() => search(null, true)} /></Panel>}
                    <Panel title="Purge all test data" icon={ShieldAlert} testid="dataops-purge">
                        <p className="text-xs text-slate-400">Architecture prepared (count preview, typed phrase <span className="font-mono">PURGE ALL TEST DATA</span>, second confirmation, audit) but intentionally <span className="font-bold text-slate-200">not enabled</span> in this release. Use per-record RESET TEST PATIENT.</p>
                    </Panel>
                </>
            )}
        </div>
    );
}
