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
