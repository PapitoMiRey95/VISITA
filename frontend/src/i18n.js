import i18n from "i18next";
import { initReactI18next } from "react-i18next";

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
// Phase 1 patient experience: English + Spanish are enabled; French is still
// "Coming soon" (files exist but are empty and fall back to English).
export const ENABLED_LANGUAGES = ["en", "es"];

const LANG_KEY = "visita_lang"; // device-only preference; no PHI stored.

export function getSavedLanguage() {
    try { return localStorage.getItem(LANG_KEY); } catch { return null; }
}

export function setAppLanguage(lng) {
    if (!ENABLED_LANGUAGES.includes(lng)) return;
    i18n.changeLanguage(lng);
    try { localStorage.setItem(LANG_KEY, lng); } catch { /* ignore */ }
}

const resources = {
    en: { common: enCommon, auth: enAuth, portal: enPortal, requests: enRequests },
    es: { common: esCommon, auth: esAuth, portal: esPortal, requests: esRequests },
    fr: { common: frCommon, auth: frAuth, portal: frPortal, requests: frRequests },
};

i18n
    .use(initReactI18next)
    .init({
        resources,
        // Use the saved device preference if present; otherwise default to English.
        // We never auto-pick a language from the browser/device — the patient chooses.
        lng: getSavedLanguage() || "en",
        fallbackLng: "en",
        supportedLngs: SUPPORTED_LANGUAGES,
        ns: ["common", "auth", "portal", "requests"],
        defaultNS: "common",
        returnEmptyString: false,
        interpolation: { escapeValue: false },
    });

export default i18n;
