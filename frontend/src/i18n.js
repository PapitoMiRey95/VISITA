import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import enCommon from "./locales/en/common.json";
import enAuth from "./locales/en/auth.json";
import enPortal from "./locales/en/portal.json";
import enRequests from "./locales/en/requests.json";
import esCommon from "./locales/es/common.json";
import esAuth from "./locales/es/auth.json";
import esPortal from "./locales/es/portal.json";
import esRequests from "./locales/es/requests.json";
import frCommon from "./locales/fr/common.json";
import frAuth from "./locales/fr/auth.json";
import frPortal from "./locales/fr/portal.json";
import frRequests from "./locales/fr/requests.json";

export const SUPPORTED_LANGUAGES = ["en", "es", "fr"];
// Only English is enabled for now. Spanish/French files exist but are empty and
// therefore fall back to English until translations are added (Phase 2).
export const ENABLED_LANGUAGES = ["en"];

const resources = {
    en: { common: enCommon, auth: enAuth, portal: enPortal, requests: enRequests },
    es: { common: esCommon, auth: esAuth, portal: esPortal, requests: esRequests },
    fr: { common: frCommon, auth: frAuth, portal: frPortal, requests: frRequests },
};

i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
        resources,
        // Phase 1: force English active. Detection config is present so we can
        // enable per-user language switching later without re-architecting.
        lng: "en",
        fallbackLng: "en",
        supportedLngs: SUPPORTED_LANGUAGES,
        ns: ["common", "auth", "portal", "requests"],
        defaultNS: "common",
        returnEmptyString: false,
        interpolation: { escapeValue: false },
        detection: {
            order: ["localStorage", "navigator"],
            caches: ["localStorage"],
            lookupLocalStorage: "visita_lang",
        },
    });

export default i18n;
