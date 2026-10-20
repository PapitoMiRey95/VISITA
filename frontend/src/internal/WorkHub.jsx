import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Inbox, Check } from "lucide-react";
import { api } from "../lib/api";
import { useInvalidate } from "./hooks";
import { Button } from "../components/ui/button";
import { Chip, STATUS_TONE, STATUS_LABEL, ownerLabel, whenLabel, NewWorkDialog, WorkDetail, PriorityBadge, OverdueBadge, SignedBadge, CategoryTag } from "./workHubParts";

const VIEWS = [["my", "My Work"], ["sent", "Sent"], ["waiting", "Waiting"], ["completed", "History"]];
const HISTORY_PAGE = 30;

function WorkCard({ item, selected, onClick }) {
    return (
        <button data-testid="work-card" data-status={item.status} data-priority={item.priority || "NORMAL"} onClick={onClick}
            className={`w-full text-left bg-white border rounded-sm px-3 py-2 transition-colors ${selected ? "border-visita-green ring-1 ring-visita-green" : "border-slate-300 hover:border-visita-green/60"}`}>
            <div className="flex items-center gap-1.5 min-w-0">
                <CategoryTag category={item.category} testid="work-card-category" className="shrink-0" />
                {item.patient_name && <span className="text-[11px] text-slate-500 uppercase tracking-wide font-semibold truncate">· {item.patient_name}</span>}
            </div>
            <div className="text-sm font-medium text-slate-900 truncate">{item.message}</div>
            <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-slate-500">
                <span className="flex items-center gap-1 flex-wrap">
                    <PriorityBadge priority={item.priority} testid="work-card-priority" />
                    <OverdueBadge item={item} testid="work-card-overdue" />
                    <SignedBadge item={item} testid="work-card-signed" />
                    <Chip tone="bg-visita-greenLight text-visita-greenDark border-visita-green/40">With {ownerLabel(item)}</Chip>
                    <Chip tone={STATUS_TONE[item.status]}>{STATUS_LABEL[item.status]}</Chip>
                </span>
                <span className="truncate">from {item.created_by_name} · {whenLabel(item.updated_at)}</span>
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
                {item.patient_name && <span className="text-[11px] text-slate-500 uppercase tracking-wide font-semibold truncate">· {item.patient_name}</span>}
                <span className="ml-auto text-[10px] text-slate-400 shrink-0">{item.ref_number}</span>
            </div>
            <div className="text-sm text-slate-800 truncate">{item.message}</div>
            <div className="text-[11px] text-emerald-700 flex items-center gap-1"><Check className="w-3 h-3" /> Completed {whenLabel(item.completed_at)} · {item.completed_by}</div>
        </button>
    );
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
    const categories = meta.data?.categories || [];
    const selected = items.find((i) => i.id === selectedId) || null;
    useEffect(() => { if (selectedId && !list.isLoading && !list.isPlaceholderData && !selected) setSelectedId(null); }, [selectedId, selected, list.isLoading, list.isPlaceholderData]);
    const refresh = () => { invalidate(); list.refetch(); };
    const changeView = (k) => { setView(k); setSelectedId(null); setHistoryPages(1); };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2"><Inbox className="w-6 h-6 text-visita-green" /> Work Hub</h1>
                    <p className="text-sm text-slate-500">What needs doing · for whom · who owns it</p>
                </div>
                <Button data-testid="work-new" onClick={() => setCreating(true)} className="bg-visita-green hover:bg-visita-greenDark text-white"><Plus className="w-4 h-4 mr-1" /> New</Button>
            </div>
            <div className="flex items-center gap-2 flex-wrap mb-3">
                <div className="flex rounded-sm border border-slate-300 overflow-hidden text-sm w-full sm:w-auto sm:inline-flex" data-testid="work-views">
                    {VIEWS.map(([k, l]) => (
                        <button key={k} data-testid={`work-view-${k}`} onClick={() => changeView(k)}
                            className={`flex-1 sm:flex-none px-3 py-1.5 border-r last:border-r-0 border-slate-300 ${view === k ? "bg-visita-green text-white font-semibold" : "bg-white text-slate-600 hover:bg-slate-50"}`}>{l}</button>
                    ))}
                </div>
                {view === "sent" && (
                    <label className="inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer" data-testid="work-sent-include-completed">
                        <input type="checkbox" checked={includeCompleted} onChange={(e) => { setIncludeCompleted(e.target.checked); setSelectedId(null); }} className="accent-visita-green" /> Include completed
                    </label>
                )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-3">
                <div className={`space-y-1.5 ${selected ? "hidden md:block" : ""}`} data-testid="work-list">
                    {list.isLoading && <p className="text-sm text-slate-400">Loading…</p>}
                    {!list.isLoading && items.length === 0 && <p className="text-sm text-slate-400 py-6 text-center" data-testid="work-empty">{view === "my" ? "Nothing needs your attention." : isHistory ? "No completed items yet." : "No items."}</p>}
                    {items.map((it) => isHistory
                        ? <HistoryCard key={it.id} item={it} selected={it.id === selectedId} onClick={() => setSelectedId(it.id)} />
                        : <WorkCard key={it.id} item={it} selected={it.id === selectedId} onClick={() => setSelectedId(it.id)} />)}
                    {isHistory && list.data?.has_more && (
                        <Button variant="outline" size="sm" data-testid="work-history-load-more" disabled={list.isFetching} onClick={() => setHistoryPages((p) => p + 1)} className="w-full h-8 text-xs">{list.isFetching ? "Loading…" : "Load more"}</Button>
                    )}
                </div>
                <div className={selected ? "" : "hidden md:block"}>
                    {selected ? <WorkDetail item={selected} side={side} userId={meta.data?.user_id} members={meta.data?.members || []} queues={meta.data?.queues || []} categories={categories} documentCategories={meta.data?.document_categories || []} onChanged={refresh} onBack={() => setSelectedId(null)} />
                        : <div className="hidden md:flex h-40 items-center justify-center rounded-sm border border-dashed border-slate-300 text-sm text-slate-400">Select an item to see its history and actions.</div>}
                </div>
            </div>
            {creating && side && <NewWorkDialog side={side} categories={categories} members={meta.data?.members || []} queues={meta.data?.queues || []} userId={meta.data?.user_id} onClose={() => setCreating(false)} onDone={refresh} />}
        </div>
    );
}
