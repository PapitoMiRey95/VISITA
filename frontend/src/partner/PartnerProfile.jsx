import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Building2, Loader2, Plus, X, CheckCircle2, ShieldAlert, Info } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";

const STATUS_BADGE = {
    UNVERIFIED: "bg-slate-100 text-slate-600",
    VERIFIED: "bg-emerald-100 text-emerald-700",
    FLAGGED: "bg-amber-100 text-amber-800",
    SUSPENDED: "bg-red-100 text-red-700",
};

export default function PartnerProfile() {
    const [org, setOrg] = useState(null);
    const [form, setForm] = useState(null);
    const [busy, setBusy] = useState(false);

    const load = async () => {
        try {
            const { data } = await api.get("/partner/me");
            setOrg(data.organization);
            setForm({
                phone: data.organization.phone || "", address: data.organization.address || "",
                city: data.organization.city || "", province: data.organization.province || "",
                postal_code: data.organization.postal_code || "", website: data.organization.website || "",
                fax: data.organization.fax || "", description: data.organization.description || "",
                specialties: data.organization.specialties || "", services: data.organization.services || "",
                languages: data.organization.languages || "", business_hours: data.organization.business_hours || "",
                referral_instructions: data.organization.referral_instructions || "",
                referral_addressed_to: data.organization.referral_addressed_to || "",
                referral_destination: data.organization.referral_destination || "",
                referral_provider_id: data.organization.referral_provider_id || "",
                photos: data.organization.photos || [],
                locations: data.organization.locations || [],
                providers: data.organization.providers || [],
            });
        } catch (e) { toast.error(formatErr(e)); }
    };
    useEffect(() => { load(); }, []);

    const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
    const addProvider = () => setForm({ ...form, providers: [...form.providers, { name: "", specialty: "", location_ids: [] }] });
    const setProvider = (i, k, v) => {
        const p = [...form.providers]; p[i] = { ...p[i], [k]: v }; setForm({ ...form, providers: p });
    };
    const toggleProviderLoc = (i, locId) => {
        const p = [...form.providers];
        const cur = p[i].location_ids || [];
        p[i] = { ...p[i], location_ids: cur.includes(locId) ? cur.filter((x) => x !== locId) : [...cur, locId] };
        setForm({ ...form, providers: p });
    };
    const removeProvider = (i) => setForm({ ...form, providers: form.providers.filter((_, x) => x !== i) });

    const newLocId = () => "loc_" + Math.random().toString(36).slice(2, 10);
    const addLocation = () => setForm({ ...form, locations: [...form.locations, { id: newLocId(), label: "", address: "", city: "", province: "", postal_code: "", phone: "", fax: "", business_hours: "" }] });
    const setLoc = (i, k, v) => { const l = [...form.locations]; l[i] = { ...l[i], [k]: v }; setForm({ ...form, locations: l }); };
    const removeLocation = (i) => setForm({ ...form, locations: form.locations.filter((_, x) => x !== i) });

    const addPhoto = () => setForm({ ...form, photos: [...form.photos, ""] });
    const setPhoto = (i, v) => { const p = [...form.photos]; p[i] = v; setForm({ ...form, photos: p }); };
    const removePhoto = (i) => setForm({ ...form, photos: form.photos.filter((_, x) => x !== i) });

    const save = async () => {
        setBusy(true);
        try {
            const payload = { ...form, providers: form.providers.filter((p) => (p.name || "").trim()), photos: form.photos.filter((u) => (u || "").trim()), locations: form.locations.filter((l) => (l.label || l.address || "").trim()) };
            const { data } = await api.put("/partner/profile", payload);
            setOrg(data.organization);
            toast.success("Organization profile saved.");
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    if (!org || !form) return <div className="text-slate-400 text-sm p-6">Loading…</div>;

    return (
        <div className="space-y-5 animate-fade-in" data-testid="partner-profile">
            {/* Header */}
            <div className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                        <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-cyan-500/10 border border-cyan-500/30 shrink-0">
                            <Building2 className="w-5 h-5 text-cyan-600" />
                        </span>
                        <div className="min-w-0">
                            <h1 className="text-lg font-bold text-slate-900 truncate" data-testid="partner-org-name">{org.organization_name}</h1>
                            <p className="text-sm text-slate-500">{org.organization_type}</p>
                        </div>
                    </div>
                    <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${STATUS_BADGE[org.verification_status]}`} data-testid="partner-status">
                        {org.verification_status}
                    </span>
                </div>
                <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
                    <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                        <div className="h-full bg-cyan-500" style={{ width: `${org.profile_completeness}%` }} />
                    </div>
                    <span data-testid="partner-completeness">{org.profile_completeness}% complete</span>
                </div>
                {org.verification_status === "UNVERIFIED" && (
                    <p className="mt-3 flex items-start gap-2 text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded-lg p-2.5" data-testid="partner-unverified-note">
                        <Info className="w-4 h-4 mt-0.5 shrink-0 text-slate-400" />
                        Your account is active. "Unverified" simply means the clinic has not yet reviewed your partner-submitted information — it does not limit your access.
                    </p>
                )}
                {org.verification_status === "VERIFIED" && (
                    <p className="mt-3 flex items-center gap-2 text-xs text-emerald-700"><CheckCircle2 className="w-4 h-4" /> Verified by the clinic.</p>
                )}
                {org.verification_status === "FLAGGED" && (
                    <p className="mt-3 flex items-center gap-2 text-xs text-amber-700"><ShieldAlert className="w-4 h-4" /> This account has been flagged for review by the clinic.</p>
                )}
            </div>

            {/* Complete your profile */}
            <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4" data-testid="partner-profile-form">
                <div>
                    <h2 className="font-bold text-slate-800">Complete your Organization Profile</h2>
                    <p className="text-sm text-slate-500">Add the details you'd like the clinic and patients to see.</p>
                </div>

                <F label="About / Description"><Textarea data-testid="p-description" value={form.description} onChange={set("description")} /></F>

                <div className="grid grid-cols-2 gap-3">
                    <F label="Phone"><Input data-testid="p-phone" value={form.phone} onChange={set("phone")} /></F>
                    <F label="Fax"><Input data-testid="p-fax" value={form.fax} onChange={set("fax")} /></F>
                </div>
                <div className="grid grid-cols-2 gap-3">
                    <F label="Website"><Input data-testid="p-website" value={form.website} onChange={set("website")} placeholder="https://" /></F>
                    <F label="Languages"><Input data-testid="p-languages" value={form.languages} onChange={set("languages")} placeholder="English, French…" /></F>
                </div>

                <F label="Street Address"><Input data-testid="p-address" value={form.address} onChange={set("address")} /></F>
                <div className="grid grid-cols-3 gap-3">
                    <F label="City"><Input data-testid="p-city" value={form.city} onChange={set("city")} /></F>
                    <F label="Province"><Input data-testid="p-province" value={form.province} onChange={set("province")} /></F>
                    <F label="Postal Code"><Input data-testid="p-postal" value={form.postal_code} onChange={set("postal_code")} /></F>
                </div>

                <F label="Specialties"><Input data-testid="p-specialties" value={form.specialties} onChange={set("specialties")} placeholder="Cardiology, Internal Medicine…" /></F>
                <F label="Services"><Textarea data-testid="p-services" value={form.services} onChange={set("services")} /></F>
                <F label="Business Hours"><Textarea data-testid="p-hours" value={form.business_hours} onChange={set("business_hours")} placeholder="Mon–Fri 9:00–17:00…" /></F>

                <F label="Referral Instructions"><Textarea data-testid="p-referral-instructions" value={form.referral_instructions} onChange={set("referral_instructions")} /></F>
                <F label="Referral destination preference">
                    <Select value={form.referral_destination} onValueChange={(v) => setForm({ ...form, referral_destination: v })}>
                        <SelectTrigger data-testid="p-referral-dest-trigger"><SelectValue placeholder="Select…" /></SelectTrigger>
                        <SelectContent>
                            <SelectItem value="organization">Organization / General Intake</SelectItem>
                            <SelectItem value="specific_provider">A specific provider</SelectItem>
                        </SelectContent>
                    </Select>
                </F>
                {form.referral_destination === "specific_provider" && (
                    <F label="Referral provider">
                        <Select value={form.referral_provider_id} onValueChange={(v) => setForm({ ...form, referral_provider_id: v })}>
                            <SelectTrigger data-testid="p-referral-provider-trigger"><SelectValue placeholder="Select a provider…" /></SelectTrigger>
                            <SelectContent>
                                {form.providers.filter((p) => p.id && (p.name || "").trim()).map((p) => (
                                    <SelectItem key={p.id} value={p.id}>{p.name}{p.specialty ? ` · ${p.specialty}` : ""}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        {form.providers.filter((p) => p.id).length === 0 && (
                            <p className="text-xs text-slate-400 mt-1">Add and save providers below first, then pick one here.</p>
                        )}
                    </F>
                )}

                {/* Locations */}
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <Label className="text-sm font-semibold text-slate-700">Locations</Label>
                        <button type="button" onClick={addLocation} data-testid="p-add-location"
                            className="inline-flex items-center gap-1 text-sm font-semibold text-cyan-700 hover:text-cyan-600">
                            <Plus className="w-4 h-4" /> Add location
                        </button>
                    </div>
                    <div className="space-y-3">
                        {form.locations.length === 0 && <p className="text-xs text-slate-400">No locations added yet.</p>}
                        {form.locations.map((l, i) => (
                            <div key={l.id || i} className="rounded-lg border border-slate-200 p-3 space-y-2" data-testid={`p-location-${i}`}>
                                <div className="flex items-center justify-between">
                                    <Input placeholder="Location label (e.g. Main Office)" value={l.label} onChange={(e) => setLoc(i, "label", e.target.value)} data-testid={`p-location-label-${i}`} />
                                    <button type="button" onClick={() => removeLocation(i)} className="ml-2 text-slate-400 hover:text-red-600 shrink-0"><X className="w-4 h-4" /></button>
                                </div>
                                <Input placeholder="Street address" value={l.address} onChange={(e) => setLoc(i, "address", e.target.value)} data-testid={`p-location-address-${i}`} />
                                <div className="grid grid-cols-3 gap-2">
                                    <Input placeholder="City" value={l.city} onChange={(e) => setLoc(i, "city", e.target.value)} />
                                    <Input placeholder="Province" value={l.province} onChange={(e) => setLoc(i, "province", e.target.value)} />
                                    <Input placeholder="Postal" value={l.postal_code} onChange={(e) => setLoc(i, "postal_code", e.target.value)} />
                                </div>
                                <div className="grid grid-cols-2 gap-2">
                                    <Input placeholder="Phone" value={l.phone} onChange={(e) => setLoc(i, "phone", e.target.value)} />
                                    <Input placeholder="Fax" value={l.fax} onChange={(e) => setLoc(i, "fax", e.target.value)} />
                                </div>
                                <Textarea placeholder="Business hours for this location" value={l.business_hours} onChange={(e) => setLoc(i, "business_hours", e.target.value)} data-testid={`p-location-hours-${i}`} />
                            </div>
                        ))}
                    </div>
                </div>

                {/* Photos */}
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <Label className="text-sm font-semibold text-slate-700">Photos</Label>
                        <button type="button" onClick={addPhoto} data-testid="p-add-photo"
                            className="inline-flex items-center gap-1 text-sm font-semibold text-cyan-700 hover:text-cyan-600">
                            <Plus className="w-4 h-4" /> Add photo URL
                        </button>
                    </div>
                    <div className="space-y-2">
                        {form.photos.length === 0 && <p className="text-xs text-slate-400">Add image links (logo, clinic photos).</p>}
                        {form.photos.map((u, i) => (
                            <div key={i} className="flex gap-2 items-center" data-testid={`p-photo-${i}`}>
                                {u ? <img src={u} alt="" className="w-10 h-10 rounded object-cover border border-slate-200 shrink-0" onError={(e) => { e.target.style.visibility = "hidden"; }} /> : <span className="w-10 h-10 rounded bg-slate-100 shrink-0" />}
                                <Input placeholder="https://…" value={u} onChange={(e) => setPhoto(i, e.target.value)} data-testid={`p-photo-url-${i}`} />
                                <button type="button" onClick={() => removePhoto(i)} className="text-slate-400 hover:text-red-600 shrink-0"><X className="w-4 h-4" /></button>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Providers */}
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <Label className="text-sm font-semibold text-slate-700">Providers / Doctors</Label>
                        <button type="button" onClick={addProvider} data-testid="p-add-provider"
                            className="inline-flex items-center gap-1 text-sm font-semibold text-cyan-700 hover:text-cyan-600">
                            <Plus className="w-4 h-4" /> Add
                        </button>
                    </div>
                    <div className="space-y-2">
                        {form.providers.length === 0 && <p className="text-xs text-slate-400">No providers added yet.</p>}
                        {form.providers.map((p, i) => (
                            <div key={p.id || i} className="rounded-lg border border-slate-200 p-3 space-y-2" data-testid={`p-provider-${i}`}>
                                <div className="flex gap-2 items-center">
                                    <Input placeholder="Name" value={p.name} onChange={(e) => setProvider(i, "name", e.target.value)} data-testid={`p-provider-name-${i}`} />
                                    <Input placeholder="Specialties (comma-separated)" value={p.specialty || p.specialties || ""} onChange={(e) => setProvider(i, "specialty", e.target.value)} data-testid={`p-provider-spec-${i}`} />
                                    <button type="button" onClick={() => removeProvider(i)} className="text-slate-400 hover:text-red-600 shrink-0"><X className="w-4 h-4" /></button>
                                </div>
                                {form.locations.filter((l) => l.id).length > 0 && (
                                    <div>
                                        <div className="text-xs text-slate-500 mb-1">Works at location(s):</div>
                                        <div className="flex flex-wrap gap-1.5">
                                            {form.locations.filter((l) => l.id).map((l) => {
                                                const on = (p.location_ids || []).includes(l.id);
                                                return (
                                                    <button type="button" key={l.id} data-testid={`p-provider-${i}-loc-${l.id}`}
                                                        onClick={() => toggleProviderLoc(i, l.id)}
                                                        className={`px-2 py-1 rounded-full text-xs font-medium border transition-colors ${on ? "bg-cyan-500 text-white border-cyan-500" : "bg-white text-slate-600 border-slate-200 hover:border-cyan-400"}`}>
                                                        {l.label || l.address || "Location"}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>

                <Button onClick={save} disabled={busy} data-testid="partner-profile-save"
                    className="w-full h-11 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-bold">
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Save Profile"}
                </Button>
            </div>
        </div>
    );
}

function F({ label, children }) {
    return (
        <div>
            <Label className="text-sm font-semibold text-slate-700">{label}</Label>
            <div className="mt-1">{children}</div>
        </div>
    );
}
