import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { CreditCard, Clock, CheckCircle2 } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { usePortal, Card } from "./shared";
import { HealthCardNumberInput } from "../components/HealthCardNumberInput";
import { IssueDatePicker } from "../components/IssueDatePicker";
import { ExpiryPicker } from "../components/ExpiryPicker";

import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { displayHcDate } from "../lib/hcDates";


export default function PortalHealthCard() {
    const { t } = useTranslation(["portal"]);
    const { overview, refetch, delegate } = usePortal();
    const p = overview.data?.patient;
    const pending = p?.pending_health_card;
    const [hc, setHc] = useState({ health_card_number: "", health_card_version: "", health_card_issue_date: "", health_card_expiry_date: "" });
    const [busy, setBusy] = useState(false);

    const submit = async () => {
        const num = hc.health_card_number.replace(/\D/g, "");
        const ver = hc.health_card_version.replace(/[^A-Za-z]/g, "");
        if (num.length !== 10) return toast.error(t("account.errHcNumber", "Health Card number must be 10 digits."));
        if (ver.length !== 2) return toast.error(t("account.errVersionCode", "Version code must be 2 letters."));
        setBusy(true);
        try {
            await api.post("/portal/profile/health-card", hc);
            toast.success(t("managed.hcSubmitted", "Health Card update submitted for staff review."));
            setHc({ health_card_number: "", health_card_version: "", health_card_issue_date: "", health_card_expiry_date: "" });
            refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <div className="space-y-4 animate-fade-in" data-testid="managed-health-card-page">
            <div className="flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-portal-blue" />
                <h1 className="text-xl font-bold text-slate-900">{t("nav.healthCard", "Health Card")}</h1>
            </div>
            <p className="text-sm text-slate-500">
                {t("managed.hcIntro", { name: delegate?.patient_name, defaultValue: "Submit a Health Card update for this patient. Changes are reviewed and approved by clinic staff before they take effect." })}
            </p>

            <Card data-testid="managed-hc-current">
                <p className="text-xs uppercase tracking-wide text-slate-400 font-bold mb-1">{t("managed.hcCurrent", "Current on file")}</p>
                <div className="font-semibold text-slate-800 tracking-wide" data-testid="managed-hc-current-value">{p?.health_card_display || t("account.notOnFile", "Not on file")}</div>
                <div className="text-xs text-slate-500 mt-0.5">
                    {t("account.issue", "Issued")}: {displayHcDate(p?.health_card_issue_date) || "—"} · {t("account.expiry", "Expires")}: {displayHcDate(p?.health_card_expiry_date) || "—"}
                </div>
            </Card>

            {pending && (
                <Card data-testid="managed-hc-pending" className="bg-amber-50 border-amber-200">
                    <div className="flex items-center gap-2 text-amber-800 font-bold text-sm"><Clock className="w-4 h-4" /> {t("managed.hcPendingTitle", "Pending staff review")}</div>
                    <div className="text-sm text-amber-900 mt-1" data-testid="managed-hc-pending-value">{pending.display}</div>
                    <div className="text-xs text-amber-800/80 mt-0.5">
                        {t("account.issue", "Issued")}: {displayHcDate(pending.health_card_issue_date) || "—"} · {t("account.expiry", "Expires")}: {displayHcDate(pending.health_card_expiry_date) || "—"}
                    </div>
                    <p className="text-xs text-amber-800/70 mt-2">{t("managed.hcPendingNote", "Submitted — the clinic will review and approve before this becomes active.")}</p>
                </Card>
            )}

            <Card data-testid="managed-hc-form">
                <div className="flex items-center gap-2 mb-3"><CheckCircle2 className="w-4 h-4 text-portal-blue" /><h2 className="font-bold text-slate-800 text-sm">{t("managed.hcSubmitTitle", "Submit an update")}</h2></div>
                <div className="grid grid-cols-2 gap-3">
                    <div className="col-span-2">
                        <Label className="text-xs">{t("account.hcNumber", "Health Card Number")}</Label>
                        <HealthCardNumberInput data-testid="managed-hc-number" value={hc.health_card_number} onChange={(v) => setHc({ ...hc, health_card_number: v })} placeholder="1234 567 890" />
                    </div>
                    <div>
                        <Label className="text-xs">{t("account.hcVersion", "Version Code")}</Label>
                        <Input data-testid="managed-hc-version" value={hc.health_card_version} onChange={(e) => setHc({ ...hc, health_card_version: e.target.value.toUpperCase() })} placeholder="XX" maxLength={2} />
                    </div>
                    <div><Label className="text-xs">{t("account.hcIssue", "Issue Date")}</Label><IssueDatePicker testid="managed-hc-issue" value={hc.health_card_issue_date} onChange={(v) => setHc({ ...hc, health_card_issue_date: v })} /></div>
                    <div><Label className="text-xs">{t("account.hcExpiry", "Expiry Date")}</Label><ExpiryPicker testid="managed-hc-expiry" value={hc.health_card_expiry_date} onChange={(v) => setHc({ ...hc, health_card_expiry_date: v })} dob={p?.date_of_birth} /></div>
                </div>
                <Button data-testid="managed-hc-submit" disabled={busy} onClick={submit} className="mt-3 bg-portal-blue text-white">
                    {busy ? t("common:loading", "Submitting…") : t("managed.hcSubmitBtn", "Submit for review")}
                </Button>
            </Card>
        </div>
    );
}
