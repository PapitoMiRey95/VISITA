import { useState } from "react";
import { useNavigate, Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ChevronLeft, Loader2, Clock } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Logo } from "../components/Logo";

const TYPES = [
    { key: "ohip", title: "Yes — OHIP patient", desc: "I have an Ontario Health Card" },
    { key: "private", title: "Yes — Private / Uninsured patient", desc: "I pay privately for visits" },
    { key: "tourist", title: "Tourist / Visitor", desc: "I am visiting from another country" },
    { key: "none", title: "I am not currently a patient", desc: "I have not seen Dr. Aguayo before" },
];

export default function Register() {
    const { register } = useAuth();
    const nav = useNavigate();
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

    const choose = (t) => {
        setType(t);
        setStep(t === "none" ? 99 : 2);
    };

    const submit = async (e) => {
        e.preventDefault();
        if (type === "ohip") {
            const num = (form.health_card_number || "").replace(/\D/g, "");
            const ver = (form.health_card_version || "").replace(/[^A-Za-z]/g, "");
            if (num.length !== 10) { toast.error("Health Card number must be exactly 10 digits."); return; }
            if (ver.length !== 2) { toast.error("Version Code must be exactly 2 letters."); return; }
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
            toast.success("Account created. Verification pending.");
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
                        <h1 className="text-2xl font-bold text-slate-900 mb-1">Welcome</h1>
                        <p className="text-slate-600 mb-5">Are you currently a patient of Dr. Aguayo?</p>
                        <div className="space-y-3">
                            {TYPES.map((t) => (
                                <button
                                    key={t.key}
                                    data-testid={`reg-type-${t.key}`}
                                    onClick={() => choose(t.key)}
                                    className="w-full text-left bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:border-portal-blue hover:shadow transition active:scale-[0.99]"
                                >
                                    <div className="font-bold text-slate-900">{t.title}</div>
                                    <div className="text-sm text-slate-500">{t.desc}</div>
                                </button>
                            ))}
                        </div>
                        <p className="text-center text-sm text-slate-600 mt-6">
                            Already registered?{" "}
                            <Link to="/signin" className="text-portal-blueDark font-bold hover:underline">Sign in</Link>
                        </p>
                    </div>
                )}

                {step === 2 && (
                    <form onSubmit={submit} data-testid="register-current-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => setStep(1)} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> Back
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">Create your account</h2>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label="First name" testid="reg-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label="Second name" testid="reg-second"><Input value={form.second_name} onChange={set("second_name")} placeholder="Optional" /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label="First last name" testid="reg-last"><Input required value={form.last_name} onChange={set("last_name")} /></Field>
                            <Field label="Second last name" testid="reg-second-last"><Input value={form.second_last_name} onChange={set("second_last_name")} placeholder="Optional" /></Field>
                        </div>
                        <Field label="Date of birth" testid="reg-dob"><Input type="date" required value={form.date_of_birth} onChange={set("date_of_birth")} /></Field>

                        {type === "ohip" && (
                            <>
                                <div className="grid grid-cols-3 gap-3">
                                    <div className="col-span-2">
                                        <Field label="Health Card Number (10 digits)" testid="reg-hcn">
                                            <Input required value={form.health_card_number} onChange={set("health_card_number")} placeholder="1234 567 890" />
                                        </Field>
                                    </div>
                                    <Field label="Version Code" testid="reg-hcv">
                                        <Input required value={form.health_card_version} onChange={(e) => setForm({ ...form, health_card_version: e.target.value.toUpperCase() })} placeholder="XX" maxLength={2} />
                                    </Field>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <Field label="Issue Date (optional)" testid="reg-hc-issue"><Input type="date" value={form.health_card_issue_date} onChange={set("health_card_issue_date")} /></Field>
                                    <Field label="Expiry Date (optional)" testid="reg-hc-expiry"><Input type="date" value={form.health_card_expiry_date} onChange={set("health_card_expiry_date")} /></Field>
                                </div>
                            </>
                        )}
                        {type === "private" && (
                            <Field label="Province (if applicable)" testid="reg-province"><Input value={form.province} onChange={set("province")} /></Field>
                        )}
                        {type === "tourist" && (
                            <Field label="Country" testid="reg-country"><Input required value={form.country} onChange={set("country")} /></Field>
                        )}

                        <Field label="Phone" testid="reg-phone"><Input required value={form.phone} onChange={set("phone")} placeholder="(416) 555-0000" /></Field>
                        <Field label="Email" testid="reg-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>
                        <Field label="Password" testid="reg-password"><Input type="password" required minLength={6} value={form.password} onChange={set("password")} /></Field>
                        {(type === "private" || type === "tourist") && (
                            <Field label="Additional identifying info (optional)" testid="reg-extra"><Input value={form.extra_info} onChange={set("extra_info")} /></Field>
                        )}

                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
                            Your account will be reviewed by clinic staff before full access is granted.
                        </div>

                        <Button data-testid="reg-submit" type="submit" disabled={busy}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Create account"}
                        </Button>
                    </form>
                )}

                {step === "former" && (
                    <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in" data-testid="former-notice">
                        <h2 className="text-xl font-bold text-slate-900 mb-3">Before we continue</h2>
                        <p className="text-slate-600 mb-5 leading-relaxed">{former?.message}</p>
                        <Button data-testid="reestablish-start" onClick={() => setStep("reestablish")}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            Request to Re-establish Care
                        </Button>
                        <p className="text-center text-sm text-slate-600 mt-5">
                            Already have portal access?{" "}
                            <Link to="/signin" className="text-portal-blueDark font-bold hover:underline">Sign in</Link>
                        </p>
                    </div>
                )}

                {step === "reestablish" && (
                    <form onSubmit={submitReestablish} data-testid="reestablish-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => setStep("former")} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> Back
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">Request to Re-establish Care</h2>
                        <p className="text-sm text-slate-500">Please confirm or update your details below.</p>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label="First name" testid="re-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label="Second name" testid="re-second"><Input value={form.second_name} onChange={set("second_name")} placeholder="Optional" /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label="First last name" testid="re-last"><Input required value={form.last_name} onChange={set("last_name")} /></Field>
                            <Field label="Second last name" testid="re-second-last"><Input value={form.second_last_name} onChange={set("second_last_name")} placeholder="Optional" /></Field>
                        </div>
                        <Field label="Date of birth" testid="re-dob"><Input type="date" required value={form.date_of_birth} onChange={set("date_of_birth")} /></Field>
                        <Field label="OHIP / Health Card Number" testid="re-hcn"><Input value={form.health_card_number} onChange={set("health_card_number")} placeholder="0000-000-000-XX" /></Field>
                        <Field label="Phone" testid="re-phone"><Input required value={form.phone} onChange={set("phone")} /></Field>
                        <Field label="Email" testid="re-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>
                        <Field label="Address (optional)" testid="re-address"><Input value={form.address} onChange={set("address")} /></Field>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label="City" testid="re-city"><Input value={form.city} onChange={set("city")} /></Field>
                            <Field label="Postal code" testid="re-postal"><Input value={form.postal_code} onChange={set("postal_code")} /></Field>
                        </div>
                        <Field label="Message (optional)" testid="re-message"><Input value={form.patient_message} onChange={set("patient_message")} placeholder="Anything you'd like the clinic to know" /></Field>

                        <Button data-testid="reestablish-submit" type="submit" disabled={busy}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Submit request"}
                        </Button>
                    </form>
                )}

                {step === 99 && (
                    <form onSubmit={submitNewPatient} data-testid="new-patient-form" className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => (isNew ? nav("/login") : setStep(1))} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> Back
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">New patient request</h2>
                        <p className="text-slate-600 text-sm leading-relaxed">
                            New patients are accepted by request. Please share your details and our staff will follow up.
                            Submitting a request does not guarantee acceptance as a patient.
                        </p>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label="First name" testid="np-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label="Second name" testid="np-second"><Input value={form.second_name} onChange={set("second_name")} placeholder="Optional" /></Field>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label="First last name" testid="np-last"><Input required value={form.last_name} onChange={set("last_name")} /></Field>
                            <Field label="Second last name" testid="np-second-last"><Input value={form.second_last_name} onChange={set("second_last_name")} placeholder="Optional" /></Field>
                        </div>
                        <Field label="Date of birth" testid="np-dob"><Input type="date" required value={form.date_of_birth} onChange={set("date_of_birth")} /></Field>
                        <Field label="Phone" testid="np-phone"><Input required value={form.phone} onChange={set("phone")} /></Field>
                        <Field label="Email" testid="np-email"><Input type="email" required value={form.email} onChange={set("email")} /></Field>
                        <div className="grid grid-cols-2 gap-3">
                            <Field label="City" testid="np-city"><Input value={form.city} onChange={set("city")} /></Field>
                            <Field label="Province" testid="np-province"><Input value={form.province} onChange={set("province")} /></Field>
                        </div>
                        <Field label="Reason for request" testid="np-reason">
                            <Select value={form.join_reason} onValueChange={(v) => setForm({ ...form, join_reason: v })}>
                                <SelectTrigger data-testid="np-reason-trigger" className="w-full">
                                    <SelectValue placeholder="Select a reason" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="I don't have a family doctor">I don't have a family doctor</SelectItem>
                                    <SelectItem value="My doctor is retiring">My doctor is retiring</SelectItem>
                                    <SelectItem value="My doctor moved away">My doctor moved away</SelectItem>
                                    <SelectItem value="I am new to the city">I am new to the city</SelectItem>
                                    <SelectItem value="Doctor–patient relationship ended">Doctor–patient relationship ended</SelectItem>
                                </SelectContent>
                            </Select>
                        </Field>
                        <Field label="Additional message (optional)" testid="np-message"><Input value={form.patient_message} onChange={set("patient_message")} placeholder="Anything else you'd like the clinic to know" /></Field>

                        <Button data-testid="new-patient-submit" type="submit" disabled={busy}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white text-base h-12 rounded-xl">
                            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Submit request"}
                        </Button>
                    </form>
                )}

                {step === "done" && (
                    <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in text-center" data-testid="application-confirmation">
                        <div className="w-14 h-14 rounded-full bg-portal-blue/10 flex items-center justify-center mx-auto mb-4">
                            <Clock className="w-7 h-7 text-portal-blueDark" />
                        </div>
                        <h2 className="text-xl font-bold text-slate-900 mb-2">Request received</h2>
                        <p className="text-slate-600 leading-relaxed mb-4">{confirm?.message}</p>
                        {confirm?.ref_number && (
                            <p className="text-sm text-slate-500 mb-5">Reference: <span className="font-semibold text-slate-700">{confirm.ref_number}</span></p>
                        )}
                        <Button data-testid="application-done" onClick={() => nav("/login")}
                            className="w-full bg-portal-blue hover:bg-portal-blueDark text-white h-11 rounded-xl">
                            Done
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
