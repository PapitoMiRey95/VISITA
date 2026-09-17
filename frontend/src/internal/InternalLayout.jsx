import { Outlet, NavLink, useNavigate } from "react-router-dom";
import {
    LayoutGrid, Pill, Calendar, Scan, MessageSquare, ClipboardCheck,
    Send, UserCheck, Settings as SettingsIcon, LogOut, Stethoscope,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useCounters } from "./hooks";

export default function InternalLayout() {
    const { user, logout } = useAuth();
    const nav = useNavigate();
    const counters = useCounters();
    const c = counters.data?.counters || {};
    const role = user?.role;
    const isPhysician = role === "physician";

    const items = isPhysician
        ? [
              { to: "/internal", icon: LayoutGrid, label: "Hub", end: true, key: null },
              { to: "/internal/rx", icon: Pill, label: "Rx", key: "rx" },
              { to: "/internal/imaging", icon: Scan, label: "Imaging", key: "imaging" },
              { to: "/internal/messages", icon: MessageSquare, label: "Messages", key: "messages" },
              { to: "/internal/tasks", icon: Send, label: "Intercom", key: null },
              { to: "/internal/referrals", icon: ClipboardCheck, label: "Referral Drop-Off", key: null },
          ]
        : [
              { to: "/internal", icon: LayoutGrid, label: "Hub", end: true, key: null },
              { to: "/internal/rx", icon: Pill, label: "Rx", key: "rx" },
              { to: "/internal/referrals", icon: ClipboardCheck, label: "Referrals", key: "referrals" },
              { to: "/internal/imaging", icon: Scan, label: "Imaging", key: "imaging" },
              { to: "/internal/messages", icon: MessageSquare, label: "Messages", key: "messages" },
              { to: "/internal/appointments", icon: Calendar, label: "Appointments", key: "appointments" },
              { to: "/internal/tasks", icon: Send, label: "Doctor Tasks", key: "doctor_tasks" },
              { to: "/internal/verifications", icon: UserCheck, label: "Verifications", key: "verifications" },
              ...(role === "admin" ? [{ to: "/internal/settings", icon: SettingsIcon, label: "Settings", key: null }] : []),
          ];

    return (
        <div className="min-h-screen bg-visita-bg font-plex flex flex-col">
            <header className="h-12 bg-visita-ribbon text-white flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded bg-visita-green flex items-center justify-center">
                        <Stethoscope className="w-4 h-4" />
                    </div>
                    <span className="font-bold tracking-tight">VISITA</span>
                    <span className="text-white/50 text-sm">— Dr. Aguayo Family Practice</span>
                </div>
                <div className="flex items-center gap-3 text-sm">
                    <span className="text-white/80">{user?.name} · <span className="uppercase text-white/50">{role}</span></span>
                    <button data-testid="internal-logout" onClick={() => { logout(); nav("/login"); }}
                        className="flex items-center gap-1 hover:text-white text-white/70">
                        <LogOut className="w-4 h-4" /> Logout
                    </button>
                </div>
            </header>

            <div className="flex flex-1 min-h-0">
                <aside className="w-52 bg-white border-r border-slate-300 flex-shrink-0 py-2 overflow-y-auto hidden md:block">
                    {items.map((it) => (
                        <NavLink
                            key={it.to}
                            to={it.to}
                            end={it.end}
                            data-testid={`sidebar-${it.label.toLowerCase().replace(/[^a-z]/g, "-")}`}
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
                    ))}
                </aside>

                <main className="flex-1 min-w-0 overflow-y-auto p-4">
                    <Outlet context={{ counters }} />
                </main>
            </div>
        </div>
    );
}
