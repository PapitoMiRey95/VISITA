import { useOutletContext } from "react-router-dom";
import { useTranslation } from "react-i18next";

export const usePortal = () => useOutletContext();

export function StatusPill({ status }) {
    const { t } = useTranslation(["requests"]);
    const map = {
        "Completed": "bg-emerald-100 text-emerald-700",
        "Appointment Confirmed": "bg-emerald-100 text-emerald-700",
        "Under Review": "bg-blue-100 text-blue-700",
        "Received": "bg-slate-100 text-slate-600",
        "Appointment Requested": "bg-amber-100 text-amber-700",
        "Appointment Required": "bg-amber-100 text-amber-700",
        "New Time Suggested": "bg-amber-100 text-amber-700",
        "More Information Requested": "bg-amber-100 text-amber-700",
        "Declined": "bg-red-100 text-red-700",
    };
    return (
        <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-bold ${map[status] || "bg-slate-100 text-slate-600"}`}>
            {status ? t(`statuses.${status}`, status) : "—"}
        </span>
    );
}

export function PendingBanner({ status }) {
    const { t } = useTranslation(["requests"]);
    if (status === "verified") return null;
    if (status === "rejected")
        return (
            <div data-testid="verification-banner" className="bg-red-50 border border-red-200 text-red-800 rounded-xl p-4 text-sm">
                {t("pendingBanner.rejected")}
            </div>
        );
    return (
        <div data-testid="verification-banner" className="bg-amber-50 border border-amber-200 text-amber-900 rounded-xl p-4 text-sm">
            <p className="font-bold mb-1">{t("pendingBanner.pendingTitle")}</p>
            {t("pendingBanner.pendingBody")}
        </div>
    );
}

export function SectionTitle({ children }) {
    return <h1 className="text-2xl font-bold text-slate-900 mb-1">{children}</h1>;
}

export function Card({ children, className = "", ...rest }) {
    return <div className={`bg-white rounded-2xl border border-slate-200 shadow-sm p-5 ${className}`} {...rest}>{children}</div>;
}
