import { Play, Square, PenLine, ShieldCheck } from "lucide-react";

/* One canonical Visit lifecycle drives BOTH toggles (header + lower center). START → STOP (final) → SIGN → SIGNED. */
export const TIMER_LABEL = { READY: "START VISIT", RUNNING: "STOP VISIT", PAUSED: "STOP VISIT", STOPPED: "SIGN VISIT", SIGNED: "SIGNED" };
const STYLE = {
    READY: ["bg-emerald-600 hover:bg-emerald-700 border-emerald-800 text-white", Play],
    RUNNING: ["bg-red-600 hover:bg-red-700 border-red-800 text-white", Square],
    PAUSED: ["bg-red-600 hover:bg-red-700 border-red-800 text-white", Square],
    STOPPED: ["bg-visita-ribbon hover:bg-[#0f2a44] border-[#0a1f33] text-white", PenLine],
    SIGNED: ["bg-slate-200 border-slate-300 text-slate-600 cursor-default", ShieldCheck],
};

export function VisitToggle({ timerState, onClick, busy, testid, compact, fullWidth }) {
    const [color, Icon] = STYLE[timerState] || STYLE.READY;
    const signed = timerState === "SIGNED";
    return (
        <button type="button" onClick={signed ? undefined : onClick} disabled={busy || signed} data-testid={testid} data-timer-state={timerState}
            className={`inline-flex items-center justify-center gap-1.5 rounded-sm border font-bold tracking-wide whitespace-nowrap shadow-sm transition-colors disabled:opacity-80 ${color} ${compact ? "h-7 px-3 text-xs" : "h-9 px-4 text-sm"} ${fullWidth ? "w-full" : ""}`}>
            <Icon className={compact ? "w-3.5 h-3.5" : "w-4 h-4"} fill={signed || timerState === "STOPPED" ? "none" : "currentColor"} /> {TIMER_LABEL[timerState] || TIMER_LABEL.READY}
        </button>
    );
}
