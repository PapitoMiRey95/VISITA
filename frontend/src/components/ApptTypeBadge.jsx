import { Hospital, Phone, HelpCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

// Appointment type badge — visible everywhere appointment requests are shown.
export function ApptTypeBadge({ type, size = "sm", className = "" }) {
    const { t } = useTranslation("requests");
    const cfg = {
        IN_CLINIC: { label: t("apptType.inClinic"), Icon: Hospital, cls: "bg-emerald-100 text-emerald-800 border-emerald-300" },
        TELEPHONE: { label: t("apptType.phone"), Icon: Phone, cls: "bg-sky-100 text-sky-800 border-sky-300" },
    }[type] || { label: t("apptType.notSpecified"), Icon: HelpCircle, cls: "bg-slate-100 text-slate-500 border-slate-300" };
    const pad = size === "lg" ? "px-2.5 py-1 text-xs" : "px-2 py-0.5 text-[11px]";
    return (
        <span data-testid={`appt-type-badge-${type || "none"}`}
            className={`inline-flex items-center gap-1 rounded-full border font-bold uppercase tracking-wide ${pad} ${cfg.cls} ${className}`}>
            <cfg.Icon className="w-3.5 h-3.5" /> {cfg.label}
        </span>
    );
}

export function apptTypeConfirmationLabel(type) {
    if (type === "TELEPHONE") return "Telephone Appointment";
    if (type === "IN_CLINIC") return "In-Clinic Appointment";
    return "Not specified";
}
