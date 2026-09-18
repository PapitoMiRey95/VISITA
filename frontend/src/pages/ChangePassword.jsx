import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, KeyRound } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function ChangePassword() {
    const { user, refreshMe, logout } = useAuth();
    const nav = useNavigate();
    const [cur, setCur] = useState("");
    const [pw, setPw] = useState("");
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState(false);

    if (user === null) return <div className="min-h-screen flex items-center justify-center bg-[#0a1524] text-cyan-300 font-plex">Loading…</div>;
    if (user === false) { nav("/login", { replace: true }); return null; }

    const forced = user.must_change_password;

    const submit = async (e) => {
        e.preventDefault();
        if (pw.length < 8) return toast.error("New password must be at least 8 characters.");
        if (pw !== confirm) return toast.error("New passwords do not match.");
        setBusy(true);
        try {
            await api.post("/auth/change-password", { current_password: cur, new_password: pw });
            await refreshMe();
            toast.success("Password updated.");
            nav(user.role === "patient" ? "/portal" : "/internal", { replace: true });
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#0a1524] font-plex flex items-center justify-center px-4">
            <form onSubmit={submit} className="w-full max-w-sm rounded-md border border-white/10 bg-[#0b1524]/90 p-7 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8)]">
                <div className="flex items-center gap-2 mb-4">
                    <div className="w-8 h-8 rounded-sm bg-cyan-500/15 border border-cyan-400/30 flex items-center justify-center">
                        <KeyRound className="w-4 h-4 text-cyan-300" />
                    </div>
                    <div>
                        <h2 className="text-lg font-bold text-slate-100 leading-tight">
                            {forced ? "Set a new password" : "Change password"}
                        </h2>
                        <p className="text-xs text-slate-400">{user.name}</p>
                    </div>
                </div>

                {forced && (
                    <div className="mb-4 text-xs text-amber-300/90 bg-amber-500/10 border border-amber-400/20 rounded-sm p-2">
                        For security, you must change your temporary password before continuing.
                    </div>
                )}

                <Label className="text-[11px] uppercase tracking-widest text-slate-400">Current password</Label>
                <Input data-testid="cp-current" type="password" required value={cur} onChange={(e) => setCur(e.target.value)}
                    className="mt-1 mb-4 bg-[#0f1e30] border-white/10 text-slate-100 focus-visible:ring-cyan-400/60" />

                <Label className="text-[11px] uppercase tracking-widest text-slate-400">New password</Label>
                <Input data-testid="cp-new" type="password" required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)}
                    className="mt-1 mb-4 bg-[#0f1e30] border-white/10 text-slate-100 focus-visible:ring-cyan-400/60" placeholder="At least 8 characters" />

                <Label className="text-[11px] uppercase tracking-widest text-slate-400">Confirm new password</Label>
                <Input data-testid="cp-confirm" type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)}
                    className="mt-1 mb-5 bg-[#0f1e30] border-white/10 text-slate-100 focus-visible:ring-cyan-400/60" />

                <Button data-testid="cp-submit" type="submit" disabled={busy}
                    className="w-full bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold">
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Update password"}
                </Button>

                <button type="button" onClick={() => { logout(); nav("/login"); }}
                    className="w-full mt-3 text-xs text-slate-500 hover:text-slate-300">Sign out</button>
            </form>
        </div>
    );
}
