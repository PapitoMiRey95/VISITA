import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, ShieldPlus } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

const BG = "https://customer-assets-4nw71qhi.emergentagent.net/job_visita-admin/artifacts/ndj1izcs_ChatGPT%20Image%20Sep%2018%2C%202026%2C%2010_35_01%20AM.png";

export default function Login() {
    const { login } = useAuth();
    const nav = useNavigate();
    const [identifier, setIdentifier] = useState("");
    const [password, setPassword] = useState("");
    const [busy, setBusy] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const u = await login(identifier.trim(), password);
            if (u.must_change_password) {
                toast.message("Please set a new password to continue.");
                nav("/change-password", { replace: true });
                return;
            }
            toast.success(`Welcome back, ${u.name?.split(" ")[0] || ""}`);
            nav(u.role === "patient" ? "/portal" : "/internal", { replace: true });
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="relative min-h-screen w-full overflow-hidden font-plex">
            {/* Background artwork */}
            <div
                className="absolute inset-0 bg-cover bg-center"
                style={{ backgroundImage: `url("${BG}")` }}
                aria-hidden
            />
            {/* Cold dark overlay for contrast */}
            <div className="absolute inset-0 bg-gradient-to-r from-[#060b16]/95 via-[#0a1524]/80 to-[#0a1524]/55" aria-hidden />
            <div className="absolute inset-0 visita-scanlines" aria-hidden />

            {/* Content */}
            <div className="relative z-10 min-h-screen flex flex-col lg:flex-row lg:items-center lg:justify-between px-6 py-10 lg:px-16 gap-10">
                {/* Branding */}
                <div className="max-w-xl">
                    <h1
                        data-text="VISITA"
                        className="visita-glitch text-6xl sm:text-7xl lg:text-8xl font-bold tracking-tight leading-none"
                    >
                        VISITA
                    </h1>
                    <p className="mt-4 text-lg text-slate-200/90 font-semibold tracking-wide">
                        Dr. Aguayo Family Practice
                    </p>
                    <p className="mt-2 max-w-md text-sm text-slate-400 leading-relaxed">
                        Secure portal for appointments, prescriptions, referrals, and clinic communication.
                    </p>
                    <div className="mt-6 h-px w-40 bg-gradient-to-r from-cyan-400/50 to-transparent" />
                </div>

                {/* Login card */}
                <div className="w-full max-w-sm lg:mr-4">
                    <form
                        onSubmit={submit}
                        className="rounded-md border border-white/10 bg-[#0b1524]/75 backdrop-blur-xl p-7 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8)]"
                    >
                        <div className="flex items-center gap-2 mb-5">
                            <div className="w-8 h-8 rounded-sm bg-cyan-500/15 border border-cyan-400/30 flex items-center justify-center">
                                <ShieldPlus className="w-4 h-4 text-cyan-300" />
                            </div>
                            <div>
                                <h2 className="text-lg font-bold text-slate-100 leading-tight">Sign in</h2>
                                <p className="text-xs text-slate-400">Patients, clinic staff, and physician</p>
                            </div>
                        </div>

                        <Label htmlFor="email" className="text-[11px] uppercase tracking-widest text-slate-400">Email or Username</Label>
                        <Input
                            id="email" data-testid="login-email" type="text" required value={identifier}
                            onChange={(e) => setIdentifier(e.target.value)}
                            className="mt-1 mb-4 bg-[#0f1e30] border-white/10 text-slate-100 placeholder:text-slate-500 focus-visible:ring-cyan-400/60"
                            placeholder="you@example.com  or  USERNAME"
                        />

                        <Label htmlFor="password" className="text-[11px] uppercase tracking-widest text-slate-400">Password</Label>
                        <Input
                            id="password" data-testid="login-password" type="password" required value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="mt-1 mb-6 bg-[#0f1e30] border-white/10 text-slate-100 placeholder:text-slate-500 focus-visible:ring-cyan-400/60"
                            placeholder="••••••••"
                        />

                        <Button
                            data-testid="login-submit" type="submit" disabled={busy}
                            className="w-full bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold tracking-wide transition-colors"
                        >
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sign in"}
                        </Button>

                        <p className="text-sm text-center text-slate-400 mt-5">
                            New patient?{" "}
                            <Link to="/register" data-testid="go-register" className="text-cyan-300 font-semibold hover:underline">
                                Create an account
                            </Link>
                        </p>
                    </form>

                    <p className="mt-4 text-[11px] leading-relaxed text-slate-500/80 lg:text-right">
                        Not for emergencies. If you are experiencing a medical emergency, call 911 or go to the nearest
                        Emergency Department.
                    </p>
                </div>
            </div>
        </div>
    );
}
