import { Outlet, useNavigate, NavLink, useLocation } from "react-router-dom";
import { useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Home, Calendar, Pill, MessageSquare, ClipboardList, Bell, LogOut, User, Receipt, FileText, CreditCard, ArrowLeft } from "lucide-react";
import { api, setOnBehalfOf } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { ThemeToggle } from "../components/ThemeToggle";
import { Logo } from "../components/Logo";
import { setAppLanguage, getSavedLanguage } from "../i18n";

// Persist the patient's language to their account so emails follow their choice.
const persistLang = (lng) => { api.post("/portal/language", { language: lng }).catch(() => {}); };

const PRIVATE_TYPES = ["private", "tourist", "uninsured"];

export default function PortalLayout() {
    const { user, logout } = useAuth();
    const { t, i18n } = useTranslation(["portal"]);
    const nav = useNavigate();
    const loc = useLocation();

    // Managed-patient ("on behalf of") mode is driven entirely by the URL so the
    // header is set synchronously BEFORE any nested page fires its queries.
    const match = loc.pathname.match(/^\/portal\/manage\/([^/]+)/);
    const obo = match ? match[1] : null;
    setOnBehalfOf(obo);
    const base = obo ? `/portal/manage/${obo}` : "/portal";

    useEffect(() => () => setOnBehalfOf(null), []);

    useEffect(() => {
        if (obo) return;
        const saved = getSavedLanguage();
        if (saved) persistLang(saved);
    }, [obo]);

    const overview = useQuery({
        queryKey: ["overview", obo || "self"],
        queryFn: async () => (await api.get("/portal/overview", obo ? { headers: { "X-On-Behalf-Of": obo } } : {})).data,
    });
    const cfg = useQuery({
        queryKey: ["public-settings"],
        queryFn: async () => (await api.get("/settings/public")).data,
    });

    const del = overview.data?.delegate;
    const managed = !!obo;
    const perms = del?.permissions || [];
    const can = (p) => perms.includes(p);

    const unread = (overview.data?.notifications || []).filter((n) => !n.read).length;
    const ptype = overview.data?.patient?.patient_type;
    const billing = overview.data?.billing || { open: 0, total: 0 };
    const showInvoices = PRIVATE_TYPES.includes(ptype) || (billing.total || 0) > 0;

    const navItems = useMemo(() => {
        if (managed) {
            const items = [
                { to: base, icon: Home, label: t("portal:nav.home", "Home"), end: true, testid: "mnav-home" },
            ];
            if (can("APPOINTMENTS")) items.push({ to: `${base}/appointments`, icon: Calendar, label: t("portal:nav.appts", "Appts"), testid: "mnav-appointments" });
            if (can("RX_REQUESTS")) items.push({ to: `${base}/prescriptions`, icon: Pill, label: t("portal:nav.rx", "Rx"), testid: "mnav-prescriptions" });
            if (can("DOCUMENTS")) items.push({ to: `${base}/documents`, icon: FileText, label: t("portal:nav.documents", "Results"), testid: "mnav-documents" });
            if (can("REQUEST_STATUS")) items.push({ to: `${base}/requests`, icon: ClipboardList, label: t("portal:nav.requests", "Requests"), testid: "mnav-requests" });
            if (can("HEALTH_CARD_UPDATE")) items.push({ to: `${base}/health-card`, icon: CreditCard, label: t("portal:nav.healthCard", "Health Card"), testid: "mnav-health-card" });
            return items;
        }
        const items = [
            { to: "/portal", icon: Home, label: t("portal:nav.home"), end: true, testid: "nav-home" },
            { to: "/portal/appointments", icon: Calendar, label: t("portal:nav.appts"), testid: "nav-appointments" },
            { to: "/portal/prescriptions", icon: Pill, label: t("portal:nav.rx"), testid: "nav-prescriptions" },
            { to: "/portal/messages", icon: MessageSquare, label: t("portal:nav.help"), testid: "nav-messages" },
            { to: "/portal/requests", icon: ClipboardList, label: t("portal:nav.requests"), testid: "nav-requests" },
            { to: "/portal/account", icon: User, label: t("portal:nav.profile"), testid: "nav-profile" },
        ];
        if (showInvoices) {
            items.splice(items.length - 1, 0, {
                to: "/portal/invoices", icon: Receipt, label: t("portal:nav.invoices", "Invoices"),
                testid: "nav-invoices", badge: billing.open || 0,
            });
        }
        return items;
    }, [managed, base, perms, showInvoices, billing.open, t]);

    const outletCtx = useMemo(
        () => ({ overview, cfg, refetch: overview.refetch, base, managed, delegate: del, can }),
        [overview, cfg, base, managed, del]
    );

    return (
        <div className="min-h-screen bg-portal-blue/5 font-nunito flex flex-col">
            <header className="sticky top-0 z-20 bg-white border-b border-slate-200 px-4 py-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Logo variant="light" iconClass="h-8 w-8" textClass="text-lg" />
                </div>
                <div className="flex items-center gap-1">
                    <div data-testid="portal-lang-toggle" className="flex items-center rounded-full border border-slate-200 overflow-hidden mr-1">
                        {["en", "es"].map((lng) => (
                            <button key={lng} data-testid={`portal-lang-${lng}`} onClick={() => { setAppLanguage(lng); if (!managed) persistLang(lng); }}
                                className={`px-2 py-1 text-[11px] font-bold uppercase transition-colors ${(i18n.language || "en").startsWith(lng) ? "bg-portal-blue text-white" : "text-slate-500 hover:bg-slate-100"}`}>
                                {lng}
                            </button>
                        ))}
                    </div>
                    {!managed && (
                        <button data-testid="portal-notifications" onClick={() => nav("/portal/account")} className="relative p-2 rounded-full hover:bg-slate-100">
                            <Bell className="w-5 h-5 text-slate-600" />
                            {unread > 0 && (
                                <span className="absolute top-0 right-0 bg-red-500 text-white text-[10px] w-4 h-4 rounded-full flex items-center justify-center">{unread}</span>
                            )}
                        </button>
                    )}
                    <button data-testid="portal-account-btn" onClick={() => nav(managed ? "/portal/people" : "/portal/account")}
                        className="p-2 rounded-full hover:bg-slate-100 text-sm font-bold text-portal-blueDark">
                        {user?.name?.[0] || "P"}
                    </button>
                    <ThemeToggle className="border-slate-300 text-slate-700" />
                    <button data-testid="portal-logout" onClick={() => { logout(); nav("/login"); }} className="p-2 rounded-full hover:bg-slate-100">
                        <LogOut className="w-5 h-5 text-slate-600" />
                    </button>
                </div>
            </header>

            {managed && (
                <div data-testid="managed-banner" className="sticky top-[57px] z-10 bg-portal-blue text-white px-4 py-2.5">
                    <div className="max-w-lg mx-auto flex items-center justify-between gap-3">
                        <span className="text-sm font-semibold truncate">
                            {t("portal:managed.banner", { name: del?.patient_name })}
                            {del?.relationship ? <span className="font-normal opacity-80"> · {del.relationship}</span> : null}
                        </span>
                        <button data-testid="return-to-my-account" onClick={() => { setOnBehalfOf(null); nav("/portal/people"); }}
                            className="text-xs font-semibold underline flex items-center gap-1 flex-shrink-0">
                            <ArrowLeft className="w-3 h-3" /> {t("portal:managed.return", "Return to my account")}
                        </button>
                    </div>
                </div>
            )}

            <main className="flex-1 w-full max-w-lg mx-auto px-4 py-5 pb-24">
                <Outlet context={outletCtx} />
            </main>

            <nav className="fixed bottom-0 inset-x-0 z-20 bg-white border-t border-slate-200 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)]">
                <div className="max-w-lg mx-auto flex justify-around">
                    {navItems.map((n) => {
                        const active = n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to);
                        return (
                            <NavLink key={n.to} to={n.to} end={n.end} data-testid={n.testid}
                                className="relative flex flex-col items-center justify-center gap-0.5 py-2 min-h-[56px] flex-1">
                                <n.icon className={`w-5 h-5 ${active ? "text-portal-blue" : "text-slate-400"}`} />
                                {n.badge > 0 && (
                                    <span className="absolute top-1 right-1/4 bg-red-500 text-white text-[9px] min-w-[15px] h-[15px] px-1 rounded-full flex items-center justify-center">{n.badge}</span>
                                )}
                                <span className={`text-[11px] font-semibold ${active ? "text-portal-blue" : "text-slate-400"}`}>{n.label}</span>
                            </NavLink>
                        );
                    })}
                </div>
            </nav>
        </div>
    );
}
