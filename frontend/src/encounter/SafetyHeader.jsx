import { useEffect, useMemo, useState } from "react";
import { formatDate } from "../lib/date";

export function useElapsed(timer, serverTime) {
    const [now, setNow] = useState(() => Date.now());
    const running = timer?.timer_state === "RUNNING";
    useEffect(() => {
        if (!running) return undefined;
        setNow(Date.now());
        const id = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(id);
    }, [running]);
    // Clock skew captured ONCE when the server payload arrived (not per render, or the ticking would cancel out).
    const skew = useMemo(() => (serverTime ? new Date(serverTime).getTime() - Date.now() : 0), [serverTime]);
    let secs = timer?.elapsed_seconds || 0;
    if (running && timer.running_since) secs += Math.max(0, Math.floor((now + skew - new Date(timer.running_since).getTime()) / 1000));
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/* Same health-card status semantics used on the Patients page (identity.health_card_status). */
const HC_STYLE = {
    VALID: "bg-emerald-400/20 text-emerald-100",
    EXPIRING_SOON: "bg-amber-400/25 text-amber-100",
    EXPIRED: "bg-red-500/30 text-red-100",
    INCOMPLETE: "bg-white/10 text-white/70",
};
const HC_TEXT = { VALID: "VALID", EXPIRING_SOON: "EXPIRING", EXPIRED: "EXPIRED", INCOMPLETE: "INCOMPLETE" };

function Item({ label, value, testid, className = "" }) {
    return (
        <div className={`whitespace-nowrap ${className}`} data-testid={testid}>
            <div className="text-[10px] uppercase tracking-wide text-white/60 leading-none mb-0.5">{label}</div>
            <div className="text-sm font-semibold leading-tight">{value || "—"}</div>
        </div>
    );
}

const STATUS_STYLE = { READY: "bg-white/15 text-white", RUNNING: "bg-emerald-400/25 text-emerald-100", PAUSED: "bg-amber-400/25 text-amber-100" };
const STATUS_TEXT = { READY: "READY · NOT STARTED", RUNNING: "IN PROGRESS", PAUSED: "PAUSED" };

export function SafetyHeader({ visit, timerState, elapsed, typeLabel, onExit, exiting, toggle }) {
    const s = visit.patient_snapshot || {};
    const age = s.date_of_birth ? Math.floor((Date.now() - new Date(s.date_of_birth).getTime()) / 31557600000) : null;
    const ohip = s.health_card_display
        ? `${s.health_card_display}${s.health_card_version_code && !s.health_card_display.endsWith(` ${s.health_card_version_code}`) ? " " + s.health_card_version_code : ""}`
        : null;
    const hcStatus = s.health_card_status;
    return (
        <header className="sticky top-0 z-20 bg-visita-ribbon text-white border-b border-white/10 shadow-md" data-testid="encounter-safety-header">
            {/* Row 1: identity (never truncated) + status/timer/exit. Row 2 (<1500px): secondary context. */}
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-1.5">
                <div className="whitespace-nowrap">
                    <div className="text-[10px] uppercase tracking-wide text-cyan-200 leading-none mb-0.5">Patient</div>
                    <div className="text-xl font-bold leading-tight" data-testid="encounter-patient-name">
                        {(s.last_name || "").toUpperCase()}, {s.first_name}
                    </div>
                </div>
                <Item label="PIN" value={visit.visita_patient_id || "Not assigned"} testid="encounter-pin" />
                <Item label="DOB / Age" value={s.date_of_birth ? `${formatDate(s.date_of_birth)}${age != null ? ` · ${age}y` : ""}` : null} testid="encounter-dob" />
                <div className="whitespace-nowrap" data-testid="encounter-ohip">
                    <div className="text-[10px] uppercase tracking-wide text-white/60 leading-none mb-0.5">OHIP · Version</div>
                    <div className="text-sm font-semibold leading-tight flex items-center gap-1.5">
                        {ohip || "—"}
                        {hcStatus && <span className={`px-1 py-px rounded-sm text-[9px] font-bold tracking-wide ${HC_STYLE[hcStatus] || HC_STYLE.INCOMPLETE}`} data-testid="encounter-hc-status">{HC_TEXT[hcStatus] || hcStatus}</span>}
                    </div>
                </div>
                <Item label="HC Expiry" value={s.health_card_expiry_date ? formatDate(s.health_card_expiry_date) : null} testid="encounter-hc-expiry" className="hidden 2xl:block" />
                <Item label="Encounter" value={typeLabel} testid="encounter-type" className="hidden 2xl:block" />
                <Item label="Physician" value={visit.physician_name} testid="encounter-physician" className="hidden 2xl:block" />

                <div className="ml-auto flex items-center gap-3 whitespace-nowrap">
                    <span className={`px-2 py-0.5 rounded-sm text-xs font-bold tracking-wide whitespace-nowrap ${STATUS_STYLE[timerState] || STATUS_STYLE.READY}`} data-testid="encounter-status" data-timer-state={timerState}>
                        {STATUS_TEXT[timerState] || timerState}
                    </span>
                    <span className="font-mono text-[21px] leading-none tabular-nums px-2.5 py-1 rounded-sm bg-black/25 border border-white/15" data-testid="encounter-timer">{elapsed}</span>
                    {toggle}
                    <button type="button" onClick={onExit} disabled={exiting} data-testid="exit-encounter-btn"
                        className="whitespace-nowrap rounded-sm bg-white text-visita-ribbon px-3 py-1.5 text-sm font-bold hover:bg-cyan-50 disabled:opacity-60">
                        {exiting ? "Saving…" : "Exit Encounter"}
                    </button>
                </div>
            </div>
            {/* Secondary row shown below 2xl so nothing truncates */}
            <div className="flex items-center gap-x-6 px-4 pb-1.5 -mt-0.5 text-xs text-white/85 2xl:hidden whitespace-nowrap" data-testid="encounter-header-row2">
                <span><span className="text-white/55 uppercase text-[10px] tracking-wide mr-1">HC Expiry</span>{s.health_card_expiry_date ? formatDate(s.health_card_expiry_date) : "—"}</span>
                <span><span className="text-white/55 uppercase text-[10px] tracking-wide mr-1">Encounter</span>{typeLabel}</span>
                <span><span className="text-white/55 uppercase text-[10px] tracking-wide mr-1">Physician</span>{visit.physician_name}</span>
            </div>
        </header>
    );
}
