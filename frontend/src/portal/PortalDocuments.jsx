import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { FileText, Download, Eye, FlaskConical, Stethoscope, CalendarDays, Lock } from "lucide-react";
import { api, openAttachment, saveAttachment, formatErr } from "../lib/api";
import { usePortal, Card, PendingBanner } from "./shared";
import { formatDate } from "../lib/date";

export default function PortalDocuments() {
    const { t } = useTranslation(["portal"]);
    const nav = useNavigate();
    const { overview, refetch, base } = usePortal();
    const p = overview.data?.patient;
    const docs = overview.data?.documents || [];
    const pending = overview.data?.pending_results || [];
    const [busy, setBusy] = useState("");

    const view = async (d) => {
        try { await openAttachment(`/portal/documents/${d.id}/download`); }
        catch (e) { toast.error(formatErr(e)); }
    };
    const download = async (d) => {
        try { await saveAttachment(`/portal/documents/${d.id}/download`, d.original_filename); }
        catch (e) { toast.error(formatErr(e)); }
    };
    const requestAccess = async (r) => {
        setBusy(r.id);
        try {
            await api.post(`/portal/results/${r.id}/request-access`);
            toast.success(t("documents.accessRequested"));
            refetch && refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(""); }
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

            {pending.length > 0 && (
                <div className="space-y-3" data-testid="pending-results">
                    <p className="text-sm font-semibold text-slate-600">{t("documents.reviewedPendingTitle")}</p>
                    {pending.map((r) => (
                        <Card key={r.id} data-testid="pending-result-item" className="p-4">
                            <div className="flex items-start gap-3">
                                <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center flex-shrink-0">
                                    <Lock className="w-5 h-5 text-slate-400" />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="font-bold text-slate-800">{r.type_label}</div>
                                    <div className="flex flex-wrap items-center gap-x-3 text-xs text-slate-500 mt-1">
                                        <span className="inline-flex items-center gap-1"><CalendarDays className="w-3.5 h-3.5" /> {formatDate(r.reviewed_at)}</span>
                                        {r.reviewed_by && <span className="inline-flex items-center gap-1"><Stethoscope className="w-3.5 h-3.5" /> {t("documents.reviewedBy")} {r.reviewed_by}</span>}
                                    </div>
                                    <p className="text-xs text-slate-400 mt-1">{t("documents.reviewedPendingNote")}</p>
                                    <div className="mt-3">
                                        {r.access_requested ? (
                                            <span className="inline-flex items-center gap-1 text-sm font-semibold text-amber-600" data-testid="access-requested-badge">{t("documents.accessRequestedBadge")}</span>
                                        ) : (
                                            <button data-testid={`request-access-${r.id}`} disabled={busy === r.id} onClick={() => requestAccess(r)}
                                                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-portal-blue text-portal-blueDark text-sm font-semibold hover:bg-portal-blue/5 transition">
                                                {t("documents.requestAccess")}
                                            </button>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </Card>
                    ))}
                </div>
            )}

            <Card data-testid="results-questions-card" className="bg-slate-50 border-slate-200">
                <p className="font-bold text-slate-800">{t("documents.questionsTitle")}</p>
                <button data-testid="results-request-appointment" onClick={() => nav(`${base}/appointments`)}
                    className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-sm font-bold transition active:scale-95">
                    {t("documents.requestAppointment")}
                </button>
            </Card>
        </div>
    );
}
