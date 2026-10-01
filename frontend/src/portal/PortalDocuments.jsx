import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { FileText, Download, Eye, FolderOpen } from "lucide-react";
import { openAttachment, saveAttachment, formatErr } from "../lib/api";
import { usePortal, Card, PendingBanner } from "./shared";
import { formatDate } from "../lib/date";

export default function PortalDocuments() {
    const { t } = useTranslation(["portal"]);
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
                <h1 className="text-2xl font-bold text-slate-900">{t("documents.title")}</h1>
                <p className="text-slate-500 text-sm">{t("documents.subtitle")}</p>
            </div>
            {p && <PendingBanner status={p.verification_status} />}

            {docs.length === 0 ? (
                <Card data-testid="documents-empty" className="text-center py-10">
                    <FolderOpen className="w-10 h-10 text-slate-300 mx-auto mb-2" />
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
                                    <div className="font-bold text-slate-800 truncate">{d.original_filename || t("documents.document")}</div>
                                    <div className="text-sm text-slate-500">
                                        {d.service_label}{d.related_ref ? ` · ${d.related_ref}` : ""}
                                    </div>
                                    <div className="text-xs text-slate-400 mt-0.5">{t("documents.sharedOn")} {formatDate(d.shared_at)}</div>
                                    <div className="flex gap-2 mt-2">
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
        </div>
    );
}
