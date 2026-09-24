import { usePortal, StatusPill, Card } from "./shared";
import { useTranslation } from "react-i18next";
import { Calendar, Pill, Scan, MessageSquare } from "lucide-react";
import { formatDate } from "../lib/date";

const ICONS = { Appointment: Calendar, Prescription: Pill, Imaging: Scan, Message: MessageSquare };

export default function PortalMyRequests() {
    const { t } = useTranslation(["requests"]);
    const { overview } = usePortal();
    const reqs = overview.data?.requests || [];

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">{t("myRequests.title")}</h1>
            <p className="text-slate-500 text-sm -mt-2">{t("myRequests.subtitle")}</p>

            <div className="space-y-3">
                {reqs.length === 0 && <p className="text-slate-500 text-sm">{t("myRequests.none")}</p>}
                {reqs.map((r) => {
                    const Icon = ICONS[r.type] || MessageSquare;
                    return (
                        <Card key={r.id} className="p-4 flex items-center gap-3" data-testid="my-request-item">
                            <div className="w-10 h-10 rounded-full bg-portal-blue/10 flex items-center justify-center flex-shrink-0">
                                <Icon className="w-5 h-5 text-portal-blue" />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="font-bold text-slate-800">{t(`myRequests.types.${r.type}`, r.type)} {t("myRequests.requestSuffix")}</div>
                                <div className="text-sm text-slate-500 truncate">
                                    {r.ref_number} · {formatDate(r.created_at)}
                                </div>
                            </div>
                            <StatusPill status={r.status} />
                        </Card>
                    );
                })}
            </div>
        </div>
    );
}
