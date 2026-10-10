import { Play, Square } from "lucide-react";

/* One canonical Visit timer state drives BOTH toggles (header + lower center). No local state here. */
export const TIMER_LABEL = { READY: "START VISIT", RUNNING: "STOP VISIT", PAUSED: "RESUME VISIT" };

export function VisitToggle({ timerState, onClick, busy, testid, compact, fullWidth }) {
    const running = timerState === "RUNNING";
    const Icon = running ? Square : Play;
    const color = running
        ? "bg-red-600 hover:bg-red-700 border-red-800 text-white"
        : "bg-emerald-600 hover:bg-emerald-700 border-emerald-800 text-white";
    return (
        <button type="button" onClick={onClick} disabled={busy} data-testid={testid} data-timer-state={timerState}
            className={`inline-flex items-center justify-center gap-1.5 rounded-sm border font-bold tracking-wide whitespace-nowrap shadow-sm transition-colors disabled:opacity-60 ${color} ${compact ? "h-7 px-3 text-xs" : "h-9 px-4 text-sm"} ${fullWidth ? "w-full" : ""}`}>
            <Icon className={compact ? "w-3.5 h-3.5" : "w-4 h-4"} fill="currentColor" /> {TIMER_LABEL[timerState] || TIMER_LABEL.READY}
        </button>
    );
}
