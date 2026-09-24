import { Outlet, useNavigate } from "react-router-dom";
import { Building2, LogOut } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { Logo } from "../components/Logo";

export default function PartnerLayout() {
    const { logout } = useAuth();
    const nav = useNavigate();
    return (
        <div className="min-h-screen bg-slate-50 font-plex flex flex-col">
            <header className="h-12 bg-[#0a1524] text-white flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                    <Logo variant="dark" iconClass="h-8 w-8" textClass="text-base" />
                    <span className="text-white/50 text-sm hidden sm:inline truncate">— Partner Portal</span>
                </div>
                <button data-testid="partner-logout" onClick={() => { logout(); nav("/login"); }}
                    className="flex items-center gap-1 hover:text-white text-white/70 text-sm">
                    <LogOut className="w-4 h-4" /> Logout
                </button>
            </header>
            <nav className="bg-white border-b border-slate-300 flex-shrink-0 px-4 flex gap-1">
                <span data-testid="partner-nav-profile" className="flex items-center gap-1.5 px-2 py-3 text-sm font-medium border-b-2 border-cyan-500 text-cyan-700">
                    <Building2 className="w-4 h-4" /> Organization Profile
                </span>
            </nav>
            <main className="flex-1 min-w-0 overflow-y-auto p-4 max-w-3xl w-full mx-auto">
                <Outlet />
            </main>
        </div>
    );
}
