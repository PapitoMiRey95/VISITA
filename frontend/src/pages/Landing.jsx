import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { LogIn, UserRound, Stethoscope, Building2, Search, ChevronLeft, ChevronRight, ArrowRight, Loader2 } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Logo } from "../components/Logo";
import { api, formatErr } from "../lib/api";
import { setAppLanguage } from "../i18n";

const BG = "https://customer-assets-4nw71qhi.emergentagent.net/job_visita-admin/artifacts/5zizgajz_ChatGPT%20Image%20Sep%2024%2C%202026%2C%2003_43_19%20PM.png";
const BG_MOBILE = "https://customer-assets-4nw71qhi.emergentagent.net/job_visita-admin/artifacts/8ttghv0k_ChatGPT%20Image%20Sep%2025%2C%202026%2C%2006_17_18%20PM.png";

export default function Landing() {
    const nav = useNavigate();
    const { t, i18n } = useTranslation(["common", "auth"]);
    const cur = i18n.language?.startsWith("es") ? "es" : "en";
    const [mode, setMode] = useState("home"); // home | roles

    return (
        <div className="relative min-h-screen w-full overflow-hidden font-plex">
            <div className="absolute inset-0 bg-cover bg-center lg:hidden" style={{ backgroundImage: `url("${BG_MOBILE}")` }} aria-hidden />
            <div className="absolute inset-0 bg-cover bg-center hidden lg:block" style={{ backgroundImage: `url("${BG}")` }} aria-hidden />
            <div className="absolute inset-0 bg-gradient-to-r from-[#060b16]/96 via-[#0a1524]/86 to-[#0a1524]/60" aria-hidden />
            <div className="absolute inset-0 visita-scanlines" aria-hidden />

            {/* Language selector — EN/ES active; FR reserved */}
            <div data-testid="lang-selector"
                className="absolute top-4 right-4 z-20 flex items-center gap-0.5 rounded-full border border-white/10 bg-[#0b1524]/70 backdrop-blur px-1 py-0.5">
                <button type="button" data-testid="lang-en" onClick={() => setAppLanguage("en")} aria-current={cur === "en"}
                    className={`px-2 py-0.5 text-[11px] font-semibold rounded-full tracking-wide transition-colors ${cur === "en" ? "bg-cyan-500/20 text-cyan-200" : "text-slate-300 hover:text-cyan-200"}`}>EN</button>
                <button type="button" data-testid="lang-es" onClick={() => setAppLanguage("es")} aria-current={cur === "es"}
                    className={`px-2 py-0.5 text-[11px] font-semibold rounded-full tracking-wide transition-colors ${cur === "es" ? "bg-cyan-500/20 text-cyan-200" : "text-slate-300 hover:text-cyan-200"}`}>ES</button>
                <span data-testid="lang-fr" aria-disabled="true" title={t("common:language.comingSoon")}
                    className="px-2 py-0.5 text-[11px] font-semibold rounded-full tracking-wide text-slate-600 cursor-not-allowed select-none">FR</span>
                <span className="pl-1 pr-1.5 text-[9px] uppercase tracking-widest text-slate-500 inline">{t("common:language.comingSoon")}</span>
            </div>

            <div className="relative z-10 min-h-screen flex flex-col items-center px-5 py-16 lg:py-20 gap-8">
                {/* Branding — centered hero (unchanged identity) */}
                <div className="w-full max-w-2xl text-center px-8 py-8 lg:px-12 lg:py-10">
                    <Logo variant="dark" iconClass="h-16 w-16 lg:h-24 lg:w-24 drop-shadow-[0_0_30px_rgba(23,179,196,0.35)]"
                        textClass="text-3xl sm:text-4xl lg:text-5xl" className="justify-center" />
                </div>

                {mode === "home" ? (
                    <>
                        {/* Dominant Google-style search */}
                        <SearchBar nav={nav} t={t} />

                        {/* Compact actions card below the search */}
                        <div className="w-full max-w-md">
                            <div className="space-y-4 p-0 sm:rounded-2xl sm:border sm:border-white/10 sm:bg-[#0b1524]/80 sm:backdrop-blur-xl sm:p-5 sm:shadow-[0_20px_60px_-15px_rgba(0,0,0,0.85)]">
                                <Button data-testid="landing-signin" onClick={() => setMode("roles")}
                                    className="w-full h-11 bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold">
                                    <LogIn className="w-4 h-4 mr-1.5" /> {t("auth:landing2.signIn")}
                                </Button>
                                <div className="flex items-center justify-between gap-3 text-sm">
                                    <span className="text-white font-medium [text-shadow:0_1px_4px_rgba(0,0,0,0.9)] sm:[text-shadow:none] sm:text-slate-300 sm:font-normal">{t("auth:landing2.createPortalPrompt")}</span>
                                    <button data-testid="landing-create-portal" onClick={() => nav("/register")}
                                        className="font-bold text-cyan-300 hover:text-cyan-200 inline-flex items-center gap-1">
                                        {t("auth:landing2.createPortal")} <ArrowRight className="w-4 h-4" />
                                    </button>
                                </div>
                                <div className="flex items-center justify-between gap-3 text-sm border-t border-white/10 pt-4">
                                    <span className="text-white font-medium [text-shadow:0_1px_4px_rgba(0,0,0,0.9)] sm:[text-shadow:none] sm:text-slate-400 sm:font-normal">{t("auth:landing2.applyPrompt")}</span>
                                    <button data-testid="landing-apply-care" onClick={() => nav("/register?new=1")}
                                        className="font-bold text-slate-200 hover:text-cyan-200 inline-flex items-center gap-1">
                                        {t("auth:landing2.applyForCare")} <ArrowRight className="w-4 h-4" />
                                    </button>
                                </div>
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="w-full max-w-md">
                        <div className="rounded-2xl border border-cyan-400/25 bg-[#0b1524]/85 backdrop-blur-xl p-6 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.85)]">
                            <RolePanel nav={nav} t={t} onBack={() => setMode("home")} />
                        </div>
                    </div>
                )}

                <p className="w-full max-w-md text-[11px] leading-relaxed text-center text-slate-300 rounded-2xl border border-white/10 bg-gradient-to-br from-[rgba(8,20,35,0.72)] to-[rgba(8,20,35,0.55)] backdrop-blur-md px-4 py-3 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.7)]">{t("common:emergencyNotice")}</p>
            </div>
        </div>
    );
}

function SearchBar({ nav, t }) {
    const [q, setQ] = useState("");
    const [results, setResults] = useState(null);
    const [busy, setBusy] = useState(false);

    const search = async () => {
        if (!q.trim()) return;
        setBusy(true);
        try {
            const { data } = await api.get("/practices", { params: { q: q.trim() } });
            setResults(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <div className="w-full max-w-[760px]" data-testid="landing-home">
            <div className="relative">
                <Search className="w-5 h-5 text-slate-400 absolute left-5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <Input
                    data-testid="landing-search-input"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && search()}
                    placeholder={t("auth:landing2.searchPlaceholder")}
                    aria-label={t("auth:landing2.searchHint")}
                    className="h-14 lg:h-16 w-full rounded-full border-white/10 bg-[#0f1e30]/95 pl-14 pr-32 text-base lg:text-lg text-slate-100 placeholder:text-slate-500 shadow-[0_18px_50px_-18px_rgba(0,0,0,0.9)] focus-visible:ring-2 focus-visible:ring-cyan-400/60"
                />
                <Button
                    data-testid="landing-search-btn"
                    onClick={search}
                    disabled={busy}
                    className="absolute right-2 top-1/2 -translate-y-1/2 h-10 lg:h-12 rounded-full px-5 lg:px-7 bg-cyan-500 hover:bg-cyan-400 text-[#04121f] font-bold">
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : t("auth:landing2.searchBtn")}
                </Button>
            </div>

            {results && results.length === 0 && (
                <p className="text-sm text-slate-300 mt-3 text-center" data-testid="landing-search-none">{t("auth:landing2.searchNone")}</p>
            )}
            {results && results.length > 0 && (
                <div className="mt-3 space-y-2 max-h-72 overflow-auto rounded-2xl border border-white/10 bg-[#0b1524]/90 backdrop-blur-xl p-2 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.85)]">
                    {results.map((p) => (
                        <button key={p.id} data-testid={`landing-result-${p.slug}`} onClick={() => nav(`/register/${p.slug}`)}
                            className="w-full text-left flex items-center gap-3 rounded-xl border border-transparent hover:border-cyan-400/40 hover:bg-[#0f1e30] p-3 transition">
                            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/15 border border-cyan-400/30 flex-shrink-0">
                                <Stethoscope className="w-4 h-4 text-cyan-300" />
                            </span>
                            <span className="flex-1 min-w-0">
                                <span className="block font-bold text-slate-100 truncate">{p.physician_name}</span>
                                {p.clinic_name && <span className="block text-xs text-slate-400 truncate">{p.clinic_name}</span>}
                            </span>
                            <span className="text-xs font-semibold text-cyan-300 flex items-center gap-0.5 flex-shrink-0">{t("auth:landing2.viewClinic")} <ChevronRight className="w-4 h-4" /></span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

function RolePanel({ nav, t, onBack }) {
    const roles = [
        { key: "patient", icon: UserRound, label: t("auth:landing2.rolePatient"), go: () => nav("/signin"), testid: "role-patient" },
        { key: "clinic", icon: Stethoscope, label: t("auth:landing2.roleClinic"), go: () => nav("/signin?internal=1"), testid: "role-clinic" },
        { key: "partner", icon: Building2, label: t("auth:landing2.rolePartner"), go: () => nav("/signin?partner=1"), testid: "role-partner" },
    ];
    return (
        <div className="space-y-4" data-testid="landing-roles">
            <button onClick={onBack} data-testid="landing-role-back" className="flex items-center gap-1 text-slate-400 hover:text-slate-200 text-sm">
                <ChevronLeft className="w-4 h-4" /> {t("auth:landing2.back")}
            </button>
            <h2 className="text-xl font-bold text-slate-100">{t("auth:landing2.roleQ")}</h2>
            <div className="space-y-2.5">
                {roles.map((r) => (
                    <button key={r.key} data-testid={r.testid} onClick={r.go}
                        className="w-full flex items-center gap-3 rounded-xl border border-white/10 bg-[#0f1e30] hover:border-cyan-400/40 p-4 transition active:scale-[0.99]">
                        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-500/15 border border-cyan-400/30 flex-shrink-0">
                            <r.icon className="w-5 h-5 text-cyan-300" />
                        </span>
                        <span className="flex-1 text-left font-bold text-slate-100">{r.label}</span>
                        <ChevronRight className="w-5 h-5 text-slate-500" />
                    </button>
                ))}
            </div>
        </div>
    );
}
