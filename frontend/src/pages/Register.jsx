import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { ChevronLeft, Loader2, HeartPulse } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

const TYPES = [
    { key: "ohip", title: "Yes — OHIP patient", desc: "I have an Ontario Health Card" },
    { key: "private", title: "Yes — Private / Uninsured patient", desc: "I pay privately for visits" },
    { key: "tourist", title: "Tourist / Visitor", desc: "I am visiting from another country" },
    { key: "none", title: "I am not currently a patient", desc: "I have not seen Dr. Aguayo before" },
];

export default function Register() {
    const { register } = useAuth();
    const nav = useNavigate();
    const [step, setStep] = useState(1);
    const [type, setType] = useState(null);
    const [busy, setBusy] = useState(false);
    const [form, setForm] = useState({
        first_name: "", last_name: "", date_of_birth: "", phone: "", email: "", password: "",
        health_card_number: "", province: "", country: "", extra_info: "",
    });
    const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

    const choose = (t) => {
        setType(t);
        setStep(t === "none" ? 99 : 2);
    };

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await register({ ...form, patient_type: type });
            toast.success("Account created. Verification pending.");
            nav("/portal", { replace: true });
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="min-h-screen bg-portal-blue/5 font-nunito flex flex-col items-center px-4 py-8">
            <div className="w-full max-w-md">
                <div className="flex items-center gap-2 mb-6 text-portal-blueDark">
                    <HeartPulse className="w-7 h-7" />
                    <span className="text-xl font-extrabold">VISITA Patient Portal</span>
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
                            <Link to="/login" className="text-portal-blueDark font-bold hover:underline">Sign in</Link>
                        </p>
                    </div>
                )}

                {step === 99 && (
                    <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in">
                        <button onClick={() => setStep(1)} className="flex items-center text-slate-500 mb-3 text-sm">
                            <ChevronLeft className="w-4 h-4" /> Back
                        </button>
                        <h2 className="text-xl font-bold text-slate-900 mb-2">Becoming a patient</h2>
                        <p className="text-slate-600 mb-4">
                            This portal is for existing patients of Dr. Aguayo. To become a new patient, please contact
                            the clinic directly and our staff will help you get started.
                        </p>
                        <p className="text-sm text-slate-500">
                            Phone: (647) 555-0123 · VISITA — Dr. Aguayo Family Practice
                        </p>
                    </div>
                )}

                {step === 2 && (
                    <form onSubmit={submit} className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm animate-fade-in space-y-4">
                        <button type="button" onClick={() => setStep(1)} className="flex items-center text-slate-500 text-sm">
                            <ChevronLeft className="w-4 h-4" /> Back
                        </button>
                        <h2 className="text-xl font-bold text-slate-900">Create your account</h2>

                        <div className="grid grid-cols-2 gap-3">
                            <Field label="First name" testid="reg-first"><Input required value={form.first_name} onChange={set("first_name")} /></Field>
                            <Field label="Last name" testid="reg-last"><Input required value={form.last_name} onChange={set("last_name")} /></Field>
                        </div>
                        <Field label="Date of birth" testid="reg-dob"><Input type="date" required value={form.date_of_birth} onChange={set("date_of_birth")} /></Field>

                        {type === "ohip" && (
                            <Field label="Health Card Number" testid="reg-hcn">
                                <Input required value={form.health_card_number} onChange={set("health_card_number")} placeholder="0000-000-000-XX" />
                            </Field>
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
