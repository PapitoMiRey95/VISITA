import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { Building2, Loader2, ChevronLeft } from "lucide-react";
import { api, formatErr, setToken } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Logo } from "../components/Logo";

export default function PartnerRegister() {
    const nav = useNavigate();
    const { refreshMe } = useAuth();
    const [types, setTypes] = useState([]);
    const [busy, setBusy] = useState(false);
    const [form, setForm] = useState({
        organization_name: "", organization_type: "",
        contact_first_name: "", contact_last_name: "",
        email: "", phone: "", city: "", province: "",
        address: "", website: "", password: "", confirm_password: "",
    });
    const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

    useEffect(() => {
        api.get("/partner/org-types").then(({ data }) => setTypes(data.types || [])).catch(() => {});
    }, []);

    const submit = async (e) => {
        e.preventDefault();
        if (!form.organization_type) return toast.error("Please select an organization type.");
        if (form.password !== form.confirm_password) return toast.error("Passwords do not match.");
        setBusy(true);
        try {
            const { data } = await api.post("/partner/register", form);
            setToken(data.token);
            await refreshMe();
            toast.success("Organization account created. Welcome!");
            nav("/partner", { replace: true });
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="min-h-screen bg-slate-50 font-plex flex flex-col items-center px-4 py-8">
            <div className="w-full max-w-lg">
                <div className="flex items-center justify-between mb-6">
                    <Logo variant="light" iconClass="h-9 w-9" textClass="text-xl" />
                    <Link to="/login" className="flex items-center text-slate-500 text-sm hover:text-slate-800">
                        <ChevronLeft className="w-4 h-4" /> Home
                    </Link>
                </div>

                <form onSubmit={submit} data-testid="partner-register-form"
                    className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
                    <div className="flex items-center gap-2.5">
                        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-500/10 border border-cyan-500/30">
                            <Building2 className="w-5 h-5 text-cyan-600" />
                        </span>
                        <div>
                            <h1 className="text-xl font-bold text-slate-900">Register a Healthcare Organization</h1>
                            <p className="text-sm text-slate-500">Create an active partner account — you can complete your profile right after.</p>
                        </div>
                    </div>

                    <Field label="Organization / Business Name" testid="org-name-field">
                        <Input required data-testid="org-name" value={form.organization_name} onChange={set("organization_name")} />
                    </Field>

                    <Field label="Organization Type" testid="org-type-field">
                        <Select value={form.organization_type} onValueChange={(v) => setForm({ ...form, organization_type: v })}>
                            <SelectTrigger data-testid="org-type-trigger"><SelectValue placeholder="Select a type" /></SelectTrigger>
                            <SelectContent>
                                {types.map((t) => <SelectItem key={t} value={t} data-testid={`org-type-opt`}>{t}</SelectItem>)}
                            </SelectContent>
                        </Select>
                    </Field>

                    <div className="grid grid-cols-2 gap-3">
                        <Field label="Contact First Name" testid="contact-first-field"><Input required data-testid="contact-first" value={form.contact_first_name} onChange={set("contact_first_name")} /></Field>
                        <Field label="Contact Last Name" testid="contact-last-field"><Input required data-testid="contact-last" value={form.contact_last_name} onChange={set("contact_last_name")} /></Field>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <Field label="Business Email" testid="email-field"><Input type="email" required data-testid="org-email" value={form.email} onChange={set("email")} /></Field>
                        <Field label="Phone" testid="phone-field"><Input required data-testid="org-phone" value={form.phone} onChange={set("phone")} /></Field>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <Field label="City" testid="city-field"><Input required data-testid="org-city" value={form.city} onChange={set("city")} /></Field>
                        <Field label="Province" testid="province-field"><Input required data-testid="org-province" value={form.province} onChange={set("province")} placeholder="ON" /></Field>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <Field label="Street Address (optional)" testid="address-field"><Input data-testid="org-address" value={form.address} onChange={set("address")} /></Field>
                        <Field label="Website (optional)" testid="website-field"><Input data-testid="org-website" value={form.website} onChange={set("website")} placeholder="https://" /></Field>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <Field label="Password" testid="password-field"><Input type="password" required minLength={8} data-testid="org-password" value={form.password} onChange={set("password")} /></Field>
                        <Field label="Confirm Password" testid="confirm-field"><Input type="password" required minLength={8} data-testid="org-confirm" value={form.confirm_password} onChange={set("confirm_password")} /></Field>
                    </div>

                    <p className="text-xs text-slate-500 leading-relaxed bg-slate-50 border border-slate-200 rounded-lg p-3">
                        Your organization profile is <b>partner-submitted</b>: you supply and manage your own information. Partner accounts can only manage their own organization profile and cannot access patient records.
                    </p>

                    <Button type="submit" disabled={busy} data-testid="partner-register-submit"
                        className="w-full h-12 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-base font-bold">
                        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Create Organization Account"}
                    </Button>

                    <p className="text-center text-sm text-slate-600">
                        Already registered?{" "}
                        <Link to="/signin?partner=1" className="text-cyan-700 font-bold hover:underline">Partner Sign In</Link>
                    </p>
                </form>
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
