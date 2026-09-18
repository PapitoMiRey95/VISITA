import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, KeyRound, ChevronLeft } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function ForgotPassword() {
    const nav = useNavigate();
    const [step, setStep] = useState(1);
    const [identifier, setIdentifier] = useState("");
    const [code, setCode] = useState("");
    const [pw, setPw] = useState("");
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState(false);

    const request = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const { data } = await api.post("/auth/forgot-password", { identifier: identifier.trim() });
            toast.success(data.message || "If an account matches, a code has been sent.");
            setStep(2);
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const reset = async (e) => {
        e.preventDefault();
        if (pw.length < 8) return toast.error("New password must be at least 8 characters.");
        if (pw !== confirm) return toast.error("Passwords do not match.");
        setBusy(true);
        try {
            await api.post("/auth/reset-password", { identifier: identifier.trim(), code: code.trim(), new_password: pw });
            toast.success("Password reset. Please sign in.");
            nav("/signin", { replace: true });
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    return (
        <div className="min-h-screen bg-[#0a1524] font-plex flex items-center justify-center px-4">
            <div className="w-full max-w-sm">
                <button onClick={() => (step === 2 ? setStep(1) : nav("/signin"))} data-testid="fp-back"
                    className="flex items-center gap-1 text-slate-400 hover:text-slate-200 text-sm mb-3">
                    <ChevronLeft className="w-4 h-4" /> Back
                </button>

                <form onSubmit={step === 1 ? request : reset}
                    className="rounded-md border border-white/10 bg-[#0b1524]/90 p-7 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8)]">
                    <div className="flex items-center gap-2 mb-4">
                        <div className="w-8 h-8 rounded-sm bg-cyan-500/15 border border-cyan-400/30 flex items-center justify-center">
                            <KeyRound className="w-4 h-4 text-cyan-300" />
                        </div>
                        <div>
                            <h2 className="text-lg font-bold text-slate-100 leading-tight">Reset password</h2>
                            <p className="text-xs text-slate-400">{step === 1 ? "We'll email you a verification code" : "Enter the code from your email"}</p>
                        </div>
                    </div>

                    {step === 1 && (
                        <>
                            <Label className="text-[11px] uppercase tracking-widest text-slate-400">Email or Username</Label>
                            <Input data-testid="fp-identifier" required value={identifier} onChange={(e) => setIdentifier(e.target.value)}
                                className="mt-1 mb-5 bg-[#0f1e30] border-white/10 text-slate-100 focus-visible:ring-cyan-400/60" placeholder="you@example.com or USERNAME" />
                            <Button data-testid="fp-request" type="submit" disabled={busy} className="w-full bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold">
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Send code"}
                            </Button>
                        </>
                    )}

                    {step === 2 && (
                        <>
                            <Label className="text-[11px] uppercase tracking-widest text-slate-400">Verification code</Label>
                            <Input data-testid="fp-code" required value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric"
                                className="mt-1 mb-4 bg-[#0f1e30] border-white/10 text-slate-100 tracking-widest focus-visible:ring-cyan-400/60" placeholder="6-digit code" />
                            <Label className="text-[11px] uppercase tracking-widest text-slate-400">New password</Label>
                            <Input data-testid="fp-new" type="password" required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)}
                                className="mt-1 mb-4 bg-[#0f1e30] border-white/10 text-slate-100 focus-visible:ring-cyan-400/60" placeholder="At least 8 characters" />
                            <Label className="text-[11px] uppercase tracking-widest text-slate-400">Confirm new password</Label>
                            <Input data-testid="fp-confirm" type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)}
                                className="mt-1 mb-5 bg-[#0f1e30] border-white/10 text-slate-100 focus-visible:ring-cyan-400/60" />
                            <Button data-testid="fp-submit" type="submit" disabled={busy} className="w-full bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold">
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Reset password"}
                            </Button>
                            <button type="button" onClick={request} disabled={busy} className="w-full mt-3 text-xs text-slate-400 hover:text-slate-200">Resend code</button>
                        </>
                    )}
                </form>
            </div>
        </div>
    );
}
