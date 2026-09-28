import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { LayoutGrid, Pill, Inbox, MessageSquare, User, LogOut } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import { Logo } from "../components/Logo";

const NAV = [
    { to: "/pharmacy", icon: LayoutGrid, label: "Hub", end: true },
    { to: "/pharmacy/incoming", icon: Inbox, label: "Incoming Rx", badge: "incoming" },
    { to: "/pharmacy/rx", icon: Pill, label: "Rx Requests" },
    { to: "/pharmacy/messages", icon: MessageSquare, label: "Messages" },
    { to: "/pharmacy/account", icon: User, label: "Account" },
];

export default function PharmacyLayout() {
    const { user, logout } = useAuth();
    const nav = useNavigate();
    const [unviewed, setUnviewed] = useState(0);

    useEffect(() => {
        let alive = true;
        const poll = () => api.get("/pharmacy/incoming").then(({ data }) => { if (alive) setUnviewed(data.unviewed || 0); }).catch(() => {});
        poll();
        const t = setInterval(poll, 60000);
        return () => { alive = false; clearInterval(t); };
    }, []);

    return (
        <div className="min-h-screen bg-visita-bg font-plex flex flex-col">
            <header className="h-12 bg-visita-ribbon text-white flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                    <Logo variant="dark" iconClass="h-8 w-8" textClass="text-base" />
                    <span className="text-white/50 text-sm hidden sm:inline truncate">— Pharmacy Portal</span>
                </div>
                <div className="flex items-center gap-3 text-sm min-w-0">
                    <span className="text-white/80 truncate hidden xs:inline" data-testid="pharmacy-name">{user?.pharmacy_name}</span>
                    <button data-testid="pharmacy-logout" onClick={() => { logout(); nav("/login"); }}
                        className="flex items-center gap-1 hover:text-white text-white/70">
                        <LogOut className="w-4 h-4" /> Logout
                    </button>
                </div>
            </header>

            <nav className="bg-white border-b border-slate-300 flex-shrink-0 px-2 flex gap-1">
                {NAV.map((it) => (
                    <NavLink key={it.to} to={it.to} end={it.end}
                        data-testid={`pharmacy-nav-${it.label.toLowerCase()}`}
                        className={({ isActive }) =>
                            `flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                                isActive ? "border-visita-green text-visita-greenDark" : "border-transparent text-slate-600 hover:text-slate-900"
                            }`
                        }>
                        <it.icon className="w-4 h-4" /> {it.label}
                        {it.badge === "incoming" && unviewed > 0 && (
                            <span className="bg-red-600 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] px-1 flex items-center justify-center" data-testid="pharmacy-incoming-badge">{unviewed}</span>
                        )}
                    </NavLink>
                ))}
            </nav>

            <main className="flex-1 min-w-0 overflow-y-auto p-4 max-w-4xl w-full mx-auto">
                <Outlet />
            </main>
        </div>
    );
}
