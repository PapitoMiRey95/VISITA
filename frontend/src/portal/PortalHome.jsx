import { useNavigate } from "react-router-dom";
import { Calendar, Pill, FileHeart, MessageSquare, ClipboardList, Scan, Droplet, ChevronRight } from "lucide-react";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { usePortal, PendingBanner } from "./shared";

const TILES = [
    { to: "/portal/appointments", icon: Calendar, title: "Request an Appointment", color: "text-portal-blue", testid: "tile-appointments" },
    { to: "/portal/prescriptions", icon: Pill, title: "Prescription Request", color: "text-emerald-500", testid: "tile-prescriptions" },
    { to: "/portal/bloodwork", icon: Droplet, title: "Bloodwork Request", color: "text-rose-500", testid: "tile-bloodwork" },
    { to: "/portal/imaging", icon: Scan, title: "X-Ray / Ultrasound", color: "text-sky-500", testid: "tile-imaging" },
    { to: "/portal/referrals", icon: FileHeart, title: "Referral Status", color: "text-violet-500", testid: "tile-referrals" },
    { to: "/portal/messages", icon: MessageSquare, title: "Message the Clinic", color: "text-amber-500", testid: "tile-messages" },
    { to: "/portal/requests", icon: ClipboardList, title: "My Requests", color: "text-slate-500", testid: "tile-requests" },
];

export default function PortalHome() {
    const nav = useNavigate();
    const { overview, cfg } = usePortal();
    const p = overview.data?.patient;
    const notice = cfg.data?.templates?.emergency_notice;

    return (
        <div className="space-y-5 animate-fade-in">
            <div>
                <p className="text-slate-500 font-semibold">Hello,</p>
                <h1 className="text-3xl font-extrabold text-slate-900">{p ? `${p.first_name} ${p.last_name}` : "Patient"}</h1>
            </div>

            {p && <PendingBanner status={p.verification_status} />}
            <EmergencyNotice text={notice} />

            <div className="grid grid-cols-2 gap-3">
                {TILES.map((t) => (
                    <button
                        key={t.to}
                        data-testid={t.testid}
                        onClick={() => nav(t.to)}
                        className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5 text-left hover:shadow-md transition active:scale-95 flex flex-col gap-3"
                    >
                        <t.icon className={`w-8 h-8 ${t.color}`} />
                        <span className="font-bold text-slate-800 leading-tight">{t.title}</span>
                        <ChevronRight className="w-4 h-4 text-slate-300 self-end" />
                    </button>
                ))}
            </div>
        </div>
    );
}
