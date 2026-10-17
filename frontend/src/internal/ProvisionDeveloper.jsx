import { useState } from "react";
import { Navigate } from "react-router-dom";
import { ShieldCheck, Copy, Check, AlertTriangle } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "../components/ui/alert-dialog";

const OWNER_EMAIL = "kevinrodriguez9528@gmail.com";
const PREFILL = { email: "info.oakmontinc@gmail.com", username: "VIENDEV", name: "Kevin Rodriguez – Developer" };
const ENDPOINT = "/internal/admin/maintenance/provision-developer-ops";

function Field({ label, value, testid }) {
    return (
        <div className="grid grid-cols-[170px_1fr] items-center gap-3 text-sm">
            <span className="text-slate-500">{label}</span>
            <span className="font-semibold text-slate-900" data-testid={testid}>{value}</span>
        </div>
    );
}

function SuccessPanel({ result }) {
    const [copied, setCopied] = useState(false);
    const copy = async () => { await navigator.clipboard.writeText(result.temp_password); setCopied(true); setTimeout(() => setCopied(false), 1500); };
    return (
        <div className="rounded-md border border-emerald-300 bg-emerald-50 p-4 space-y-3" data-testid="provision-success">
            <div className="flex items-center gap-2 font-bold text-emerald-800"><ShieldCheck className="w-4 h-4" /> Developer account created successfully.</div>
            <Field label="Login" value="https://visitaemr.com/signin?internal=1" testid="provision-login-url" />
            <Field label="Username" value={result.created.username} testid="provision-created-username" />
            <div className="grid grid-cols-[170px_1fr] items-center gap-3 text-sm">
                <span className="text-slate-500">Temporary password</span>
                <div className="flex items-center gap-2">
                    <code className="rounded bg-white border border-emerald-200 px-2 py-1 font-mono text-sm text-slate-900" data-testid="provision-temp-password">{result.temp_password}</code>
                    <Button size="sm" variant="outline" onClick={copy} data-testid="provision-copy-password">{copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />} {copied ? "Copied" : "Copy"}</Button>
                </div>
            </div>
            <p className="text-xs text-emerald-900 font-medium">Shown once. Change your password immediately on first login. Closing or refreshing this page removes it permanently.</p>
            <p className="text-xs text-slate-600">The placeholder account <span className="font-mono">devops@visita.demo</span> was NOT deleted.</p>
        </div>
    );
}

const TEST_PATIENT = { patient_id: "5f0584ab-7a13-4b75-a7ac-7c8e4553cf23", pin: "8536", portal_email: "info.oakmontinc@gmail.com", name: "Steph DE RODRIGUEZ" };

function VoidTestPatient({ token, setToken }) {
    const [out, setOut] = useState(null);
    const [busy, setBusy] = useState(false);
    const [confirm, setConfirm] = useState(false);
    const call = async (apply) => {
        setBusy(true);
        try {
            const { data } = await api.post("/internal/admin/maintenance/void-test-patient", { ...TEST_PATIENT, token, confirm: apply });
            setOut(data);
        } catch (e) { setOut({ mode: "error", msg: formatErr(e) }); } finally { setBusy(false); setConfirm(false); }
    };
    const deps = out?.dependencies || out?.would_archive?.dependencies || out?.archived?.dependencies;
    return (
        <div className="space-y-3 rounded-md border border-amber-200 bg-amber-50/60 p-4" data-testid="void-test-patient">
            <div>
                <div className="text-xs font-bold text-amber-900 uppercase tracking-wide">Step 1 — Archive confirmed TEST patient</div>
                <p className="text-[11px] text-amber-900/80 mt-0.5">{TEST_PATIENT.name} · PIN {TEST_PATIENT.pin} · {TEST_PATIENT.portal_email}. Soft-voids the record (no hard delete), detaches its login and releases the email. Refuses if any dependency exists.</p>
            </div>
            <div className="grid grid-cols-[170px_1fr] items-center gap-3 text-sm">
                <label className="text-slate-500" htmlFor="void-token">OPS_PROVISION_TOKEN</label>
                <Input id="void-token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} data-testid="void-token-input" />
            </div>
            {out && (
                <div className={`rounded-sm border px-3 py-2 text-xs ${out.mode === "apply" ? "border-emerald-300 bg-emerald-50 text-emerald-900" : out.mode === "dry_run" ? "border-sky-300 bg-sky-50 text-sky-900" : "border-red-300 bg-red-50 text-red-800"}`} data-testid="void-result">
                    <div className="font-bold">{out.mode === "apply" ? "ARCHIVED — email released" : out.mode === "dry_run" ? "DEPENDENCY CHECK PASS — nothing changed" : out.mode === "blocked" ? "BLOCKED — dependencies found" : "ERROR"}</div>
                    {out.msg && <div>{out.msg}</div>}
                    {out.blocking && <div>{Object.entries(out.blocking).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>}
                    {deps && <div className="mt-1 text-[11px] opacity-80">Checked {Object.keys(deps).length} collections — all zero{(out.would_archive?.removable_relationships?.length || out.archived?.removable_relationships?.length) ? ` except this patient's own per-practice relationship record(s) (${(out.would_archive || out.archived).removable_relationships.map((r) => `${r.status} · ${r.id?.slice(0, 8)}`).join(", ")}) which will be removed with it` : ""}{out.mode === "apply" ? ` · released ${out.released_email}` : ""}.</div>}
                </div>
            )}
            <div className="flex gap-2 justify-end">
                <Button type="button" size="sm" variant="outline" disabled={busy || !token || out?.mode === "apply"} onClick={() => call(false)} data-testid="void-dry-run-btn">CHECK DEPENDENCIES</Button>
                <Button type="button" size="sm" disabled={busy || !token || out?.mode !== "dry_run"} onClick={() => setConfirm(true)} className="bg-amber-600 hover:bg-amber-700 text-white" data-testid="void-apply-btn">ARCHIVE TEST PATIENT</Button>
            </div>
            <AlertDialog open={confirm} onOpenChange={setConfirm}>
                <AlertDialogContent data-testid="void-confirm-dialog">
                    <AlertDialogHeader>
                        <AlertDialogTitle>Archive TEST patient PIN {TEST_PATIENT.pin}?</AlertDialogTitle>
                        <AlertDialogDescription>The record is marked VOIDED_TEST (not deleted), its portal login is detached and {TEST_PATIENT.portal_email} is released. PIN {TEST_PATIENT.pin} is never reissued. Audited.</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel data-testid="void-confirm-cancel">Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => call(true)} data-testid="void-confirm-apply">Archive</AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}

export default function ProvisionDeveloper() {
    const { user } = useAuth();
    const [token, setToken] = useState("");
    const [dry, setDry] = useState(null);
    const [result, setResult] = useState(null);
    const [busy, setBusy] = useState(false);
    const [confirm, setConfirm] = useState(false);

    if (!user || user.role !== "admin" || (user.email || "").toLowerCase() !== OWNER_EMAIL) return <Navigate to="/internal" replace />;

    const call = async (apply) => {
        setBusy(true);
        try {
            const { data } = await api.post(ENDPOINT, { ...PREFILL, token, confirm: apply });
            if (apply) { setResult(data); setToken(""); } else setDry({ ok: true, plan: data.would_create });
        } catch (e) {
            const msg = formatErr(e);
            if (apply) setDry({ ok: false, msg }); else setDry({ ok: false, msg });
        } finally { setBusy(false); setConfirm(false); }
    };

    return (
        <div className="max-w-xl space-y-5" data-testid="provision-developer-page">
            <div>
                <h1 className="text-xl font-bold text-slate-900">Production Developer Operator</h1>
                <p className="text-sm text-slate-600">One-time, owner-only provisioning of the installation-level <span className="font-mono">developer_ops</span> account. Not a user-management tool.</p>
            </div>
            {result ? <SuccessPanel result={result} /> : (
                <>
                <VoidTestPatient token={token} setToken={setToken} />
                <form className="space-y-4 rounded-md border border-slate-200 bg-white p-4" onSubmit={(e) => { e.preventDefault(); call(false); }}>
                    <Field label="Email" value={PREFILL.email} testid="provision-email" />
                    <Field label="Username" value={PREFILL.username} testid="provision-username" />
                    <Field label="Display name" value={PREFILL.name} testid="provision-name" />
                    <div className="grid grid-cols-[170px_1fr] items-center gap-3 text-sm">
                        <label className="text-slate-500" htmlFor="ops-token">OPS_PROVISION_TOKEN</label>
                        <Input id="ops-token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} data-testid="provision-token-input" />
                    </div>
                    {dry && (
                        <div className={`flex items-start gap-2 rounded-sm border px-3 py-2 text-sm ${dry.ok ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-red-300 bg-red-50 text-red-800"}`} data-testid="provision-dry-result">
                            {dry.ok ? <ShieldCheck className="w-4 h-4 mt-0.5" /> : <AlertTriangle className="w-4 h-4 mt-0.5" />}
                            <div>
                                <div className="font-bold">{dry.ok ? "PASS" : "BLOCKED"}</div>
                                <div className="text-xs">{dry.ok ? "Email and username available · no real developer_ops exists · endpoint eligible. Nothing was created." : dry.msg}</div>
                            </div>
                        </div>
                    )}
                    <div className="flex gap-2 justify-end">
                        <Button type="submit" variant="outline" disabled={busy || !token} data-testid="provision-dry-run-btn">DRY RUN</Button>
                        <Button type="button" disabled={busy || !token || !dry?.ok} onClick={() => setConfirm(true)} className="bg-visita-ribbon hover:bg-[#162c49] text-white" data-testid="provision-apply-btn">PROVISION DEVELOPER</Button>
                    </div>
                </form>
                </>
            )}
            <AlertDialog open={confirm} onOpenChange={setConfirm}>
                <AlertDialogContent data-testid="provision-confirm-dialog">
                    <AlertDialogHeader>
                        <AlertDialogTitle>Provision developer_ops account?</AlertDialogTitle>
                        <AlertDialogDescription>This creates exactly one developer_ops account ({PREFILL.username}) and can only run once. The temporary password will be shown a single time.</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel data-testid="provision-confirm-cancel">Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => call(true)} data-testid="provision-confirm-apply">Provision</AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
