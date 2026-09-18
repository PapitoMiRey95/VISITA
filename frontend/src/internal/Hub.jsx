import { useNavigate } from "react-router-dom";
import { useCounters } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { Pill, ClipboardCheck, Scan, MessageSquare, Calendar, Send, UserCheck, UserPlus } from "lucide-react";

const STAFF = [
    { key: "rx", label: "Rx", to: "/internal/rx", icon: Pill },
    { key: "referrals", label: "Referrals", to: "/internal/referrals", icon: ClipboardCheck },
    { key: "imaging", label: "Imaging", to: "/internal/imaging", icon: Scan },
    { key: "messages", label: "Messages", to: "/internal/messages", icon: MessageSquare },
    { key: "appointments", label: "Appointments", to: "/internal/appointments", icon: Calendar },
    { key: "doctor_tasks", label: "Doctor Tasks", to: "/internal/tasks", icon: Send },
    { key: "verifications", label: "Verifications", to: "/internal/verifications", icon: UserCheck },
    { key: "applications", label: "Applications", to: "/internal/applications", icon: UserPlus },
];

const PHYS = [
    { key: "rx", label: "Rx", to: "/internal/rx", icon: Pill },
    { key: "imaging", label: "Imaging", to: "/internal/imaging", icon: Scan },
    { key: "messages", label: "Messages", to: "/internal/messages", icon: MessageSquare },
    { key: "applications", label: "Applications", to: "/internal/applications", icon: UserPlus },
];

function Counter({ item, value, onClick }) {
    return (
        <button
            data-testid={`counter-${item.key}`}
            onClick={onClick}
            className="group bg-white border border-slate-300 border-l-4 border-l-visita-green rounded-sm px-4 py-3 flex items-center justify-between text-left hover:bg-slate-50 hover:border-l-visita-greenDark transition-colors duration-75"
        >
            <div className="flex items-center gap-3">
                <item.icon className="w-5 h-5 text-visita-green" />
                <span className="text-xs uppercase tracking-wider text-slate-600 font-medium">{item.label}</span>
            </div>
            <span className="text-3xl font-bold text-slate-900 tabular-nums">{value ?? 0}</span>
        </button>
    );
}

export default function Hub() {
    const nav = useNavigate();
    const { user } = useAuth();
    const counters = useCounters();
    const c = counters.data?.counters || {};
    const items = user?.role === "physician" ? PHYS : STAFF;

    return (
        <div className="animate-fade-in">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
                        {user?.role === "physician" ? "Physician Hub" : "Clinic Staff Hub"}
                    </h1>
                    <p className="text-sm text-slate-500">Live work queues — click a counter to open its queue.</p>
                </div>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {items.map((it) => (
                    <Counter key={it.key} item={it} value={c[it.key]} onClick={() => nav(it.to)} />
                ))}
            </div>

            {user?.role === "physician" && (
                <div className="mt-6">
                    <button
                        data-testid="physician-dropoff"
                        onClick={() => nav("/internal/referrals")}
                        className="bg-visita-green hover:bg-visita-greenDark text-white rounded-sm px-5 py-3 font-semibold flex items-center gap-2"
                    >
                        <ClipboardCheck className="w-5 h-5" /> Referral Drop-Off (upload completed PDF)
                    </button>
                    <p className="text-sm text-slate-500 mt-2 max-w-xl">
                        Referrals are completed in the existing VISITA EMR. Upload the finished PDF here and it becomes a
                        Ready-to-Fax item for clinic staff.
                    </p>
                </div>
            )}
        </div>
    );
}
