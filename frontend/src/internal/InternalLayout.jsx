import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useState, useRef, useCallback } from "react";
import {
    ClipboardList, Pill, Calendar, Scan, Droplet, MessageSquare, ClipboardCheck,
    Send, UserCheck, UserPlus, CalendarDays, Settings as SettingsIcon, LogOut, UserSearch, Menu, Building2, Stethoscope, Users, Receipt, AlertTriangle,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useCounters } from "./hooks";
import { Logo } from "../components/Logo";
import { Button } from "../components/ui/button";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "../components/ui/sheet";
import { UnsavedGuardContext } from "./unsavedGuard";

export default function InternalLayout() {
    const { user, logout } = useAuth();
    const nav = useNavigate();
    const counters = useCounters();
    const c = counters.data?.counters || {};
    const role = user?.role;
    const isPhysician = role === "physician";
    const [mobileOpen, setMobileOpen] = useState(false);

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
              { to: "/internal/imaging", icon: Scan, label: "Imaging", key: "imaging" },
              { to: "/internal/bloodwork", icon: Droplet, label: "Bloodwork", key: "bloodwork" },
              { to: "/internal/messages", icon: MessageSquare, label: "Messages", key: "messages" },
              { to: "/internal/applications", icon: UserPlus, label: "Applications", key: "applications" },
              { to: "/internal/calendar", icon: CalendarDays, label: "Calendar", key: null },
              { to: "/internal/private-requests", icon: Users, label: "Private Requests", key: null },
              { to: "/internal/billing", icon: Receipt, label: "Billing", key: null },
              { to: "/internal/tasks", icon: Send, label: "Intercom", key: "doctor_tasks" },
              { to: "/internal/referrals", icon: ClipboardCheck, label: "Referral Drop-Off", key: null },
              { to: "/internal/verifications", icon: UserCheck, label: "Verifications", key: "verifications" },
              { to: "/internal/providers", icon: Stethoscope, label: "Providers", key: null },
              { to: "/internal/settings", icon: SettingsIcon, label: "Settings", key: null },
          ]
        : [
              { to: "/internal", icon: ClipboardList, label: "Hub", end: true, key: null, iconClass: "text-pink-600" },
              { to: "/internal/patients", icon: UserSearch, label: "Patients", key: null },
              { to: "/internal/rx", icon: Pill, label: "Rx", key: "rx" },
              { to: "/internal/referrals", icon: ClipboardCheck, label: "Referrals", key: "referrals" },
              { to: "/internal/imaging", icon: Scan, label: "Imaging", key: "imaging" },
              { to: "/internal/bloodwork", icon: Droplet, label: "Bloodwork", key: "bloodwork" },
              { to: "/internal/messages", icon: MessageSquare, label: "Messages", key: "messages" },
              { to: "/internal/appointments", icon: Calendar, label: "Appointments", key: "appointments" },
              { to: "/internal/private-requests", icon: Users, label: "Private Requests", key: null },
              { to: "/internal/billing", icon: Receipt, label: "Billing", key: null },
              { to: "/internal/calendar", icon: CalendarDays, label: "Calendar", key: null },
              { to: "/internal/tasks", icon: Send, label: "Intercom", key: "doctor_tasks" },
              { to: "/internal/verifications", icon: UserCheck, label: "Verifications", key: "verifications" },
              { to: "/internal/applications", icon: UserPlus, label: "Applications", key: "applications" },
              { to: "/internal/organizations", icon: Building2, label: "Organizations", key: null },
              { to: "/internal/providers", icon: Stethoscope, label: "Providers", key: null },
              ...(role === "admin" ? [{ to: "/internal/settings", icon: SettingsIcon, label: "Settings", key: null }] : []),
          ];

    const renderNav = (onNavigate, prefix = "sidebar") => items.map((it) => (
        <NavLink
            key={it.to}
            to={it.to}
            end={it.end}
            onClick={guarded(() => { nav(it.to); onNavigate?.(); })}
            data-testid={`${prefix}-${it.label.toLowerCase().replace(/[^a-z]/g, "-")}`}
            className={({ isActive }) =>
                `flex items-center justify-between px-3 py-2 mx-2 my-0.5 rounded-sm text-sm font-medium transition-colors duration-75 ${
                    isActive ? "bg-visita-green text-white" : "text-slate-700 hover:bg-visita-greenLight"
                }`
            }
        >
            <span className="flex items-center gap-2">
                <it.icon className={`w-4 h-4 ${it.iconClass || ""}`} /> {it.label}
            </span>
            {it.key && c[it.key] > 0 && (
                <span className="bg-red-600 text-white text-xs font-bold rounded-full min-w-[20px] h-5 px-1 flex items-center justify-center">
                    {c[it.key]}
                </span>
            )}
        </NavLink>
    ));

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
                    <span className="text-white/80 hidden sm:inline">{user?.name} · <span className="uppercase text-white/50">{role}</span></span>
                    <button data-testid="internal-logout" onClick={guarded(() => { logout(); nav("/login"); })}
                        className="flex items-center gap-1 hover:text-white text-white/70">
                        <LogOut className="w-4 h-4" /> Logout
                    </button>
                </div>
            </header>

            <div className="flex flex-1 min-h-0">
                <aside className="w-52 bg-white border-r border-slate-300 flex-shrink-0 py-2 overflow-y-auto hidden md:block">
                    {renderNav()}
                </aside>

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
