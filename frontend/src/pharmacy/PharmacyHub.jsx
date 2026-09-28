import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Inbox, Pill, MessageSquare, User, ArrowRight, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";

const Card = ({ to, icon: Icon, title, desc, badge, testId }) => (
    <Link to={to} data-testid={testId}
        className="group bg-white border border-slate-300 rounded-sm p-5 flex items-start gap-4 hover:border-visita-green hover:shadow-sm transition-colors">
        <div className="w-10 h-10 rounded-sm bg-visita-green/10 text-visita-greenDark flex items-center justify-center flex-shrink-0">
            <Icon className="w-5 h-5" />
        </div>
        <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
                <h3 className="font-semibold text-slate-900">{title}</h3>
                {badge > 0 && <span className="bg-red-600 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] px-1 flex items-center justify-center">{badge}</span>}
            </div>
            <p className="text-sm text-slate-500 mt-0.5">{desc}</p>
        </div>
        <ArrowRight className="w-4 h-4 text-slate-300 group-hover:text-visita-green mt-1 flex-shrink-0" />
    </Link>
);

export default function PharmacyHub() {
    const { user } = useAuth();
    const [unviewed, setUnviewed] = useState(0);

    useEffect(() => {
        api.get("/pharmacy/incoming").then(({ data }) => setUnviewed(data.unviewed || 0)).catch(() => {});
    }, []);

    return (
        <div className="animate-fade-in" data-testid="pharmacy-hub">
            <div className="flex items-center gap-3 mb-1">
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Pharmacy Hub</h1>
                <span className="inline-flex items-center gap-1 text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5 text-xs font-semibold" data-testid="pharmacy-verified">
                    <ShieldCheck className="w-3.5 h-3.5" /> Verified
                </span>
            </div>
            <p className="text-slate-500 mb-6">{user?.pharmacy_name} — VIen EMR Network</p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Card to="/pharmacy/incoming" icon={Inbox} title="Incoming Prescriptions" badge={unviewed}
                    desc="Prescriptions sent to your pharmacy by physicians" testId="hub-incoming" />
                <Card to="/pharmacy/rx" icon={Pill} title="Rx Requests / Renewals"
                    desc="Send refill and renewal requests to the clinic" testId="hub-rx" />
                <Card to="/pharmacy/messages" icon={MessageSquare} title="Messages"
                    desc="Secure messages with the clinic" testId="hub-messages" />
                <Card to="/pharmacy/account" icon={User} title="Organization Profile"
                    desc="Your pharmacy account and contact details" testId="hub-account" />
            </div>
        </div>
    );
}
