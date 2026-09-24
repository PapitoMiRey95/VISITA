import { useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

export default function PortalBloodwork() {
    const { t } = useTranslation(["requests"]);
    const { overview, refetch } = usePortal();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const list = overview.data?.bloodwork || [];
    const [f, setF] = useState({ reason: "", patient_note: "" });
    const [busy, setBusy] = useState(false);
    const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await api.post("/portal/bloodwork", f);
            toast.success(t("bloodwork.toast"));
            setF({ reason: "", patient_note: "" });
            refetch();
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">{t("bloodwork.title")}</h1>
            <EmergencyNotice />
            {p && <PendingBanner status={p.verification_status} />}

            {verified && (
                <Card>
                    <form onSubmit={submit} className="space-y-4" data-testid="bloodwork-form">
                        <div>
                            <Label className="font-semibold text-slate-700">{t("bloodwork.reasonLabel")}</Label>
                            <select className="mt-1 w-full h-11 border border-slate-300 rounded-md px-3 text-sm bg-white"
                                required value={f.reason} onChange={(e) => set("reason", e.target.value)} data-testid="bld-reason">
                                <option value="" disabled>{t("form.selectReason")}</option>
                                <option value="Routine / Annual bloodwork">{t("bloodwork.reasonRoutine")}</option>
                                <option value="Follow-up / Repeat bloodwork">{t("bloodwork.reasonFollowup")}</option>
                                <option value="New symptoms or health concern">{t("bloodwork.reasonSymptoms")}</option>
                                <option value="Other">{t("form.reasonOther")}</option>
                            </select>
                        </div>
                        <div>
                            <Label className="font-semibold text-slate-700">{t("form.additionalNoteOptional")}</Label>
                            <Textarea className="mt-1" maxLength={50} value={f.patient_note} onChange={(e) => set("patient_note", e.target.value)} data-testid="bld-note" />
                            <div className="text-xs text-slate-400 mt-1 text-right">{f.patient_note.length}/50</div>
                        </div>
                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
                            {t("bloodwork.disclaimer")}
                        </div>
                        <Button type="submit" disabled={busy} data-testid="bld-submit" className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">{busy ? t("form.submitting") : t("form.submitRequest")}</Button>
                    </form>
                </Card>
            )}

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">{t("bloodwork.listTitle")}</h2>
                {list.length === 0 && <p className="text-slate-500 text-sm">{t("form.noRequestsYet")}</p>}
                {list.map((i) => (
                    <Card key={i.ref_number} className="p-4 flex justify-between items-start gap-2">
                        <div>
                            <div className="font-bold text-slate-800">{i.reason || t("bloodwork.defaultLabel")}</div>
                            <div className="text-sm text-slate-500">{i.ref_number}</div>
                        </div>
                        <StatusPill status={i.status} />
                    </Card>
                ))}
            </div>
        </div>
    );
}
