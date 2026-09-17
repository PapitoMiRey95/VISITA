import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { Stethoscope, Loader2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function Login() {
    const { login } = useAuth();
    const nav = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [busy, setBusy] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const u = await login(email.trim(), password);
            toast.success(`Welcome back, ${u.name?.split(" ")[0] || ""}`);
            nav(u.role === "patient" ? "/portal" : "/internal", { replace: true });
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="min-h-screen grid md:grid-cols-2 font-plex">
            <div className="hidden md:flex flex-col justify-between bg-visita-ribbon text-white p-10">
                <div className="flex items-center gap-2">
                    <div className="w-9 h-9 rounded bg-visita-green flex items-center justify-center">
                        <Stethoscope className="w-5 h-5" />
                    </div>
                    <span className="text-xl font-bold tracking-tight">VISITA</span>
                </div>
                <div>
                    <h1 className="text-3xl font-bold leading-tight">Dr. Aguayo Family Practice</h1>
                    <p className="mt-3 text-white/70 max-w-sm">
                        Secure web portal for appointment requests, prescriptions, referrals and clinic communication.
                    </p>
                </div>
                <p className="text-xs text-white/50">Not for emergencies. Call 911 for urgent medical needs.</p>
            </div>

            <div className="flex items-center justify-center p-6 bg-visita-bg">
                <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-lg border border-slate-200 p-7 shadow-sm">
                    <div className="md:hidden flex items-center gap-2 mb-4">
                        <div className="w-8 h-8 rounded bg-visita-green flex items-center justify-center">
                            <Stethoscope className="w-4 h-4 text-white" />
                        </div>
                        <span className="text-lg font-bold text-visita-ribbon">VISITA</span>
                    </div>
                    <h2 className="text-xl font-bold text-slate-900">Sign in</h2>
                    <p className="text-sm text-slate-500 mb-5">Patients, clinic staff and physician</p>

                    <Label htmlFor="email" className="text-xs uppercase tracking-wide text-slate-600">Email</Label>
                    <Input id="email" data-testid="login-email" type="email" required value={email}
                        onChange={(e) => setEmail(e.target.value)} className="mt-1 mb-4" placeholder="you@example.com" />

                    <Label htmlFor="password" className="text-xs uppercase tracking-wide text-slate-600">Password</Label>
                    <Input id="password" data-testid="login-password" type="password" required value={password}
                        onChange={(e) => setPassword(e.target.value)} className="mt-1 mb-5" placeholder="••••••••" />

                    <Button data-testid="login-submit" type="submit" disabled={busy}
                        className="w-full bg-visita-green hover:bg-visita-greenDark text-white">
                        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sign in"}
                    </Button>

                    <p className="text-sm text-center text-slate-600 mt-5">
                        New patient?{" "}
                        <Link to="/register" data-testid="go-register" className="text-visita-green font-semibold hover:underline">
                            Create an account
                        </Link>
                    </p>
                </form>
            </div>
        </div>
    );
}
