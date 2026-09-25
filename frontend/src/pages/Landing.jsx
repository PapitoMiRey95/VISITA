import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LogIn, UserPlus, UserRound, ArrowRight, Stethoscope, Building2 } from "lucide-react";
import { Button } from "../components/ui/button";
import { Logo } from "../components/Logo";

const BG = "https://customer-assets-4nw71qhi.emergentagent.net/job_visita-admin/artifacts/5zizgajz_ChatGPT%20Image%20Sep%2024%2C%202026%2C%2003_43_19%20PM.png";

export default function Landing() {
    const nav = useNavigate();
    const { t } = useTranslation(["common", "auth"]);

    return (
        <div className="relative min-h-screen w-full overflow-hidden font-plex">
            <div className="absolute inset-0 bg-cover bg-center" style={{ backgroundImage: `url("${BG}")` }} aria-hidden />
            <div className="absolute inset-0 bg-gradient-to-r from-[#060b16]/96 via-[#0a1524]/86 to-[#0a1524]/60" aria-hidden />
            <div className="absolute inset-0 visita-scanlines" aria-hidden />

            {/* Language selector — EN active; ES/FR reserved (translations not yet available) */}
            <div data-testid="lang-selector"
                className="absolute top-4 right-4 z-20 flex items-center gap-0.5 rounded-full border border-white/10 bg-[#0b1524]/70 backdrop-blur px-1 py-0.5">
                <span data-testid="lang-en" aria-current="true"
                    className="px-2 py-0.5 text-[11px] font-semibold rounded-full tracking-wide bg-cyan-500/20 text-cyan-200">
                    EN
                </span>
                {["ES", "FR"].map((l) => (
                    <span key={l} data-testid={`lang-${l.toLowerCase()}`}
                        aria-disabled="true" title={t("common:language.comingSoon")}
                        className="px-2 py-0.5 text-[11px] font-semibold rounded-full tracking-wide text-slate-600 cursor-not-allowed select-none">
                        {l}
                    </span>
                ))}
                <span className="pl-1 pr-1.5 text-[9px] uppercase tracking-widest text-slate-500 hidden sm:inline">{t("common:language.comingSoon")}</span>
            </div>

            <div className="relative z-10 min-h-screen flex flex-col lg:flex-row lg:items-center lg:justify-between px-6 py-12 lg:px-16 gap-10">
                {/* Branding */}
                <div className="max-w-xl text-center">
                    <Logo variant="dark" iconClass="h-20 w-20 lg:h-28 lg:w-28 drop-shadow-[0_0_30px_rgba(23,179,196,0.35)]"
                        textClass="text-4xl sm:text-5xl lg:text-6xl" className="justify-center" />
                    <p className="mt-4 text-lg text-slate-200/90 font-semibold tracking-wide">{t("common:practice")}</p>
                    <p className="mt-2 max-w-md mx-auto text-sm text-slate-400 leading-relaxed">{t("common:tagline")}</p>
                    <div className="mt-6 h-px w-40 mx-auto bg-gradient-to-r from-cyan-400/50 to-transparent" />
                </div>

                {/* Access groups */}
                <div className="w-full max-w-md space-y-4">
                    {/* Patients — primary */}
                    <div data-testid="pathway-patients"
                        className="rounded-md border border-cyan-400/25 bg-[#0b1524]/80 backdrop-blur-xl p-6 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8)]">
                        <div className="flex items-center gap-2.5 mb-1">
                            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-cyan-500/15 border border-cyan-400/30">
                                <UserRound className="w-5 h-5 text-cyan-300" />
                            </span>
                            <h2 className="text-xl font-bold text-slate-100 tracking-tight">{t("auth:landing.patients.title")}</h2>
                        </div>
                        <p className="text-sm text-slate-400 leading-relaxed mb-4">{t("auth:landing.patients.desc")}</p>
                        <div className="grid grid-cols-2 gap-3">
                            <Button data-testid="patient-signin" onClick={() => nav("/signin")}
                                className="bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold h-11">
                                <LogIn className="w-4 h-4 mr-1.5" /> {t("common:actions.signIn")}
                            </Button>
                            <Button data-testid="patient-register" onClick={() => nav("/register")}
                                variant="outline" className="h-11 border-cyan-400/40 bg-transparent text-cyan-200 hover:bg-cyan-500/10 hover:text-cyan-100 font-semibold">
                                <UserPlus className="w-4 h-4 mr-1.5" /> {t("common:actions.register")}
                            </Button>
                        </div>
                        <button data-testid="patient-new-request" onClick={() => nav("/register?new=1")}
                            className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-slate-300 hover:text-cyan-200 transition-colors">
                            {t("auth:landing.patients.newRequest")} <ArrowRight className="w-4 h-4" />
                        </button>
                    </div>

                    {/* Clinic Team + Partners — secondary, equal cards */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div data-testid="pathway-clinic"
                            className="flex flex-col rounded-md border border-white/10 bg-[#0b1524]/60 backdrop-blur-md p-5">
                            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-white/5 border border-white/10 mb-2">
                                <Stethoscope className="w-5 h-5 text-slate-200" />
                            </span>
                            <h3 className="text-sm font-bold text-slate-100 tracking-tight">{t("auth:landing.clinic.title")}</h3>
                            <p className="text-[11px] uppercase tracking-widest text-slate-500 mt-0.5 mb-4">{t("auth:landing.clinic.roles")}</p>
                            <Button data-testid="clinic-login" onClick={() => nav("/signin?internal=1")}
                                variant="outline" className="mt-auto h-10 border-white/15 bg-transparent text-slate-100 hover:bg-white/10 font-semibold">
                                {t("auth:landing.clinic.login")}
                            </Button>
                        </div>

                        <div data-testid="pathway-partners"
                            className="flex flex-col rounded-md border border-white/10 bg-[#0b1524]/60 backdrop-blur-md p-5">
                            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-white/5 border border-white/10 mb-2">
                                <Building2 className="w-5 h-5 text-slate-200" />
                            </span>
                            <h3 className="text-sm font-bold text-slate-100 tracking-tight">{t("auth:landing.partners.title")}</h3>
                            <p className="text-[11px] uppercase tracking-widest text-slate-500 mt-0.5 mb-4">{t("auth:landing.partners.roles")}</p>
                            <div className="mt-auto grid grid-cols-1 gap-2">
                                <Button data-testid="partner-login" onClick={() => nav("/signin?partner=1")}
                                    variant="outline" className="h-10 border-white/15 bg-transparent text-slate-100 hover:bg-white/10 font-semibold">
                                    {t("auth:landing.partners.signIn")}
                                </Button>
                                <Button data-testid="partner-register" onClick={() => nav("/partners/register")}
                                    className="h-10 bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold">
                                    <UserPlus className="w-4 h-4 mr-1.5" /> {t("auth:landing.partners.register")}
                                </Button>
                            </div>
                        </div>
                    </div>

                    <p className="text-[11px] leading-relaxed text-slate-500/80 pt-1">{t("common:emergencyNotice")}</p>
                </div>
            </div>
        </div>
    );
}
