import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { FileSearch, ChevronRight } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";

// Structured request actions only — the patient portal is an action/informational
// portal. Unrestricted free-text messaging to the physician is intentionally NOT
// offered here. Each action routes into its existing dedicated workflow.
const ROUTES = [
    { key: "Appointment", to: "/portal/appointments" },
    { key: "Prescription", to: "/portal/prescriptions" },
    { key: "New Referral", to: "/portal/referrals" },
    { key: "Referral Status", to: "/portal/referrals" },
    { key: "X-Ray / Ultrasound", to: "/portal/imaging" },
];

const DOC_PURPOSES = ["copy_result", "copy_imaging", "copy_other"];

export default function PortalMessages() {
    const nav = useNavigate();
    const { t } = useTranslation(["requests"]);
    const { overview, cfg, refetch } = usePortal();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const list = overview.data?.messages || [];
    const intro = cfg.data?.templates?.smart_routing_intro || t("messages.introFallback");
    const [docOpen, setDocOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    // Historical messages may carry legacy categories; render their labels read-only.
    const catLabel = (c) => (c === "Message for Doctor" ? t("messages.messageForDoctor") : c === "Other" ? t("messages.other") : t(`messages.routes.${c}`, c));

    const submitDocRequest = async (purpose) => {
        setBusy(true);
        try {
            await api.post("/portal/document-requests", { purpose });
            toast.success(t("docRequest.toast"));
            setDocOpen(false);
            refetch && refetch();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">{t("messages.title")}</h1>
            <EmergencyNotice />
            {p && <PendingBanner status={p.verification_status} />}

            {verified && (
                <Card>
                    <h2 className="font-bold text-slate-800 mb-3">{intro}</h2>
                    <div className="space-y-2">
                        {ROUTES.map((r) => (
                            <button key={r.key} data-testid={`route-${r.key}`} onClick={() => nav(r.to)}
                                className="w-full text-left px-4 py-3 rounded-xl border border-slate-200 font-semibold text-slate-700 hover:border-portal-blue hover:bg-portal-blue/5 transition">
                                {t(`messages.routes.${r.key}`, r.key)}
                            </button>
                        ))}
                        <button data-testid="route-document-request" onClick={() => setDocOpen((v) => !v)}
                            className="w-full text-left px-4 py-3 rounded-xl border border-slate-200 font-semibold text-slate-700 hover:border-portal-blue hover:bg-portal-blue/5 transition flex items-center gap-2">
                            <FileSearch className="w-4 h-4 text-portal-blue" /> {t("docRequest.action")}
                        </button>
                    </div>

                    {docOpen && (
                        <div className="mt-3 border-t border-slate-100 pt-3" data-testid="document-request-panel">
                            <p className="text-sm text-slate-600 mb-2">{t("docRequest.prompt")}</p>
                            <div className="space-y-2">
                                {DOC_PURPOSES.map((purpose) => (
                                    <button key={purpose} data-testid={`doc-purpose-${purpose}`} disabled={busy}
                                        onClick={() => submitDocRequest(purpose)}
                                        className="w-full text-left px-4 py-3 rounded-xl border border-slate-200 font-semibold text-slate-700 hover:border-portal-blue hover:bg-portal-blue/5 transition flex items-center justify-between">
                                        {t(`docRequest.purposes.${purpose}`)}
                                        <ChevronRight className="w-4 h-4 text-slate-300" />
                                    </button>
                                ))}
                            </div>
                            <p className="text-xs text-slate-500 mt-2">{t("docRequest.interpretationPre")}{" "}
                                <button type="button" data-testid="doc-request-appointment-link" onClick={() => nav("/portal/appointments")}
                                    className="text-portal-blue font-semibold underline">{t("docRequest.requestAppointment")}</button>.
                            </p>
                        </div>
                    )}
                </Card>
            )}

            {list.length > 0 && (
                <div className="space-y-3">
                    <h2 className="font-bold text-slate-700">{t("messages.listTitle")}</h2>
                    {list.map((m) => (
                        <Card key={m.ref_number} className="p-4">
                            <div className="flex justify-between items-start gap-2 mb-2">
                                <div className="font-bold text-slate-800">{m.subject || catLabel(m.category)}</div>
                                <StatusPill status={m.status} />
                            </div>
                            <div className="space-y-1.5">
                                {(m.thread || []).map((msg, i) => (
                                    <div key={i} className={`text-sm rounded-lg px-3 py-2 ${msg.from === "patient" ? "bg-slate-100 text-slate-700" : "bg-portal-blue/10 text-slate-800"}`}>
                                        <span className="font-bold">{msg.from === "patient" ? t("messages.you") : t("messages.clinic")}: </span>{msg.body}
                                    </div>
                                ))}
                            </div>
                        </Card>
                    ))}
                </div>
            )}
        </div>
    );
}
