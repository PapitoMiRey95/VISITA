import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, AlertTriangle, Bell, CalendarClock } from "lucide-react";
import { api } from "../lib/api";
import { formatDate } from "../lib/date";
import { overdueDays, PRIORITY_HELP } from "./workHubParts";

// Priority sections for active lists (My Work / Sent). Uses the existing `priority` field only.
export const SECTIONS = [
    { key: "ASAP", title: "ASAP — Urgent", accent: "text-red-700 border-red-300", icon: AlertTriangle },
    { key: "B1", title: "B1 — About 1 week", accent: "text-amber-800 border-amber-300" },
    { key: "B2", title: "B2 — Regular follow-up · 3–4 weeks", accent: "text-slate-700 border-slate-300" },
    { key: "NORMAL", title: "Routine / Normal", accent: "text-slate-600 border-slate-200" },
];

const isToday = (iso) => iso && new Date(iso).toDateString() === new Date().toDateString();
// Inside a section: overdue → due today → earliest due → oldest unresolved.
export function sectionSort(a, b) {
    const oa = overdueDays(a) !== null, ob = overdueDays(b) !== null;
    if (oa !== ob) return oa ? -1 : 1;
    const ta = isToday(a.due_at), tb = isToday(b.due_at);
    if (ta !== tb) return ta ? -1 : 1;
    if (a.due_at && b.due_at && a.due_at !== b.due_at) return a.due_at < b.due_at ? -1 : 1;
    if (!!a.due_at !== !!b.due_at) return a.due_at ? -1 : 1;
    return (a.created_at || "") < (b.created_at || "") ? -1 : 1;
}
// Physician My Work: incoming clinic requests grouped by Attention. No attention_level (physician-created / Signed) → Routine as a display fallback only.
export const ATTENTION_SECTIONS = [
    { key: "NEEDS_ATTENTION", title: "Needs attention soon", accent: "text-red-700 border-red-300", icon: AlertTriangle },
    { key: "IMPORTANT", title: "Important", accent: "text-amber-800 border-amber-300" },
    { key: "ROUTINE", title: "Routine", accent: "text-emerald-700 border-emerald-200" },
];
export function groupByAttention(items) {
    const active = items.filter((i) => i.status !== "COMPLETED");
    return ATTENTION_SECTIONS.map((s) => ({ ...s, items: active.filter((i) => (i.attention_level || "ROUTINE") === s.key).sort(sectionSort) })).filter((s) => s.items.length > 0);
}
export function groupByPriority(items) {
    const active = items.filter((i) => i.status !== "COMPLETED");
    return SECTIONS.map((s) => ({ ...s, items: active.filter((i) => (i.priority || "NORMAL") === s.key).sort(sectionSort) })).filter((s) => s.items.length > 0);
}

export function PrioritySection({ section, children }) {
    const [open, setOpen] = useState(true);
    const Icon = section.icon;
    return (
        <div data-testid={`work-section-${section.key.toLowerCase()}`} data-open={open} className="space-y-1.5">
            <button type="button" data-testid={`work-section-toggle-${section.key.toLowerCase()}`} onClick={() => setOpen((o) => !o)} title={PRIORITY_HELP[section.key]}
                className={`w-full flex items-center gap-1.5 border-b pb-1 text-[11px] font-bold uppercase tracking-wide ${section.accent}`}>
                {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                {Icon && <Icon className="w-3.5 h-3.5" />}
                <span className="flex-1 text-left">{section.title}</span>
                <span data-testid={`work-section-count-${section.key.toLowerCase()}`} className="rounded-sm bg-slate-100 px-1.5 text-slate-700 tabular-nums">{section.items.length}</span>
            </button>
            {open && children}
        </div>
    );
}

// Physician-only right panel when nothing is selected: compact counts + upcoming Calendar personal reminders (reused, never duplicated).
export function PhysicianSummary() {
    const my = useQuery({ queryKey: ["queue", "work", "my", false, 0], queryFn: async () => (await api.get("/internal/work", { params: { view: "my" } })).data, refetchInterval: 20000 });
    const sent = useQuery({ queryKey: ["queue", "work", "sent", false, 0], queryFn: async () => (await api.get("/internal/work", { params: { view: "sent" } })).data, refetchInterval: 20000 });
    const cal = useQuery({ queryKey: ["work-summary-reminders"], queryFn: async () => (await api.get("/internal/calendar", { params: { days: 4 } })).data, staleTime: 60000 });
    // Active items I own or sent (deduped) — answers "what did I mark ASAP / what is overdue" without a new counter system.
    const items = [...new Map([...(my.data?.items || []), ...(sent.data?.items || [])].filter((i) => i.status !== "COMPLETED").map((i) => [i.id, i])).values()];
    const asap = items.filter((i) => i.priority === "ASAP").length;
    const overdue = items.filter((i) => overdueDays(i) !== null).length;
    const dueToday = items.filter((i) => isToday(i.due_at) && overdueDays(i) === null).length;
    const incoming = (my.data?.items || []).filter((i) => i.status !== "COMPLETED" && i.attention_level); // active incoming clinic work only
    const needs = incoming.filter((i) => i.attention_level === "NEEDS_ATTENTION").length, important = incoming.filter((i) => i.attention_level === "IMPORTANT").length;
    const today = new Date().toISOString().slice(0, 10);
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    const dayLabel = (d) => (d === today ? "Today" : d === tomorrow ? "Tomorrow" : formatDate(d));
    const reminders = (cal.data?.days || []).flatMap((d) => (d.reminders || []).map((r) => ({ ...r, date: d.date }))).slice(0, 5);
    const Stat = ({ n, label, tone, testid }) => <div data-testid={testid} className={`rounded-sm border px-2 py-1.5 text-center ${tone}`}><div className="text-lg font-bold leading-none tabular-nums">{n}</div><div className="text-[10px] uppercase tracking-wide mt-1">{label}</div></div>;
    return (
        <div data-testid="work-physician-summary" className="hidden md:block rounded-sm border border-dashed border-slate-300 p-3 text-sm space-y-3">
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500 flex items-center gap-1.5"><CalendarClock className="w-3.5 h-3.5" /> Today / Upcoming</div>
            <div className="grid grid-cols-3 gap-2">
                <Stat n={asap} label="ASAP" tone={asap ? "border-red-300 bg-red-50 text-red-700" : "border-slate-200 text-slate-500"} testid="work-summary-asap" />
                <Stat n={overdue} label="Overdue" tone={overdue ? "border-red-300 bg-red-50 text-red-700" : "border-slate-200 text-slate-500"} testid="work-summary-overdue" />
                <Stat n={dueToday} label="Due today" tone={dueToday ? "border-amber-300 bg-amber-50 text-amber-800" : "border-slate-200 text-slate-500"} testid="work-summary-due-today" />
            </div>
            {(needs > 0 || important > 0) && (
                <div className="flex items-center gap-3 text-xs" data-testid="work-summary-incoming">
                    <span className="text-slate-500 font-semibold uppercase tracking-wide text-[10px]">From clinic</span>
                    {needs > 0 && <span className="inline-flex items-center gap-1 text-red-700 font-semibold" data-testid="work-summary-needs-attention"><span className="w-1.5 h-1.5 rounded-full bg-red-500" />Needs attention soon: {needs}</span>}
                    {important > 0 && <span className="inline-flex items-center gap-1 text-amber-800 font-semibold" data-testid="work-summary-important"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" />Important: {important}</span>}
                </div>
            )}
            <div>
                <div className="text-[11px] font-bold uppercase tracking-wide text-indigo-600 flex items-center gap-1.5 mb-1"><Bell className="w-3.5 h-3.5" /> Reminders</div>
                {reminders.length === 0 && <p className="text-xs text-slate-400" data-testid="work-summary-no-reminders">No personal reminders in the next few days.</p>}
                {reminders.map((r) => (
                    <div key={r.id} data-testid="work-summary-reminder" className="flex items-baseline gap-2 text-xs py-0.5">
                        <span className="text-indigo-700 font-semibold shrink-0 tabular-nums">{dayLabel(r.date)} · {r.label || r.time}</span>
                        <span className="text-slate-800 truncate">{r.title}</span>
                    </div>
                ))}
            </div>
            <p className="text-[11px] text-slate-400">Select a work item to see its history and actions.</p>
        </div>
    );
}
