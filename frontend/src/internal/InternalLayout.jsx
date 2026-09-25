import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useState } from "react";
import {
    LayoutGrid, Pill, Calendar, Scan, Droplet, MessageSquare, ClipboardCheck,
    Send, UserCheck, UserPlus, CalendarDays, Settings as SettingsIcon, LogOut, UserSearch, Menu, Building2, Stethoscope, HeartPulse,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useCounters } from "./hooks";
import { Logo } from "../components/Logo";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "../components/ui/sheet";

export default function InternalLayout() {
    const { user, logout } = useAuth();
    const nav = useNavigate();
    const counters = useCounters();
    const c = counters.data?.counters || {};
    const role = user?.role;
    const isPhysician = role === "physician";
    const [mobileOpen, setMobileOpen] = useState(false);

    const items = isPhysician
        ? [
              { to: "/internal", icon: LayoutGrid, label: "Hub", end: true, key: null },
              { to: "/internal/patients", icon: UserSearch, label: "Patients", key: null },
              { to: "/internal/rx", icon: Pill, label: "Rx", key: "rx" },
              { to: "/internal/imaging", icon: Scan, label: "Imaging", key: "imaging" },
              { to: "/internal/bloodwork", icon: Droplet, label: "Bloodwork", key: "bloodwork" },
              { to: "/internal/messages", icon: MessageSquare, label: "Messages", key: "messages" },
              { to: "/internal/applications", icon: UserPlus, label: "Applications", key: "applications" },
              { to: "/internal/calendar", icon: CalendarDays, label: "Calendar", key: null },
              { to: "/internal/private-requests", icon: HeartPulse, label: "Private Requests", key: null },
              { to: "/internal/tasks", icon: Send, label: "Intercom", key: "doctor_tasks" },
              { to: "/internal/referrals", icon: ClipboardCheck, label: "Referral Drop-Off", key: null },
              { to: "/internal/providers", icon: Stethoscope, label: "Providers", key: null },
          ]
        : [
              { to: "/internal", icon: LayoutGrid, label: "Hub", end: true, key: null },
              { to: "/internal/patients", icon: UserSearch, label: "Patients", key: null },
              { to: "/internal/rx", icon: Pill, label: "Rx", key: "rx" },
              { to: "/internal/referrals", icon: ClipboardCheck, label: "Referrals", key: "referrals" },
              { to: "/internal/imaging", icon: Scan, label: "Imaging", key: "imaging" },
              { to: "/internal/bloodwork", icon: Droplet, label: "Bloodwork", key: "bloodwork" },
              { to: "/internal/messages", icon: MessageSquare, label: "Messages", key: "messages" },
              { to: "/internal/appointments", icon: Calendar, label: "Appointments", key: "appointments" },
              { to: "/internal/private-requests", icon: HeartPulse, label: "Private Requests", key: null },
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
            onClick={onNavigate}
            data-testid={`${prefix}-${it.label.toLowerCase().replace(/[^a-z]/g, "-")}`}
            className={({ isActive }) =>
                `flex items-center justify-between px-3 py-2 mx-2 my-0.5 rounded-sm text-sm font-medium transition-colors duration-75 ${
                    isActive ? "bg-visita-green text-white" : "text-slate-700 hover:bg-visita-greenLight"
                }`
            }
        >
            <span className="flex items-center gap-2">
                <it.icon className="w-4 h-4" /> {it.label}
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
                    <span className="text-white/50 text-sm hidden sm:inline">— Dr. Aguayo Family Practice</span>
                </div>
                <div className="flex items-center gap-3 text-sm">
                    <span className="text-white/80 hidden sm:inline">{user?.name} · <span className="uppercase text-white/50">{role}</span></span>
                    <button data-testid="internal-logout" onClick={() => { logout(); nav("/login"); }}
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
                    <Outlet context={{ counters }} />
                </main>
            </div>
        </div>
    );
}
