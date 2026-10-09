import { useEffect, useState } from "react";
import { formatDate } from "../lib/date";

export function useElapsed(startedAt, serverTime) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(id);
    }, []);
    const skew = serverTime ? new Date(serverTime).getTime() - Date.now() : 0;
    const secs = startedAt ? Math.max(0, Math.floor((now + skew - new Date(startedAt).getTime()) / 1000)) : 0;
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function Item({ label, value, testid }) {
    return (
        <div className="min-w-0" data-testid={testid}>
            <div className="text-[10px] uppercase tracking-wide text-white/60">{label}</div>
            <div className="text-sm font-semibold truncate">{value || "—"}</div>
        </div>
    );
}

export function SafetyHeader({ visit, elapsed, typeLabel, onExit, exiting }) {
    const s = visit.patient_snapshot || {};
    const age = s.date_of_birth ? Math.floor((Date.now() - new Date(s.date_of_birth).getTime()) / 31557600000) : null;
    return (
        <header className="sticky top-0 z-20 bg-visita-ribbon text-white border-b border-white/10" data-testid="encounter-safety-header">
            <div className="flex items-center gap-6 px-5 py-2">
                <div className="min-w-0">
                    <div className="text-[10px] uppercase tracking-wide text-cyan-200">Patient</div>
                    <div className="text-lg font-bold leading-tight truncate" data-testid="encounter-patient-name">
                        {(s.last_name || "").toUpperCase()}, {s.first_name}
                    </div>
                </div>
                <Item label="PIN" value={visit.visita_patient_id || "Not assigned"} testid="encounter-pin" />
                <Item label="DOB / Age" value={s.date_of_birth ? `${formatDate(s.date_of_birth)}${age != null ? ` · ${age}y` : ""}` : null} testid="encounter-dob" />
                <Item label="OHIP · Version" value={s.health_card_display ? `${s.health_card_display}${s.health_card_version_code && !s.health_card_display.endsWith(` ${s.health_card_version_code}`) ? " " + s.health_card_version_code : ""}` : null} testid="encounter-ohip" />
                <Item label="HC Expiry" value={s.health_card_expiry_date ? formatDate(s.health_card_expiry_date) : null} testid="encounter-hc-expiry" />
                <Item label="Encounter" value={typeLabel} testid="encounter-type" />
                <Item label="Physician" value={visit.physician_name} testid="encounter-physician" />
                <div className="ml-auto flex items-center gap-4">
                    <span className="px-2 py-0.5 rounded-sm bg-cyan-400/20 text-cyan-100 text-xs font-bold tracking-wide" data-testid="encounter-status">
                        {visit.status === "IN_PROGRESS" ? "IN PROGRESS" : visit.status}
                    </span>
                    <span className="font-mono text-base tabular-nums" data-testid="encounter-timer">{elapsed}</span>
                    <button type="button" onClick={onExit} disabled={exiting} data-testid="exit-encounter-btn"
                        className="rounded-sm border border-white/40 px-3 py-1.5 text-sm font-semibold hover:bg-white/10 disabled:opacity-50">
                        {exiting ? "Saving…" : "Exit Encounter"}
                    </button>
                </div>
            </div>
        </header>
    );
}
