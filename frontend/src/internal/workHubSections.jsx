import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Bell, CalendarClock, ClipboardList } from "lucide-react";
import { api } from "../lib/api";
import { formatDate } from "../lib/date";
import { overdueDays, CATEGORY_META } from "./workHubParts";
import { isDueToday } from "./workHubTriage";

const TONE_TEXT = { red: "text-red-700", amber: "text-amber-800", slate: "text-slate-500" };

// Header line: "4 need attention · 3 due soon · 13 routine" — read the workload without reading every card.
export function TriageSummary({ counts, testid = "work-triage-summary" }) {
    const total = counts.NOW + counts.NEXT + counts.ROUTINE;
    if (total === 0) return null;
    const Part = ({ n, label, tone, k }) => <span data-testid={`${testid}-${k}`} className={`inline-flex items-baseline gap-1 ${n ? TONE_TEXT[tone] : "text-slate-400"}`}><span className="font-bold tabular-nums text-base">{n}</span><span className="text-xs">{label}</span></span>;
    return (
        <div data-testid={testid} className="flex items-center gap-2 text-sm flex-wrap">
            <Part n={counts.NOW} label={counts.NOW === 1 ? "needs attention" : "need attention"} tone="red" k="now" />
            <span className="text-slate-300">·</span>
            <Part n={counts.NEXT} label="due soon" tone="amber" k="next" />
            <span className="text-slate-300">·</span>
            <Part n={counts.ROUTINE} label="routine" tone="slate" k="routine" />
        </div>
    );
}

export function TriageSection({ section, children }) {
    const [open, setOpen] = useState(true);
    return (
        <div data-testid={`work-section-${section.key.toLowerCase()}`} data-open={open} className="space-y-1">
            <button type="button" data-testid={`work-section-toggle-${section.key.toLowerCase()}`} onClick={() => setOpen((o) => !o)} title={section.hint}
                className={`w-full flex items-center gap-1.5 border-b pb-1 text-[11px] font-bold uppercase tracking-wide ${section.accent}`}>
                {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                <span className={`w-2 h-2 rounded-full ${section.dot}`} />
                <span className="flex-1 text-left">{section.title}</span>
                <span className="hidden sm:inline font-normal normal-case tracking-normal text-slate-400 mr-1">{section.hint}</span>
                <span data-testid={`work-section-count-${section.key.toLowerCase()}`} className="rounded-sm bg-slate-100 px-1.5 text-slate-700 tabular-nums">{section.items.length}</span>
            </button>
            {open && children}
        </div>
    );
}

// Visual group of identical work ("Book BMD follow-ups · 7"). Expands to the individual records; never merges them.
export function ClusterRow({ cluster, tone, defaultOpen, forceOpen, children }) {
    const [open, setOpen] = useState(defaultOpen);
    useEffect(() => { if (forceOpen) setOpen(true); }, [forceOpen]);
    const m = CATEGORY_META[cluster.category] || { icon: ClipboardList, label: cluster.category };
    const Icon = m.icon;
    const patients = [...new Set(cluster.items.map((i) => i.patient_name).filter(Boolean))];
    return (
        <div data-testid="work-cluster" data-count={cluster.items.length} data-open={open} className={`rounded-sm border ${open ? "border-slate-300 bg-slate-50/60" : "border-slate-300 bg-white"}`}>
            <button type="button" data-testid="work-cluster-toggle" onClick={() => setOpen((o) => !o)} className="w-full text-left px-3 py-2 flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full shrink-0 ${tone}`} />
                <Icon className="w-4 h-4 text-slate-500 shrink-0" strokeWidth={2.25} />
                <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-slate-900 truncate" data-testid="work-cluster-task">{cluster.task}</span>
                    <span className="block text-[11px] text-slate-500 truncate">{cluster.items.length} items{patients.length ? ` · ${patients.length} patient${patients.length === 1 ? "" : "s"} · ${patients.slice(0, 3).join(", ")}${patients.length > 3 ? "…" : ""}` : ""}</span>
                </span>
                <span data-testid="work-cluster-count" className="rounded-full bg-slate-200 text-slate-800 text-xs font-bold px-2 py-0.5 tabular-nums">{cluster.items.length}</span>
                {open ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
            </button>
            {open && <div className="px-2 pb-2 space-y-1" data-testid="work-cluster-items">{children}</div>}
        </div>
    );
}

// Physician-only right panel when nothing is selected: compact counts + upcoming Calendar personal reminders (reused, never duplicated).
export function PhysicianSummary() {
    const my = useQuery({ queryKey: ["queue", "work", "my", false, 0], queryFn: async () => (await api.get("/internal/work", { params: { view: "my" } })).data, refetchInterval: 20000 });
    const sent = useQuery({ queryKey: ["queue", "work", "sent", false, 0], queryFn: async () => (await api.get("/internal/work", { params: { view: "sent" } })).data, refetchInterval: 20000 });
    const cal = useQuery({ queryKey: ["work-summary-reminders"], queryFn: async () => (await api.get("/internal/calendar", { params: { days: 4 } })).data, staleTime: 60000 });
    const items = [...new Map([...(my.data?.items || []), ...(sent.data?.items || [])].filter((i) => i.status !== "COMPLETED").map((i) => [i.id, i])).values()];
    const asap = items.filter((i) => i.priority === "ASAP").length;
    const overdue = items.filter((i) => overdueDays(i) !== null).length;
    const dueToday = items.filter((i) => isDueToday(i.due_at) && overdueDays(i) === null).length;
    const incoming = (my.data?.items || []).filter((i) => i.status !== "COMPLETED" && i.attention_level);
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
                <Stat n={dueToday} label="Due today" tone={dueToday ? "border-red-300 bg-red-50 text-red-700" : "border-slate-200 text-slate-500"} testid="work-summary-due-today" />
            </div>
            {(needs > 0 || important > 0) && (
                <div className="flex items-center gap-3 text-xs" data-testid="work-summary-incoming">
                    <span className="text-slate-500 font-semibold uppercase tracking-wide text-[10px]">From clinic</span>
                    {needs > 0 && <span className="inline-flex items-center gap-1 text-red-700 font-semibold" data-testid="work-summary-needs-attention"><span className="w-1.5 h-1.5 rounded-full bg-red-500" />Needs attention soon: {needs}</span>}
                    {important > 0 && <span className="inline-flex items-center gap-1 text-amber-800 font-semibold" data-testid="work-summary-important"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" />Important: {important}</span>}
                </div>
            )}
            <div>
                <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500 flex items-center gap-1.5 mb-1"><Bell className="w-3.5 h-3.5" /> Reminders</div>
                {reminders.length === 0 && <p className="text-xs text-slate-400" data-testid="work-summary-no-reminders">No personal reminders in the next few days.</p>}
                {reminders.map((r) => (
                    <div key={r.id} data-testid="work-summary-reminder" className="flex items-baseline gap-2 text-xs py-0.5">
                        <span className="text-slate-700 font-semibold shrink-0 tabular-nums">{dayLabel(r.date)} · {r.label || r.time}</span>
                        <span className="text-slate-800 truncate">{r.title}</span>
                    </div>
                ))}
            </div>
            <p className="text-[11px] text-slate-400">Select a work item to see its history and actions.</p>
        </div>
    );
}
