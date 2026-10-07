import { useNavigate, Navigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Calendar, Pill, FileHeart, MessageSquare, ClipboardList, ChevronRight, User, Users, CalendarClock, CalendarX, FlaskConical, FileText, BellRing } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { usePortal, PendingBanner, Card, StatusPill } from "./shared";
import { formatDate } from "../lib/date";

const TILES = [
    { to: "/portal/appointments", icon: Calendar, tkey: "home.tiles.appointments", color: "text-portal-blue", testid: "tile-appointments" },
    { to: "/portal/prescriptions", icon: Pill, tkey: "home.tiles.prescriptions", color: "text-emerald-500", testid: "tile-prescriptions" },
    { to: "/portal/documents", icon: FileText, tkey: "home.tiles.documents", color: "text-cyan-600", testid: "tile-documents" },
    { to: "/portal/referrals", icon: FileHeart, tkey: "home.tiles.referrals", color: "text-violet-500", testid: "tile-referrals" },
    { to: "/portal/messages", icon: MessageSquare, tkey: "home.tiles.messages", color: "text-amber-500", testid: "tile-messages" },
    { to: "/portal/requests", icon: ClipboardList, tkey: "home.tiles.requests", color: "text-slate-500", testid: "tile-requests" },
    { to: "/portal/account", icon: User, tkey: "home.tiles.profile", color: "text-teal-500", testid: "tile-profile" },
];

function NewUpdatesCard() {
    const nav = useNavigate();
    const { t } = useTranslation(["portal"]);
    const { overview, refetch, base } = usePortal();
    const updates = overview.data?.updates || [];
    if (updates.length === 0) return null;

    const open = async () => {
        try {
            await Promise.all(updates.map((u) => api.post(`/portal/updates/${u.id}/read`).catch(() => {})));
        } catch (e) { toast.error(formatErr(e)); }
        refetch && refetch();
        nav(`${base}/documents`);
    };

    return (
        <Card data-testid="new-update-card" className="bg-cyan-50 border-cyan-200">
            <div className="flex items-start gap-3">
                <div className="relative w-10 h-10 rounded-full bg-cyan-100 flex items-center justify-center flex-shrink-0">
                    <BellRing className="w-5 h-5 text-cyan-700" />
                    <span data-testid="new-update-badge" className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] min-w-[18px] h-[18px] px-1 rounded-full flex items-center justify-center font-bold">{updates.length}</span>
                </div>
                <div className="flex-1">
                    <p className="font-bold text-cyan-900">{t("home.updates.title")}</p>
                    <p className="text-sm text-cyan-800 mt-0.5">{t("home.updates.body")}</p>
                    <button data-testid="new-update-view" onClick={open}
                        className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-cyan-700 hover:bg-cyan-800 text-white text-sm font-bold transition active:scale-95">
                        {t("home.updates.cta")} <ChevronRight className="w-4 h-4" />
                    </button>
                </div>
            </div>
        </Card>
    );
}

const todayIso = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// Prominent Home alert for a CLINIC-originated cancellation (never for patient self-cancel).
function ClinicCancellationAlert() {
    const nav = useNavigate();
    const { t } = useTranslation(["portal"]);
    const { overview, refetch, base } = usePortal();
    const alert = overview.data?.patient?.clinic_cancellation_alert;
    if (!alert) return null;
    const dismiss = async () => {
        try { await api.post(`/portal/appointments/${alert.id}/ack-cancellation`); refetch && refetch(); }
        catch (e) { toast.error(formatErr(e)); }
    };
    return (
        <Card data-testid="clinic-cancel-alert" className="bg-red-50 border-red-200">
            <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0">
                    <CalendarX className="w-5 h-5 text-red-700" />
                </div>
                <div className="flex-1">
                    <p className="font-bold text-red-900">{t("home.cancelAlert.title")}</p>
                    <p className="text-sm text-red-800 mt-0.5" data-testid="clinic-cancel-alert-body">{t("home.cancelAlert.body", { when: alert.display || alert.ref_number })}</p>
                    {alert.reason && <p className="text-sm text-red-800" data-testid="clinic-cancel-alert-reason">{t("home.cancelAlert.reason", { reason: alert.reason })}</p>}
                    <div className="flex flex-wrap gap-2 mt-3">
                        <button data-testid="clinic-cancel-alert-book" onClick={async () => { await dismiss(); nav(`${base}/appointments`); }}
                            className="inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-red-700 hover:bg-red-800 text-white text-sm font-bold transition active:scale-95">
                            {t("home.cancelAlert.cta")} <ChevronRight className="w-4 h-4" />
                        </button>
                        <button data-testid="clinic-cancel-alert-dismiss" onClick={dismiss}
                            className="px-4 py-2 rounded-xl border border-red-300 text-red-800 text-sm font-semibold hover:bg-red-100">
                            {t("home.cancelAlert.dismiss")}
                        </button>
                    </div>
                </div>
            </div>
        </Card>
    );
}

function UpcomingAppointment() {
    const nav = useNavigate();
    const { t } = useTranslation(["portal"]);
    const { overview, base } = usePortal();
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
                        <button data-testid="upcoming-request-cta" onClick={() => nav(`${base}/appointments`)}
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
                <button data-testid="upcoming-view-btn" onClick={() => nav(`${base}/appointments`)}
                    className="inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-white text-portal-blueDark text-sm font-bold transition active:scale-95 hover:bg-white/90">
                    {t("home.upcoming.viewAppointment")} <ChevronRight className="w-4 h-4" />
                </button>
                {upcoming.length > 1 && (
                    <button data-testid="upcoming-view-all" onClick={() => nav(`${base}/appointments`)}
                        className="text-sm font-semibold text-white/85 underline underline-offset-2">
                        {t("home.upcoming.viewAll")}
                    </button>
                )}
            </div>
        </Card>
    );
}

function YourMedicinesCard() {
    const nav = useNavigate();
    const { t } = useTranslation(["portal"]);
    const { base } = usePortal();
    const [meds, setMeds] = useState(null);
    useEffect(() => {
        api.get("/portal/medications").then(({ data }) => setMeds(data.medications || [])).catch(() => setMeds([]));
    }, []);
    if (!meds || meds.length === 0) return null;
    return (
        <Card data-testid="your-medicines-home-card">
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-emerald-50 flex items-center justify-center flex-shrink-0">
                    <Pill className="w-5 h-5 text-emerald-500" />
                </div>
                <div className="flex-1">
                    <p className="font-bold text-slate-800">{t("home.medicines.title")}</p>
                    <p className="text-sm text-slate-500" data-testid="your-medicines-count">{t("home.medicines.count", { count: meds.length })}</p>
                </div>
                <button data-testid="your-medicines-view" onClick={() => nav(`${base}/prescriptions`)}
                    className="inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-bold transition active:scale-95">
                    {t("home.medicines.view")} <ChevronRight className="w-4 h-4" />
                </button>
            </div>
        </Card>
    );
}

function PeopleIManageCard() {
    const nav = useNavigate();
    const [managing, setManaging] = useState([]);
    useEffect(() => {
        api.get("/portal/my-delegations").then(({ data }) => setManaging(data.managing || [])).catch(() => {});
    }, []);
    if (managing.length === 0) return null;
    return (
        <Card data-testid="people-i-manage-card">
            <div className="flex items-center gap-2 mb-2"><Users className="w-4 h-4 text-portal-blue" /><h2 className="font-bold text-slate-800 text-sm">People I help manage</h2></div>
            <div className="space-y-1.5">
                {managing.map((m) => (
                    <button key={m.patient_id} data-testid="people-i-manage-item" onClick={() => nav(`/portal/manage/${m.patient_id}`)}
                        className="w-full flex items-center justify-between p-2.5 rounded-lg border border-slate-200 hover:border-portal-blue text-left">
                        <span className="text-sm"><b className="text-slate-800">{m.patient_name}</b> <span className="text-slate-400">· {m.relationship}</span></span>
                        <ChevronRight className="w-4 h-4 text-slate-300" />
                    </button>
                ))}
            </div>
        </Card>
    );
}

export default function PortalHome() {
    const nav = useNavigate();
    const { user } = useAuth();
    const { t, i18n } = useTranslation(["portal"]);
    const { overview, cfg, base, managed, delegate, can } = usePortal();
    // Caregiver-only accounts have no own-patient chart — send them straight to
    // their managed-people list instead of an own-patient overview.
    if (user?.role === "caregiver" && !managed) return <Navigate to="/portal/people" replace />;
    const p = overview.data?.patient;
    const notice = (i18n.language || "en").startsWith("es") ? undefined : cfg.data?.templates?.emergency_notice;

    // Managed-patient Home: same portal shell, permission-gated quick actions.
    if (managed) {
        const actions = [
            { perm: "APPOINTMENTS", to: `${base}/appointments`, icon: Calendar, color: "text-portal-blue", label: t("nav.appts", "Appointments"), testid: "mhome-appointments" },
            { perm: "RX_REQUESTS", to: `${base}/prescriptions`, icon: Pill, color: "text-emerald-500", label: t("nav.rx", "Prescriptions"), testid: "mhome-prescriptions" },
            { perm: "DOCUMENTS", to: `${base}/documents`, icon: FileText, color: "text-sky-500", label: t("nav.documents", "Results & Documents"), testid: "mhome-documents" },
            { perm: "REQUEST_STATUS", to: `${base}/requests`, icon: ClipboardList, color: "text-amber-500", label: t("nav.requests", "Requests & Status"), testid: "mhome-requests" },
            { perm: "HEALTH_CARD_UPDATE", to: `${base}/health-card`, icon: User, color: "text-indigo-500", label: t("nav.healthCard", "Health Card"), testid: "mhome-health-card" },
        ].filter((a) => can(a.perm));
        return (
            <div className="space-y-5 animate-fade-in" data-testid="managed-home">
                <div>
                    <p className="text-slate-500 font-semibold">{t("home.greeting")}</p>
                    <h1 className="text-3xl font-extrabold text-slate-900">{delegate?.patient_name || `${p?.first_name || ""} ${p?.last_name || ""}`}</h1>
                </div>
                <NewUpdatesCard />
                {can("APPOINTMENTS") && <ClinicCancellationAlert />}
                {can("RX_REQUESTS") && <YourMedicinesCard />}
                {can("APPOINTMENTS") && <UpcomingAppointment />}
                <div className="grid grid-cols-2 gap-3">
                    {actions.map((a) => (
                        <button key={a.to} data-testid={a.testid} onClick={() => nav(a.to)}
                            className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5 text-left hover:shadow-md transition active:scale-95 flex flex-col gap-3">
                            <a.icon className={`w-8 h-8 ${a.color}`} />
                            <span className="font-bold text-slate-800 leading-tight">{a.label}</span>
                            <ChevronRight className="w-4 h-4 text-slate-300 self-end" />
                        </button>
                    ))}
                </div>
                <EmergencyNotice text={notice} />
            </div>
        );
    }

    return (
        <div className="space-y-5 animate-fade-in">
            <div>
                <p className="text-slate-500 font-semibold">{t("home.greeting")}</p>
                <h1 className="text-3xl font-extrabold text-slate-900">{p ? `${p.first_name} ${p.last_name}` : t("home.patientFallback")}</h1>
            </div>

            {p && <PendingBanner status={p.verification_status} />}

            <ClinicCancellationAlert />

            <NewUpdatesCard />

            <YourMedicinesCard />

            <PeopleIManageCard />

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
                <button data-testid="results-request-appointment" onClick={() => nav(`${base}/appointments`)}
                    className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-xl border border-portal-blue text-portal-blueDark text-sm font-bold hover:bg-portal-blue/5 transition active:scale-95">
                    {t("home.results.cta")}
                </button>
            </Card>

            <EmergencyNotice text={notice} />
        </div>
    );
}
