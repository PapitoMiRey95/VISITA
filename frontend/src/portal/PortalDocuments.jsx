import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { FileText, Download, Eye, FlaskConical, Stethoscope, CalendarDays } from "lucide-react";
import { openAttachment, saveAttachment, formatErr } from "../lib/api";
import { usePortal, Card, PendingBanner } from "./shared";
import { formatDate } from "../lib/date";

export default function PortalDocuments() {
    const { t } = useTranslation(["portal"]);
    const nav = useNavigate();
    const { overview } = usePortal();
    const p = overview.data?.patient;
    const docs = overview.data?.documents || [];

    const view = async (d) => {
        try { await openAttachment(`/portal/documents/${d.id}/download`); }
        catch (e) { toast.error(formatErr(e)); }
    };
    const download = async (d) => {
        try { await saveAttachment(`/portal/documents/${d.id}/download`, d.original_filename); }
        catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <div>
                <h1 className="text-2xl font-bold text-slate-900" data-testid="results-reports-title">{t("documents.title")}</h1>
                <p className="text-slate-500 text-sm">{t("documents.subtitle")}</p>
            </div>
            {p && <PendingBanner status={p.verification_status} />}

            {docs.length === 0 ? (
                <Card data-testid="documents-empty" className="text-center py-10">
                    <FlaskConical className="w-10 h-10 text-slate-300 mx-auto mb-2" />
                    <p className="text-slate-500 text-sm">{t("documents.empty")}</p>
                </Card>
            ) : (
                <div className="space-y-3">
                    {docs.map((d) => (
                        <Card key={d.id} data-testid="document-item" className="p-4">
                            <div className="flex items-start gap-3">
                                <div className="w-10 h-10 rounded-full bg-sky-50 flex items-center justify-center flex-shrink-0">
                                    <FileText className="w-5 h-5 text-sky-500" />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="font-bold text-slate-800" data-testid="document-type">{d.type_label || d.service_label || t("documents.document")}</div>
                                    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-500 mt-1">
                                        <span className="inline-flex items-center gap-1" data-testid="document-date">
                                            <CalendarDays className="w-3.5 h-3.5" /> {formatDate(d.reviewed_at || d.shared_at)}
                                        </span>
                                        {d.reviewed_by && (
                                            <span className="inline-flex items-center gap-1" data-testid="document-reviewed-by">
                                                <Stethoscope className="w-3.5 h-3.5" /> {t("documents.reviewedBy")} {d.reviewed_by}
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex gap-2 mt-3">
                                        <button data-testid={`document-view-${d.id}`} onClick={() => view(d)}
                                            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-portal-blue text-portal-blueDark text-sm font-semibold hover:bg-portal-blue/5 transition">
                                            <Eye className="w-4 h-4" /> {t("documents.view")}
                                        </button>
                                        <button data-testid={`document-download-${d.id}`} onClick={() => download(d)}
                                            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-portal-blue hover:bg-portal-blueDark text-white text-sm font-semibold transition">
                                            <Download className="w-4 h-4" /> {t("documents.download")}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </Card>
                    ))}
                </div>
            )}

            <Card data-testid="results-questions-card" className="bg-slate-50 border-slate-200">
                <p className="font-bold text-slate-800">{t("documents.questionsTitle")}</p>
                <button data-testid="results-request-appointment" onClick={() => nav("/portal/appointments")}
                    className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-sm font-bold transition active:scale-95">
                    {t("documents.requestAppointment")}
                </button>
            </Card>
        </div>
    );
}
