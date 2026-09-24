import { Outlet, useNavigate, NavLink, useLocation } from "react-router-dom";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Home, Calendar, Pill, MessageSquare, ClipboardList, Bell, LogOut, User } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Logo } from "../components/Logo";

const NAV = [
    { to: "/portal", icon: Home, tkey: "portal:nav.home", end: true, testid: "nav-home" },
    { to: "/portal/appointments", icon: Calendar, tkey: "portal:nav.appts", testid: "nav-appointments" },
    { to: "/portal/prescriptions", icon: Pill, tkey: "portal:nav.rx", testid: "nav-prescriptions" },
    { to: "/portal/messages", icon: MessageSquare, tkey: "portal:nav.messages", testid: "nav-messages" },
    { to: "/portal/requests", icon: ClipboardList, tkey: "portal:nav.requests", testid: "nav-requests" },
    { to: "/portal/account", icon: User, tkey: "portal:nav.profile", testid: "nav-profile" },
];

export default function PortalLayout() {
    const { user, logout } = useAuth();
    const { t } = useTranslation(["portal"]);
    const nav = useNavigate();
    const loc = useLocation();

    const overview = useQuery({
        queryKey: ["overview"],
        queryFn: async () => (await api.get("/portal/overview")).data,
    });
    const cfg = useQuery({
        queryKey: ["public-settings"],
        queryFn: async () => (await api.get("/settings/public")).data,
    });

    const unread = (overview.data?.notifications || []).filter((n) => !n.read).length;

    const outletCtx = useMemo(
        () => ({ overview, cfg, refetch: overview.refetch }),
        [overview, cfg]
    );

    return (
        <div className="min-h-screen bg-portal-blue/5 font-nunito flex flex-col">
            <header className="sticky top-0 z-20 bg-white border-b border-slate-200 px-4 py-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Logo variant="light" iconClass="h-8 w-8" textClass="text-lg" />
                </div>
                <div className="flex items-center gap-1">
                    <button
                        data-testid="portal-notifications"
                        onClick={() => nav("/portal/account")}
                        className="relative p-2 rounded-full hover:bg-slate-100"
                    >
                        <Bell className="w-5 h-5 text-slate-600" />
                        {unread > 0 && (
                            <span className="absolute top-0 right-0 bg-red-500 text-white text-[10px] w-4 h-4 rounded-full flex items-center justify-center">
                                {unread}
                            </span>
                        )}
                    </button>
                    <button data-testid="portal-account-btn" onClick={() => nav("/portal/account")}
                        className="p-2 rounded-full hover:bg-slate-100 text-sm font-bold text-portal-blueDark">
                        {user?.name?.[0] || "P"}
                    </button>
                    <button data-testid="portal-logout" onClick={() => { logout(); nav("/login"); }}
                        className="p-2 rounded-full hover:bg-slate-100">
                        <LogOut className="w-5 h-5 text-slate-600" />
                    </button>
                </div>
            </header>

            <main className="flex-1 w-full max-w-lg mx-auto px-4 py-5 pb-24">
                <Outlet context={outletCtx} />
            </main>

            <nav className="fixed bottom-0 inset-x-0 z-20 bg-white border-t border-slate-200 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)]">
                <div className="max-w-lg mx-auto flex justify-around">
                    {NAV.map((n) => {
                        const active = n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to);
                        return (
                            <NavLink key={n.to} to={n.to} end={n.end} data-testid={n.testid}
                                className="flex flex-col items-center justify-center gap-0.5 py-2 min-h-[56px] flex-1">
                                <n.icon className={`w-5 h-5 ${active ? "text-portal-blue" : "text-slate-400"}`} />
                                <span className={`text-[11px] font-semibold ${active ? "text-portal-blue" : "text-slate-400"}`}>{t(n.tkey)}</span>
                            </NavLink>
                        );
                    })}
                </div>
            </nav>
        </div>
    );
}
