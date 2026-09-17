import { createContext, useContext, useEffect, useState } from "react";
import { api, setToken, clearToken, getToken } from "../lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null); // null = checking, false = logged out, obj = logged in
    const [patient, setPatient] = useState(null);

    const loadMe = async () => {
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
    };

    useEffect(() => {
        loadMe();
    }, []);

    const login = async (email, password) => {
        const { data } = await api.post("/auth/login", { email, password });
        setToken(data.token);
        setUser(data.user);
        await loadMe();
        return data.user;
    };

    const register = async (payload) => {
        const { data } = await api.post("/auth/register", payload);
        setToken(data.token);
        setUser(data.user);
        await loadMe();
        return data.user;
    };

    const logout = () => {
        clearToken();
        setUser(false);
        setPatient(null);
    };

    return (
        <AuthCtx.Provider value={{ user, patient, login, register, logout, refreshMe: loadMe }}>
            {children}
        </AuthCtx.Provider>
    );
}

export const useAuth = () => useContext(AuthCtx);
