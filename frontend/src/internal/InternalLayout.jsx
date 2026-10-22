import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useState, useRef, useCallback } from "react";
import {
    ClipboardList, Pill, Calendar, MessageSquare, ClipboardCheck,
    Send, UserCheck, UserPlus, CalendarDays, Settings as SettingsIcon, LogOut, UserSearch, Menu, Building2, Stethoscope, Users, Receipt, AlertTriangle, Truck, Contact, QrCode, ShieldCheck, Microscope, CreditCard, LayoutGrid, ChevronsLeft, ChevronsRight,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useCounters } from "./hooks";
import { usePlatformConfig, NAV_FEATURE } from "../lib/platform";
import { api, setToken } from "../lib/api";
const WORKSPACE_NAV = {
    patients: ["/internal/patients", "/internal/registration-qr"], calendar: ["/internal/calendar", "/internal/appointments"],
    messages: ["/internal/messages", "/internal/tasks", "/internal/work"], registration: ["/internal/applications", "/internal/verifications", "/internal/portal-access-requests", "/internal/health-card-updates", "/internal/registration-qr"],
    rx: ["/internal/rx", "/internal/send-rx"], billing: ["/internal/billing", "/internal/private-requests"],
};
import { ThemeToggle } from "../components/ThemeToggle";
import { Logo } from "../components/Logo";
import { Button } from "../components/ui/button";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "../components/ui/sheet";
import { UnsavedGuardContext } from "./unsavedGuard";

export default function InternalLayout() {
    const { user, logout } = useAuth();
    const nav = useNavigate();
    const role = user?.role;
    const counters = useCounters();
    const c = counters.data?.counters || {};
    const isPhysician = role === "physician";
    const [mobileOpen, setMobileOpen] = useState(false);
    const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vien.sidebar.collapsed") === "1");
    const toggleCollapsed = () => setCollapsed((v) => { localStorage.setItem("vien.sidebar.collapsed", v ? "0" : "1"); return !v; });

    const guardRef = useRef({ dirty: false, save: null });
    const setGuard = useCallback((g) => { guardRef.current = g || { dirty: false, save: null }; }, []);
    const [pending, setPending] = useState(null); // { proceed: () => void }
    const [saving, setSaving] = useState(false);

    // Intercept a navigation/logout action if the current page has unsaved edits.
    const guarded = (proceed) => (e) => {
        if (guardRef.current?.dirty) {
            e?.preventDefault?.();
            setPending({ proceed });
            return;
        }
        proceed();
    };
    const doSaveThenProceed = async () => {
        const save = guardRef.current?.save;
        if (!save) { setPending(null); return; }
        setSaving(true);
        try {
            const ok = await save();
            if (ok) { const p = pending; setPending(null); p?.proceed?.(); }
        } finally { setSaving(false); }
    };
    const doDiscard = () => { guardRef.current = { dirty: false, save: null }; const p = pending; setPending(null); p?.proceed?.(); };

    const items = isPhysician
        ? [
              { to: "/internal", icon: ClipboardList, label: "Hub", end: true, key: null, iconClass: "text-pink-600" },
              { to: "/internal/patients", icon: UserSearch, label: "Patients", key: null },
              { to: "/internal/rx", icon: Pill, label: "Rx", key: "rx" },
              { to: "/internal/send-rx", icon: Truck, label: "Send Rx to Pharmacy", key: null },
              { to: "/internal/exams", icon: Microscope, label: "Results to Review", key: "results_review" },
              { to: "/internal/messages", icon: MessageSquare, label: "Messages", key: "messages" },
              { to: "/internal/applications", icon: UserPlus, label: "Applications", key: "applications" },
              { to: "/internal/portal-access-requests", icon: ShieldCheck, label: "Portal Access", key: "portal_access" },
              { to: "/internal/health-card-updates", icon: CreditCard, label: "Health Card Updates", key: "health_card_updates" },
              { to: "/internal/registration-qr", icon: QrCode, label: "Registration QR", key: null },
              { to: "/internal/calendar", icon: CalendarDays, label: "Calendar", key: null },
              { to: "/internal/private-requests", icon: Users, label: "Private Requests", key: null },
              { to: "/internal/billing", icon: Receipt, label: "Billing", key: null },
              { to: "/internal/work", icon: Send, label: "Work Hub", key: "work_hub" },
              { to: "/internal/referrals", icon: ClipboardCheck, label: "Referral Drop-Off", key: null },
              { to: "/internal/verifications", icon: UserCheck, label: "Verifications", key: "verifications" },
              { to: "/internal/providers", icon: Stethoscope, label: "Providers", key: null },
              { to: "/internal/professionals", icon: Contact, label: "Professional profile", key: null },
              { to: "/internal/clinic", icon: Building2, label: "Clinic profile", key: null },
              { to: "/internal/settings", icon: SettingsIcon, label: "Settings", key: null },
          ]
        : [
              { to: "/internal", icon: ClipboardList, label: "Hub", end: true, key: null, iconClass: "text-pink-600" },
              { to: "/internal/patients", icon: UserSearch, label: "Patients", key: null },
              { to: "/internal/rx", icon: Pill, label: "Rx", key: "rx" },
              { to: "/internal/send-rx", icon: Truck, label: "Send Rx to Pharmacy", key: null },
              { to: "/internal/referrals", icon: ClipboardCheck, label: "Referrals", key: "referrals" },
              { to: "/internal/exams", icon: Microscope, label: "Exams & Results", key: "exams" },
              { to: "/internal/messages", icon: MessageSquare, label: "Messages", key: "messages" },
              { to: "/internal/appointments", icon: Calendar, label: "Appointments", key: "appointments" },
              { to: "/internal/private-requests", icon: Users, label: "Private Requests", key: null },
              { to: "/internal/billing", icon: Receipt, label: "Billing", key: null },
              { to: "/internal/calendar", icon: CalendarDays, label: "Calendar", key: null },
              { to: "/internal/work", icon: Send, label: "Work Hub", key: "work_hub" },
              { to: "/internal/verifications", icon: UserCheck, label: "Verifications", key: "verifications" },
              { to: "/internal/applications", icon: UserPlus, label: "Applications", key: "applications" },
              { to: "/internal/portal-access-requests", icon: ShieldCheck, label: "Portal Access", key: "portal_access" },
              { to: "/internal/health-card-updates", icon: CreditCard, label: "Health Card Updates", key: "health_card_updates" },
              { to: "/internal/registration-qr", icon: QrCode, label: "Registration QR", key: null },
              { to: "/internal/organizations", icon: Building2, label: "Organizations", key: null },
              { to: "/internal/providers", icon: Stethoscope, label: "Providers", key: null },
              { to: "/internal/professionals", icon: Contact, label: "Professional profile", key: null },
              { to: "/internal/clinic", icon: Building2, label: "Clinic profile", key: null },
              ...(role === "admin" ? [{ to: "/internal/settings", icon: SettingsIcon, label: "Settings", key: null }] : []),
          ];

    // Permanent quick-access set; everything else lives inside the Central Work Hub drawer.
    const { navVisible } = usePlatformConfig();
    const audience = role === "physician" ? "physician" : "staff";
    const ws = user?.workspace;
    const wsItems = ws ? items.filter((it) => it.to === "/internal" || (user.allowed_modules || []).some((m) => (WORKSPACE_NAV[m] || []).includes(it.to))) : items;
    const netItem = !ws && ["physician", "admin", "staff"].includes(role) && navVisible("network", audience, role) ? [{ to: "/network", icon: Building2, label: "VIen Network", key: null }] : [];
    const visibleItems = [...wsItems, ...netItem].filter((it) => !NAV_FEATURE[it.to] || navVisible(NAV_FEATURE[it.to], audience, role));
    const QUICK = new Set(["/internal/patients", "/internal/work", "/internal/rx", "/internal/send-rx", "/internal/exams", "/internal/calendar", "/network", "/internal/verifications",
                           "/internal/registration-qr", "/internal/clinic", "/internal/settings"]);
    // Physicians keep Verifications inside All Queues; staff/admin see it in the quick sidebar.
    const isQuick = (it) => QUICK.has(it.to) && !(isPhysician && it.to === "/internal/verifications");
    const quickItems = visibleItems.filter(isQuick);
    const hubItems = visibleItems.filter((it) => !isQuick(it));
    const hubBadge = hubItems.reduce((n, it) => n + (it.key && c[it.key] > 0 ? c[it.key] : 0), 0);
    const [hubOpen, setHubOpen] = useState(false);

    const renderItem = (it, onNavigate, prefix, compact = false) => (
        <NavLink
            key={it.to}
            to={it.to}
            end={it.end}
            title={compact ? it.label : undefined}
            onClick={guarded(() => { nav(it.to); onNavigate?.(); })}
            data-testid={`${prefix}-${it.label.toLowerCase().replace(/[^a-z]/g, "-")}`}
            className={({ isActive }) =>
                `relative flex items-center ${compact ? "justify-center px-0 py-2.5 mx-1.5" : "justify-between px-3 py-2 mx-2"} my-0.5 rounded-sm text-sm font-medium transition-colors duration-75 ${
                    isActive ? "bg-visita-green text-white" : "text-slate-700 hover:bg-visita-greenLight"
                }`
            }
        >
            <span className="flex items-center gap-2">
                <it.icon className={`${compact ? "w-5 h-5" : "w-4 h-4"} ${it.iconClass || ""}`} /> {!compact && it.label}
            </span>
            {it.key && c[it.key] > 0 && (
                <span className={`bg-red-600 text-white text-xs font-bold rounded-full min-w-[20px] h-5 px-1 flex items-center justify-center ${compact ? "absolute -top-0.5 -right-0.5 scale-[0.8]" : ""}`}>
                    {c[it.key]}
                </span>
            )}
        </NavLink>
    );

    const workHubButton = (onNavigate, prefix, compact = false) => (
        <button key="work-hub" type="button" data-testid={`${prefix}-work-hub`} onClick={() => { onNavigate?.(); setHubOpen(true); }} title={compact ? "All Queues" : undefined}
            className={`relative flex items-center my-0.5 rounded-sm text-sm font-semibold text-visita-greenDark bg-visita-greenLight/60 hover:bg-visita-greenLight border border-visita-green/30 transition-colors duration-75 ${compact ? "w-[calc(100%-0.75rem)] justify-center px-0 py-2.5 mx-1.5" : "w-[calc(100%-1rem)] justify-between px-3 py-2 mx-2"}`}>
            <span className="flex items-center gap-2"><LayoutGrid className={compact ? "w-5 h-5" : "w-4 h-4"} /> {!compact && "All Queues"}</span>
            {hubBadge > 0 && (
                <span className={`bg-red-600 text-white text-xs font-bold rounded-full min-w-[20px] h-5 px-1 flex items-center justify-center ${compact ? "absolute -top-0.5 -right-0.5 scale-[0.8]" : ""}`} data-testid={`${prefix}-work-hub-badge`}>
                    {hubBadge}
                </span>
            )}
        </button>
    );

    // Sidebar order: Patients, Work Hub, Calendar, then the remaining quick items, All Queues, Settings, Network.
    const QUICK_ORDER = ["/internal/patients", "/internal/work", "/internal/calendar"];
    const renderNav = (onNavigate, prefix = "sidebar", compact = false) => {
        const first = QUICK_ORDER.map((to) => quickItems.find((it) => it.to === to)).filter(Boolean);
        const TAIL = ["/internal/clinic", "/internal/settings", "/network"];
        const rest = quickItems.filter((it) => !QUICK_ORDER.includes(it.to) && !TAIL.includes(it.to));
        const tail = TAIL.map((to) => quickItems.find((it) => it.to === to)).filter(Boolean);
        return [...first.map((it) => renderItem(it, onNavigate, prefix, compact)), ...rest.map((it) => renderItem(it, onNavigate, prefix, compact)),
            workHubButton(onNavigate, prefix, compact), ...tail.map((it) => renderItem(it, onNavigate, prefix, compact))];
    };

    return (
        <div className="min-h-screen bg-visita-bg font-plex flex flex-col">
            <header className="h-12 bg-visita-ribbon text-white flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2">
                    <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
                        <SheetTrigger asChild>
                            <button data-testid="internal-mobile-menu" aria-label="Open menu"
                                className="md:hidden -ml-1 mr-1 p-1 text-white/80 hover:text-white">
                                <Menu className="w-5 h-5" />
                            </button>
                        </SheetTrigger>
                        <SheetContent side="left" className="w-64 p-0 bg-white overflow-y-auto" data-testid="internal-mobile-nav">
                            <SheetTitle className="sr-only">Navigation</SheetTitle>
                            <div className="h-12 bg-visita-ribbon flex items-center px-4">
                                <Logo variant="dark" iconClass="h-7 w-7" textClass="text-base" />
                            </div>
                            <div className="py-2">{renderNav(() => setMobileOpen(false), "mobile-sidebar")}</div>
                        </SheetContent>
                    </Sheet>
                    <Logo variant="dark" iconClass="h-8 w-8" textClass="text-base" />
                </div>
                <div className="flex items-center gap-3 text-sm">
                    {user?.workspace ? (
                        <span className="hidden sm:inline-flex items-center gap-2 text-xs" data-testid="workspace-banner">
                            <span className="px-2 py-0.5 rounded-sm bg-emerald-500/25 text-emerald-100 font-bold uppercase tracking-wide">Workspace</span>
                            <span className="text-white/90">{user.workspace.org_name} · {user.workspace.role_title} · {user.name}</span>
                            <button type="button" className="underline text-white/80" data-testid="workspace-exit" onClick={async () => { const { data } = await api.post("/network/workspace/exit"); setToken(data.token); window.location.assign("/network"); }}>Exit workspace</button>
                        </span>
                    ) : <span className="text-white/80 hidden sm:inline">{user?.name} · <span className="capitalize text-white/50">{role}</span></span>}
                    <ThemeToggle className="border-white/30 text-white/80 hover:bg-white/10" />
                    <button data-testid="internal-logout" onClick={guarded(() => { logout(); nav("/login"); })}
                        className="flex items-center gap-1 hover:text-white text-white/70">
                        <LogOut className="w-4 h-4" /> Logout
                    </button>
                </div>
            </header>

            <div className="flex flex-1 min-h-0">
                <aside className={`${collapsed ? "w-14" : "w-52"} bg-white border-r border-slate-300 flex-shrink-0 py-2 overflow-y-auto hidden md:flex md:flex-col transition-[width] duration-150`} data-testid="internal-sidebar" data-collapsed={collapsed ? "1" : "0"}>
                    <div className="flex-1">{renderNav(undefined, "sidebar", collapsed)}</div>
                    {!collapsed && counters.data?.registered_patients != null && (
                        <div className="mx-3 mt-3 mb-1 border-t border-slate-200 pt-2 flex items-center justify-between text-[11px] text-slate-500" data-testid="registered-patients-total" title="Verified, active portal patients in this practice">
                            <span className="flex items-center gap-1"><Users className="w-3.5 h-3.5" /> Registered patients</span>
                            <span className="font-mono font-bold text-slate-800 text-sm">{counters.data.registered_patients.toLocaleString()}</span>
                        </div>
                    )}
                    <button type="button" onClick={toggleCollapsed} data-testid="sidebar-collapse-toggle"
                        title={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                        className={`mx-2 mt-2 flex items-center ${collapsed ? "justify-center" : "justify-end gap-1 px-2"} py-1.5 rounded-sm text-[11px] text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors`}>
                        {collapsed ? <ChevronsRight className="w-4 h-4" /> : <><span>Collapse</span><ChevronsLeft className="w-4 h-4" /></>}
                    </button>
                </aside>

                <Sheet open={hubOpen} onOpenChange={setHubOpen}>
                    <SheetContent side="left" className="w-80 p-0 bg-white overflow-y-auto" data-testid="work-hub-drawer">
                        <div className="h-12 bg-visita-ribbon flex items-center gap-2 px-4 text-white">
                            <LayoutGrid className="w-5 h-5" />
                            <SheetTitle className="text-white text-base font-semibold">All Queues</SheetTitle>
                        </div>
                        <p className="px-4 pt-3 pb-1 text-xs text-slate-500">All clinic tools you're authorized to use. Quick-access items stay in the sidebar.</p>
                        <div className="py-2" data-testid="work-hub-items">
                            {hubItems.map((it) => renderItem(it, () => setHubOpen(false), "workhub"))}
                        </div>
                    </SheetContent>
                </Sheet>

                <main className="flex-1 min-w-0 overflow-y-auto p-4">
                    <UnsavedGuardContext.Provider value={{ setGuard }}>
                        <Outlet context={{ counters }} />
                    </UnsavedGuardContext.Provider>
                </main>
            </div>

            {pending && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" data-testid="unsaved-guard-overlay">
                    <div className="bg-white rounded-sm border border-slate-300 shadow-lg w-full max-w-sm p-5" role="dialog" aria-modal="true">
                        <div className="flex items-start gap-3">
                            <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                            <div>
                                <h3 className="font-semibold text-slate-900">Unsaved changes</h3>
                                <p className="text-sm text-slate-500 mt-1">You have unsaved changes on this page. What would you like to do before leaving?</p>
                            </div>
                        </div>
                        <div className="flex items-center justify-end gap-2 mt-5">
                            <Button variant="ghost" data-testid="unsaved-cancel" onClick={() => setPending(null)} disabled={saving}>Cancel</Button>
                            <Button variant="outline" data-testid="unsaved-discard" onClick={doDiscard} disabled={saving} className="border-red-200 text-red-600 hover:bg-red-50">Discard</Button>
                            <Button data-testid="unsaved-save" onClick={doSaveThenProceed} disabled={saving} className="bg-visita-green hover:bg-visita-greenDark text-white">
                                {saving ? "Saving…" : "Save & leave"}
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
