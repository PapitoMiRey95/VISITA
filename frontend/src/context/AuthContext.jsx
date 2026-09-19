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
        if (data.former_detected) return data; // no account created; caller handles re-establish flow
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

    const value = useMemo(
        () => ({ user, patient, login, register, logout, refreshMe: loadMe }),
        [user, patient, login, register, logout, loadMe]
    );

    return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
