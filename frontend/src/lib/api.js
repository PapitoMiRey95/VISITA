import axios from "axios";
import i18n from "../i18n";

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const TOKEN_KEY = "visita_token";

// Use sessionStorage (cleared when the tab closes) instead of localStorage to
// reduce XSS token-theft exposure and enforce session-scoped auth.
export const getToken = () => sessionStorage.getItem(TOKEN_KEY);
export const setToken = (t) => sessionStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => sessionStorage.removeItem(TOKEN_KEY);

export const api = axios.create({ baseURL: API });

// Managed-patient (caregiver "on behalf of") context. When set, every /portal
// API call is scoped to the managed patient via the X-On-Behalf-Of header the
// backend already enforces (active delegate grant + permission + practice).
let onBehalfOf = null;
export const setOnBehalfOf = (id) => { onBehalfOf = id || null; };
export const getOnBehalfOf = () => onBehalfOf;

api.interceptors.request.use((cfg) => {
    const t = getToken();
    if (t) cfg.headers.Authorization = `Bearer ${t}`;
    if (onBehalfOf && typeof cfg.url === "string" && cfg.url.includes("/portal/")) {
        cfg.headers["X-On-Behalf-Of"] = onBehalfOf;
    }
    return cfg;
});

// Outage detection: gateway/origin failures (502/504/52x, network errors, non-JSON 503) → friendly in-app card.
// MAINTENANCE_MODE 503s are intentional and handled by the maintenance screen, not the outage card.
const OUTAGE_STATUSES = new Set([502, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530]);
const outageListeners = new Set();
export const onOutage = (fn) => { outageListeners.add(fn); return () => outageListeners.delete(fn); };
const isOutage = (err) => {
    if (err?.code === "ERR_CANCELED") return false;
    const r = err?.response;
    if (!r) return !!err?.request; // request sent, no response (network/origin unreachable)
    if (OUTAGE_STATUSES.has(r.status)) return true;
    if (r.status === 503) return !(r.data && typeof r.data === "object" && r.data.detail?.code === "MAINTENANCE_MODE");
    return false;
};
api.interceptors.response.use((res) => res, (err) => {
    if (isOutage(err)) {
        if (err.response) err.response.data = { detail: i18n.t("common:system.outageBody") }; // never surface origin/CDN HTML
        else err.message = i18n.t("common:system.outageBody");
        outageListeners.forEach((fn) => fn(err));
    }
    return Promise.reject(err);
});

// Known patient-facing backend error strings → stable codes, localized via i18n
// (common:apiErrors.*). Falls back to the raw server detail when unmapped.
const SERVER_ERR_CODES = {
    "This time is no longer available. Please select another time.": "E_TIME_UNAVAILABLE_SELECT",
    "That time is no longer available. Please contact the clinic.": "E_TIME_UNAVAILABLE_CONTACT",
    "This request can no longer be cancelled.": "E_CANNOT_CANCEL",
    "Payment proof can no longer be uploaded for this invoice.": "E_PROOF_LOCKED",
    "Invalid credentials. Please check your email/username and password.": "E_INVALID_CREDENTIALS",
    "This account has been disabled. Contact the clinic.": "E_ACCOUNT_DISABLED",
    "Please enter your email or username.": "E_ENTER_IDENTIFIER",
};

function localizeDetail(detail) {
    const code = SERVER_ERR_CODES[detail];
    return code ? i18n.t(`common:apiErrors.${code}`, { defaultValue: detail }) : detail;
}

export function formatErr(err) {
    const detail = err?.response?.data?.detail;
    if (detail == null) return err?.message || "Something went wrong. Please try again.";
    if (typeof detail === "string") return localizeDetail(detail);
    if (Array.isArray(detail))
        return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" ");
    if (detail && typeof detail.msg === "string") return detail.msg;
    if (detail && typeof detail.message === "string") return detail.message;
    return String(detail);
}

// Open an authenticated attachment (blob) in a new tab.
export async function openAttachment(url) {
    const { data } = await api.get(url, { responseType: "blob" });
    const objUrl = URL.createObjectURL(data);
    window.open(objUrl, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(objUrl), 60000);
}

export async function saveAttachment(url, filename) {
    const { data } = await api.get(url, { responseType: "blob" });
    const objUrl = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = filename || "document";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objUrl), 60000);
}
