import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Building2, Phone, Mail, Globe, Clock, Stethoscope, Languages, Save, Eye, Printer } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { AddressFields, emptyAddress } from "../components/AddressFields";

const DAYS = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"]];

const Field = ({ label, icon: Icon, children }) => (
    <div>
        <Label className="text-xs flex items-center gap-1.5 text-slate-600">{Icon && <Icon className="w-3.5 h-3.5" />}{label}</Label>
        <div className="mt-1">{children}</div>
    </div>
);

const listToText = (l) => (l || []).join(", ");
const textToList = (t) => (t || "").split(/[,\n]/).map((s) => s.trim()).filter(Boolean);

export default function ClinicProfile() {
    const { user } = useAuth();
    const canEdit = ["admin", "physician"].includes(user?.role);
    const [p, setP] = useState(null);
    const [busy, setBusy] = useState(false);
    const [servicesText, setServicesText] = useState("");
    const [langsText, setLangsText] = useState("");

    useEffect(() => {
        api.get("/internal/clinic-profile").then(({ data }) => {
            setP({ ...data, address_struct: { ...emptyAddress(), ...(data.address_struct || {}) }, hours: data.hours || {} });
            setServicesText(listToText(data.services)); setLangsText(listToText(data.languages));
        }).catch((e) => toast.error(formatErr(e)));
    }, []);

    const set = (k) => (e) => setP((s) => ({ ...s, [k]: e?.target ? e.target.value : e }));
    const setHour = (d, v) => setP((s) => ({ ...s, hours: { ...(s.hours || {}), [d]: v } }));

    const save = async () => {
        setBusy(true);
        try {
            const body = { ...p, services: textToList(servicesText), languages: textToList(langsText) };
            delete body.slug; delete body.profile_updated_at;
            const { data } = await api.put("/internal/clinic-profile", body);
            setP({ ...data, address_struct: { ...emptyAddress(), ...(data.address_struct || {}) }, hours: data.hours || {} });
            toast.success("Clinic profile saved — reflected across the VIen network.");
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const publicUrl = useMemo(() => (p?.slug ? `${window.location.origin}/api/practices/${p.slug}/profile` : ""), [p?.slug]);

    if (!p) return <div className="p-6 text-sm text-slate-500" data-testid="clinic-profile-loading">Loading clinic profile…</div>;

    return (
        <div className="p-4 sm:p-6 max-w-6xl" data-testid="clinic-profile-page">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2"><Building2 className="w-6 h-6 text-visita-green" /> Clinic Profile</h1>
                    <p className="text-sm text-slate-500 mt-1">The clinic's identity on the VIen network — phones, emails, address, hours and services. Public information, reused by the patient portal, messages and the network directory.</p>
                </div>
                {canEdit && <Button onClick={save} disabled={busy} data-testid="clinic-profile-save" className="bg-visita-green hover:bg-visita-greenDark text-white"><Save className="w-4 h-4 mr-1.5" /> {busy ? "Saving…" : "Save profile"}</Button>}
            </div>

            <div className="grid lg:grid-cols-[1fr_380px] gap-5">
                <div className="space-y-5">
                    <section className="border border-slate-200 rounded-sm p-4 space-y-3 bg-white" data-testid="clinic-identity">
                        <h2 className="text-sm font-semibold text-slate-800">Identity</h2>
                        <div className="grid sm:grid-cols-2 gap-3">
                            <Field label="Clinic name"><Input data-testid="clinic-name" value={p.clinic_name || ""} onChange={set("clinic_name")} disabled={!canEdit} /></Field>
                            <Field label="Lead physician" icon={Stethoscope}><Input data-testid="clinic-physician" value={p.physician_name || ""} onChange={set("physician_name")} disabled={!canEdit} /></Field>
                        </div>
                        <Field label="About the clinic (what you do)"><Textarea data-testid="clinic-about" rows={3} value={p.about || ""} onChange={set("about")} disabled={!canEdit} placeholder="Family medicine, walk-in hours, prenatal care…" /></Field>
                        <label className="flex items-center gap-2 text-sm text-slate-700 select-none">
                            <input type="checkbox" data-testid="clinic-accepting" checked={!!p.accepting_new_patients} onChange={(e) => setP((s) => ({ ...s, accepting_new_patients: e.target.checked }))} disabled={!canEdit} className="w-4 h-4" /> Accepting new patients
                        </label>
                    </section>

                    <section className="border border-slate-200 rounded-sm p-4 space-y-3 bg-white" data-testid="clinic-contact">
                        <h2 className="text-sm font-semibold text-slate-800">Contact</h2>
                        <div className="grid sm:grid-cols-2 gap-3">
                            <Field label="Phone" icon={Phone}><Input data-testid="clinic-phone" value={p.clinic_phone || ""} onChange={set("clinic_phone")} disabled={!canEdit} placeholder="(416) 652-7667" /></Field>
                            <Field label="Fax" icon={Printer}><Input data-testid="clinic-fax" value={p.clinic_fax || ""} onChange={set("clinic_fax")} disabled={!canEdit} /></Field>
                            <Field label="Email" icon={Mail}><Input data-testid="clinic-email" type="email" value={p.clinic_email || ""} onChange={set("clinic_email")} disabled={!canEdit} /></Field>
                            <Field label="Website" icon={Globe}><Input data-testid="clinic-website" value={p.website || ""} onChange={set("website")} disabled={!canEdit} placeholder="https://" /></Field>
                        </div>
                    </section>

                    <section className="border border-slate-200 rounded-sm p-4 space-y-3 bg-white" data-testid="clinic-address">
                        <h2 className="text-sm font-semibold text-slate-800">Address <span className="font-normal text-slate-400">· Smart Address (postal code first)</span></h2>
                        {p.clinic_address && <div className="text-xs text-slate-500">Current: <span className="font-medium text-slate-700" data-testid="clinic-address-current">{p.clinic_address}</span></div>}
                        <div className={canEdit ? "" : "pointer-events-none opacity-70"} data-testid="clinic-addr-wrap">
                            <AddressFields value={p.address_struct} onChange={(v) => setP((s) => ({ ...s, address_struct: { ...s.address_struct, ...v } }))} internal={canEdit} testid="clinic-addr" />
                        </div>
                    </section>

                    <section className="border border-slate-200 rounded-sm p-4 space-y-3 bg-white" data-testid="clinic-hours">
                        <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-1.5"><Clock className="w-4 h-4" /> Hours</h2>
                        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
                            {DAYS.map(([d, l]) => (
                                <div key={d} className="flex items-center gap-2">
                                    <span className="w-9 text-xs font-semibold text-slate-500">{l}</span>
                                    <Input data-testid={`clinic-hours-${d}`} value={p.hours?.[d] || ""} onChange={(e) => setHour(d, e.target.value)} disabled={!canEdit} placeholder="9:00–17:00 / Closed" className="h-8 text-sm" />
                                </div>
                            ))}
                        </div>
                        <Field label="Hours summary (shown in messages)"><Input data-testid="clinic-office-hours" value={p.office_hours || ""} onChange={set("office_hours")} disabled={!canEdit} placeholder="Mon–Fri 9–5" /></Field>
                    </section>

                    <section className="border border-slate-200 rounded-sm p-4 space-y-3 bg-white" data-testid="clinic-services">
                        <h2 className="text-sm font-semibold text-slate-800">Services & languages</h2>
                        <Field label="Services offered (comma or line separated)"><Textarea data-testid="clinic-services-text" rows={3} value={servicesText} onChange={(e) => setServicesText(e.target.value)} disabled={!canEdit} placeholder="Family medicine, Prescription renewals, Referrals, Bloodwork requisitions…" /></Field>
                        <Field label="Languages spoken" icon={Languages}><Input data-testid="clinic-languages" value={langsText} onChange={(e) => setLangsText(e.target.value)} disabled={!canEdit} placeholder="English, Spanish, Portuguese" /></Field>
                        <Field label="Emergency notice"><Textarea data-testid="clinic-emergency" rows={2} value={p.emergency_notice || ""} onChange={set("emergency_notice")} disabled={!canEdit} placeholder="If this is an emergency, call 911…" /></Field>
                    </section>
                </div>

                <aside className="lg:sticky lg:top-4 self-start border border-slate-200 rounded-sm p-4 bg-slate-50 space-y-2" data-testid="clinic-public-preview">
                    <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-1.5"><Eye className="w-4 h-4" /> Public preview</h2>
                    <div className="text-lg font-bold text-slate-900">{p.clinic_name || "—"}</div>
                    <div className="text-sm text-slate-600">{p.physician_name}</div>
                    {p.about && <p className="text-sm text-slate-700">{p.about}</p>}
                    <div className="text-sm text-slate-800 space-y-1 pt-1">
                        {p.clinic_phone && <div className="flex items-center gap-2"><Phone className="w-3.5 h-3.5 text-slate-400" /> <a href={`tel:${String(p.clinic_phone).replace(/\D/g, "")}`} className="underline" data-testid="clinic-preview-phone">{p.clinic_phone}</a></div>}
                        {p.clinic_fax && <div className="flex items-center gap-2"><Printer className="w-3.5 h-3.5 text-slate-400" /> {p.clinic_fax}</div>}
                        {p.clinic_email && <div className="flex items-center gap-2"><Mail className="w-3.5 h-3.5 text-slate-400" /> {p.clinic_email}</div>}
                        {p.website && <div className="flex items-center gap-2"><Globe className="w-3.5 h-3.5 text-slate-400" /> {p.website}</div>}
                        {p.clinic_address && <div className="flex items-start gap-2"><Building2 className="w-3.5 h-3.5 text-slate-400 mt-0.5" /> {p.clinic_address}</div>}
                    </div>
                    {(textToList(servicesText).length > 0) && <div className="flex flex-wrap gap-1 pt-1">{textToList(servicesText).map((s) => <span key={s} className="px-2 py-0.5 rounded-full bg-visita-green/10 text-visita-greenDark text-[11px] font-semibold">{s}</span>)}</div>}
                    {textToList(langsText).length > 0 && <div className="text-xs text-slate-500">Languages: {textToList(langsText).join(", ")}</div>}
                    <div className="text-xs text-slate-500">{p.accepting_new_patients ? "Accepting new patients" : "Not accepting new patients"}</div>
                    {publicUrl && <div className="text-[11px] text-slate-400 break-all pt-2 border-t border-slate-200">Public endpoint: <span data-testid="clinic-public-url">{publicUrl}</span></div>}
                </aside>
            </div>
        </div>
    );
}
