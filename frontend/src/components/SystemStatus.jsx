import { createContext, useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Info, OctagonAlert } from "lucide-react";
import { api } from "../lib/api";

const Ctx = createContext({ announcement: null, maintenance: { on: false }, state: "NORMAL", notice: null, refresh: () => {} });

// Polls the public system banner (managed notice + announcement + maintenance flag) for the whole app shell.
export function SystemStatusProvider({ children }) {
    const [state, setState] = useState({ announcement: null, maintenance: { on: false, message: "" }, state: "NORMAL", notice: null });
    const refresh = async () => {
        try { setState((await api.get("/system/banner")).data); return true; } catch { return false; }
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

/* Managed notice (UPDATING / SERVICE_ISSUE / MAINTENANCE on public pages): calm, short, above any manual message. */
export function ManagedNotice() {
    const { notice } = useSystemStatus();
    const { t } = useTranslation("common");
    if (!notice) return null;
    const issue = notice.kind !== "UPDATE";
    return (
        <div className={`w-full px-4 py-2 text-[13px] flex items-center justify-center gap-2 ${issue ? "bg-[#0b2545] text-white" : "bg-[#0b2545] text-white"}`}
            role="status" data-testid="managed-notice" data-kind={notice.kind}>
            <span className={`w-2 h-2 rounded-full shrink-0 ${issue ? "bg-amber-300" : "bg-sky-300 animate-pulse"}`} />
            <span data-testid="managed-notice-message">{t(issue ? "system.noticeIssue" : "system.noticeUpdate")}</span>
        </div>
    );
}

export function AnnouncementBar() {
    const { announcement } = useSystemStatus();
    const manual = announcement?.active ? (STYLES[announcement.type] || STYLES.INFO) : null;
    return (
        <>
            <ManagedNotice />
            {manual && (
                <div className={`w-full px-4 py-2 text-sm font-semibold flex items-center justify-center gap-2 ${manual.cls}`} role="status" data-testid="global-announcement">
                    <manual.Icon className="w-4 h-4 shrink-0" />
                    <span className="uppercase text-xs tracking-wide opacity-80">{announcement.type}</span>
                    <span data-testid="global-announcement-message">{announcement.message}</span>
                </div>
            )}
        </>
    );
}

/* Branded Full Maintenance screen. Auto-polls via the provider (30 s) + manual Retry. Never shows technical detail. */
export function MaintenanceScreen() {
    const { refresh } = useSystemStatus();
    const { t } = useTranslation("common");
    const [busy, setBusy] = useState(false);
    const retry = async () => { setBusy(true); await refresh(); setBusy(false); };
    return (
        <div className="min-h-screen flex items-center justify-center bg-[#0b2545] text-white p-6" data-testid="maintenance-screen">
            <div className="max-w-sm text-center">
                <div className="mx-auto w-14 h-14 rounded-2xl bg-cyan-500 flex items-center justify-center"><img src="/vien-logo.png" alt="" className="w-9 h-9" /></div>
                <h1 className="mt-6 text-2xl font-extrabold" data-testid="maintenance-screen-title">{t("system.maintenanceTitle")}</h1>
                <p className="mt-3 text-slate-300 text-[15px] leading-relaxed" data-testid="maintenance-screen-message">{t("system.maintenanceBody")}</p>
                <button type="button" onClick={retry} disabled={busy} data-testid="maintenance-retry"
                    className="mt-6 px-6 py-2.5 rounded-full bg-white text-[#0b2545] font-bold text-sm hover:bg-cyan-50 disabled:opacity-60 transition-colors">
                    {busy ? t("system.retrying") : t("system.retry")}
                </button>
                <p className="mt-8 text-xs text-slate-400">{t("system.maintenanceAuto")}</p>
                <p className="mt-2 text-[11px] text-slate-500">{t("system.emergency")}</p>
            </div>
        </div>
    );
}
