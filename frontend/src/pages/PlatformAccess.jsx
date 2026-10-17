import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Loader2, Eye, EyeOff, ChevronLeft, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Logo } from "../components/Logo";

export default function PlatformAccess() {
    const { platformLogin } = useAuth();
    const nav = useNavigate();
    const [identifier, setIdentifier] = useState("");
    const [password, setPassword] = useState("");
    const [show, setShow] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true); setError("");
        try {
            const u = await platformLogin(identifier.trim(), password);
            nav(u.must_change_password ? "/change-password" : "/developer", { replace: true });
        } catch (err) {
            setError(err?.response?.status === 401 ? "Invalid credentials." : formatErr(err));
        } finally { setBusy(false); }
    };

    return (
        <div className="min-h-screen bg-[#0b0e12] text-slate-100 flex flex-col" data-testid="platform-access-page">
            <div className="p-4">
                <Link to="/" className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200" data-testid="platform-access-back"><ChevronLeft className="w-3.5 h-3.5" /> VIen home</Link>
            </div>
            <div className="flex-1 flex items-center justify-center px-4">
                <form onSubmit={submit} className="w-full max-w-sm rounded-xl border border-white/10 bg-[#11151b] p-6 space-y-4 shadow-[0_30px_80px_-20px_rgba(0,0,0,.8)]">
                    <div className="flex items-center gap-3">
                        <Logo iconClass="h-9 w-9" showText={false} />
                        <div>
                            <div className="font-bold tracking-tight">VIen Platform Access</div>
                            <div className="text-[11px] uppercase tracking-widest text-slate-400">Installation operator sign-in</div>
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="pa-id" className="text-slate-300">Operator email or username</Label>
                        <Input id="pa-id" autoComplete="username" value={identifier} onChange={(e) => setIdentifier(e.target.value)} required data-testid="platform-access-identifier" className="bg-[#0b0e12] border-white/15 text-slate-100" />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="pa-pw" className="text-slate-300">Password</Label>
                        <div className="relative">
                            <Input id="pa-pw" type={show ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required data-testid="platform-access-password" className="bg-[#0b0e12] border-white/15 text-slate-100 pr-10" />
                            <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200" aria-label="Toggle password" data-testid="platform-access-toggle-password">{show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}</button>
                        </div>
                    </div>
                    {error && <p className="text-sm text-red-400" role="alert" data-testid="platform-access-error">{error}</p>}
                    <Button type="submit" disabled={busy} className="w-full bg-[#17c3e6] hover:bg-[#12a9c8] text-[#06202a] font-bold tracking-wide" data-testid="platform-access-submit">
                        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4 mr-1" />} Sign in
                    </Button>
                    <p className="text-[11px] leading-relaxed text-slate-500">Restricted to authorized VIen platform operators. Clinic, pharmacy and patient accounts use the regular sign-in. Access attempts are logged.</p>
                </form>
            </div>
        </div>
    );
}
