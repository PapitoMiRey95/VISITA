import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Calendar, Pill, FileHeart, MessageSquare, ClipboardList, Scan, Droplet, ChevronRight, User } from "lucide-react";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { usePortal, PendingBanner } from "./shared";

const TILES = [
    { to: "/portal/appointments", icon: Calendar, tkey: "home.tiles.appointments", color: "text-portal-blue", testid: "tile-appointments" },
    { to: "/portal/prescriptions", icon: Pill, tkey: "home.tiles.prescriptions", color: "text-emerald-500", testid: "tile-prescriptions" },
    { to: "/portal/bloodwork", icon: Droplet, tkey: "home.tiles.bloodwork", color: "text-rose-500", testid: "tile-bloodwork" },
    { to: "/portal/imaging", icon: Scan, tkey: "home.tiles.imaging", color: "text-sky-500", testid: "tile-imaging" },
    { to: "/portal/referrals", icon: FileHeart, tkey: "home.tiles.referrals", color: "text-violet-500", testid: "tile-referrals" },
    { to: "/portal/messages", icon: MessageSquare, tkey: "home.tiles.messages", color: "text-amber-500", testid: "tile-messages" },
    { to: "/portal/requests", icon: ClipboardList, tkey: "home.tiles.requests", color: "text-slate-500", testid: "tile-requests" },
    { to: "/portal/account", icon: User, tkey: "home.tiles.profile", color: "text-teal-500", testid: "tile-profile" },
];

export default function PortalHome() {
    const nav = useNavigate();
    const { t, i18n } = useTranslation(["portal"]);
    const { overview, cfg } = usePortal();
    const p = overview.data?.patient;
    // Standard safety notice: use the clinic-configured template only for English
    // sessions; Spanish sessions get the localized notice (EmergencyNotice default).
    const notice = (i18n.language || "en").startsWith("es") ? undefined : cfg.data?.templates?.emergency_notice;

    return (
        <div className="space-y-5 animate-fade-in">
            <div>
                <p className="text-slate-500 font-semibold">{t("home.greeting")}</p>
                <h1 className="text-3xl font-extrabold text-slate-900">{p ? `${p.first_name} ${p.last_name}` : t("home.patientFallback")}</h1>
            </div>

            {p && <PendingBanner status={p.verification_status} />}
            <EmergencyNotice text={notice} />

            <div className="grid grid-cols-2 gap-3">
                {TILES.map((tile) => (
                    <button
                        key={tile.to}
                        data-testid={tile.testid}
                        onClick={() => nav(tile.to)}
                        className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5 text-left hover:shadow-md transition active:scale-95 flex flex-col gap-3"
                    >
                        <tile.icon className={`w-8 h-8 ${tile.color}`} />
                        <span className="font-bold text-slate-800 leading-tight">{t(tile.tkey)}</span>
                        <ChevronRight className="w-4 h-4 text-slate-300 self-end" />
                    </button>
                ))}
            </div>
        </div>
    );
}
