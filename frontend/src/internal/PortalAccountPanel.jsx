import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { KeyRound, Mail, ShieldAlert, ShieldCheck, Ban, RotateCcw, Copy, RefreshCw, UserCog, Clock } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

function StatusBadge({ status }) {
    const map = {
        "Active": "bg-emerald-100 text-emerald-700",
        "Disabled": "bg-red-100 text-red-700",
        "Pending activation": "bg-amber-100 text-amber-800",
        "Must change password": "bg-sky-100 text-sky-800",
    };
    return <span data-testid="portal-account-status" className={`px-2 py-0.5 rounded text-[11px] font-bold ${map[status] || "bg-slate-100 text-slate-600"}`}>{status}</span>;
}

function Line({ label, children, testid }) {
    return (
        <div className="flex justify-between gap-4 py-1.5 border-b border-slate-100">
            <span className="text-slate-400 text-xs uppercase tracking-wide whitespace-nowrap">{label}</span>
            <span data-testid={testid} className="text-slate-800 text-right text-sm font-medium break-all">{children ?? "—"}</span>
        </div>
    );
}

export default function PortalAccountPanel({ patientId }) {
    const [acct, setAcct] = useState(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState("");
    const [temp, setTemp] = useState(null);
    const [emailMode, setEmailMode] = useState(false);
    const [newEmail, setNewEmail] = useState("");

    const load = useCallback(async () => {
        setLoading(true); setTemp(null); setEmailMode(false);
        try {
            const { data } = await api.get(`/internal/patients/${patientId}/portal-account`);
            setAcct(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, [patientId]);

    useEffect(() => { load(); }, [load]);

    const act = async (key, fn, successMsg) => {
        setBusy(key);
        try { await fn(); if (successMsg) toast.success(successMsg); await load(); }
        catch (e) { toast.error(formatErr(e)); setBusy(""); }
    };

    const sendReset = () => act("reset", async () => {
        const { data } = await api.post(`/internal/patients/${patientId}/portal-account/send-reset`);
        toast.success(`Reset code sent to ${data.sent_to}.`);
    });
    const resendVerification = () => act("verify", async () => {
        const { data } = await api.post(`/internal/patients/${patientId}/portal-account/resend-verification`);
        toast.success(`Verification link re-sent to ${data.sent_to}.`);
    });
    const forceChange = () => act("force", async () => {
        await api.post(`/internal/patients/${patientId}/portal-account/force-password-change`);
    }, "Patient will be required to change password at next login.");
    const disable = () => act("disable", async () => {
        await api.post(`/internal/patients/${patientId}/portal-account/disable`);
    }, "Portal access disabled. Patient record and PIN are unchanged.");
    const enable = () => act("enable", async () => {
        await api.post(`/internal/patients/${patientId}/portal-account/enable`);
    }, "Portal access re-enabled.");

    const genTemp = async () => {
        setBusy("temp");
        try {
            const { data } = await api.post(`/internal/patients/${patientId}/portal-account/temp-password`);
            setTemp(data);
            await load();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(""); }
    };

    const saveEmail = async () => {
        const e = newEmail.trim().toLowerCase();
        if (!e || !e.includes("@")) { toast.error("Enter a valid email."); return; }
        setBusy("email");
        try {
            await api.post(`/internal/patients/${patientId}/portal-account/email`, { new_email: e });
            toast.success("Login email updated. The patient should verify it from their account.");
            setEmailMode(false); setNewEmail("");
            await load();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(""); }
    };

    if (loading) return <div className="mt-6 pt-4 border-t border-slate-200 text-sm text-slate-400" data-testid="portal-account-loading">Loading portal account…</div>;
    if (!acct) return null;

    return (
        <div className="mt-6 pt-4 border-t border-slate-200" data-testid="portal-account-panel">
            <div className="flex items-center gap-2 mb-3">
                <UserCog className="w-4 h-4 text-visita-green" />
                <h3 className="font-bold text-slate-900 text-sm">Portal Account</h3>
                {acct.has_account && <StatusBadge status={acct.status} />}
            </div>

            {!acct.has_account ? (
                <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-sm px-3 py-4" data-testid="portal-account-none">
                    This patient does not have a portal login account.
                </div>
            ) : (
                <>
                    <div className="max-w-xl">
                        <Line label="Login Email" testid="pa-email">{acct.login_email}</Line>
                        <Line label="Email Verified" testid="pa-verified">
                            {acct.email_verified
                                ? <span className="text-emerald-700 inline-flex items-center gap-1"><ShieldCheck className="w-3.5 h-3.5" /> Verified</span>
                                : <span className="text-amber-700 inline-flex items-center gap-1"><ShieldAlert className="w-3.5 h-3.5" /> Not verified</span>}
                        </Line>
                        <Line label="Access" testid="pa-access">{acct.disabled ? <span className="text-red-600 font-semibold">Disabled</span> : "Enabled"}</Line>
                        <Line label="Must Change Password" testid="pa-mustchange">{acct.must_change_password ? "Yes" : "No"}</Line>
                        {acct.pending_activation && <Line label="Activation" testid="pa-activation">Pending (not yet set password)</Line>}
                        <Line label="Last Login" testid="pa-lastlogin">{acct.last_login_at ? formatDate(acct.last_login_at) : "Never"}</Line>
                        {acct.temp_password_expires_at && (
                            <Line label="Temp Password Expires" testid="pa-tempexp">
                                <span className="inline-flex items-center gap-1"><Clock className="w-3.5 h-3.5 text-amber-500" />{formatDate(acct.temp_password_expires_at)}</span>
                            </Line>
                        )}
                    </div>

                    {temp && (
                        <div className="mt-3 rounded-md border border-sky-300 bg-sky-50 p-3 max-w-xl" data-testid="pa-temp-box">
                            <div className="text-xs font-bold text-sky-900 uppercase tracking-wide mb-1">One-time temporary password</div>
                            <div className="flex items-center gap-2">
                                <code data-testid="pa-temp-value" className="text-base font-mono font-bold text-slate-900 bg-white border border-sky-200 rounded px-2 py-1 flex-1">{temp.temp_password}</code>
                                <Button size="sm" variant="outline" data-testid="pa-temp-copy"
                                    onClick={() => { navigator.clipboard?.writeText(temp.temp_password); toast.success("Copied."); }}>
                                    <Copy className="w-3.5 h-3.5 mr-1" /> Copy
                                </Button>
                            </div>
                            <p className="text-[11px] text-slate-600 mt-2">Share securely. Expires {formatDate(temp.expires_at)}. The patient must change it at first login. It is shown once and never stored in plain text.</p>
                        </div>
                    )}

                    {emailMode ? (
                        <div className="mt-3 max-w-xl flex items-end gap-2" data-testid="pa-email-form">
                            <div className="flex-1">
                                <Label className="text-xs">Correct login email</Label>
                                <Input type="email" data-testid="pa-email-input" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} placeholder="name@example.com" />
                            </div>
                            <Button size="sm" disabled={busy === "email"} data-testid="pa-email-save" onClick={saveEmail} className="bg-visita-green hover:bg-visita-greenDark text-white">Save</Button>
                            <Button size="sm" variant="outline" onClick={() => { setEmailMode(false); setNewEmail(""); }}>Cancel</Button>
                        </div>
                    ) : null}

                    <div className="mt-4 flex flex-wrap gap-2">
                        <Button size="sm" variant="outline" disabled={!!busy} data-testid="pa-send-reset" onClick={sendReset}>
                            <KeyRound className="w-3.5 h-3.5 mr-1" /> Send password reset
                        </Button>
                        {acct.pending_activation && (
                            <Button size="sm" variant="outline" disabled={!!busy} data-testid="pa-resend-verification" onClick={resendVerification}>
                                <Mail className="w-3.5 h-3.5 mr-1" /> Re-send verification
                            </Button>
                        )}
                        <Button size="sm" variant="outline" disabled={!!busy} data-testid="pa-temp-password" onClick={genTemp}>
                            <RefreshCw className="w-3.5 h-3.5 mr-1" /> Generate temp password
                        </Button>
                        <Button size="sm" variant="outline" disabled={!!busy || acct.must_change_password} data-testid="pa-force-change" onClick={forceChange}>
                            <ShieldAlert className="w-3.5 h-3.5 mr-1" /> Force password change
                        </Button>
                        <Button size="sm" variant="outline" disabled={!!busy} data-testid="pa-change-email" onClick={() => { setEmailMode(true); setNewEmail(acct.login_email || ""); }}>
                            <Mail className="w-3.5 h-3.5 mr-1" /> Change / correct email
                        </Button>
                        {acct.disabled ? (
                            <Button size="sm" disabled={!!busy} data-testid="pa-enable" onClick={enable} className="bg-visita-green hover:bg-visita-greenDark text-white">
                                <RotateCcw className="w-3.5 h-3.5 mr-1" /> Re-enable access
                            </Button>
                        ) : (
                            <Button size="sm" variant="outline" disabled={!!busy} data-testid="pa-disable" onClick={disable} className="border-red-200 text-red-600 hover:bg-red-50">
                                <Ban className="w-3.5 h-3.5 mr-1" /> Disable access
                            </Button>
                        )}
                    </div>
                    <p className="text-[11px] text-slate-400 mt-2">Disabling portal access only blocks login. The patient record, VISITA PIN and all history are preserved. Every action is audited.</p>
                </>
            )}
        </div>
    );
}
