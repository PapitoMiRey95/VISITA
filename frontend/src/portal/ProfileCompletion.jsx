import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { AlertTriangle, ChevronRight, IdCard } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { usePortal, Card } from "./shared";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";

// Own-patient only (never for caregiver "on behalf of" mode).
export function useCompleteness(enabled = true) {
    return useQuery({ queryKey: ["profile-completeness"], queryFn: async () => (await api.get("/portal/profile-completeness")).data, enabled, staleTime: 30000 });
}

export function MissingList({ missing, testid = "completion-missing-list" }) {
    const { t } = useTranslation(["portal"]);
    return (
        <ul data-testid={testid} className="text-sm text-amber-900 list-disc pl-5 space-y-0.5">
            {missing.map((m) => <li key={m} data-testid={`completion-missing-${m}`}>{t(`completion.fields.${m}`)}</li>)}
        </ul>
    );
}

export function CompletionBanner({ onOpen }) {
    const { t } = useTranslation(["portal"]);
    const c = useCompleteness();
    if (!c.data?.required) return null;
    return (
        <Card data-testid="completion-banner" className="bg-amber-50 border-amber-300">
            <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0"><IdCard className="w-5 h-5 text-amber-700" /></div>
                <div className="flex-1">
                    <p className="font-bold text-amber-900">{t("completion.bannerTitle")}</p>
                    <p className="text-sm text-amber-800 mt-0.5">{t("completion.bannerBody")}</p>
                    <div className="mt-2"><span className="text-xs font-bold text-amber-900">{t("completion.missingLabel")}</span><MissingList missing={c.data.missing} /></div>
                    <button data-testid="completion-banner-cta" onClick={onOpen}
                        className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-amber-700 hover:bg-amber-800 text-white text-sm font-bold transition active:scale-95">
                        {t("completion.bannerCta")} <ChevronRight className="w-4 h-4" />
                    </button>
                </div>
            </div>
        </Card>
    );
}

// Compact dynamic form: only the genuinely missing fields + health-card name confirmation.
export function CompletionModal({ open, onClose }) {
    const { t } = useTranslation(["portal"]);
    const { refetch } = usePortal();
    const c = useCompleteness();
    const missing = c.data?.missing || [];
    const name = c.data?.name_on_file || {};
    const [f, setF] = useState({});
    const [nm, setNm] = useState({});
    const [busy, setBusy] = useState(false);
    useEffect(() => { if (open) { setF({}); setNm({ first_name: name.first_name || "", middle_name: name.middle_name || "", last_name: name.last_name || "", second_last_name: name.second_last_name || "" }); } }, [open, c.data]); // eslint-disable-line react-hooks/exhaustive-deps
    const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
    const submit = async () => {
        setBusy(true);
        try {
            const body = { ...f, hc_first_name: nm.first_name, hc_middle_name: nm.middle_name, hc_last_name: nm.last_name, hc_second_last_name: nm.second_last_name };
            const { data } = await api.post("/portal/profile-completion", body);
            toast.success(data.completeness.required ? t("completion.savedPartial") : t("completion.savedAll"));
            if (data.conflicts.length || data.name_review) toast.message(t("completion.reviewNote"));
            await c.refetch(); refetch && refetch();
            if (!data.completeness.required) onClose();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const canSave = missing.some((m) => (f[m] || "").trim());
    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent data-testid="completion-modal" className="max-w-md">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2"><IdCard className="w-5 h-5 text-portal-blue" /> {t("completion.modalTitle")}</DialogTitle>
                    <DialogDescription>{t("completion.modalIntro")}</DialogDescription>
                </DialogHeader>
                <div className="space-y-3">
                    {c.data?.health_card_number_on_file && <p className="text-xs text-slate-500" data-testid="completion-hc-on-file">{t("completion.hcNumberOnFile")}: ✓</p>}
                    {missing.includes("health_card_version_code") && (
                        <div><Label className="text-xs">{t("completion.fields.health_card_version_code")}</Label>
                            <Input data-testid="completion-field-health_card_version_code" value={f.health_card_version_code || ""} onChange={(e) => set("health_card_version_code", e.target.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 2))} placeholder="AB" maxLength={2} className="w-24 uppercase" />
                            <p className="text-[11px] text-slate-500 mt-1">{t("completion.versionHelp")}</p></div>
                    )}
                    {missing.includes("health_card_issue_date") && (
                        <div><Label className="text-xs">{t("completion.fields.health_card_issue_date")}</Label><Input type="date" data-testid="completion-field-health_card_issue_date" value={f.health_card_issue_date || ""} onChange={(e) => set("health_card_issue_date", e.target.value)} /></div>
                    )}
                    {missing.includes("health_card_expiry_date") && (
                        <div><Label className="text-xs">{t("completion.fields.health_card_expiry_date")}</Label><Input type="date" data-testid="completion-field-health_card_expiry_date" value={f.health_card_expiry_date || ""} onChange={(e) => set("health_card_expiry_date", e.target.value)} /></div>
                    )}
                    {missing.includes("sex") && (
                        <div><Label className="text-xs">{t("completion.fields.sex")}</Label>
                            <Select value={f.sex || ""} onValueChange={(v) => set("sex", v)}>
                                <SelectTrigger data-testid="completion-field-sex"><SelectValue placeholder={t("account.selectSex")} /></SelectTrigger>
                                <SelectContent>{["Male", "Female", "X"].map((s) => <SelectItem key={s} value={s} data-testid={`completion-sex-${s}`}>{s}</SelectItem>)}</SelectContent>
                            </Select></div>
                    )}
                    <div className="rounded-lg border border-slate-200 p-3" data-testid="completion-name-block">
                        <p className="text-sm font-bold text-slate-800">{t("completion.nameTitle")}</p>
                        <p className="text-[11px] text-slate-500 mb-2">{t("completion.nameHelp")}</p>
                        <div className="grid grid-cols-2 gap-2">
                            {[["first_name", "firstName"], ["middle_name", "middleName"], ["last_name", "lastName"], ["second_last_name", "secondLastName"]].map(([k, lk]) => (
                                <div key={k}><Label className="text-[11px]">{t(`completion.${lk}`)}</Label><Input data-testid={`completion-name-${k}`} value={nm[k] || ""} onChange={(e) => setNm((s) => ({ ...s, [k]: e.target.value }))} /></div>
                            ))}
                        </div>
                    </div>
                </div>
                <div className="flex items-center justify-end gap-2 mt-2">
                    <Button variant="ghost" data-testid="completion-later" onClick={onClose}>{t("completion.later")}</Button>
                    <Button data-testid="completion-save" disabled={busy || !canSave} onClick={submit} className="bg-portal-blue text-white">{busy ? t("completion.saving") : t("completion.save")}</Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}

// Home: persistent banner + first-visit modal (dismissible per session only; banner always remains).
export function CompletionPrompt() {
    const c = useCompleteness();
    const [open, setOpen] = useState(false);
    useEffect(() => {
        if (c.data?.required && !sessionStorage.getItem("vien_completion_seen")) { setOpen(true); sessionStorage.setItem("vien_completion_seen", "1"); }
    }, [c.data?.required]);
    if (!c.data?.required) return null;
    return <><CompletionBanner onOpen={() => setOpen(true)} /><CompletionModal open={open} onClose={() => setOpen(false)} /></>;
}

// My Profile: "Information required" card.
export function CompletionProfileCard() {
    const { t } = useTranslation(["portal"]);
    const c = useCompleteness();
    const [open, setOpen] = useState(false);
    if (!c.data?.required) return null;
    return (
        <>
            <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 flex items-start gap-3" data-testid="completion-profile-card">
                <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
                <div className="flex-1">
                    <div className="font-bold text-amber-900">{t("completion.profileTitle")}</div>
                    <div className="text-sm text-amber-800 mb-1">{t("completion.profileBody")}</div>
                    <MissingList missing={c.data.missing} testid="completion-profile-missing" />
                    <Button size="sm" data-testid="completion-profile-cta" onClick={() => setOpen(true)} className="mt-2 bg-amber-700 hover:bg-amber-800 text-white">{t("completion.profileCta")}</Button>
                </div>
            </div>
            <CompletionModal open={open} onClose={() => setOpen(false)} />
        </>
    );
}
