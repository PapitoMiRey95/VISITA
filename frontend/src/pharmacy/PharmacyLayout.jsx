import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useEffect, useState, useRef, useCallback } from "react";
import { LayoutGrid, Pill, Inbox, MessageSquare, User, LogOut, AlertTriangle } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import { Logo } from "../components/Logo";
import { Button } from "../components/ui/button";
import { UnsavedGuardContext } from "../internal/unsavedGuard";

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

    const guardRef = useRef({ dirty: false, save: null });
    const setGuard = useCallback((g) => { guardRef.current = g || { dirty: false, save: null }; }, []);
    const [pending, setPending] = useState(null);

    const guarded = (proceed) => (e) => {
        if (guardRef.current?.dirty) { e?.preventDefault?.(); setPending({ proceed }); return; }
        proceed();
    };
    const doDiscard = () => { guardRef.current = { dirty: false, save: null }; const p = pending; setPending(null); p?.proceed?.(); };

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
                    <button data-testid="pharmacy-logout" onClick={guarded(() => { logout(); nav("/login"); })}
                        className="flex items-center gap-1 hover:text-white text-white/70">
                        <LogOut className="w-4 h-4" /> Logout
                    </button>
                </div>
            </header>

            <nav className="bg-white border-b border-slate-300 flex-shrink-0 px-2 flex gap-1">
                {NAV.map((it) => (
                    <NavLink key={it.to} to={it.to} end={it.end}
                        onClick={guarded(() => nav(it.to))}
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
                <UnsavedGuardContext.Provider value={{ setGuard }}>
                    <Outlet />
                </UnsavedGuardContext.Provider>
            </main>

            {pending && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" data-testid="pharmacy-unsaved-guard">
                    <div className="bg-white rounded-sm border border-slate-300 shadow-lg w-full max-w-sm p-5" role="dialog" aria-modal="true">
                        <div className="flex items-start gap-3">
                            <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                            <div>
                                <h3 className="font-semibold text-slate-900">Unsent Rx request in progress</h3>
                                <p className="text-sm text-slate-500 mt-1">You have an unsent Rx request in progress. Leaving will discard it.</p>
                            </div>
                        </div>
                        <div className="flex items-center justify-end gap-2 mt-5">
                            <Button variant="ghost" data-testid="pharmacy-guard-stay" onClick={() => setPending(null)}>Stay</Button>
                            <Button variant="outline" data-testid="pharmacy-guard-discard" onClick={doDiscard} className="border-red-200 text-red-600 hover:bg-red-50">Leave and discard</Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
