import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Inbox, Check, ClipboardList } from "lucide-react";
import { api } from "../lib/api";
import { useInvalidate } from "./hooks";
import { Button } from "../components/ui/button";
import { whenLabel, NewWorkDialog, WorkDetail, OutcomeBadge, CategoryTag, CATEGORY_META } from "./workHubParts";
import { StructuredSummary } from "./workHubStructured";
import { TriageSection, TriageSummary, ClusterRow, PhysicianSummary } from "./workHubSections";
import { groupByTriage, triageCounts, clusterItems, taskLine, ownerState, dueText, loadSeen, markSeen, isUnread } from "./workHubTriage";

const VIEWS = [["my", "My Work"], ["sent", "Sent"], ["waiting", "Waiting"], ["completed", "History"]];
const HISTORY_PAGE = 30;
const DOT = { red: "bg-red-500", amber: "bg-amber-400", slate: "bg-slate-300" };
const DUE_TEXT = { red: "text-red-700 font-semibold", amber: "text-amber-800 font-semibold", slate: "text-slate-500" };

// Compact triage card: urgency dot · category icon · patient / task / owner · due. Everything else lives in the detail panel.
function WorkCard({ item, selected, onClick, unread, ctx }) {
    const m = CATEGORY_META[item.category] || { icon: ClipboardList, label: item.category };
    const Icon = m.icon;
    const due = dueText(item);
    return (
        <button data-testid="work-card" data-status={item.status} data-priority={item.priority || "NORMAL"} data-unread={unread ? "1" : "0"} onClick={onClick}
            className={`w-full text-left bg-white border rounded-sm pl-2.5 pr-3 py-2 transition-colors ${selected ? "border-visita-green ring-1 ring-visita-green" : "border-slate-300 hover:border-visita-green/60"}`}>
            <div className="flex items-start gap-2">
                <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${DOT[due.tone]}`} data-testid="work-card-urgency" data-tone={due.tone} />
                <span title={m.label} className="mt-0.5 shrink-0"><Icon className="w-4 h-4 text-slate-500" strokeWidth={2.25} aria-label={m.label} /></span>
                <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5 min-w-0">
                        <span className="text-sm font-bold text-slate-900 truncate" data-testid="work-card-patient">{item.patient_name || "No patient"}</span>
                        {unread && <span className="w-1.5 h-1.5 rounded-full bg-sky-500 shrink-0" title="Unread" data-testid="work-card-unread" />}
                        {due.text && <span className={`ml-auto text-[11px] shrink-0 ${DUE_TEXT[due.tone]}`} data-testid="work-card-due">{due.text}</span>}
                    </span>
                    <span className="block text-sm text-slate-700 truncate" data-testid="work-card-task">{taskLine(item)}</span>
                    <span className="block text-[11px] text-slate-500 truncate" data-testid="work-card-owner">{ownerState(item, ctx)}{item.created_by_name && item.created_by !== ctx.userId ? ` · from ${item.created_by_name}` : ""}</span>
                </span>
            </div>
        </button>
    );
}

// Compact archival card for History: category · patient, task, completed when/by.
function HistoryCard({ item, selected, onClick }) {
    return (
        <button data-testid="work-card" data-status={item.status} data-priority={item.priority || "NORMAL"} onClick={onClick}
            className={`w-full text-left bg-slate-50 border rounded-sm px-3 py-1.5 transition-colors ${selected ? "border-visita-green ring-1 ring-visita-green" : "border-slate-200 hover:border-visita-green/60"}`}>
            <div className="flex items-center gap-1.5 min-w-0">
                <CategoryTag category={item.category} testid="work-card-category" className="shrink-0" />
                <StructuredSummary item={item} testid="work-card-summary" />
                {item.patient_name && <span className="text-[11px] text-slate-500 uppercase tracking-wide font-semibold truncate">· {item.patient_name}</span>}
                <span className="ml-auto text-[10px] text-slate-400 shrink-0">{item.ref_number}</span>
            </div>
            <div className="text-sm text-slate-800 truncate">{item.reason_label ? `${item.reason_label}${item.clinic_action_label ? ` · ${item.clinic_action_label}` : ""}` : item.message}</div>
            <div className="text-[11px] flex items-center gap-1.5 flex-wrap">
                <OutcomeBadge item={item} testid="work-card-outcome" />
                <span className="text-emerald-700 inline-flex items-center gap-1"><Check className="w-3 h-3" /> {item.completion_outcome && item.completion_outcome !== "COMPLETED" ? "Closed" : "Completed"} {whenLabel(item.completed_at)} · {item.completed_by}</span>
            </div>
        </button>
    );
}

// Section body: identical work is clustered visually (records stay independent); NOW clusters open by default.
function TriageList({ section, selectedId, onSelect, seen, ctx }) {
    const rows = clusterItems(section.items);
    const card = (it) => <WorkCard key={it.id} item={it} ctx={ctx} unread={isUnread(it, seen, ctx.userId)} selected={it.id === selectedId} onClick={() => onSelect(it)} />;
    return rows.map((r) => r.type === "item" ? card(r.item) : (
        <ClusterRow key={r.key} cluster={r} tone={section.dot} defaultOpen={section.key === "NOW"} forceOpen={r.items.some((i) => i.id === selectedId)}>
            {r.items.map(card)}
        </ClusterRow>
    ));
}

// Central Clinic ↔ Doctor work inbox. Master list (left) + selected item detail (right); stacked on mobile.
export default function WorkHub() {
    const invalidate = useInvalidate();
    const [view, setView] = useState("my");
    const [selectedId, setSelectedId] = useState(null);
    const [creating, setCreating] = useState(false);
    const [includeCompleted, setIncludeCompleted] = useState(false);
    const [historyPages, setHistoryPages] = useState(1);
    const isHistory = view === "completed";
    const params = isHistory ? { view, limit: HISTORY_PAGE * historyPages, offset: 0 } : view === "sent" ? { view, include_completed: includeCompleted } : { view };
    const meta = useQuery({ queryKey: ["work-meta"], queryFn: async () => (await api.get("/internal/work/meta")).data, staleTime: 600000 });
    const list = useQuery({ queryKey: ["queue", "work", view, includeCompleted, isHistory ? historyPages : 0], queryFn: async () => (await api.get("/internal/work", { params })).data, refetchInterval: 20000, placeholderData: (prev) => prev });
    const items = list.data?.items || [];
    const side = meta.data?.side || list.data?.side;
    const userId = meta.data?.user_id;
    const categories = meta.data?.categories || [];
    const selected = items.find((i) => i.id === selectedId) || null;
    const triaged = !isHistory;
    const completedSent = view === "sent" ? items.filter((i) => i.status === "COMPLETED") : [];
    const [seen, setSeen] = useState(() => loadSeen(null));
    useEffect(() => { if (userId) setSeen(loadSeen(userId)); }, [userId]);
    const sections = useMemo(() => (triaged ? groupByTriage(items) : []), [items, triaged]);
    const counts = useMemo(() => triageCounts(items), [items]);
    useEffect(() => { if (selectedId && !list.isLoading && !list.isPlaceholderData && !selected) setSelectedId(null); }, [selectedId, selected, list.isLoading, list.isPlaceholderData]);
    const refresh = () => { invalidate(); list.refetch(); };
    const changeView = (k) => { setView(k); setSelectedId(null); setHistoryPages(1); };
    const select = (it) => { setSelectedId(it.id); if (it.status === "NEW") setSeen(markSeen(userId, it.id)); };
    const ctx = { userId, side };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2"><Inbox className="w-6 h-6 text-visita-green" /> Work Hub</h1>
                    <p className="text-sm text-slate-500">What to do next · who has it · the full record on the right</p>
                </div>
                <Button data-testid="work-new" onClick={() => setCreating(true)} className="bg-visita-green hover:bg-visita-greenDark text-white"><Plus className="w-4 h-4 mr-1" /> New</Button>
            </div>
            <div className="flex items-center gap-x-4 gap-y-2 flex-wrap mb-3">
                <div className="flex rounded-sm border border-slate-300 overflow-hidden text-sm w-full sm:w-auto sm:inline-flex" data-testid="work-views">
                    {VIEWS.map(([k, l]) => (
                        <button key={k} data-testid={`work-view-${k}`} onClick={() => changeView(k)}
                            className={`flex-1 sm:flex-none px-3 py-1.5 border-r last:border-r-0 border-slate-300 ${view === k ? "bg-visita-green text-white font-semibold" : "bg-white text-slate-600 hover:bg-slate-50"}`}>{l}</button>
                    ))}
                </div>
                {triaged && !list.isLoading && <TriageSummary counts={counts} />}
                {view === "sent" && (
                    <label className="inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer" data-testid="work-sent-include-completed">
                        <input type="checkbox" checked={includeCompleted} onChange={(e) => { setIncludeCompleted(e.target.checked); setSelectedId(null); }} className="accent-visita-green" /> Include completed
                    </label>
                )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-3">
                <div className={`space-y-3 ${selected ? "hidden md:block" : ""} md:max-h-[calc(100vh-13rem)] md:overflow-y-auto md:pr-1`} data-testid="work-list">
                    {list.isLoading && <p className="text-sm text-slate-400">Loading…</p>}
                    {!list.isLoading && items.length === 0 && <p className="text-sm text-slate-400 py-6 text-center" data-testid="work-empty">{view === "my" ? "Nothing needs your attention." : isHistory ? "No completed items yet." : "No items."}</p>}
                    {isHistory && items.map((it) => <HistoryCard key={it.id} item={it} selected={it.id === selectedId} onClick={() => setSelectedId(it.id)} />)}
                    {triaged && sections.map((s) => (
                        <TriageSection key={`${view}-${s.key}`} section={s}>
                            <TriageList section={s} selectedId={selectedId} onSelect={select} seen={seen} ctx={ctx} />
                        </TriageSection>
                    ))}
                    {triaged && completedSent.length > 0 && (
                        <TriageSection section={{ key: "COMPLETED", title: "Completed", hint: "", accent: "text-emerald-700 border-emerald-200", dot: "bg-emerald-500", items: completedSent }}>
                            {completedSent.map((it) => <HistoryCard key={it.id} item={it} selected={it.id === selectedId} onClick={() => setSelectedId(it.id)} />)}
                        </TriageSection>
                    )}
                    {isHistory && list.data?.has_more && (
                        <Button variant="outline" size="sm" data-testid="work-history-load-more" disabled={list.isFetching} onClick={() => setHistoryPages((p) => p + 1)} className="w-full h-8 text-xs">{list.isFetching ? "Loading…" : "Load more"}</Button>
                    )}
                </div>
                <div className={`${selected ? "" : "hidden md:block"} md:max-h-[calc(100vh-13rem)] md:overflow-y-auto`}>
                    {selected ? <WorkDetail item={selected} side={side} userId={userId} members={meta.data?.members || []} queues={meta.data?.queues || []} categories={categories} documentCategories={meta.data?.document_categories || []} onChanged={refresh} onBack={() => setSelectedId(null)} />
                        : side === "PHYSICIAN" ? <PhysicianSummary />
                        : <div className="hidden md:flex h-40 items-center justify-center rounded-sm border border-dashed border-slate-300 text-sm text-slate-400">Select an item to see its history and actions.</div>}
                </div>
            </div>
            {creating && side && <NewWorkDialog side={side} categories={categories} catalog={meta.data?.catalog} members={meta.data?.members || []} queues={meta.data?.queues || []} userId={userId} onClose={() => setCreating(false)} onDone={refresh} />}
        </div>
    );
}
