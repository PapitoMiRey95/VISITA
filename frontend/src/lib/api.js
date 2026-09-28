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

api.interceptors.request.use((cfg) => {
    const t = getToken();
    if (t) cfg.headers.Authorization = `Bearer ${t}`;
    return cfg;
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
    return String(detail);
}

// Open an authenticated attachment (blob) in a new tab.
export async function openAttachment(url) {
    const { data } = await api.get(url, { responseType: "blob" });
    const objUrl = URL.createObjectURL(data);
    window.open(objUrl, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(objUrl), 60000);
}
