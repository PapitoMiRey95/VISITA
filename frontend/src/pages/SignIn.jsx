import { useState, useEffect, useRef } from "react";
import { useNavigate, Link, useSearchParams, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Loader2, ChevronLeft, Eye, EyeOff } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Logo } from "../components/Logo";

const BG = "https://customer-assets-4nw71qhi.emergentagent.net/job_visita-admin/artifacts/ndj1izcs_ChatGPT%20Image%20Sep%2018%2C%202026%2C%2010_35_01%20AM.png";

const GoogleIcon = () => (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden focusable="false">
        <path fill="#FFC107" d="M43.611 20.083H42V20H24v8h11.303c-1.649 4.657-6.08 8-11.303 8-6.627 0-12-5.373-12-12s5.373-12 12-12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917z" />
        <path fill="#FF3D00" d="M6.306 14.691l6.571 4.819C14.655 15.108 18.961 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 16.318 4 9.656 8.337 6.306 14.691z" />
        <path fill="#4CAF50" d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238C29.211 35.091 26.715 36 24 36c-5.202 0-9.619-3.317-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44z" />
        <path fill="#1976D2" d="M43.611 20.083H42V20H24v8h11.303c-.792 2.237-2.231 4.166-4.087 5.571.001-.001 6.19 5.238 6.19 5.238C36.971 39.205 44 34 44 24c0-1.341-.138-2.65-.389-3.917z" />
    </svg>
);

export default function SignIn() {
    const { login, googleLogin } = useAuth();
    const { t } = useTranslation(["common", "auth"]);
    const nav = useNavigate();
    const loc = useLocation();
    const [params] = useSearchParams();
    const internal = params.get("internal") === "1";
    const partner = params.get("partner") === "1";
    const [identifier, setIdentifier] = useState("");
    const [password, setPassword] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [busy, setBusy] = useState(false);
    const [googleBusy, setGoogleBusy] = useState(loc.hash?.includes("session_id="));
    const googleProcessed = useRef(false);

    const routeAfterLogin = (u) => {
        if (u.must_change_password) {
            toast.message(t("auth:signin.mustChangePassword"));
            nav("/change-password", { replace: true });
            return;
        }
        toast.success(t("auth:signin.welcomeBack", { name: u.name?.split(" ")[0] || "" }));
        nav(u.role === "patient" ? "/portal" : u.role === "pharmacy" ? "/pharmacy" : u.role === "partner" ? "/partner" : "/internal", { replace: true });
    };

    // Handle the return trip from Google: exchange the one-time session_id (in the
    // URL fragment) for our JWT, then clear the fragment and route the patient in.
    useEffect(() => {
        if (!loc.hash?.includes("session_id=")) return;
        if (googleProcessed.current) return;
        googleProcessed.current = true;
        const sessionId = new URLSearchParams(loc.hash.replace(/^#/, "")).get("session_id");
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        (async () => {
            try {
                const u = await googleLogin(sessionId);
                routeAfterLogin(u);
            } catch (err) {
                toast.error(formatErr(err));
                setGoogleBusy(false);
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const startGoogle = () => {
        setGoogleBusy(true);
        // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
        const redirectUrl = window.location.origin + "/signin";
        window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
    };

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const u = await login(identifier.trim(), password);
            routeAfterLogin(u);
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="relative min-h-screen w-full overflow-hidden font-plex">
            <div className="absolute inset-0 bg-cover bg-center" style={{ backgroundImage: `url("${BG}")` }} aria-hidden />
            <div className="absolute inset-0 bg-gradient-to-r from-[#060b16]/95 via-[#0a1524]/85 to-[#0a1524]/70" aria-hidden />
            <div className="absolute inset-0 visita-scanlines" aria-hidden />

            <div className="relative z-10 min-h-screen flex items-center justify-center px-4 py-10">
                <div className="w-full max-w-sm">
                    <button onClick={() => nav("/login")} data-testid="signin-back"
                        className="flex items-center gap-1 text-slate-400 hover:text-slate-200 text-sm mb-3">
                        <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
                    </button>

                    <form onSubmit={submit}
                        className="rounded-md border border-white/10 bg-[#0b1524]/80 backdrop-blur-xl p-7 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8)]">
                        <div className="flex items-center gap-3 mb-5">
                            <Logo variant="dark" iconClass="h-11 w-11" showText={false} />
                            <div>
                                <h2 className="text-lg font-bold text-slate-100 leading-tight">
                                    {partner ? t("auth:signin.titlePartner") : internal ? t("auth:signin.titleClinic") : t("auth:signin.titlePatient")}
                                </h2>
                                <p className="text-xs text-slate-400">
                                    {partner ? t("auth:signin.subPartner") : internal ? t("auth:signin.subClinic") : t("auth:signin.subPatient")}
                                </p>
                            </div>
                        </div>

                        <Label htmlFor="email" className="text-[11px] uppercase tracking-widest text-slate-400">{t("auth:signin.emailLabel")}</Label>
                        <Input id="email" data-testid="login-email" type="text" required value={identifier}
                            onChange={(e) => setIdentifier(e.target.value)}
                            className="mt-1 mb-4 bg-[#0f1e30] border-white/10 text-slate-100 placeholder:text-slate-500 focus-visible:ring-cyan-400/60"
                            placeholder={internal ? "USERNAME" : partner ? "you@pharmacy.com" : "you@example.com"} />

                        <Label htmlFor="password" className="text-[11px] uppercase tracking-widest text-slate-400">{t("auth:signin.passwordLabel")}</Label>
                        <div className="relative mt-1 mb-6">
                            <Input id="password" data-testid="login-password" type={showPassword ? "text" : "password"} required value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="pr-10 bg-[#0f1e30] border-white/10 text-slate-100 placeholder:text-slate-500 focus-visible:ring-cyan-400/60"
                                placeholder="••••••••" />
                            <button type="button" data-testid="toggle-password-visibility"
                                onClick={() => setShowPassword((v) => !v)}
                                aria-label={showPassword ? "Hide password" : "Show password"}
                                className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-cyan-200">
                                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                        </div>

                        <Button data-testid="login-submit" type="submit" disabled={busy}
                            className="w-full bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold tracking-wide">
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : (internal ? t("auth:signin.submitClinic") : partner ? t("auth:signin.submitPartner") : t("auth:signin.submitPatient"))}
                        </Button>

                        <div className="text-center mt-4">
                            <Link to="/forgot-password" data-testid="forgot-password-link" className="text-xs text-slate-400 hover:text-cyan-200">
                                {t("auth:signin.forgot")}
                            </Link>
                        </div>

                        {!internal && !partner && (
                            <>
                                <div className="flex items-center gap-3 my-5" aria-hidden>
                                    <div className="h-px flex-1 bg-white/10" />
                                    <span className="text-[11px] uppercase tracking-widest text-slate-500">or</span>
                                    <div className="h-px flex-1 bg-white/10" />
                                </div>
                                <Button type="button" data-testid="google-signin-button" onClick={startGoogle} disabled={googleBusy}
                                    className="w-full bg-white hover:bg-slate-100 text-slate-800 font-semibold border border-white/10 flex items-center justify-center gap-2">
                                    {googleBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <GoogleIcon />}
                                    {googleBusy ? "Signing in…" : "Continue with Google"}
                                </Button>
                            </>
                        )}

                        {!internal && !partner && (
                            <p className="text-sm text-center text-slate-400 mt-5">
                                {t("auth:signin.registerPrompt")}{" "}
                                <Link to="/register" data-testid="go-register" className="text-cyan-300 font-semibold hover:underline">{t("auth:signin.registerLink")}</Link>
                            </p>
                        )}
                    </form>
                </div>
            </div>
        </div>
    );
}
