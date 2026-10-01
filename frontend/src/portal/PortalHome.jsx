import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Calendar, Pill, FileHeart, MessageSquare, ClipboardList, Scan, Droplet, ChevronRight, User, CalendarClock, FlaskConical } from "lucide-react";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { usePortal, PendingBanner, Card, StatusPill } from "./shared";
import { formatDate } from "../lib/date";

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

const todayIso = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function UpcomingAppointment() {
    const nav = useNavigate();
    const { t } = useTranslation(["portal"]);
    const { overview } = usePortal();
    const appts = overview.data?.appointments || [];
    const today = todayIso();
    const upcoming = appts
        .filter((a) => ["confirmed", "rescheduled"].includes(a.raw_status) && a.confirmed_date && a.confirmed_date >= today)
        .sort((a, b) =>
            a.confirmed_date === b.confirmed_date
                ? (a.confirmed_slot_time || "").localeCompare(b.confirmed_slot_time || "")
                : a.confirmed_date.localeCompare(b.confirmed_date));

    if (upcoming.length === 0) {
        return (
            <Card data-testid="upcoming-appointment-none" className="border-dashed">
                <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-full bg-portal-blue/10 flex items-center justify-center flex-shrink-0">
                        <CalendarClock className="w-5 h-5 text-portal-blue" />
                    </div>
                    <div className="flex-1">
                        <p className="font-bold text-slate-800">{t("home.upcoming.noneTitle")}</p>
                        <p className="text-sm text-slate-500 mt-0.5">{t("home.upcoming.nonePrompt")}</p>
                        <button data-testid="upcoming-request-cta" onClick={() => nav("/portal/appointments")}
                            className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-sm font-bold transition active:scale-95">
                            {t("home.upcoming.requestCta")}
                        </button>
                    </div>
                </div>
            </Card>
        );
    }

    const next = upcoming[0];
    return (
        <Card data-testid="upcoming-appointment-card" className="bg-gradient-to-br from-portal-blue to-portal-blueDark text-white border-0">
            <div className="flex items-center gap-2 text-white/80 text-xs font-bold uppercase tracking-wide mb-2">
                <CalendarClock className="w-4 h-4" /> {t("home.upcoming.title")}
            </div>
            <div className="flex items-end justify-between gap-3">
                <div>
                    <div className="text-2xl font-extrabold leading-tight" data-testid="upcoming-date">{formatDate(next.confirmed_date)}</div>
                    <div className="text-lg font-bold text-white/90" data-testid="upcoming-time">{next.confirmed_time}</div>
                    <div className="text-sm text-white/80 mt-1" data-testid="upcoming-reason">{next.reason}</div>
                </div>
                <div className="flex flex-col items-end gap-2">
                    <StatusPill status={next.status} />
                </div>
            </div>
            <div className="mt-4 flex items-center gap-3">
                <button data-testid="upcoming-view-btn" onClick={() => nav("/portal/appointments")}
                    className="inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-white text-portal-blueDark text-sm font-bold transition active:scale-95 hover:bg-white/90">
                    {t("home.upcoming.viewAppointment")} <ChevronRight className="w-4 h-4" />
                </button>
                {upcoming.length > 1 && (
                    <button data-testid="upcoming-view-all" onClick={() => nav("/portal/appointments")}
                        className="text-sm font-semibold text-white/85 underline underline-offset-2">
                        {t("home.upcoming.viewAll")}
                    </button>
                )}
            </div>
        </Card>
    );
}

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

            <UpcomingAppointment />

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

            <Card data-testid="results-followup-card">
                <div className="flex items-center gap-2 mb-2">
                    <div className="w-9 h-9 rounded-full bg-sky-50 flex items-center justify-center flex-shrink-0">
                        <FlaskConical className="w-5 h-5 text-sky-500" />
                    </div>
                    <h2 className="font-bold text-slate-800">{t("home.results.title")}</h2>
                </div>
                <p className="text-sm text-slate-600 leading-snug">{t("home.results.body")}</p>
                <button data-testid="results-request-appointment" onClick={() => nav("/portal/appointments")}
                    className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-xl border border-portal-blue text-portal-blueDark text-sm font-bold hover:bg-portal-blue/5 transition active:scale-95">
                    {t("home.results.cta")}
                </button>
            </Card>

            <EmergencyNotice text={notice} />
        </div>
    );
}
