import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CalendarCheck, Pill, FileText, Share2, Receipt, UserCircle, AlertCircle, CheckCheck, ArrowLeft } from "lucide-react";
import { api } from "../lib/api";
import { Sheet, SheetContent, SheetTitle } from "../components/ui/sheet";

// Category → icon + accent. RED is reserved for action_required (true cancellation / attention needed).
const CATS = {
    appointment: { icon: CalendarCheck, cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" },
    prescription: { icon: Pill, cls: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" },
    results: { icon: FileText, cls: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300" },
    referral: { icon: Share2, cls: "bg-teal-100 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300" },
    invoice: { icon: Receipt, cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" },
    account: { icon: UserCircle, cls: "bg-slate-100 text-slate-600 dark:bg-slate-500/20 dark:text-slate-300" },
    action_required: { icon: AlertCircle, cls: "bg-red-100 text-red-600 dark:bg-red-500/15 dark:text-red-300" },
};

export function useNotifications() {
    const qc = useQueryClient();
    const q = useQuery({ queryKey: ["portal-notifications"], queryFn: async () => (await api.get("/portal/notifications")).data, refetchInterval: 60000 });
    const refresh = () => { qc.invalidateQueries({ queryKey: ["portal-notifications"] }); qc.invalidateQueries({ queryKey: ["portal-overview"] }); };
    const markAll = async () => { await api.post("/portal/notifications/read"); refresh(); };
    const markOne = async (id) => { await api.post(`/portal/notifications/${id}/read`); refresh(); };
    return { items: q.data?.items || [], unread: q.data?.unread || 0, loading: q.isLoading, markAll, markOne };
}

function bucket(iso, t) {
    const d = new Date(iso); const now = new Date();
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(now) - day(d)) / 86400000);
    if (diff <= 0) return t("portal:notif.today", "Today");
    if (diff === 1) return t("portal:notif.yesterday", "Yesterday");
    if (diff < 7) return t("portal:notif.thisWeek", "This week");
    return t("portal:notif.earlier", "Earlier");
}

function when(iso, t) {
    const d = new Date(iso); const mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return t("portal:notif.justNow", "Just now");
    if (mins < 60) return t("portal:notif.minAgo", "{{n}} min ago", { n: mins });
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const days = Math.round((day(new Date()) - day(d)) / 86400000);
    if (days <= 1) return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    if (days < 7) return d.toLocaleDateString([], { weekday: "long" });
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function NotificationFeed({ onNavigate, compact = false }) {
    const { t } = useTranslation(["portal"]);
    const nav = useNavigate();
    const { items, unread, loading, markAll, markOne } = useNotifications();
    const [tab, setTab] = useState("all");
    const list = tab === "unread" ? items.filter((n) => !n.read) : items;
    const groups = useMemo(() => {
        const g = [];
        list.forEach((n) => { const b = bucket(n.created_at, t); const last = g[g.length - 1]; if (last && last.label === b) last.items.push(n); else g.push({ label: b, items: [n] }); });
        return g;
    }, [list, t]);

    const open = async (n) => {
        if (!n.read) markOne(n.id);
        onNavigate && onNavigate();
        if (n.link) nav(n.link);
    };

    return (
        <div className="flex flex-col h-full" data-testid="notification-feed">
            <div className="flex items-center gap-5 px-1 border-b border-slate-200 dark:border-white/10">
                {[["all", t("portal:notif.all", "All")], ["unread", t("portal:notif.unread", "Unread")]].map(([k, l]) => (
                    <button key={k} type="button" data-testid={`notif-tab-${k}`} onClick={() => setTab(k)}
                        className={`relative py-2.5 text-sm font-semibold transition-colors ${tab === k ? "text-portal-blueDark dark:text-white" : "text-slate-500"}`}>
                        {l}{k === "unread" && unread > 0 && <span className="ml-1.5 text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-portal-blue text-white" data-testid="notif-unread-pill">{unread}</span>}
                        {tab === k && <span className="absolute left-0 right-0 -bottom-px h-0.5 bg-portal-blue rounded-full" />}
                    </button>
                ))}
                <div className="flex-1" />
                {unread > 0 && (
                    <button type="button" data-testid="notif-mark-all" onClick={markAll} className="text-xs font-semibold text-portal-blueDark dark:text-sky-300 flex items-center gap-1">
                        <CheckCheck className="w-3.5 h-3.5" /> {t("portal:notif.markAll", "Mark all read")}
                    </button>
                )}
            </div>

            <div className={`flex-1 overflow-y-auto ${compact ? "pr-1" : ""}`}>
                {loading && <p className="text-sm text-slate-400 px-1 py-6">{t("portal:notif.loading", "Loading…")}</p>}
                {!loading && list.length === 0 && (
                    <div className="text-center py-14 text-slate-400" data-testid="notif-empty">
                        <Bell className="w-8 h-8 mx-auto mb-2 opacity-40" />
                        <p className="text-sm">{tab === "unread" ? t("portal:notif.noUnread", "You're all caught up.") : t("portal:notif.none", "No notifications yet.")}</p>
                    </div>
                )}
                {groups.map((g) => (
                    <div key={g.label} className="pt-4" data-testid={`notif-group-${g.label.toLowerCase().replace(/\s+/g, "-")}`}>
                        <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500 px-1 mb-2">{g.label}</div>
                        <div className="space-y-2">
                            {g.items.map((n) => {
                                const c = CATS[n.category] || CATS.account; const Icon = c.icon;
                                return (
                                    <button key={n.id} type="button" data-testid={`notif-item-${n.id}`} onClick={() => open(n)}
                                        className={`w-full text-left flex items-start gap-3 rounded-2xl px-3 py-3 border transition-colors ${n.read
                                            ? "bg-white border-slate-100 dark:border-white/5 hover:border-slate-200"
                                            : "bg-white border-portal-blue/25 dark:border-sky-400/30 shadow-[0_1px_8px_rgba(37,99,235,0.08)]"}`}>
                                        <span className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${c.cls}`}><Icon className="w-4.5 h-4.5 w-[18px] h-[18px]" /></span>
                                        <span className="flex-1 min-w-0">
                                            <span className="flex items-start justify-between gap-2">
                                                <span className={`text-sm leading-tight ${n.read ? "font-semibold text-slate-700" : "font-bold text-slate-900"}`}>
                                                    {n.title}{(n.count || 1) > 1 && <span className="ml-1.5 text-[10px] font-bold text-slate-400" data-testid="notif-count">×{n.count}</span>}
                                                </span>
                                                <span className="text-[11px] text-slate-400 whitespace-nowrap shrink-0 pt-0.5">{when(n.created_at, t)}</span>
                                            </span>
                                            {n.body && <span className="block text-xs text-slate-500 mt-0.5 truncate">{n.body}</span>}
                                        </span>
                                        {!n.read && <span className="w-2 h-2 rounded-full bg-portal-blue shrink-0 mt-2" data-testid="notif-unread-dot" />}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

/** Desktop entry: compact right-side panel. */
export function NotificationPanel({ open, onOpenChange }) {
    const { t } = useTranslation(["portal"]);
    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent side="right" className="w-full sm:max-w-md p-0 flex flex-col bg-slate-50 dark:bg-[#0f1216]" data-testid="notification-panel">
                <div className="px-5 pt-5 pb-3">
                    <SheetTitle className="text-lg font-bold text-slate-900 flex items-center gap-2"><Bell className="w-5 h-5 text-portal-blue" /> {t("portal:notif.title", "Notifications")}</SheetTitle>
                </div>
                <div className="flex-1 min-h-0 px-4 pb-4"><NotificationFeed compact onNavigate={() => onOpenChange(false)} /></div>
            </SheetContent>
        </Sheet>
    );
}

/** Mobile entry: dedicated screen. */
export default function NotificationsPage() {
    const { t } = useTranslation(["portal"]);
    const nav = useNavigate();
    return (
        <div className="max-w-xl mx-auto" data-testid="notifications-page">
            <div className="flex items-center gap-2 mb-2">
                <button type="button" onClick={() => nav(-1)} data-testid="notif-back" className="p-2 -ml-2 rounded-full hover:bg-slate-100 text-slate-700"><ArrowLeft className="w-5 h-5" /></button>
                <h1 className="flex-1 text-center text-base font-bold text-slate-900 pr-9">{t("portal:notif.title", "Notifications")}</h1>
            </div>
            <NotificationFeed />
        </div>
    );
}
