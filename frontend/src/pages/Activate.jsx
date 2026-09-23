import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, ShieldCheck } from "lucide-react";
import { api, formatErr, setToken } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function Activate() {
    const nav = useNavigate();
    const [params] = useSearchParams();
    const { refreshMe } = useAuth();
    const uid = params.get("uid") || "";
    const token = params.get("token") || "";

    const [state, setState] = useState("checking"); // checking | valid | invalid
    const [info, setInfo] = useState(null);
    const [pw, setPw] = useState("");
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        (async () => {
            if (!uid || !token) { setState("invalid"); return; }
            try {
                const { data } = await api.post("/auth/activate/validate", { uid, token });
                setInfo(data); setState("valid");
            } catch { setState("invalid"); }
        })();
    }, [uid, token]);

    const submit = async (e) => {
        e.preventDefault();
        if (pw.length < 8) return toast.error("Password must be at least 8 characters.");
        if (pw !== confirm) return toast.error("Passwords do not match.");
        setBusy(true);
        try {
            const { data } = await api.post("/auth/activate", { uid, token, new_password: pw });
            setToken(data.token);
            await refreshMe();
            toast.success("Portal activated. Welcome!");
            nav("/portal", { replace: true });
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    return (
        <div className="min-h-screen bg-[#0a1524] font-plex flex items-center justify-center px-4">
            <div className="w-full max-w-sm">
                <div className="rounded-md border border-white/10 bg-[#0b1524]/90 p-7 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8)]">
                    <div className="flex items-center gap-2 mb-4">
                        <div className="w-8 h-8 rounded-sm bg-cyan-500/15 border border-cyan-400/30 flex items-center justify-center">
                            <ShieldCheck className="w-4 h-4 text-cyan-300" />
                        </div>
                        <div>
                            <h2 className="text-lg font-bold text-slate-100 leading-tight">Activate your portal</h2>
                            <p className="text-xs text-slate-400">Set a password to access your patient portal</p>
                        </div>
                    </div>

                    {state === "checking" && (
                        <div className="flex items-center gap-2 text-slate-300 text-sm py-6" data-testid="activate-checking">
                            <Loader2 className="w-4 h-4 animate-spin" /> Verifying your activation link…
                        </div>
                    )}

                    {state === "invalid" && (
                        <div className="py-4" data-testid="activate-invalid">
                            <p className="text-sm text-slate-300 mb-4">
                                This activation link is invalid or has expired. Please contact the clinic to request a new one.
                            </p>
                            <Button data-testid="activate-signin" onClick={() => nav("/signin")}
                                className="w-full bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold">Go to Sign in</Button>
                        </div>
                    )}

                    {state === "valid" && (
                        <form onSubmit={submit} data-testid="activate-form">
                            {info?.email && <p className="text-xs text-slate-400 mb-4">Activating <span className="text-slate-200 font-semibold">{info.email}</span></p>}
                            <Label className="text-[11px] uppercase tracking-widest text-slate-400">New password</Label>
                            <Input data-testid="activate-pw" type="password" required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)}
                                className="mt-1 mb-4 bg-[#0f1e30] border-white/10 text-slate-100 focus-visible:ring-cyan-400/60" placeholder="At least 8 characters" />
                            <Label className="text-[11px] uppercase tracking-widest text-slate-400">Confirm password</Label>
                            <Input data-testid="activate-confirm" type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)}
                                className="mt-1 mb-5 bg-[#0f1e30] border-white/10 text-slate-100 focus-visible:ring-cyan-400/60" />
                            <Button data-testid="activate-submit" type="submit" disabled={busy}
                                className="w-full bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold">
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Activate & Sign in"}
                            </Button>
                        </form>
                    )}
                </div>
            </div>
        </div>
    );
}
