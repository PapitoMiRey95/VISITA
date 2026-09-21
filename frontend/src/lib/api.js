import axios from "axios";

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

export function formatErr(err) {
    const detail = err?.response?.data?.detail;
    if (detail == null) return err?.message || "Something went wrong. Please try again.";
    if (typeof detail === "string") return detail;
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
