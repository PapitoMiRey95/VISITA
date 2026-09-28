import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { KeyRound, Copy, Check, Pill, ShieldCheck } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import {
    Dialog, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription,
} from "../components/ui/dialog";

// Admin-only: reset a pharmacy login account's temporary password using the EXISTING
// audited endpoint (POST /api/admin/pharmacy/reset-temp-password). The temp password is
// generated server-side and shown here ONCE — never stored or redisplayed later.
export default function PharmacyAccountsAdmin() {
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [confirmFor, setConfirmFor] = useState(null); // account pending confirmation
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null); // { username, pharmacy_name, temp_password }
    const [copied, setCopied] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/admin/pharmacy-accounts");
            setRows(data);
        } catch (e) {
            if (e?.response?.status === 401) toast.error("Your admin session has expired. Please sign in again.");
            else toast.error(formatErr(e));
        } finally { setLoading(false); }
    }, []);
    useEffect(() => { load(); }, [load]);

    const doReset = async () => {
        if (!confirmFor) return;
        setBusy(true);
        try {
            const { data } = await api.post("/admin/pharmacy/reset-temp-password", { identifier: confirmFor.username });
            setResult(data);
            setConfirmFor(null);
            setCopied(false);
            load();
        } catch (e) {
            if (e?.response?.status === 401) toast.error("Your admin session has expired. Please sign in again.");
            else toast.error(formatErr(e));
        } finally { setBusy(false); }
    };

    const copyPw = async () => {
        try { await navigator.clipboard.writeText(result.temp_password); setCopied(true); toast.success("Copied"); }
        catch { toast.error("Copy failed — select and copy manually."); }
    };

    return (
        <div className="bg-white rounded-lg border border-slate-200" data-testid="pharmacy-accounts-admin">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-100">
                <Pill className="w-4 h-4 text-visita-greenDark" />
                <h2 className="text-sm font-bold text-slate-800">Pharmacy Login Accounts</h2>
                <span className="text-xs text-slate-400">({rows.length})</span>
            </div>
            <table className="w-full text-sm">
                <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                    <tr>
                        <th className="text-left px-3 py-2">Pharmacy</th>
                        <th className="text-left px-3 py-2">Username</th>
                        <th className="text-left px-3 py-2">Status</th>
                        <th className="text-left px-3 py-2">Last reset</th>
                        <th className="text-right px-3 py-2">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {loading && <tr><td colSpan={5} className="px-3 py-5 text-center text-slate-400">Loading…</td></tr>}
                    {!loading && rows.length === 0 && <tr><td colSpan={5} className="px-3 py-5 text-center text-slate-400">No pharmacy accounts.</td></tr>}
                    {!loading && rows.map((a, i) => (
                        <tr key={a.username || i} className="border-t border-slate-100" data-testid="pharmacy-account-row">
                            <td className="px-3 py-2 font-semibold text-slate-800">{a.pharmacy_name || "—"}<div className="text-[10px] uppercase tracking-wide text-slate-400">{a.pharmacy_id}</div></td>
                            <td className="px-3 py-2 text-slate-600">{a.username || <span className="text-slate-400 italic">no username</span>}</td>
                            <td className="px-3 py-2">
                                {a.active === false
                                    ? <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-red-100 text-red-700">Disabled</span>
                                    : a.must_change_password
                                        ? <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-100 text-amber-800">Temp — must change</span>
                                        : <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-700">Active</span>}
                            </td>
                            <td className="px-3 py-2 text-slate-500 text-xs">{a.password_rotated_at ? formatDate(a.password_rotated_at.slice(0, 10)) : "—"}</td>
                            <td className="px-3 py-2 text-right">
                                <Button size="sm" variant="outline" className="h-8" disabled={!a.username}
                                    data-testid={`pharmacy-reset-${a.username || "none"}`} onClick={() => setConfirmFor(a)}>
                                    <KeyRound className="w-4 h-4 mr-1" /> Reset Password
                                </Button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>

            {/* Confirm */}
            <Dialog open={!!confirmFor} onOpenChange={(o) => !o && setConfirmFor(null)}>
                <DialogContent data-testid="pharmacy-reset-confirm">
                    <DialogHeader>
                        <DialogTitle>Reset pharmacy password</DialogTitle>
                        <DialogDescription>
                            Generate a temporary password for <b>{confirmFor?.pharmacy_name || confirmFor?.username}</b>? The pharmacist will be forced to create a new password on next sign-in.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="ghost" onClick={() => setConfirmFor(null)} data-testid="pharmacy-reset-cancel">Cancel</Button>
                        <Button onClick={doReset} disabled={busy} className="bg-visita-green hover:bg-visita-greenDark text-white" data-testid="pharmacy-reset-generate">
                            <KeyRound className="w-4 h-4 mr-1" /> {busy ? "Generating…" : "Generate Temporary Password"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Show once */}
            <Dialog open={!!result} onOpenChange={(o) => !o && setResult(null)}>
                <DialogContent data-testid="pharmacy-reset-result">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2"><ShieldCheck className="w-5 h-5 text-emerald-600" /> Temporary password created</DialogTitle>
                        <DialogDescription>Shown once — copy it now and send it to the pharmacist securely. It won't be displayed again.</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-2">
                        <div className="text-xs text-slate-400 uppercase tracking-wide">Username</div>
                        <div className="font-mono text-sm text-slate-800" data-testid="pharmacy-reset-username">{result?.username}</div>
                        <div className="text-xs text-slate-400 uppercase tracking-wide mt-2">Temporary Password</div>
                        <div className="flex items-center gap-2">
                            <code className="flex-1 bg-slate-100 border border-slate-200 rounded px-3 py-2 font-mono text-base text-slate-900 break-all" data-testid="pharmacy-reset-temp-password">{result?.temp_password}</code>
                            <Button variant="outline" size="sm" onClick={copyPw} data-testid="pharmacy-reset-copy">
                                {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                            </Button>
                        </div>
                        <p className="text-xs text-slate-500 pt-1">The pharmacist must create a new password after signing in.</p>
                    </div>
                    <DialogFooter>
                        <Button onClick={() => setResult(null)} data-testid="pharmacy-reset-done">Done</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
