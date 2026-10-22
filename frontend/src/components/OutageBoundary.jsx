import { Component, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { api, onOutage } from "../lib/api";

const AUTO_RETRY_S = 20;

/* Friendly outage card: shown over the mounted page (unsaved state is kept). Retry probes /api/health;
   controlled auto-retry every AUTO_RETRY_S. Copy never includes technical/origin details. */
export function OutageCard({ onRecovered, hardError = false }) {
    const { t } = useTranslation("common");
    const [busy, setBusy] = useState(false);
    const [left, setLeft] = useState(AUTO_RETRY_S);
    const retry = async () => {
        setBusy(true);
        try { await api.get("/health"); onRecovered(); }
        catch { setLeft(AUTO_RETRY_S); }
        finally { setBusy(false); }
    };
    useEffect(() => {
        if (hardError) return undefined;
        const t = setInterval(() => setLeft((s) => (s <= 1 ? (retry(), AUTO_RETRY_S) : s - 1)), 1000);
        return () => clearInterval(t);
    }, [hardError]); // eslint-disable-line react-hooks/exhaustive-deps
    return (
        <div className="fixed inset-0 z-[1000] bg-slate-900/40 backdrop-blur-[2px] flex items-center justify-center p-6" data-testid="outage-overlay">
            <div className="max-w-sm w-full bg-white rounded-2xl border border-slate-200 p-8 text-center shadow-xl" data-testid="outage-card">
                <div className="mx-auto w-12 h-12 rounded-xl bg-[#0b2545] flex items-center justify-center"><img src="/vien-logo.png" alt="" className="w-8 h-8" /></div>
                <h1 className="mt-5 text-xl font-extrabold text-slate-900" data-testid="outage-title">{t("system.outageTitle")}</h1>
                <p className="mt-2 text-slate-600 text-sm leading-relaxed" data-testid="outage-body">{t("system.outageBody")}</p>
                {hardError
                    ? <button type="button" onClick={() => window.location.reload()} data-testid="outage-reload" className="mt-6 w-full py-2.5 rounded-full bg-[#0b2545] text-white font-bold text-sm">{t("system.reload")}</button>
                    : <button type="button" onClick={retry} disabled={busy} data-testid="outage-retry" className="mt-6 w-full py-2.5 rounded-full bg-[#0b2545] text-white font-bold text-sm disabled:opacity-60">{busy ? t("system.retrying") : t("system.retry")}</button>}
                <p className="mt-4 text-[11px] text-slate-400" data-testid="outage-auto">{hardError ? t("system.keptWork") : `${t("system.autoRetry", { seconds: left })} · ${t("system.keptWork")}`}</p>
            </div>
        </div>
    );
}

function NetworkOutage({ children }) {
    const [down, setDown] = useState(false);
    const qc = useQueryClient();
    useEffect(() => onOutage(() => setDown(true)), []);
    const recovered = () => { setDown(false); qc.invalidateQueries(); window.dispatchEvent(new Event("vien:outage-recovered")); };
    return <>{children}{down && <OutageCard onRecovered={recovered} />}</>;
}

/* Render-error boundary: chunk/load failures and unexpected render errors show the same calm card (no stack traces). */
class RenderBoundary extends Component {
    state = { failed: false };
    static getDerivedStateFromError() { return { failed: true }; }
    componentDidCatch(err) { if (process.env.NODE_ENV !== "production") console.error("[VIen] render failure", err); }
    render() { return this.state.failed ? <OutageCard hardError onRecovered={() => this.setState({ failed: false })} /> : this.props.children; }
}

export function OutageBoundary({ children }) {
    return <RenderBoundary><NetworkOutage>{children}</NetworkOutage></RenderBoundary>;
}
