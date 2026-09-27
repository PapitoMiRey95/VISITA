import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getSavedLanguage, setAppLanguage } from "../i18n";

// Mobile-only, first-visit language chooser. Shows once when there is no saved
// device preference. Spanish is listed first (majority of our patients), but no
// language is auto-selected — the patient must choose. No PHI is stored.
export function LanguageChooser() {
    const { t } = useTranslation("common");
    const [show, setShow] = useState(false);

    useEffect(() => {
        const isMobile = typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches;
        if (isMobile && !getSavedLanguage()) setShow(true);
    }, []);

    if (!show) return null;

    const pick = (lng) => { setAppLanguage(lng); setShow(false); };

    return (
        <div className="fixed inset-0 z-[100] flex items-end justify-center bg-black/70 backdrop-blur-sm p-4"
            data-testid="language-chooser">
            <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#0b1524]/95 backdrop-blur-xl p-6 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.9)] animate-fade-in mb-2">
                <h2 className="text-center text-xl font-bold text-slate-100">{t("language.choose")}</h2>
                <p className="text-center text-sm text-slate-400 mt-0.5">{t("language.chooseEs")}</p>
                <div className="mt-6 space-y-3">
                    <button type="button" data-testid="lang-choose-es" onClick={() => pick("es")}
                        className="w-full h-14 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-[#04121f] text-lg font-bold tracking-wide transition-colors">
                        {t("language.spanish")}
                    </button>
                    <button type="button" data-testid="lang-choose-en" onClick={() => pick("en")}
                        className="w-full h-14 rounded-xl border border-white/15 bg-transparent text-slate-100 hover:bg-white/10 text-lg font-semibold tracking-wide transition-colors">
                        {t("language.english")}
                    </button>
                </div>
            </div>
        </div>
    );
}
