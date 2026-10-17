import { createContext, useContext, useEffect, useState } from "react";
import { AlertTriangle, Info, OctagonAlert, Wrench } from "lucide-react";
import { api } from "../lib/api";

const Ctx = createContext({ announcement: null, maintenance: { on: false }, refresh: () => {} });

// Polls the public system banner (announcement + maintenance flag) for the whole app shell.
export function SystemStatusProvider({ children }) {
    const [state, setState] = useState({ announcement: null, maintenance: { on: false, message: "" } });
    const refresh = async () => {
        try { setState((await api.get("/system/banner")).data); } catch { /* keep last known state */ }
    };
    useEffect(() => { refresh(); const t = setInterval(refresh, 30000); return () => clearInterval(t); }, []);
    return <Ctx.Provider value={{ ...state, refresh }}>{children}</Ctx.Provider>;
}

export const useSystemStatus = () => useContext(Ctx);

const STYLES = {
    INFO: { cls: "bg-sky-700 text-white", Icon: Info },
    WARNING: { cls: "bg-amber-500 text-slate-900", Icon: AlertTriangle },
    CRITICAL: { cls: "bg-red-700 text-white", Icon: OctagonAlert },
};

export function AnnouncementBar() {
    const { announcement } = useSystemStatus();
    if (!announcement?.active) return null;
    const { cls, Icon } = STYLES[announcement.type] || STYLES.INFO;
    return (
        <div className={`w-full px-4 py-2 text-sm font-semibold flex items-center justify-center gap-2 ${cls}`} role="status" data-testid="global-announcement">
            <Icon className="w-4 h-4 shrink-0" />
            <span className="uppercase text-xs tracking-wide opacity-80">{announcement.type}</span>
            <span data-testid="global-announcement-message">{announcement.message}</span>
        </div>
    );
}

export function MaintenanceScreen({ message }) {
    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white p-6" data-testid="maintenance-screen">
            <div className="max-w-lg text-center space-y-4">
                <Wrench className="w-12 h-12 mx-auto text-amber-400" />
                <h1 className="text-2xl font-bold">VIen is in maintenance</h1>
                <p className="text-slate-300" data-testid="maintenance-screen-message">{message}</p>
                <p className="text-xs text-slate-500">This page refreshes automatically when service resumes.</p>
            </div>
        </div>
    );
}
