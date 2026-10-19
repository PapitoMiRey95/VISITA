import { useNavigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { useCounters } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import { Pill, ClipboardCheck, Scan, Droplet, MessageSquare, Calendar, Send, UserCheck, UserPlus, UserSearch, CalendarDays, Users, Receipt, Stethoscope, Contact, X } from "lucide-react";

const STAFF = [
    { key: "rx", label: "Rx", to: "/internal/rx", icon: Pill },
    { key: "referrals", label: "Referrals", to: "/internal/referrals", icon: ClipboardCheck },
    { key: "imaging", label: "Imaging", to: "/internal/imaging", icon: Scan },
    { key: "bloodwork", label: "Bloodwork", to: "/internal/bloodwork", icon: Droplet },
    { key: "messages", label: "Messages", to: "/internal/messages", icon: MessageSquare },
    { key: "appointments", label: "Appointments", to: "/internal/appointments", icon: Calendar },
    { key: "work_hub", label: "Work Hub", to: "/internal/work", icon: Send },
    { key: "verifications", label: "Verifications", to: "/internal/verifications", icon: UserCheck },
    { key: "applications", label: "Applications", to: "/internal/applications", icon: UserPlus },
];

// Physician Hub surfaces the full physician feature set (mirrors the sidebar)
// so mobile physicians reach everything the desktop sidebar offers. Items with
// a `key` show a live counter; the rest are plain navigation tiles.
const PHYS = [
    { label: "Patients", to: "/internal/patients", icon: UserSearch },
    { key: "rx", label: "Rx", to: "/internal/rx", icon: Pill },
    { key: "imaging", label: "Imaging", to: "/internal/imaging", icon: Scan },
    { key: "bloodwork", label: "Bloodwork", to: "/internal/bloodwork", icon: Droplet },
    { key: "messages", label: "Messages", to: "/internal/messages", icon: MessageSquare },
    { key: "applications", label: "Applications", to: "/internal/applications", icon: UserPlus },
    { label: "Calendar", to: "/internal/calendar", icon: CalendarDays },
    { label: "Private Requests", to: "/internal/private-requests", icon: Users },
    { label: "Billing", to: "/internal/billing", icon: Receipt },
    { key: "work_hub", label: "Work Hub", to: "/internal/work", icon: Send },
    { label: "Referral Drop-Off", to: "/internal/referrals", icon: ClipboardCheck },
    { key: "verifications", label: "Verifications", to: "/internal/verifications", icon: UserCheck },
    { label: "Providers", to: "/internal/providers", icon: Stethoscope },
];

function Counter({ item, value, onClick }) {
    return (
        <button
            data-testid={`counter-${item.key || item.label.toLowerCase().replace(/[^a-z]/g, "-")}`}
            onClick={onClick}
            className="group bg-white border border-slate-300 border-l-4 border-l-visita-green rounded-sm px-4 py-3 flex items-center justify-between text-left hover:bg-slate-50 hover:border-l-visita-greenDark transition-colors duration-75"
        >
            <div className="flex items-center gap-3">
                <item.icon className="w-5 h-5 text-visita-green" />
                <span className="text-xs uppercase tracking-wider text-slate-600 font-medium">{item.label}</span>
            </div>
            {item.key && <span className="text-3xl font-bold text-slate-900 tabular-nums">{value ?? 0}</span>}
        </button>
    );
}

// Lightweight, dismissible nudge — NEVER blocks any workflow. Shows only when a
// physician/admin has no professional profile yet and hasn't dismissed it.
function ProfileReminder() {
    const nav = useNavigate();
    const { user } = useAuth();
    const canHave = user?.role === "physician" || user?.role === "admin";
    const dismissKey = `vien.profileReminderDismissed.${user?.id || ""}`;
    const [show, setShow] = useState(false);
    useEffect(() => {
        if (!canHave) return;
        if (localStorage.getItem(dismissKey) === "1") return;
        let active = true;
        api.get("/professionals/me")
            .then(({ data }) => { if (active && !data.profile) setShow(true); })
            .catch(() => {});
        return () => { active = false; };
    }, [canHave, dismissKey]);
    if (!show) return null;
    const dismiss = () => { localStorage.setItem(dismissKey, "1"); setShow(false); };
    return (
        <div data-testid="profile-reminder" className="mb-4 flex items-center gap-3 rounded-sm border border-slate-200 bg-slate-50 px-4 py-2.5">
            <Contact className="w-4 h-4 text-visita-greenDark shrink-0" />
            <span className="text-sm text-slate-600">Complete your professional profile <span className="text-slate-400">(optional)</span></span>
            <button data-testid="profile-reminder-cta" onClick={() => nav("/internal/professionals")}
                className="ml-auto text-sm font-semibold text-visita-greenDark hover:underline shrink-0">Set it up</button>
            <button data-testid="profile-reminder-dismiss" onClick={dismiss} className="text-slate-400 hover:text-slate-600 shrink-0" aria-label="Dismiss">
                <X className="w-4 h-4" />
            </button>
        </div>
    );
}

export default function Hub() {
    const nav = useNavigate();
    const { user } = useAuth();
    const counters = useCounters();
    const c = counters.data?.counters || {};
    const WS_NAV = { patients: ["/internal/patients"], calendar: ["/internal/calendar", "/internal/appointments"], messages: ["/internal/messages", "/internal/tasks", "/internal/work"],
        registration: ["/internal/applications", "/internal/verifications", "/internal/portal-access-requests", "/internal/health-card-updates"], rx: ["/internal/rx", "/internal/send-rx"], billing: ["/internal/billing", "/internal/private-requests"] };
    const base = user?.role === "physician" ? PHYS : STAFF;
    const items = user?.workspace ? base.filter((it) => (user.allowed_modules || []).some((m) => (WS_NAV[m] || []).includes(it.to))) : base;

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

            <ProfileReminder />

            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {items.map((it) => (
                    <Counter key={it.to} item={it} value={c[it.key]} onClick={() => nav(it.to)} />
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
