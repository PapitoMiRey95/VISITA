import { useAuth } from "../context/AuthContext";
import { Link } from "react-router-dom";
import { Building2, User, KeyRound, LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";

function Row({ label, children }) {
    return (
        <div className="flex justify-between gap-2 border-b border-slate-100 py-2">
            <span className="text-slate-400 text-xs uppercase tracking-wide">{label}</span>
            <span className="text-slate-800 text-right font-medium">{children}</span>
        </div>
    );
}

export default function PharmacyAccount() {
    const { user, logout } = useAuth();
    const nav = useNavigate();

    return (
        <div className="animate-fade-in max-w-lg">
            <div className="flex items-center gap-2 mb-4">
                <Building2 className="w-5 h-5 text-visita-green" />
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Account</h1>
            </div>

            <div className="bg-white border border-slate-300 rounded-sm p-5 space-y-1" data-testid="pharmacy-account-card">
                <Row label="Pharmacy">{user?.pharmacy_name || "—"}</Row>
                <Row label="Username"><span className="inline-flex items-center gap-1"><User className="w-3.5 h-3.5 text-slate-400" />{user?.username || user?.name}</span></Row>
                <Row label="Role">Pharmacy</Row>
            </div>

            <p className="text-xs text-slate-500 mt-3 leading-relaxed">
                Your pharmacy is fixed to <b>{user?.pharmacy_name}</b>. To change any account details, contact the clinic.
            </p>

            <div className="flex gap-2 mt-5">
                <Button asChild variant="outline" data-testid="pharmacy-change-password">
                    <Link to="/change-password"><KeyRound className="w-4 h-4 mr-1" /> Change password</Link>
                </Button>
                <Button variant="outline" onClick={() => { logout(); nav("/login"); }} data-testid="pharmacy-account-logout">
                    <LogOut className="w-4 h-4 mr-1" /> Logout
                </Button>
            </div>
        </div>
    );
}
