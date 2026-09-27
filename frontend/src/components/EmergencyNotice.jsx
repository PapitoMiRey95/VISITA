import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";

export function EmergencyNotice({ text }) {
    const { t } = useTranslation("common");
    return (
        <div
            data-testid="emergency-notice"
            className="bg-amber-50 text-amber-900 text-sm p-3 rounded-lg border border-amber-200 flex items-start gap-2"
        >
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5 text-amber-600" />
            <p className="leading-snug">{text || t("emergencyNoticePortal")}</p>
        </div>
    );
}
