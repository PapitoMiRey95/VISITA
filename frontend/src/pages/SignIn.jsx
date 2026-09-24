import { useState } from "react";
import { useNavigate, Link, useSearchParams } from "react-router-dom";
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

export default function SignIn() {
    const { login } = useAuth();
    const { t } = useTranslation(["common", "auth"]);
    const nav = useNavigate();
    const [params] = useSearchParams();
    const internal = params.get("internal") === "1";
    const partner = params.get("partner") === "1";
    const [identifier, setIdentifier] = useState("");
    const [password, setPassword] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [busy, setBusy] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const u = await login(identifier.trim(), password);
            if (u.must_change_password) {
                toast.message(t("auth:signin.mustChangePassword"));
                nav("/change-password", { replace: true });
                return;
            }
            toast.success(t("auth:signin.welcomeBack", { name: u.name?.split(" ")[0] || "" }));
            nav(u.role === "patient" ? "/portal" : u.role === "pharmacy" ? "/pharmacy" : u.role === "partner" ? "/partner" : "/internal", { replace: true });
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
