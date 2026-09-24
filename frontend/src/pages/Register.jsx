import { useState } from "react";
import { useNavigate, Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChevronLeft, Loader2, Clock } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Logo } from "../components/Logo";

const TYPE_KEYS = ["ohip", "private", "tourist", "none"];
// Reason values are sent to the backend and MUST remain in English.
const NP_REASONS = [
    { value: "I don't have a family doctor", k: "noFamilyDoctor" },
    { value: "My doctor is retiring", k: "doctorRetiring" },
    { value: "My doctor moved away", k: "doctorMoved" },
    { value: "I am new to the city", k: "newToCity" },
    { value: "Doctor–patient relationship ended", k: "relationshipEnded" },
];

export default function Register() {
    const { register } = useAuth();
    const nav = useNavigate();
    const { t } = useTranslation(["auth", "common"]);
    const [params] = useSearchParams();
    const isNew = params.get("new") === "1";
    // steps: 1=choose, 2=current form, 99=new-patient form, "former"=neutral notice,
    //        "reestablish"=return form, "done"=confirmation
    const [step, setStep] = useState(isNew ? 99 : 1);
    const [type, setType] = useState(isNew ? "none" : null);
    const [busy, setBusy] = useState(false);
    const [former, setFormer] = useState(null); // { message, prefill }
    const [confirm, setConfirm] = useState(null); // { message, ref_number }
    const [form, setForm] = useState({
        first_name: "", last_name: "", second_name: "", second_last_name: "",
        date_of_birth: "", phone: "", email: "", password: "",
        health_card_number: "", health_card_version: "", health_card_issue_date: "", health_card_expiry_date: "",
        province: "", country: "", extra_info: "",
        address: "", city: "", postal_code: "", patient_message: "", join_reason: "",
    });
    const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
    const joinName = (a, b) => [a, b].map((s) => (s || "").replace(/\s+/g, " ").trim()).filter(Boolean).join(" ");
    const optional = t("common:status.optional");

    const choose = (tp) => {
        setType(tp);
        setStep(tp === "none" ? 99 : 2);
    };

    const submit = async (e) => {
        e.preventDefault();
        if (type === "ohip") {
            const num = (form.health_card_number || "").replace(/\D/g, "");
            const ver = (form.health_card_version || "").replace(/[^A-Za-z]/g, "");
            if (num.length !== 10) { toast.error(t("auth:register.errHcNumber")); return; }
            if (ver.length !== 2) { toast.error(t("auth:register.errVersionCode")); return; }
        }
        setBusy(true);
        try {
            const first_name = joinName(form.first_name, form.second_name);
            const last_name = joinName(form.last_name, form.second_last_name);
            const res = await register({ ...form, first_name, last_name, patient_type: type });
            if (res?.former_detected) {
                setFormer({ message: res.message, prefill: res.prefill || {} });
                setForm((f) => ({ ...f, ...(res.prefill || {}) }));
                setStep("former");
                return;
            }
            toast.success(t("auth:register.accountCreated"));
            nav("/portal", { replace: true });
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    const submitReestablish = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const { data } = await api.post("/applications/return-request", {
                first_name: joinName(form.first_name, form.second_name), last_name: joinName(form.last_name, form.second_last_name), date_of_birth: form.date_of_birth,
                health_card_number: form.health_card_number || null, phone: form.phone, email: form.email,
                address: form.address || null, city: form.city || null, province: form.province || null,
                postal_code: form.postal_code || null, patient_message: form.patient_message || null,
            });
            setConfirm({ message: data.message, ref_number: data.ref_number });
            setStep("done");
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    const submitNewPatient = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const first = joinName(form.first_name, form.second_name);
            const last = joinName(form.last_name, form.second_last_name);
            const message = [form.join_reason, form.patient_message.trim()].filter(Boolean).join(" — ");
            const { data } = await api.post("/applications/new-patient", {
                first_name: first, last_name: last, date_of_birth: form.date_of_birth,
                phone: form.phone, email: form.email, city: form.city || null,
                province: form.province || null, country: form.country || null,
                patient_message: message || null,
            });
            setConfirm({ message: data.message, ref_number: data.ref_number });
            setStep("done");
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="min-h-screen bg-portal-blue/5 font-nunito flex flex-col items-center px-4 py-8">
            <div className="w-full max-w-md">
                <div className="flex items-center gap-2 mb-6">
                    <Logo variant="light" iconClass="h-9 w-9" textClass="text-xl" />
                </div>

                {step === 1 && (
                    <div className="animate-fade-in">
                        <h1 className="text-2xl font-bold text-slate-900 mb-1">{t("auth:register.welcome")}</h1>
                        <p className="text-slate-600 mb-5">{t("auth:register.currentPatientQ")}</p>
                        <div className="space-y-3">
                            {TYPE_KEYS.map((k) => (
                                <button
                                    key={k}
                                    data-testid={`reg-type-${k}`}
                                    onClick={() => choose(k)}
                                    className="w-full text-left bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:border-portal-blue hover:shadow transition active:scale-[0.99]"
                                >
                                    <div className="font-bold text-slate-900">{t(`auth:register.types.${k}.title`)}</div>
                                    <div className="text-sm text-slate-500">{t(`auth:register.types.${k}.desc`)}</div>
                                </button>
                            ))}
                        </div>
                        <p className="text-center text-sm text-slate-600 mt-6">
                            {t("auth:register.alreadyRegistered")}{" "}
                            <Link to="/signin" className="text-portal-blueDark font-bold hover:underline">{t("auth:register.signIn")}</Link>
                        </p>
                    </div>
                )}

                {step === 2 && (
                    <form onSubmit={submit} data-testid="register-current-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => setStep(1)} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">{t("auth:register.createAccount")}</h2>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstName")} testid="reg-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label={t("auth:register.secondName")} testid="reg-second"><Input value={form.second_name} onChange={set("second_name")} placeholder={optional} /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstLastName")} testid="reg-last"><Input required value={form.last_name} onChange={set("last_name")} /></Field>
                            <Field label={t("auth:register.secondLastName")} testid="reg-second-last"><Input value={form.second_last_name} onChange={set("second_last_name")} placeholder={optional} /></Field>
                        </div>
                        <Field label={t("auth:register.dob")} testid="reg-dob"><Input type="date" required value={form.date_of_birth} onChange={set("date_of_birth")} /></Field>

                        {type === "ohip" && (
                            <>
                                <div className="grid grid-cols-3 gap-3">
                                    <div className="col-span-2">
                                        <Field label={t("auth:register.hcNumberLabel")} testid="reg-hcn">
                                            <Input required value={form.health_card_number} onChange={set("health_card_number")} placeholder="1234 567 890" />
                                        </Field>
                                    </div>
                                    <Field label={t("auth:register.versionCode")} testid="reg-hcv">
                                        <Input required value={form.health_card_version} onChange={(e) => setForm({ ...form, health_card_version: e.target.value.toUpperCase() })} placeholder="XX" maxLength={2} />
                                    </Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <Field label={t("auth:register.issueDateOptional")} testid="reg-hc-issue"><Input type="date" value={form.health_card_issue_date} onChange={set("health_card_issue_date")} /></Field>
                                    <Field label={t("auth:register.expiryDateOptional")} testid="reg-hc-expiry"><Input type="date" value={form.health_card_expiry_date} onChange={set("health_card_expiry_date")} /></Field>
                                </div>
                            </>
                        )}
                        {type === "private" && (
                            <Field label={t("auth:register.provinceIfApplicable")} testid="reg-province"><Input value={form.province} onChange={set("province")} /></Field>
                        )}
                        {type === "tourist" && (
                            <Field label={t("auth:register.country")} testid="reg-country"><Input required value={form.country} onChange={set("country")} /></Field>
                        )}

                        <Field label={t("auth:register.phone")} testid="reg-phone"><Input required value={form.phone} onChange={set("phone")} placeholder="(416) 555-0000" /></Field>
                        <Field label={t("auth:register.email")} testid="reg-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>
                        <Field label={t("auth:register.password")} testid="reg-password"><Input type="password" required minLength={6} value={form.password} onChange={set("password")} /></Field>
                        {(type === "private" || type === "tourist") && (
                            <Field label={t("auth:register.extraInfoOptional")} testid="reg-extra"><Input value={form.extra_info} onChange={set("extra_info")} /></Field>
                        )}

                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
                            {t("auth:register.reviewNotice")}
                        </div>

                        <Button data-testid="reg-submit" type="submit" disabled={busy}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : t("auth:register.createAccountBtn")}
                        </Button>
                    </form>
                )}

                {step === "former" && (
                    <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in" data-testid="former-notice">
                        <h2 className="text-xl font-bold text-slate-900 mb-3">{t("auth:register.former.title")}</h2>
                        <p className="text-slate-600 mb-5 leading-relaxed">{former?.message}</p>
                        <Button data-testid="reestablish-start" onClick={() => setStep("reestablish")}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            {t("auth:register.former.reestablishBtn")}
                        </Button>
                        <p className="text-center text-sm text-slate-600 mt-5">
                            {t("auth:register.former.alreadyPortal")}{" "}
                            <Link to="/signin" className="text-portal-blueDark font-bold hover:underline">{t("auth:register.signIn")}</Link>
                        </p>
                    </div>
                )}

                {step === "reestablish" && (
                    <form onSubmit={submitReestablish} data-testid="reestablish-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => setStep("former")} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">{t("auth:register.reestablish.title")}</h2>
                        <p className="text-sm text-slate-500">{t("auth:register.reestablish.subtitle")}</p>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstName")} testid="re-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label={t("auth:register.secondName")} testid="re-second"><Input value={form.second_name} onChange={set("second_name")} placeholder={optional} /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstLastName")} testid="re-last"><Input required value={form.last_name} onChange={set("last_name")} /></Field>
                            <Field label={t("auth:register.secondLastName")} testid="re-second-last"><Input value={form.second_last_name} onChange={set("second_last_name")} placeholder={optional} /></Field>
                        </div>
                        <Field label={t("auth:register.dob")} testid="re-dob"><Input type="date" required value={form.date_of_birth} onChange={set("date_of_birth")} /></Field>
                        <Field label={t("auth:register.reestablish.hcNumber")} testid="re-hcn"><Input value={form.health_card_number} onChange={set("health_card_number")} placeholder="0000-000-000-XX" /></Field>
                        <Field label={t("auth:register.phone")} testid="re-phone"><Input required value={form.phone} onChange={set("phone")} /></Field>
                        <Field label={t("auth:register.email")} testid="re-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>
                        <Field label={t("auth:register.reestablish.addressOptional")} testid="re-address"><Input value={form.address} onChange={set("address")} /></Field>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.reestablish.city")} testid="re-city"><Input value={form.city} onChange={set("city")} /></Field>
                            <Field label={t("auth:register.reestablish.postalCode")} testid="re-postal"><Input value={form.postal_code} onChange={set("postal_code")} /></Field>
                        </div>
                        <Field label={t("auth:register.reestablish.messageOptional")} testid="re-message"><Input value={form.patient_message} onChange={set("patient_message")} placeholder={t("auth:register.reestablish.messagePlaceholder")} /></Field>

                        <Button data-testid="reestablish-submit" type="submit" disabled={busy}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : t("auth:register.reestablish.submit")}
                        </Button>
                    </form>
                )}

                {step === 99 && (
                    <form onSubmit={submitNewPatient} data-testid="new-patient-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => (isNew ? nav("/login") : setStep(1))} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">{t("auth:register.newPatient.title")}</h2>
                        <p className="text-slate-600 text-sm leading-relaxed">
                            {t("auth:register.newPatient.intro")}
                        </p>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstName")} testid="np-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label={t("auth:register.secondName")} testid="np-second"><Input value={form.second_name} onChange={set("second_name")} placeholder={optional} /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstLastName")} testid="np-last"><Input required value={form.last_name} onChange={set("last_name")} /></Field>
                            <Field label={t("auth:register.secondLastName")} testid="np-second-last"><Input value={form.second_last_name} onChange={set("second_last_name")} placeholder={optional} /></Field>
                        </div>
                        <Field label={t("auth:register.dob")} testid="np-dob"><Input type="date" required value={form.date_of_birth} onChange={set("date_of_birth")} /></Field>
                        <Field label={t("auth:register.phone")} testid="np-phone"><Input required value={form.phone} onChange={set("phone")} /></Field>
                        <Field label={t("auth:register.email")} testid="np-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.newPatient.city")} testid="np-city"><Input value={form.city} onChange={set("city")} /></Field>
                            <Field label={t("auth:register.newPatient.province")} testid="np-province"><Input value={form.province} onChange={set("province")} /></Field>
                        </div>
                        <Field label={t("auth:register.newPatient.reasonLabel")} testid="np-reason">
                            <Select value={form.join_reason} onValueChange={(v) => setForm({ ...form, join_reason: v })}>
                                <SelectTrigger data-testid="np-reason-trigger" className="w-full">
                                    <SelectValue placeholder={t("auth:register.newPatient.reasonPlaceholder")} />
                                </SelectTrigger>
                                <SelectContent>
                                    {NP_REASONS.map((r) => (
                                        <SelectItem key={r.value} value={r.value}>{t(`auth:register.newPatient.reasons.${r.k}`)}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                        <Field label={t("auth:register.newPatient.additionalMessageOptional")} testid="np-message"><Input value={form.patient_message} onChange={set("patient_message")} placeholder={t("auth:register.newPatient.messagePlaceholder")} /></Field>

                        <Button data-testid="new-patient-submit" type="submit" disabled={busy}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : t("auth:register.newPatient.submit")}
                        </Button>
                    </form>
                )}

                {step === "done" && (
                    <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in text-center" data-testid="application-confirmation">
                        <div className="w-14 h-14 rounded-full bg-portal-blue/10 flex items-center justify-center mx-auto mb-4">
                            <Clock className="w-7 h-7 text-portal-blueDark" />
                        </div>
                        <h2 className="text-xl font-bold text-slate-900 mb-2">{t("auth:register.done.title")}</h2>
                        <p className="text-slate-600 leading-relaxed mb-4">{confirm?.message}</p>
                        {confirm?.ref_number && (
                            <p className="text-sm text-slate-500 mb-5">{t("auth:register.done.reference")} <span className="font-semibold text-slate-700">{confirm.ref_number}</span></p>
                        )}
                        <Button data-testid="application-done" onClick={() => nav("/login")}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white h-11 rounded-xl">
                            {t("auth:register.done.done")}
                        </Button>
                    </div>
                )}
            </div>
        </div>
    );
}

function Field({ label, testid, children }) {
    return (
        <div data-testid={testid}>
            <Label className="text-sm font-semibold text-slate-700">{label}</Label>
            <div className="mt-1">{children}</div>
        </div>
    );
}
