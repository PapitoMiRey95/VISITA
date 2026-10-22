import { useState, useEffect, useCallback } from "react";
import { PasswordRequirements, passwordMeetsPolicy } from "../components/PasswordRequirements";
import { postalAssist, queuePostalCandidate } from "../lib/postalAssist";
import { useNavigate, Link, useSearchParams, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChevronLeft, Loader2, Clock, Stethoscope, Search, Eye, EyeOff, User, HeartHandshake, CheckCircle2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api, formatErr } from "../lib/api";
import { DobPicker } from "../components/DobPicker";
import { HealthCardNumberInput } from "../components/HealthCardNumberInput";
import { IssueDatePicker } from "../components/IssueDatePicker";
import { ExpiryPicker } from "../components/ExpiryPicker";
import { deriveExpiryISO } from "../lib/hcDates";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Logo } from "../components/Logo";
import { normalizeSurnameInput } from "../lib/name";
import { setAppLanguage } from "../i18n";

// Reason values are sent to the backend and MUST remain in English.
const NP_REASONS = [
    { value: "Previous doctor retired", k: "retired" },
    { value: "Previous doctor moved / relocated", k: "relocated" },
    { value: "I moved to a new area", k: "movedArea" },
    { value: "Previous clinic closed", k: "clinicClosed" },
    { value: "No longer a patient at previous clinic", k: "noLongerPatient" },
    { value: "Relationship with previous doctor ended", k: "relationshipEnded" },
    { value: "Looking for a doctor closer to home", k: "closerToHome" },
    { value: "Other", k: "other" },
];

// Patient-facing "current status in Canada" — administrative info only, never used
// to auto-block an application. Values sent to the backend remain English.
const STATUS_OPTIONS = [
    { value: "Canadian citizen", k: "citizen" },
    { value: "Permanent resident", k: "pr" },
    { value: "Work permit", k: "work" },
    { value: "Study permit", k: "study" },
    { value: "Visitor", k: "visitor" },
    { value: "Refugee / protected person", k: "refugee" },
    { value: "Other", k: "other" },
    { value: "Unsure / Prefer not to say", k: "unsure" },
];

const FIELD_TESTID = {
    first_name: "reg-first", last_name: "reg-last", date_of_birth: "reg-dob", sex: "reg-sex",
    health_card_number: "reg-hcn", health_card_version: "reg-hcv", health_card_issue_date: "reg-hc-issue",
    health_card_expiry_date: "reg-hc-expiry", address: "reg-address", city: "reg-city", province: "reg-address-province",
    postal_code: "reg-postal", country: "reg-address-country", phone: "reg-phone", email: "reg-email",
    password: "reg-password-field", confirm_password: "reg-confirm-password-field",
};

export default function Register() {
    const { register } = useAuth();
    const nav = useNavigate();
    const { t, i18n } = useTranslation(["auth", "common"]);
    const [params] = useSearchParams();
    const { practiceSlug } = useParams();
    const isNew = params.get("new") === "1";
    const sysMsg = (obj) => {
        if (!obj) return "";
        if (obj.code && (i18n.language || "en").startsWith("es")) return t(`auth:sys.${obj.code}`, { defaultValue: obj.message || "" });
        return obj.message || "";
    };

    // Resolved practice context (physician/clinic). The slug is a routing identifier
    // only. If VIen already knows the practice from the link, we never ask again.
    const [practice, setPractice] = useState(null);
    // steps: "resolving" | "findClinic" | 1=patient? | "coverage" | 2=current form |
    //        99=new-patient form | "done"
    const [step, setStep] = useState("resolving");
    const [type, setType] = useState(null);
    const [busy, setBusy] = useState(false);
    const [confirm, setConfirm] = useState(null);
    const [errors, setErrors] = useState({});
    const [form, setForm] = useState({
        first_name: "", last_name: "", second_name: "", second_last_name: "",
        date_of_birth: "", phone: "", email: "", password: "", confirm_password: "", sex: "",
        health_card_number: "", health_card_version: "", health_card_issue_date: "", health_card_expiry_date: "",
        province: "", country: "Canada", extra_info: "",
        address: "", unit: "", city: "", postal_code: "", patient_message: "", join_reason: "",
        has_ohip: null, had_family_doctor: null, reason_other: "", status_in_canada: "",
    });

    const resolveContext = useCallback(async () => {
        const slug = practiceSlug || params.get("practice");
        const code = params.get("code");
        try {
            if (slug) {
                const { data } = await api.get(`/practices/${encodeURIComponent(slug)}`);
                setPractice(data); setStep(isNew ? 99 : "whoFor"); return;
            }
            if (code) {
                const { data } = await api.get(`/practices/by-code/${encodeURIComponent(code)}`);
                setPractice(data); setStep(isNew ? 99 : "whoFor"); return;
            }
        } catch (e) { /* fall through to generic lookup */ }
        setStep("findClinic");
    }, [practiceSlug, params, isNew]);

    useEffect(() => { resolveContext(); }, [resolveContext]);

    const set = (k) => (e) => { clearErr(k); setForm({ ...form, [k]: e.target.value }); };
    const setDob = (v) => { clearErr("date_of_birth"); setForm((f) => {
        let expiry = f.health_card_expiry_date;
        if (expiry) { const exYear = Number(String(expiry).split("-")[0]); expiry = deriveExpiryISO(v, exYear); }
        return { ...f, date_of_birth: v, health_card_expiry_date: expiry };
    }); };
    const setHcDate = (k) => (v) => { clearErr(k); setForm((f) => ({ ...f, [k]: v })); };
    const setSurname = (k) => (e) => { clearErr(k); setForm({ ...form, [k]: normalizeSurnameInput(e.target.value) }); };
    const optional = t("common:status.optional");
    const practiceCtx = practice ? { practice_id: practice.id, practice_slug: practice.slug } : {};

    const [postalHint, setPostalHint] = useState(null);
    const onPostalBlur = async () => {
        const r = await postalAssist(form.postal_code, form);
        if (!r) return;
        setForm(r.next); setPostalHint(r.found ? `${r.city}, ${r.province}` : "unknown");
    };
    const postalHintEl = postalHint && <p className={`text-[11px] mt-1 ${postalHint === "unknown" ? "text-amber-700" : "text-emerald-700"}`} data-testid="reg-postal-hint">{postalHint === "unknown" ? t("auth:register.postalUnknown", "Postal code not found. Please enter your City and Province.") : t("auth:register.postalSuggested", "✓ City and Province found from your postal code: {{v}}", { v: postalHint })}</p>;
    const submit = async (e) => {
        e.preventDefault();
        const errs = validateCurrent();
        if (Object.keys(errs).length) {
            setErrors(errs);
            toast.error(t("auth:register.errFixFields"));
            document.querySelector(`[data-testid="${FIELD_TESTID[Object.keys(errs)[0]] || "reg-first"}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }
        setErrors({});
        setBusy(true);
        try {
            if (postalHint === "unknown") queuePostalCandidate(form);
            const res = await register({
                ...form,
                first_name: form.first_name.trim(), last_name: form.last_name.trim(),
                middle_name: form.second_name?.trim() || null,
                second_last_name: form.second_last_name?.trim() || null,
                patient_type: type, preferred_language: i18n.language, ...practiceCtx,
            });
            if (res?.application_required) {
                setForm((f) => ({ ...f, ...(res.prefill || {}) }));
                setType("none");
                setStep(99);
                toast.info(t("auth:register.ctx.notActiveApply"));
                return;
            }
            toast.success(t("auth:register.accountCreated"));
            nav("/portal", { replace: true });
        } catch (err) {
            const detail = err?.response?.data?.detail;
            if (detail?.code === "MISSING_FIELDS" && Array.isArray(detail.fields)) {
                // Server is the final guard: mirror its missing-field list onto the form.
                const srv = {};
                detail.fields.forEach((f) => { srv[f] = t("auth:register.errRequired"); });
                setErrors(srv);
                toast.error(t("auth:register.errFixFields"));
            } else toast.error(formatErr(err));
        } finally { setBusy(false); }
    };

    // Field-level validation for the current-patient form (OHIP + private branches).
    const validateCurrent = () => {
        const errs = {};
        const req = (k, msg) => { if (!String(form[k] ?? "").trim()) errs[k] = msg || t("auth:register.errRequired"); };
        req("first_name"); req("last_name");
        req("date_of_birth", t("auth:register.errDob"));
        req("sex", t("auth:register.errSex"));
        if (type === "ohip") {
            const num = (form.health_card_number || "").replace(/\D/g, "");
            const ver = (form.health_card_version || "").replace(/[^A-Za-z]/g, "");
            if (num.length !== 10) errs.health_card_number = t("auth:register.errHcNumber");
            if (ver.length !== 2) errs.health_card_version = t("auth:register.errVersionCode");
            if (!form.health_card_issue_date) errs.health_card_issue_date = t("auth:register.errIssueDate");
            if (!form.health_card_expiry_date) errs.health_card_expiry_date = t("auth:register.errExpiryDate");
        }
        req("address"); req("city"); req("province"); req("postal_code"); req("country");
        if ((form.phone || "").replace(/\D/g, "").length < 10) errs.phone = t("auth:register.errPhone");
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email || "")) errs.email = t("auth:register.errEmail");
        if (!passwordMeetsPolicy(form.password)) errs.password = t("auth:register.errPwPolicy", "Password doesn't meet all the requirements below.");
        else if (form.password !== form.confirm_password) errs.confirm_password = t("auth:register.errPwMismatch");
        return errs;
    };
    const err = (k) => errors[k];
    const clearErr = (k) => { if (errors[k]) setErrors((e) => { const n = { ...e }; delete n[k]; return n; }); };

    const submitNewPatient = async (e) => {
        e.preventDefault();
        if (!form.address?.trim() || !form.city?.trim() || !form.province?.trim() || !form.postal_code?.trim() || !form.country?.trim()) {
            toast.error(t("auth:register.errAddress")); return;
        }
        if (form.has_ohip === null || form.had_family_doctor === null) {
            toast.error(t("auth:register.newPatient.answerRequired")); return;
        }
        setBusy(true);
        try {
            if (postalHint === "unknown") queuePostalCandidate(form);
            const { data } = await api.post("/applications/new-patient", {
                first_name: form.first_name.trim(), last_name: form.last_name.trim(),
                middle_name: form.second_name?.trim() || null,
                second_last_name: form.second_last_name?.trim() || null,
                date_of_birth: form.date_of_birth,
                phone: form.phone, email: form.email,
                address: form.address || null, unit: form.unit || null, city: form.city || null,
                province: form.province || null, postal_code: form.postal_code || null, country: form.country || null,
                has_ohip: form.has_ohip, had_family_doctor: form.had_family_doctor,
                status_in_canada: form.has_ohip === false ? (form.status_in_canada || null) : null,
                join_reason: form.had_family_doctor ? (form.join_reason || null) : null,
                reason_other: (form.had_family_doctor && form.join_reason === "Other") ? (form.reason_other || null) : null,
                patient_message: form.patient_message.trim() || null, preferred_language: i18n.language, ...practiceCtx,
            });
            setConfirm({ message: data.message, code: data.message_code, ref_number: data.ref_number });
            setStep("done");
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    return (
        <div className="min-h-screen bg-portal-blue/5 font-nunito flex flex-col items-center px-4 py-8">
            <div className="w-full max-w-md">
                <button type="button" data-testid="register-back-btn" onClick={() => nav(-1)}
                    className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-portal-blueDark font-semibold mb-4 transition-colors">
                    <ChevronLeft className="h-4 w-4" /> {t("common:actions.back")}
                </button>
                <div className="flex items-center justify-between gap-2 mb-6">
                    <Logo variant="light" iconClass="h-9 w-9" textClass="text-xl" />
                    <div className="inline-flex items-center rounded-full border border-slate-300 bg-white p-0.5 shadow-sm" role="group" aria-label={t("auth:register.langPick")} data-testid="reg-lang-switch">
                        {[["en", "EN"], ["es", "ES"]].map(([code, label]) => {
                            const on = (i18n.language || "en").startsWith(code);
                            return (
                                <button key={code} type="button" data-testid={`reg-lang-${code}`} onClick={() => setAppLanguage(code)}
                                    aria-pressed={on}
                                    className={`px-3 h-8 rounded-full text-xs font-bold tracking-wide transition-colors ${on ? "bg-portal-blue text-white" : "text-slate-600 hover:text-portal-blueDark"}`}>
                                    {label}
                                </button>
                            );
                        })}
                    </div>
                </div>

                {practice && [1, "coverage", 2, 99, "whoFor", "caregiver"].includes(step) && (
                    <div data-testid="practice-banner" className="bg-white rounded-2xl border border-portal-blue/30 p-4 shadow-sm mb-4 flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-portal-blue/10 flex items-center justify-center flex-shrink-0">
                            <Stethoscope className="w-5 h-5 text-portal-blueDark" />
                        </div>
                        <div className="min-w-0">
                            <div className="text-xs text-slate-500 font-semibold">{t("auth:register.ctx.banner")}</div>
                            <div className="font-bold text-slate-900 truncate" data-testid="practice-physician">{practice.physician_name}</div>
                            {practice.clinic_name && <div className="text-sm text-slate-500 truncate">{practice.clinic_name}</div>}
                        </div>
                    </div>
                )}

                {step === "resolving" && (
                    <div className="text-center py-16 text-slate-400" data-testid="register-resolving">
                        <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2" /> {t("auth:register.ctx.resolving")}
                    </div>
                )}

                {step === "findClinic" && (
                    <FindClinic onResolved={(p) => { setPractice(p); setStep(isNew ? 99 : "whoFor"); }} />
                )}

                {step === "whoFor" && (
                    <div className="animate-fade-in" data-testid="register-whofor">
                        <h1 className="text-2xl font-bold text-slate-900 mb-5">{t("auth:register.whoFor.title")}</h1>
                        <div className="space-y-3">
                            <button data-testid="whofor-myself" onClick={() => setStep(1)}
                                className="w-full flex items-center gap-3 bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:border-portal-blue hover:shadow transition active:scale-[0.99] text-left">
                                <span className="w-11 h-11 rounded-full bg-portal-blue/10 flex items-center justify-center flex-shrink-0"><User className="w-5 h-5 text-portal-blueDark" /></span>
                                <span className="font-bold text-slate-900">{t("auth:register.whoFor.myself")}</span>
                            </button>
                            <button data-testid="whofor-caregiver" onClick={() => setStep("caregiver")}
                                className="w-full flex items-center gap-3 bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:border-portal-blue hover:shadow transition active:scale-[0.99] text-left">
                                <span className="w-11 h-11 rounded-full bg-portal-blue/10 flex items-center justify-center flex-shrink-0"><HeartHandshake className="w-5 h-5 text-portal-blueDark" /></span>
                                <span className="font-bold text-slate-900">{t("auth:register.whoFor.caregiver")}</span>
                            </button>
                        </div>
                        <p className="text-center text-sm text-slate-600 mt-6">
                            {t("auth:register.alreadyRegistered")}{" "}
                            <Link to="/signin" className="text-portal-blueDark font-bold hover:underline">{t("auth:register.signIn")}</Link>
                        </p>
                    </div>
                )}

                {step === "caregiver" && (
                    <CaregiverRequestForm practice={practice} t={t} onBack={() => setStep("whoFor")} onDone={() => setStep("caregiverDone")} />
                )}

                {step === "caregiverDone" && (
                    <div className="bg-white rounded-2xl border border-slate-200 p-8 shadow-sm animate-fade-in text-center" data-testid="caregiver-done">
                        <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto mb-3" />
                        <h2 className="text-xl font-bold text-slate-900 mb-2">{t("auth:register.caregiver.doneTitle")}</h2>
                        <p className="text-slate-600 text-sm leading-relaxed">{t("auth:register.caregiver.doneBody")}</p>
                        <Button data-testid="caregiver-done-signin" onClick={() => nav("/signin")}
                            className="mt-5 bg-portal-blue hover:bg-portal-blueDark text-white h-11 rounded-xl px-6">
                            {t("auth:register.signIn")}
                        </Button>
                    </div>
                )}

                {step === 1 && (
                    <div className="animate-fade-in" data-testid="register-patient-q">
                        <h1 className="text-2xl font-bold text-slate-900 mb-5">{t("auth:register.ctx.atClinicQ")}</h1>
                        <div className="grid grid-cols-2 gap-3">
                            <button data-testid="patient-yes" onClick={() => setStep("coverage")}
                                className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm hover:border-portal-blue hover:shadow transition active:scale-[0.99] font-bold text-lg text-slate-900">
                                {t("auth:register.ctx.yes")}
                            </button>
                            <button data-testid="patient-no" onClick={() => { setType("none"); setStep(99); }}
                                className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm hover:border-portal-blue hover:shadow transition active:scale-[0.99] font-bold text-lg text-slate-900">
                                {t("auth:register.ctx.no")}
                            </button>
                        </div>
                        <p className="text-center text-sm text-slate-600 mt-6">
                            {t("auth:register.alreadyRegistered")}{" "}
                            <Link to="/signin" className="text-portal-blueDark font-bold hover:underline">{t("auth:register.signIn")}</Link>
                        </p>
                    </div>
                )}

                {step === "coverage" && (
                    <div className="animate-fade-in" data-testid="register-coverage-q">
                        <button type="button" onClick={() => setStep(1)} className="flex items-center text-slate-500 text-sm mb-3">
                            <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
                        </button>
                        <h1 className="text-2xl font-bold text-slate-900 mb-5">{t("auth:register.ctx.ohipQ")}</h1>
                        <div className="space-y-3">
                            <button data-testid="ohip-yes" onClick={() => { setType("ohip"); setStep(2); }}
                                className="w-full text-left bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:border-portal-blue hover:shadow transition active:scale-[0.99] font-bold text-slate-900">
                                {t("auth:register.ctx.ohipYes")}
                            </button>
                            <button data-testid="ohip-no" onClick={() => { setType("private"); setStep(2); }}
                                className="w-full text-left bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:border-portal-blue hover:shadow transition active:scale-[0.99] font-bold text-slate-900">
                                {t("auth:register.ctx.ohipNo")}
                            </button>
                        </div>
                    </div>
                )}

                {step === 2 && (
                    <form onSubmit={submit} noValidate data-testid="register-current-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => setStep("coverage")} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">{t("auth:register.createAccount")}</h2>

                        <div className="grid grid-cols-2 gap-3">
                            <Field required error={err("first_name")} label={t("auth:register.firstName")} testid="reg-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label={t("auth:register.secondName")} testid="reg-second"><Input value={form.second_name} onChange={set("second_name")} placeholder={optional} /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field required error={err("last_name")} label={t("auth:register.firstLastName")} testid="reg-last"><Input required value={form.last_name} onChange={setSurname("last_name")} /></Field>
                            <Field label={t("auth:register.secondLastName")} testid="reg-second-last"><Input value={form.second_last_name} onChange={setSurname("second_last_name")} placeholder={optional} /></Field>
                        </div>
                        <Field required error={err("date_of_birth")} label={t("auth:register.dob")} testid="reg-dob"><DobPicker value={form.date_of_birth} onChange={setDob} testid="reg-dob" /></Field>
                        <Field required error={err("sex")} label={t("auth:register.sexLabel")} testid="reg-sex">
                            <Select value={form.sex} onValueChange={(v) => { clearErr("sex"); setForm({ ...form, sex: v }); }}>
                                <SelectTrigger data-testid="reg-sex-trigger"><SelectValue placeholder={t("auth:register.sexSelect")} /></SelectTrigger>
                                <SelectContent>
                                    {["Male", "Female", "X"].map((o) => <SelectItem key={o} value={o}>{t(`auth:register.sexOptions.${o}`)}</SelectItem>)}
                                </SelectContent>
                            </Select>
                        </Field>

                        {type === "ohip" && (
                            <>
                                <div className="grid grid-cols-3 gap-3">
                                    <div className="col-span-2">
                                        <Field required error={err("health_card_number")} label={t("auth:register.hcNumberLabel")} testid="reg-hcn">
                                            <HealthCardNumberInput required value={form.health_card_number} onChange={(v) => { clearErr("health_card_number"); setForm({ ...form, health_card_number: v }); }} placeholder="1234 567 890" />
                                        </Field>
                                    </div>
                                    <Field required error={err("health_card_version")} label={t("auth:register.versionCode")} testid="reg-hcv">
                                        <Input required value={form.health_card_version} onChange={(e) => { clearErr("health_card_version"); setForm({ ...form, health_card_version: e.target.value.replace(/[^A-Za-z]/g, "").toUpperCase() }); }} placeholder="XX" maxLength={2} />
                                    </Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <Field required error={err("health_card_issue_date")} label={t("auth:register.issueDate")} testid="reg-hc-issue"><IssueDatePicker value={form.health_card_issue_date} onChange={setHcDate("health_card_issue_date")} testid="reg-hc-issue" /></Field>
                                    <Field required error={err("health_card_expiry_date")} label={t("auth:register.expiryDate")} testid="reg-hc-expiry"><ExpiryPicker value={form.health_card_expiry_date} onChange={setHcDate("health_card_expiry_date")} dob={form.date_of_birth} testid="reg-hc-expiry" /></Field>
                                </div>
                            </>
                        )}
                        <div className="pt-1">
                            <div className="text-sm font-semibold text-slate-700 mb-2">{t("auth:register.addressSection")}</div>
                            <div className="space-y-3">
                                <Field required error={err("postal_code")} label={t("auth:register.addressPostal")} testid="reg-postal"><Input required placeholder="M6E 4H1" maxLength={7} value={form.postal_code} onChange={set("postal_code")} onBlur={onPostalBlur} />{postalHintEl}</Field>
                                <p className="text-[11px] text-slate-500 -mt-1 mb-1" data-testid="reg-postal-helper">{t("auth:register.postalHelper", "Enter your Ontario postal code to help fill your address faster.")}</p>
                                <div className="grid grid-cols-3 gap-3">
                                    <div className="col-span-2">
                                        <Field required error={err("address")} label={t("auth:register.addressStreet")} testid="reg-address"><Input required value={form.address} onChange={set("address")} placeholder="123 Main St" /></Field>
                                    </div>
                                    <Field label={t("auth:register.addressUnit")} testid="reg-unit"><Input value={form.unit} onChange={set("unit")} placeholder={optional} /></Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <Field required error={err("city")} label={t("auth:register.addressCity")} testid="reg-city"><Input required value={form.city} onChange={set("city")} /></Field>
                                    <Field required error={err("province")} label={t("auth:register.addressProvince")} testid="reg-address-province"><Input required value={form.province} onChange={set("province")} /></Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    
                                    <Field required error={err("country")} label={t("auth:register.addressCountry")} testid="reg-address-country"><Input required value={form.country} onChange={set("country")} /></Field>
                                </div>
                            </div>
                        </div>

                        <Field required error={err("phone")} label={t("auth:register.phone")} testid="reg-phone"><Input required value={form.phone} onChange={set("phone")} placeholder="(416) 555-0000" /></Field>
                        <Field required error={err("email")} label={t("auth:register.email")} testid="reg-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>
                        <div data-testid="reg-password-field">
                            <Label className="text-sm font-semibold text-slate-700">{t("auth:register.password")}<span className="text-rose-500 ml-0.5">*</span></Label>
                            <PasswordInput testid="reg-password" value={form.password} onChange={(v) => { clearErr("password"); setForm({ ...form, password: v }); }} minLength={8} required />
                            <PasswordRequirements password={form.password} testid="reg-pw-rules" />
                            {err("password") && <p className="text-xs text-rose-600 font-semibold mt-1" data-testid="reg-password-field-error">{err("password")}</p>}
                        </div>
                        <div data-testid="reg-confirm-password-field">
                            <Label className="text-sm font-semibold text-slate-700">{t("auth:register.confirmPassword")}<span className="text-rose-500 ml-0.5">*</span></Label>
                            <PasswordInput testid="reg-confirm-password" value={form.confirm_password} onChange={(v) => { clearErr("confirm_password"); setForm({ ...form, confirm_password: v }); }} minLength={6} required />
                            {err("confirm_password") && <p className="text-xs text-rose-600 font-semibold mt-1" data-testid="reg-confirm-password-field-error">{err("confirm_password")}</p>}
                            {form.confirm_password.length > 0 && (
                                form.password === form.confirm_password
                                    ? <p className="text-xs text-emerald-600 font-semibold mt-1" data-testid="pw-match">{t("auth:register.pwMatch")}</p>
                                    : <p className="text-xs text-rose-600 font-semibold mt-1" data-testid="pw-mismatch">{t("auth:register.pwMismatch")}</p>
                            )}
                        </div>
                        {type === "private" && (
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

                {step === 99 && (
                    <form onSubmit={submitNewPatient} data-testid="new-patient-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => (isNew ? nav("/login") : setStep(1))} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">{t("auth:register.ctx.applyQ")}</h2>
                        <p className="text-slate-600 text-sm leading-relaxed">{t("auth:register.ctx.applyNote")}</p>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstName")} testid="np-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label={t("auth:register.secondName")} testid="np-second"><Input value={form.second_name} onChange={set("second_name")} placeholder={optional} /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstLastName")} testid="np-last"><Input required value={form.last_name} onChange={setSurname("last_name")} /></Field>
                            <Field label={t("auth:register.secondLastName")} testid="np-second-last"><Input value={form.second_last_name} onChange={setSurname("second_last_name")} placeholder={optional} /></Field>
                        </div>
                        <Field label={t("auth:register.dob")} testid="np-dob"><DobPicker value={form.date_of_birth} onChange={setDob} testid="np-dob" /></Field>
                        <Field label={t("auth:register.phone")} testid="np-phone"><Input required value={form.phone} onChange={set("phone")} /></Field>
                        <Field label={t("auth:register.email")} testid="np-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>

                        <div className="pt-1">
                            <div className="text-sm font-semibold text-slate-700 mb-2">{t("auth:register.addressSection")}</div>
                            <div className="space-y-3">
                                <Field label={t("auth:register.addressPostal")} testid="np-postal"><Input required placeholder="M6E 4H1" maxLength={7} value={form.postal_code} onChange={set("postal_code")} onBlur={onPostalBlur} />{postalHintEl}</Field>
                                <p className="text-[11px] text-slate-500 -mt-1 mb-1" data-testid="reg-postal-helper">{t("auth:register.postalHelper", "Enter your Ontario postal code to help fill your address faster.")}</p>
                                <div className="grid grid-cols-3 gap-3">
                                    <div className="col-span-2">
                                        <Field label={t("auth:register.addressStreet")} testid="np-address"><Input required value={form.address} onChange={set("address")} placeholder="123 Main St" /></Field>
                                    </div>
                                    <Field label={t("auth:register.addressUnit")} testid="np-unit"><Input value={form.unit} onChange={set("unit")} placeholder={optional} /></Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <Field label={t("auth:register.addressCity")} testid="np-city"><Input required value={form.city} onChange={set("city")} /></Field>
                                    <Field label={t("auth:register.addressProvince")} testid="np-province"><Input required value={form.province} onChange={set("province")} /></Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    
                                    <Field label={t("auth:register.addressCountry")} testid="np-country"><Input required value={form.country} onChange={set("country")} /></Field>
                                </div>
                            </div>
                        </div>

                        <Field label={t("auth:register.newPatient.ohipQ")} testid="np-ohip">
                            <YesNo value={form.has_ohip} onChange={(v) => setForm({ ...form, has_ohip: v, status_in_canada: v === false ? form.status_in_canada : "" })}
                                yes={t("auth:register.newPatient.coverageYes")} no={t("auth:register.newPatient.coverageNo")} testid="np-ohip" />
                        </Field>

                        {form.has_ohip === false && (
                            <Field label={t("auth:register.newPatient.statusQ")} testid="np-status">
                                <Select value={form.status_in_canada} onValueChange={(v) => setForm({ ...form, status_in_canada: v })}>
                                    <SelectTrigger data-testid="np-status-trigger" className="w-full">
                                        <SelectValue placeholder={t("auth:register.newPatient.statusPlaceholder")} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {STATUS_OPTIONS.map((s) => (
                                            <SelectItem key={s.value} value={s.value}>{t(`auth:register.newPatient.statusOptions.${s.k}`)}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </Field>
                        )}

                        <Field label={t("auth:register.newPatient.hadDoctorQ")} testid="np-had-doctor">
                            <YesNo value={form.had_family_doctor} onChange={(v) => setForm({ ...form, had_family_doctor: v, join_reason: v ? form.join_reason : "", reason_other: v ? form.reason_other : "" })}
                                yes={t("auth:register.newPatient.coverageYes")} no={t("auth:register.newPatient.coverageNo")} testid="np-had-doctor" />
                        </Field>

                        {form.had_family_doctor === true && (
                            <Field label={t("auth:register.newPatient.whyNewDoctor")} testid="np-reason">
                                <Select value={form.join_reason} onValueChange={(v) => setForm({ ...form, join_reason: v })}>
                                    <SelectTrigger data-testid="np-reason-trigger" className="w-full">
                                        <SelectValue placeholder={t("auth:register.newPatient.reasonPlaceholder")} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {NP_REASONS.map((r) => (
                                            <SelectItem key={r.value} value={r.value}>{t(`auth:register.newPatient.reasons2.${r.k}`)}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </Field>
                        )}
                        {form.had_family_doctor === true && form.join_reason === "Other" && (
                            <Field label={t("auth:register.newPatient.reasonOtherLabel")} testid="np-reason-other">
                                <Input value={form.reason_other} onChange={set("reason_other")} placeholder={optional} />
                            </Field>
                        )}

                        <Field label={t("auth:register.newPatient.additionalMessageOptional")} testid="np-message"><Input value={form.patient_message} onChange={set("patient_message")} placeholder={t("auth:register.newPatient.messagePlaceholder")} /></Field>

                        <Button data-testid="new-patient-submit" type="submit" disabled={busy}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : t("auth:register.ctx.applyBtn")}
                        </Button>
                    </form>
                )}

                {step === "done" && (
                    <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in text-center" data-testid="application-confirmation">
                        <div className="w-14 h-14 rounded-full bg-portal-blue/10 flex items-center justify-center mx-auto mb-4">
                            <Clock className="w-7 h-7 text-portal-blueDark" />
                        </div>
                        <h2 className="text-xl font-bold text-slate-900 mb-2">{t("auth:register.done.title")}</h2>
                        <p className="text-slate-600 leading-relaxed mb-4">{sysMsg(confirm)}</p>
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

function FindClinic({ onResolved }) {
    const { t } = useTranslation(["auth", "common"]);
    const [q, setQ] = useState("");
    const [results, setResults] = useState(null);
    const [busy, setBusy] = useState(false);

    const search = async () => {
        if (!q.trim()) return;
        setBusy(true);
        try {
            const { data } = await api.get("/practices", { params: { q: q.trim() } });
            setResults(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4" data-testid="find-clinic">
            <h2 className="text-xl font-bold text-slate-900">{t("auth:register.ctx.find.title")}</h2>
            <p className="text-sm text-slate-500">{t("auth:register.ctx.find.sub")}</p>

            <div>
                <Label className="text-sm font-semibold text-slate-700">{t("auth:register.ctx.find.searchLabel")}</Label>
                <div className="flex gap-2 mt-1">
                    <div className="relative flex-1">
                        <Search className="w-4 h-4 text-slate-400 absolute left-2 top-3" />
                        <Input data-testid="find-search-input" value={q} onChange={(e) => setQ(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && search()} className="pl-8" autoFocus />
                    </div>
                    <Button data-testid="find-search-btn" disabled={busy} onClick={search}
                        className="bg-portal-blue hover:bg-portal-blueDark text-white">{t("auth:register.ctx.find.searchBtn")}</Button>
                </div>
                {results && results.length === 0 && <p className="text-sm text-slate-400 mt-2">{t("auth:register.ctx.find.none")}</p>}
                {results && results.length > 0 && (
                    <div className="mt-2 space-y-2">
                        {results.map((p) => (
                            <button key={p.id} data-testid={`find-pick-${p.slug}`} onClick={() => onResolved(p)}
                                className="w-full text-left bg-slate-50 rounded-xl border border-slate-200 p-3 hover:border-portal-blue transition">
                                <div className="font-bold text-slate-900">{p.physician_name}</div>
                                {p.clinic_name && <div className="text-sm text-slate-500">{p.clinic_name}</div>}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

function YesNo({ value, onChange, yes, no, testid }) {
    const base = "flex-1 rounded-xl border p-3 font-bold text-slate-900 transition active:scale-[0.99]";
    return (
        <div className="flex gap-3">
            <button type="button" data-testid={`${testid}-yes`} onClick={() => onChange(true)}
                className={`${base} ${value === true ? "border-portal-blue bg-portal-blue/5" : "border-slate-200 bg-white hover:border-portal-blue"}`}>{yes}</button>
            <button type="button" data-testid={`${testid}-no`} onClick={() => onChange(false)}
                className={`${base} ${value === false ? "border-portal-blue bg-portal-blue/5" : "border-slate-200 bg-white hover:border-portal-blue"}`}>{no}</button>
        </div>
    );
}

function Field({ label, testid, children, error, required }) {
    return (
        <div data-testid={testid} className={error ? "[&_input]:border-rose-400 [&_button]:border-rose-400" : ""}>
            <Label className="text-sm font-semibold text-slate-700">{label}{required && <span className="text-rose-500 ml-0.5" aria-hidden>*</span>}</Label>
            <div className="mt-1">{children}</div>
            {error && <p className="text-xs text-rose-600 font-semibold mt-1" data-testid={`${testid}-error`}>{error}</p>}
        </div>
    );
}


function PasswordInput({ value, onChange, testid, minLength = 6, required = false }) {
    const [show, setShow] = useState(false);
    return (
        <div className="relative mt-1">
            <Input type={show ? "text" : "password"} required={required} minLength={minLength}
                value={value} onChange={(e) => onChange(e.target.value)} data-testid={testid} className="pr-10" />
            <button type="button" tabIndex={-1} data-testid={`${testid}-toggle`} onClick={() => setShow((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                aria-label={show ? "Hide password" : "Show password"}>
                {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
        </div>
    );
}

const CG_RELATIONSHIPS = ["Daughter", "Son", "Spouse / Partner", "Parent", "Caregiver", "Legal / Substitute Decision Maker", "Other"];
const CG_BASES = [
    { value: "Patient consent", k: "consent" },
    { value: "Legal / Substitute Decision Maker", k: "legal" },
    { value: "Other authorized basis", k: "other" },
];

function CaregiverRequestForm({ practice, t, onBack, onDone }) {
    const [f, setF] = useState({
        patient_first_name: "", patient_last_name: "", patient_date_of_birth: "",
        patient_health_card_number: "", patient_health_card_version: "",
        patient_health_card_issue_date: "", patient_health_card_expiry_date: "",
        first_name: "", last_name: "", email: "", phone: "",
        relationship: "", authorization_basis: "", note: "",
        password: "", confirm_password: "",
    });
    const [busy, setBusy] = useState(false);
    const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
    const setHc = (k) => (v) => setF((prev) => ({ ...prev, [k]: v }));
    const pwValid = passwordMeetsPolicy(f.password) && f.password === f.confirm_password;

    const submit = async (e) => {
        e.preventDefault();
        const num = (f.patient_health_card_number || "").replace(/\D/g, "");
        if (num.length < 10) { toast.error(t("auth:register.caregiver.errHcNumber")); return; }
        if (!(f.patient_health_card_version || "").trim()) { toast.error(t("auth:register.caregiver.errHcVersion")); return; }
        if (!f.patient_health_card_issue_date) { toast.error(t("auth:register.errIssueDate")); return; }
        if (!f.patient_health_card_expiry_date) { toast.error(t("auth:register.errExpiryDate")); return; }
        if (!f.relationship) { toast.error(t("auth:register.caregiver.errRelationship")); return; }
        if (!f.authorization_basis) { toast.error(t("auth:register.caregiver.errBasis")); return; }
        if (!passwordMeetsPolicy(f.password)) { toast.error(t("auth:register.errPwPolicy", "Password doesn't meet all the requirements below.")); return; }
        if (f.password !== f.confirm_password) { toast.error(t("auth:register.errPwMismatch")); return; }
        setBusy(true);
        try {
            await api.post("/portal-access-requests", {
                practice_slug: practice?.slug, practice_id: practice?.id,
                patient_first_name: f.patient_first_name, patient_last_name: f.patient_last_name,
                patient_date_of_birth: f.patient_date_of_birth,
                patient_health_card_number: f.patient_health_card_number,
                patient_health_card_version: f.patient_health_card_version || null,
                patient_health_card_issue_date: f.patient_health_card_issue_date || null,
                patient_health_card_expiry_date: f.patient_health_card_expiry_date || null,
                first_name: f.first_name, last_name: f.last_name, email: f.email, phone: f.phone,
                password: f.password,
                relationship: f.relationship, authorization_basis: f.authorization_basis,
                note: f.note || null,
            });
            onDone();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    return (
        <form onSubmit={submit} data-testid="caregiver-request-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
            <button type="button" onClick={onBack} className="flex items-center text-slate-500 text-sm">
                <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
            </button>
            <h2 className="text-xl font-bold text-slate-900">{t("auth:register.caregiver.title")}</h2>
            <div className="bg-portal-blue/5 border border-portal-blue/20 rounded-lg p-3 text-sm text-slate-700">
                {t("auth:register.caregiver.explain")}
            </div>

            <div className="text-sm font-semibold text-slate-700 pt-1">{t("auth:register.caregiver.personSection")}</div>
            <div className="grid grid-cols-2 gap-3">
                <Field label={t("auth:register.firstName")} testid="cg-patient-first"><Input required value={f.patient_first_name} onChange={set("patient_first_name")} /></Field>
                <Field label={t("auth:register.firstLastName")} testid="cg-patient-last"><Input required value={f.patient_last_name} onChange={set("patient_last_name")} /></Field>
            </div>
            <Field label={t("auth:register.dob")} testid="cg-patient-dob"><DobPicker value={f.patient_date_of_birth} onChange={(v) => setF({ ...f, patient_date_of_birth: v })} testid="cg-patient-dob" /></Field>
            <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                    <Field label={t("auth:register.hcNumberLabel")} testid="cg-patient-hcn">
                        <HealthCardNumberInput required value={f.patient_health_card_number} onChange={setHc("patient_health_card_number")} placeholder="1234 567 890" />
                    </Field>
                </div>
                <Field label={t("auth:register.versionCode")} testid="cg-patient-hcv">
                    <Input required value={f.patient_health_card_version} onChange={(e) => setF({ ...f, patient_health_card_version: e.target.value.toUpperCase() })} placeholder="XX" maxLength={2} />
                </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
                <Field label={t("auth:register.issueDate")} testid="cg-patient-hc-issue"><IssueDatePicker value={f.patient_health_card_issue_date} onChange={setHc("patient_health_card_issue_date")} testid="cg-patient-hc-issue" /></Field>
                <Field label={t("auth:register.expiryDate")} testid="cg-patient-hc-expiry"><ExpiryPicker value={f.patient_health_card_expiry_date} onChange={setHc("patient_health_card_expiry_date")} dob={f.patient_date_of_birth} testid="cg-patient-hc-expiry" /></Field>
            </div>

            <div className="text-sm font-semibold text-slate-700 pt-1">{t("auth:register.caregiver.yourSection")}</div>
            <div className="grid grid-cols-2 gap-3">
                <Field label={t("auth:register.firstName")} testid="cg-your-first"><Input required value={f.first_name} onChange={set("first_name")} /></Field>
                <Field label={t("auth:register.firstLastName")} testid="cg-your-last"><Input required value={f.last_name} onChange={set("last_name")} /></Field>
            </div>
            <Field label={t("auth:register.email")} testid="cg-your-email"><Input type="email" required value={f.email} onChange={set("email")} /></Field>
            <Field label={t("auth:register.phone")} testid="cg-your-phone"><Input required value={f.phone} onChange={set("phone")} placeholder="(416) 555-0000" /></Field>

            <Field label={t("auth:register.caregiver.relationshipQ")} testid="cg-relationship">
                <Select value={f.relationship} onValueChange={(v) => setF({ ...f, relationship: v })}>
                    <SelectTrigger data-testid="cg-relationship-trigger"><SelectValue placeholder={t("auth:register.caregiver.select")} /></SelectTrigger>
                    <SelectContent>
                        {CG_RELATIONSHIPS.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                </Select>
            </Field>
            <Field label={t("auth:register.caregiver.basisQ")} testid="cg-basis">
                <Select value={f.authorization_basis} onValueChange={(v) => setF({ ...f, authorization_basis: v })}>
                    <SelectTrigger data-testid="cg-basis-trigger"><SelectValue placeholder={t("auth:register.caregiver.select")} /></SelectTrigger>
                    <SelectContent>
                        {CG_BASES.map((b) => <SelectItem key={b.value} value={b.value}>{t(`auth:register.caregiver.basisOptions.${b.k}`)}</SelectItem>)}
                    </SelectContent>
                </Select>
            </Field>
            <Field label={t("auth:register.caregiver.noteOptional")} testid="cg-note"><Input value={f.note} onChange={set("note")} placeholder={t("common:status.optional")} /></Field>

            <div className="border-t border-slate-100 pt-3">
                <p className="text-xs text-slate-500 mb-2">{t("auth:register.caregiver.passwordHelp")}</p>
                <div>
                    <Label className="text-sm font-semibold text-slate-700">{t("auth:register.password")}</Label>
                    <PasswordInput testid="cg-password" value={f.password} onChange={(v) => setF({ ...f, password: v })} minLength={8} required />
                    <PasswordRequirements password={f.password} testid="cg-pw-rules" />
                </div>
                <div className="mt-3">
                    <Label className="text-sm font-semibold text-slate-700">{t("auth:register.confirmPassword")}</Label>
                    <PasswordInput testid="cg-confirm-password" value={f.confirm_password} onChange={(v) => setF({ ...f, confirm_password: v })} minLength={8} required />
                    {f.confirm_password.length > 0 && (
                        f.password === f.confirm_password
                            ? <p className="text-xs text-emerald-600 font-semibold mt-1" data-testid="cg-pw-match">{t("auth:register.pwMatch")}</p>
                            : <p className="text-xs text-rose-600 font-semibold mt-1" data-testid="cg-pw-mismatch">{t("auth:register.pwMismatch")}</p>
                    )}
                </div>
            </div>

            <Button data-testid="cg-submit" type="submit" disabled={busy || !pwValid}
                className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : t("auth:register.caregiver.submitBtn")}
            </Button>
        </form>
    );
}
