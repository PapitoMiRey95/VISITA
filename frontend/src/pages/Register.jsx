import { useState, useEffect, useCallback } from "react";
import { useNavigate, Link, useSearchParams, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChevronLeft, Loader2, Clock, Stethoscope, Search } from "lucide-react";
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
    const [form, setForm] = useState({
        first_name: "", last_name: "", second_name: "", second_last_name: "",
        date_of_birth: "", phone: "", email: "", password: "",
        health_card_number: "", health_card_version: "", health_card_issue_date: "", health_card_expiry_date: "",
        province: "", country: "Canada", extra_info: "",
        address: "", unit: "", city: "", postal_code: "", patient_message: "", join_reason: "",
        has_ohip: null, had_family_doctor: null, reason_other: "",
    });

    const resolveContext = useCallback(async () => {
        const slug = practiceSlug || params.get("practice");
        const code = params.get("code");
        try {
            if (slug) {
                const { data } = await api.get(`/practices/${encodeURIComponent(slug)}`);
                setPractice(data); setStep(isNew ? 99 : 1); return;
            }
            if (code) {
                const { data } = await api.get(`/practices/by-code/${encodeURIComponent(code)}`);
                setPractice(data); setStep(isNew ? 99 : 1); return;
            }
        } catch (e) { /* fall through to generic lookup */ }
        setStep("findClinic");
    }, [practiceSlug, params, isNew]);

    useEffect(() => { resolveContext(); }, [resolveContext]);

    const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
    const setDob = (v) => setForm((f) => {
        let expiry = f.health_card_expiry_date;
        if (expiry) { const exYear = Number(String(expiry).split("-")[0]); expiry = deriveExpiryISO(v, exYear); }
        return { ...f, date_of_birth: v, health_card_expiry_date: expiry };
    });
    const setHcDate = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
    const setSurname = (k) => (e) => setForm({ ...form, [k]: normalizeSurnameInput(e.target.value) });
    const joinName = (a, b) => [a, b].map((s) => (s || "").replace(/\s+/g, " ").trim()).filter(Boolean).join(" ");
    const optional = t("common:status.optional");
    const practiceCtx = practice ? { practice_id: practice.id, practice_slug: practice.slug } : {};

    const submit = async (e) => {
        e.preventDefault();
        if (type === "ohip") {
            const num = (form.health_card_number || "").replace(/\D/g, "");
            const ver = (form.health_card_version || "").replace(/[^A-Za-z]/g, "");
            if (num.length !== 10) { toast.error(t("auth:register.errHcNumber")); return; }
            if (ver.length !== 2) { toast.error(t("auth:register.errVersionCode")); return; }
            if (!form.health_card_issue_date) { toast.error(t("auth:register.errIssueDate")); return; }
            if (!form.health_card_expiry_date) { toast.error(t("auth:register.errExpiryDate")); return; }
        }
        if (!form.address?.trim() || !form.city?.trim() || !form.province?.trim() || !form.postal_code?.trim() || !form.country?.trim()) {
            toast.error(t("auth:register.errAddress")); return;
        }
        setBusy(true);
        try {
            const first_name = joinName(form.first_name, form.second_name);
            const last_name = joinName(form.last_name, form.second_last_name);
            const res = await register({ ...form, first_name, last_name, patient_type: type, preferred_language: i18n.language, ...practiceCtx });
            if (res?.application_required) {
                setForm((f) => ({ ...f, ...(res.prefill || {}) }));
                setType("none");
                setStep(99);
                toast.info(t("auth:register.ctx.notActiveApply"));
                return;
            }
            toast.success(t("auth:register.accountCreated"));
            nav("/portal", { replace: true });
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

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
            const first = joinName(form.first_name, form.second_name);
            const last = joinName(form.last_name, form.second_last_name);
            const { data } = await api.post("/applications/new-patient", {
                first_name: first, last_name: last, date_of_birth: form.date_of_birth,
                phone: form.phone, email: form.email,
                address: form.address || null, unit: form.unit || null, city: form.city || null,
                province: form.province || null, postal_code: form.postal_code || null, country: form.country || null,
                has_ohip: form.has_ohip, had_family_doctor: form.had_family_doctor,
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
                <div className="flex items-center gap-2 mb-6">
                    <Logo variant="light" iconClass="h-9 w-9" textClass="text-xl" />
                </div>

                {practice && [1, "coverage", 2, 99].includes(step) && (
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
                    <FindClinic onResolved={(p) => { setPractice(p); setStep(isNew ? 99 : 1); }} />
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
                    <form onSubmit={submit} data-testid="register-current-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => setStep("coverage")} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> {t("common:actions.back")}
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">{t("auth:register.createAccount")}</h2>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstName")} testid="reg-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label={t("auth:register.secondName")} testid="reg-second"><Input value={form.second_name} onChange={set("second_name")} placeholder={optional} /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label={t("auth:register.firstLastName")} testid="reg-last"><Input required value={form.last_name} onChange={setSurname("last_name")} /></Field>
                            <Field label={t("auth:register.secondLastName")} testid="reg-second-last"><Input value={form.second_last_name} onChange={setSurname("second_last_name")} placeholder={optional} /></Field>
                        </div>
                        <Field label={t("auth:register.dob")} testid="reg-dob"><DobPicker value={form.date_of_birth} onChange={setDob} testid="reg-dob" /></Field>

                        {type === "ohip" && (
                            <>
                                <div className="grid grid-cols-3 gap-3">
                                    <div className="col-span-2">
                                        <Field label={t("auth:register.hcNumberLabel")} testid="reg-hcn">
                                            <HealthCardNumberInput required value={form.health_card_number} onChange={(v) => setForm({ ...form, health_card_number: v })} placeholder="1234 567 890" />
                                        </Field>
                                    </div>
                                    <Field label={t("auth:register.versionCode")} testid="reg-hcv">
                                        <Input required value={form.health_card_version} onChange={(e) => setForm({ ...form, health_card_version: e.target.value.toUpperCase() })} placeholder="XX" maxLength={2} />
                                    </Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <Field label={t("auth:register.issueDateOptional")} testid="reg-hc-issue"><IssueDatePicker value={form.health_card_issue_date} onChange={setHcDate("health_card_issue_date")} testid="reg-hc-issue" /></Field>
                                    <Field label={t("auth:register.expiryDateOptional")} testid="reg-hc-expiry"><ExpiryPicker value={form.health_card_expiry_date} onChange={setHcDate("health_card_expiry_date")} dob={form.date_of_birth} testid="reg-hc-expiry" /></Field>
                                </div>
                            </>
                        )}
                        <div className="pt-1">
                            <div className="text-sm font-semibold text-slate-700 mb-2">{t("auth:register.addressSection")}</div>
                            <div className="space-y-3">
                                <div className="grid grid-cols-3 gap-3">
                                    <div className="col-span-2">
                                        <Field label={t("auth:register.addressStreet")} testid="reg-address"><Input required value={form.address} onChange={set("address")} placeholder="123 Main St" /></Field>
                                    </div>
                                    <Field label={t("auth:register.addressUnit")} testid="reg-unit"><Input value={form.unit} onChange={set("unit")} placeholder={optional} /></Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <Field label={t("auth:register.addressCity")} testid="reg-city"><Input required value={form.city} onChange={set("city")} /></Field>
                                    <Field label={t("auth:register.addressProvince")} testid="reg-address-province"><Input required value={form.province} onChange={set("province")} /></Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <Field label={t("auth:register.addressPostal")} testid="reg-postal"><Input required value={form.postal_code} onChange={set("postal_code")} /></Field>
                                    <Field label={t("auth:register.addressCountry")} testid="reg-address-country"><Input required value={form.country} onChange={set("country")} /></Field>
                                </div>
                            </div>
                        </div>

                        <Field label={t("auth:register.phone")} testid="reg-phone"><Input required value={form.phone} onChange={set("phone")} placeholder="(416) 555-0000" /></Field>
                        <Field label={t("auth:register.email")} testid="reg-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>
                        <Field label={t("auth:register.password")} testid="reg-password"><Input type="password" required minLength={6} value={form.password} onChange={set("password")} /></Field>
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
                                    <Field label={t("auth:register.addressPostal")} testid="np-postal"><Input required value={form.postal_code} onChange={set("postal_code")} /></Field>
                                    <Field label={t("auth:register.addressCountry")} testid="np-country"><Input required value={form.country} onChange={set("country")} /></Field>
                                </div>
                            </div>
                        </div>

                        <Field label={t("auth:register.newPatient.ohipQ")} testid="np-ohip">
                            <YesNo value={form.has_ohip} onChange={(v) => setForm({ ...form, has_ohip: v })}
                                yes={t("auth:register.newPatient.coverageYes")} no={t("auth:register.newPatient.coverageNo")} testid="np-ohip" />
                        </Field>

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

function Field({ label, testid, children }) {
    return (
        <div data-testid={testid}>
            <Label className="text-sm font-semibold text-slate-700">{label}</Label>
            <div className="mt-1">{children}</div>
        </div>
    );
}
