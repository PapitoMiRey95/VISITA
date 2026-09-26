import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { LogOut, BellRing, IdCard, Phone, CreditCard, AlertTriangle, Clock, Mail, MapPin, User } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { usePortal, Card } from "./shared";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { HealthCardNumberInput } from "../components/HealthCardNumberInput";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";

const SEX_OPTIONS = ["Male", "Female", "X"];
const TYPE_KEY = { ohip: "typeOhip", private: "typePrivate", tourist: "typeTourist" };
const HC_BADGE = {
    VALID: "bg-emerald-100 text-emerald-700",
    EXPIRING_SOON: "bg-amber-100 text-amber-800",
    EXPIRED: "bg-red-100 text-red-700",
    INCOMPLETE: "bg-slate-100 text-slate-500",
};

export default function PortalAccount() {
    const nav = useNavigate();
    const { t } = useTranslation(["portal", "common"]);
    const { user, logout } = useAuth();
    const { overview, refetch } = usePortal();
    const p = overview.data?.patient;
    const notes = overview.data?.notifications || [];

    const [editPhone, setEditPhone] = useState(false);
    const [phone, setPhone] = useState("");
    const [editSex, setEditSex] = useState(false);
    const [sex, setSex] = useState("");
    const [editAddr, setEditAddr] = useState(false);
    const [addr, setAddr] = useState({ address: "", unit: "", city: "", province: "", postal_code: "" });
    const [hcOpen, setHcOpen] = useState(false);
    const [hc, setHc] = useState({ health_card_number: "", health_card_version: "", health_card_issue_date: "", health_card_expiry_date: "" });
    const [busy, setBusy] = useState(false);

    const markRead = async () => {
        await api.post("/portal/notifications/read");
        toast.success(t("portal:account.toastNotificationsRead"));
        refetch();
    };

    const savePhone = async () => {
        setBusy(true);
        try {
            await api.post("/portal/profile/phone", { phone });
            toast.success(t("portal:account.toastPhone"));
            setEditPhone(false); refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const saveSex = async () => {
        if (!sex) return toast.error(t("portal:account.errSelectSex"));
        setBusy(true);
        try {
            await api.post("/portal/profile/sex", { sex });
            toast.success(t("portal:account.toastSex"));
            setEditSex(false); refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const openAddr = () => {
        setAddr({
            address: p?.address || "", unit: p?.unit || "", city: p?.city || "",
            province: p?.province || "", postal_code: p?.postal_code || "",
        });
        setEditAddr(true);
    };

    const saveAddress = async () => {
        setBusy(true);
        try {
            await api.post("/portal/profile/address", addr);
            toast.success(t("portal:account.toastAddress"));
            setEditAddr(false); refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const submitHc = async () => {
        const num = hc.health_card_number.replace(/\D/g, "");
        const ver = hc.health_card_version.replace(/[^A-Za-z]/g, "");
        if (num.length !== 10) return toast.error(t("portal:account.errHcNumber"));
        if (ver.length !== 2) return toast.error(t("portal:account.errVersionCode"));
        setBusy(true);
        try {
            await api.post("/portal/profile/health-card", hc);
            toast.success(t("portal:account.toastHealthCard"));
            setHcOpen(false); refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const hcStatus = p?.health_card_status;
    const typeLabel = TYPE_KEY[p?.patient_type] ? t(`portal:account.${TYPE_KEY[p.patient_type]}`) : t("portal:account.patientFallback");
    const dash = "—";

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">{t("portal:account.title")}</h1>

            <Card>
                <div className="text-lg font-extrabold text-slate-900">{p ? `${p.first_name} ${p.last_name}` : user?.name}</div>
                <div className="text-sm text-slate-500">{user?.email}</div>
                <div className="mt-3 flex flex-wrap gap-2 text-sm">
                    <span className="px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold">{typeLabel}</span>
                    <span className={`px-2.5 py-0.5 rounded-full font-semibold ${p?.verification_status === "verified" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                        {p?.verification_status === "verified" ? t("portal:account.verified") : t("portal:account.verificationPending")}
                    </span>
                </div>
            </Card>

            {p && !p.sex && !editSex && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 flex items-start gap-3" data-testid="acct-sex-prompt">
                    <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
                    <div className="flex-1">
                        <div className="font-bold text-amber-900">{t("portal:account.sexPromptTitle")}</div>
                        <div className="text-sm text-amber-800">{t("portal:account.sexPromptDesc")}</div>
                        <button data-testid="acct-sex-prompt-set" className="mt-2 text-portal-blueDark text-sm font-bold"
                            onClick={() => { setSex(""); setEditSex(true); }}>{t("common:actions.setNow")}</button>
                    </div>
                </div>
            )}

            <Card>
                <div className="font-bold text-slate-700 mb-1">{t("portal:account.myInformation")}</div>

                <Row icon={IdCard} label={t("portal:account.visitaPin")} testid="acct-pin">{p?.visita_patient_id || t("portal:account.notAssigned")}</Row>

                <div className="py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-slate-500 text-sm"><Phone className="w-4 h-4" /> {t("portal:account.cellPhone")}</div>
                        {!editPhone && <button data-testid="acct-edit-phone" className="text-portal-blueDark text-sm font-bold" onClick={() => { setPhone(p?.phone || ""); setEditPhone(true); }}>{t("common:actions.edit")}</button>}
                    </div>
                    {!editPhone ? (
                        <div className="font-semibold text-slate-800 mt-0.5" data-testid="acct-phone">{p?.phone || dash}</div>
                    ) : (
                        <div className="flex gap-2 mt-1">
                            <Input data-testid="acct-phone-input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(416) 555-0000" />
                            <Button data-testid="acct-phone-save" disabled={busy} onClick={savePhone} className="bg-portal-blue text-white">{t("common:actions.save")}</Button>
                            <Button variant="outline" onClick={() => setEditPhone(false)}>{t("common:actions.cancel")}</Button>
                        </div>
                    )}
                </div>

                {p?.email && <Row icon={Mail} label={t("portal:account.emailLabel")} testid="acct-email">{p.email}</Row>}

                <div className="py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-slate-500 text-sm"><User className="w-4 h-4" /> {t("portal:account.sexLabel")} <span className="text-red-500">*</span></div>
                        {!editSex && <button data-testid="acct-edit-sex" className="text-portal-blueDark text-sm font-bold" onClick={() => { setSex(p?.sex || ""); setEditSex(true); }}>{p?.sex ? t("common:actions.edit") : t("common:actions.add")}</button>}
                    </div>
                    {!editSex ? (
                        <div className="font-semibold text-slate-800 mt-0.5" data-testid="acct-sex">{p?.sex ? t(`portal:account.sexOptions.${p.sex}`, p.sex) : t("common:status.notSet")}</div>
                    ) : (
                        <div className="flex gap-2 mt-1">
                            <Select value={sex} onValueChange={setSex}>
                                <SelectTrigger data-testid="acct-sex-trigger" className="flex-1"><SelectValue placeholder={t("portal:account.selectSex")} /></SelectTrigger>
                                <SelectContent>
                                    {SEX_OPTIONS.map((o) => <SelectItem key={o} value={o} data-testid={`acct-sex-opt-${o}`}>{t(`portal:account.sexOptions.${o}`, o)}</SelectItem>)}
                                </SelectContent>
                            </Select>
                            <Button data-testid="acct-sex-save" disabled={busy} onClick={saveSex} className="bg-portal-blue text-white">{t("common:actions.save")}</Button>
                            <Button variant="outline" onClick={() => setEditSex(false)}>{t("common:actions.cancel")}</Button>
                        </div>
                    )}
                </div>

                <div className="py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-slate-500 text-sm"><MapPin className="w-4 h-4" /> {t("portal:account.addressLabel")}</div>
                        {!editAddr && <button data-testid="acct-edit-address" className="text-portal-blueDark text-sm font-bold" onClick={openAddr}>{(p?.address || p?.city) ? t("common:actions.edit") : t("common:actions.add")}</button>}
                    </div>
                    {!editAddr ? (
                        <div className="font-semibold text-slate-800 mt-0.5" data-testid="acct-address">
                            {[[p?.address, p?.unit ? `#${p.unit}` : ""].filter(Boolean).join(" "),
                              [p?.city, p?.province].filter(Boolean).join(", "),
                              p?.postal_code].filter(Boolean).join(" · ") || dash}
                        </div>
                    ) : (
                        <div className="mt-1 space-y-2">
                            <div className="grid grid-cols-3 gap-2">
                                <div className="col-span-2"><Label className="text-xs">{t("portal:account.streetLabel")}</Label><Input data-testid="acct-address-street" value={addr.address} onChange={(e) => setAddr({ ...addr, address: e.target.value })} placeholder={t("portal:account.streetPlaceholder")} /></div>
                                <div><Label className="text-xs">{t("portal:account.unitLabel")}</Label><Input data-testid="acct-address-unit" value={addr.unit} onChange={(e) => setAddr({ ...addr, unit: e.target.value })} placeholder={t("common:status.optional")} /></div>
                            </div>
                            <div className="grid grid-cols-3 gap-2">
                                <div><Label className="text-xs">{t("portal:account.cityLabel")}</Label><Input data-testid="acct-address-city" value={addr.city} onChange={(e) => setAddr({ ...addr, city: e.target.value })} /></div>
                                <div><Label className="text-xs">{t("portal:account.provinceLabel")}</Label><Input data-testid="acct-address-province" value={addr.province} onChange={(e) => setAddr({ ...addr, province: e.target.value })} placeholder="ON" /></div>
                                <div><Label className="text-xs">{t("portal:account.postalLabel")}</Label><Input data-testid="acct-address-postal" value={addr.postal_code} onChange={(e) => setAddr({ ...addr, postal_code: e.target.value })} placeholder="A1A 1A1" /></div>
                            </div>
                            <div className="flex gap-2">
                                <Button data-testid="acct-address-save" disabled={busy} onClick={saveAddress} className="bg-portal-blue text-white">{t("common:actions.save")}</Button>
                                <Button variant="outline" onClick={() => setEditAddr(false)}>{t("common:actions.cancel")}</Button>
                            </div>
                        </div>
                    )}
                </div>

                <div className="py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-slate-500 text-sm"><CreditCard className="w-4 h-4" /> {t("portal:account.healthCard")}</div>
                        {hcStatus && <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${HC_BADGE[hcStatus]}`} data-testid="acct-hc-badge">{t(`portal:account.hcStatus.${hcStatus}`)}</span>}
                    </div>
                    <div className="font-semibold text-slate-800 mt-0.5 tracking-wide" data-testid="acct-hc">{p?.health_card_display || t("portal:account.notOnFile")}</div>
                    <div className="text-xs text-slate-500 mt-0.5">
                        {t("portal:account.issue")}: {p?.health_card_issue_date ? formatDate(p.health_card_issue_date) : dash} · {t("portal:account.expiry")}: {p?.health_card_expiry_date ? formatDate(p.health_card_expiry_date) : dash}
                    </div>
                    {(!p?.health_card_issue_date || !p?.health_card_expiry_date) && (
                        <div className="text-xs text-slate-500 mt-1">{t("portal:account.hcIncomplete")}</div>
                    )}
                    {hcStatus === "EXPIRING_SOON" && (
                        <div className="mt-2 flex items-start gap-2 text-sm bg-amber-50 border border-amber-200 text-amber-900 rounded-lg p-2" data-testid="acct-hc-warn-soon">
                            <Clock className="w-4 h-4 mt-0.5 shrink-0" /> {t("portal:account.hcWarnSoon")}
                        </div>
                    )}
                    {hcStatus === "EXPIRED" && (
                        <div className="mt-2 flex items-start gap-2 text-sm bg-red-50 border border-red-200 text-red-800 rounded-lg p-2" data-testid="acct-hc-warn-expired">
                            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> {t("portal:account.hcWarnExpired")}
                        </div>
                    )}
                    {!hcOpen ? (
                        <button data-testid="acct-hc-update" className="text-portal-blueDark text-sm font-bold mt-2" onClick={() => setHcOpen(true)}>{t("portal:account.updateHealthCard")}</button>
                    ) : (
                        <div className="mt-2 space-y-2 border-t border-slate-100 pt-2">
                            <div className="grid grid-cols-3 gap-2">
                                <div className="col-span-2">
                                    <Label className="text-xs">{t("portal:account.hcNumber")}</Label>
                                    <HealthCardNumberInput data-testid="acct-hc-number" value={hc.health_card_number} onChange={(v) => setHc({ ...hc, health_card_number: v })} placeholder="1234 567 890" />
                                </div>
                                <div>
                                    <Label className="text-xs">{t("portal:account.hcVersion")}</Label>
                                    <Input data-testid="acct-hc-version" value={hc.health_card_version} onChange={(e) => setHc({ ...hc, health_card_version: e.target.value.toUpperCase() })} placeholder="XX" maxLength={2} />
                                </div>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                <div><Label className="text-xs">{t("portal:account.hcIssue")}</Label><Input type="date" data-testid="acct-hc-issue" value={hc.health_card_issue_date} onChange={(e) => setHc({ ...hc, health_card_issue_date: e.target.value })} /></div>
                                <div><Label className="text-xs">{t("portal:account.hcExpiry")}</Label><Input type="date" data-testid="acct-hc-expiry" value={hc.health_card_expiry_date} onChange={(e) => setHc({ ...hc, health_card_expiry_date: e.target.value })} /></div>
                            </div>
                            <div className="flex gap-2">
                                <Button data-testid="acct-hc-submit" disabled={busy} onClick={submitHc} className="bg-portal-blue text-white">{t("portal:account.saveHealthCard")}</Button>
                                <Button variant="outline" onClick={() => setHcOpen(false)}>{t("common:actions.cancel")}</Button>
                            </div>
                        </div>
                    )}
                </div>
            </Card>

            <Card>
                <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2 font-bold text-slate-700"><BellRing className="w-5 h-5 text-portal-blue" /> {t("portal:account.notifications")}</div>
                    {notes.some((n) => !n.read) && <button onClick={markRead} data-testid="mark-read" className="text-sm text-portal-blueDark font-bold">{t("portal:account.markAllRead")}</button>}
                </div>
                {notes.length === 0 && <p className="text-slate-500 text-sm">{t("portal:account.noNotifications")}</p>}
                <div className="space-y-2">
                    {notes.map((n) => (
                        <div key={n.id} className={`text-sm rounded-lg p-3 border ${n.read ? "border-slate-100 bg-white" : "border-portal-blue/30 bg-portal-blue/5"}`}>
                            <div className="font-bold text-slate-800">{n.title}</div>
                            <div className="text-slate-600">{n.body}</div>
                        </div>
                    ))}
                </div>
            </Card>

            <Button onClick={() => { logout(); nav("/login"); }} data-testid="account-logout"
                variant="outline" className="w-full h-12 rounded-xl border-slate-300 text-slate-700">
                <LogOut className="w-4 h-4 mr-2" /> {t("portal:account.signOut")}
            </Button>
        </div>
    );
}

function Row({ icon: Icon, label, children, testid }) {
    return (
        <div className="py-2 border-t border-slate-100 first:border-t-0">
            <div className="flex items-center gap-2 text-slate-500 text-sm"><Icon className="w-4 h-4" /> {label}</div>
            <div className="font-semibold text-slate-800 mt-0.5" data-testid={testid}>{children}</div>
        </div>
    );
}
