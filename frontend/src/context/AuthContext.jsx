import { createContext, useContext, useEffect, useState, useCallback, useMemo } from "react";
import { api, setToken, clearToken, getToken } from "../lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null); // null = checking, false = logged out, obj = logged in
    const [patient, setPatient] = useState(null);

    const loadMe = useCallback(async () => {
        if (!getToken()) {
            setUser(false);
            return;
        }
        try {
            const { data } = await api.get("/auth/me");
            setUser(data.user);
            setPatient(data.patient || null);
        } catch {
            clearToken();
            setUser(false);
        }
        // deps intentionally empty: api/getToken/clearToken are stable module imports and
        // setUser/setPatient are stable React setters — nothing here changes across renders.
    }, []);

    useEffect(() => {
        loadMe();
    }, [loadMe]);

    const login = useCallback(async (identifier, password) => {
        const { data } = await api.post("/auth/login", { identifier, password });
        setToken(data.token);
        setUser(data.user);
        await loadMe();
        return data.user;
    }, [loadMe]);

    const register = useCallback(async (payload) => {
        const { data } = await api.post("/auth/register", payload);
        if (data.application_required) return data; // no account created; caller routes to the apply form
        setToken(data.token);
        setUser(data.user);
        await loadMe();
        return data.user;
    }, [loadMe]);

    // Emergent Google Sign-In (patients only): exchange the one-time session_id for
    // our own JWT via the backend, which matches an existing patient by email.
    const googleLogin = useCallback(async (sessionId) => {
        const { data } = await api.post("/auth/google", { session_id: sessionId });
        setToken(data.token);
        setUser(data.user);
        await loadMe();
        return data.user;
    }, [loadMe]);

    // Installation-level operator sign-in (developer_ops only) — separate entry from clinic/patient login.
    const platformLogin = useCallback(async (identifier, password) => {
        const { data } = await api.post("/platform/auth/login", { identifier, password });
        setToken(data.token);
        setUser(data.user);
        await loadMe();
        return data.user;
    }, [loadMe]);

    const logout = useCallback(() => {
        clearToken();
        setUser(false);
        setPatient(null);
        // deps empty: clearToken is a stable import; setUser/setPatient are stable setters.
    }, []);

    // USER-LEVEL theme: VIen Light is the default; Dark applies only to this user's session (class on <html>).
    useEffect(() => {
        document.documentElement.classList.toggle("dark", !!(user && user.theme === "dark"));
    }, [user]);
    const setTheme = useCallback(async (theme) => {
        await api.put("/me/theme", { theme });
        setUser((u) => (u ? { ...u, theme } : u));
    }, []);

    const value = useMemo(
        () => ({ user, patient, login, register, googleLogin, platformLogin, logout, refreshMe: loadMe, setTheme }),
        [user, patient, login, register, googleLogin, platformLogin, logout, loadMe, setTheme]
    );

    return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
