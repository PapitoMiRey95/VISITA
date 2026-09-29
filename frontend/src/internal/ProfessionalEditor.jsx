import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Search, X, ChevronDown, Star } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";

// Dependent searchable single-select (Sphere / Area / Specialty).
function DepSelect({ label, placeholder, options, value, onChange, disabled, testid, getLabel }) {
    const [open, setOpen] = useState(false);
    const [q, setQ] = useState("");
    const ref = useRef(null);
    useEffect(() => {
        const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        document.addEventListener("mousedown", h);
        return () => document.removeEventListener("mousedown", h);
    }, []);
    const sel = options.find((o) => o.id === value);
    const filtered = useMemo(() => {
        const t = q.trim().toLowerCase();
        const list = t ? options.filter((o) => getLabel(o).toLowerCase().includes(t)) : options;
        return [...list].sort((a, b) => (b.favourite ? 1 : 0) - (a.favourite ? 1 : 0));
    }, [q, options, getLabel]);
    return (
        <div className="relative" ref={ref}>
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</label>
            <button type="button" disabled={disabled} data-testid={testid}
                onClick={() => setOpen((v) => !v)}
                className="mt-1 w-full flex items-center justify-between rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-left disabled:bg-slate-50 disabled:text-slate-400">
                <span className={sel ? "text-slate-800" : "text-slate-400"}>{sel ? getLabel(sel) : (placeholder || "Select…")}</span>
                <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
            </button>
            {open && !disabled && (
                <div className="absolute z-50 mt-1 w-full rounded-md border border-slate-200 bg-white shadow-lg">
                    <div className="p-2 border-b border-slate-100">
                        <div className="relative">
                            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                            <Input autoFocus className="h-8 pl-7 text-sm" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} data-testid={`${testid}-search`} />
                        </div>
                    </div>
                    <div className="max-h-[32rem] overflow-y-auto py-1">
                        {value && (
                            <button type="button" onClick={() => { onChange(""); setOpen(false); setQ(""); }} className="w-full px-3 py-1.5 text-left text-xs text-slate-400 hover:bg-slate-50">Clear selection</button>
                        )}
                        {filtered.length === 0 && <div className="px-3 py-2 text-xs text-slate-400">No matches</div>}
                        {filtered.map((o) => (
                            <button key={o.id} type="button" data-testid={`${testid}-opt-${o.id}`}
                                onClick={() => { onChange(o.id); setOpen(false); setQ(""); }}
                                className={`w-full px-3 py-1.5 text-left text-sm hover:bg-emerald-50 flex items-center gap-2 ${o.id === value ? "bg-emerald-50 font-semibold" : ""}`}>
                                {o.favourite && <Star className="w-3 h-3 text-amber-400 fill-amber-400 shrink-0" />}
                                <span>{getLabel(o)}</span>
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

// Searchable, cumulative multi-select with removable chips.
// `getSub` optionally renders a secondary disambiguation line (e.g. credential Desc).
function MultiSelect({ label, placeholder, options, values, onChange, testid, getLabel, getSub, grouped }) {
    const [open, setOpen] = useState(false);
    const [q, setQ] = useState("");
    const ref = useRef(null);
    useEffect(() => {
        const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        document.addEventListener("mousedown", h);
        return () => document.removeEventListener("mousedown", h);
    }, []);
    const set = new Set(values || []);
    const byId = useMemo(() => Object.fromEntries(options.map((o) => [o.id, o])), [options]);
    const filtered = useMemo(() => {
        const t = q.trim().toLowerCase();
        const list = t ? options.filter((o) => getLabel(o).toLowerCase().includes(t) || (getSub && (getSub(o) || "").toLowerCase().includes(t))) : options;
        return [...list].sort((a, b) => (b.favourite ? 1 : 0) - (a.favourite ? 1 : 0) || (a.sort_order || 0) - (b.sort_order || 0));
    }, [q, options, getLabel, getSub]);
    const groups = useMemo(() => {
        if (!grouped) return null;
        const m = new Map();
        filtered.forEach((o) => { const k = o.category || "Other"; if (!m.has(k)) m.set(k, []); m.get(k).push(o); });
        return [...m.entries()];
    }, [filtered, grouped]);
    const toggle = (id) => {
        const next = new Set(set);
        next.has(id) ? next.delete(id) : next.add(id);
        onChange([...next]);
    };
    const renderOpt = (o) => (
        <button key={o.id} type="button" data-testid={`${testid}-opt-${o.id}`}
            onClick={() => toggle(o.id)}
            className={`w-full px-3 py-1.5 text-left text-sm hover:bg-emerald-50 flex items-start gap-2 ${set.has(o.id) ? "bg-emerald-50" : ""}`}>
            <span className={`mt-0.5 w-3.5 h-3.5 shrink-0 rounded-sm border ${set.has(o.id) ? "bg-emerald-600 border-emerald-600" : "border-slate-300"}`} />
            {o.favourite && <Star className="w-3 h-3 mt-0.5 text-amber-400 fill-amber-400 shrink-0" />}
            <span className="min-w-0">
                <span className="text-slate-800">{getLabel(o)}</span>
                {getSub && getSub(o) && <span className="block text-xs text-slate-400 truncate">{getSub(o)}</span>}
            </span>
        </button>
    );
    return (
        <div className="relative" ref={ref}>
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</label>
            <div className="mt-1 rounded-md border border-slate-300 bg-white px-2 py-1.5">
                <div className="flex flex-wrap gap-1.5">
                    {[...set].map((id) => byId[id] && (
                        <Badge key={id} className="bg-emerald-100 text-emerald-800 gap-1 pr-1" data-testid={`${testid}-chip-${id}`}>
                            {getLabel(byId[id])}
                            <button type="button" onClick={() => toggle(id)} className="hover:text-emerald-950"><X className="w-3 h-3" /></button>
                        </Badge>
                    ))}
                    <button type="button" data-testid={testid} onClick={() => setOpen((v) => !v)} className="text-xs text-slate-400 px-1 py-0.5 hover:text-slate-600">
                        {set.size ? "+ add" : (placeholder || "Search…")}
                    </button>
                </div>
            </div>
            {open && (
                <div className="absolute z-50 mt-1 w-full rounded-md border border-slate-200 bg-white shadow-lg">
                    <div className="p-2 border-b border-slate-100">
                        <div className="relative">
                            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                            <Input autoFocus className="h-8 pl-7 text-sm" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} data-testid={`${testid}-search`} />
                        </div>
                    </div>
                    <div className="max-h-[32rem] overflow-y-auto py-1">
                        {filtered.length === 0 && <div className="px-3 py-2 text-xs text-slate-400">No matches</div>}
                        {grouped
                            ? groups.map(([cat, items]) => (
                                <div key={cat}>
                                    <div className="px-3 pt-2 pb-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">{cat}</div>
                                    {items.map(renderOpt)}
                                </div>
                            ))
                            : filtered.map(renderOpt)}
                    </div>
                    <div className="flex items-center justify-between px-3 py-2 border-t border-slate-100 bg-slate-50">
                        <span className="text-xs text-slate-400">{set.size} selected</span>
                        <button type="button" onClick={() => setOpen(false)} data-testid={`${testid}-done`}
                            className="text-xs font-semibold text-visita-greenDark hover:underline px-2 py-1">Done</button>
                    </div>
                </div>
            )}
        </div>
    );
}

const EMPTY_ADDRESS = { street: "", unit: "", city: "", province: "Ontario", postal_code: "", country: "Canada" };

const EMPTY = {
    surname: "", first_name: "", second_name: "", sex: "",
    sphere_id: "", area_id: "", specialty_id: "",
    credential_ids: [], language_ids: [], areas_of_practice_ids: [],
    practice_type_ids: [], primary_care_model_ids: [],
    registration_number: "", professorship: "",
    accepting_patients: null, waiting_list: null,
    public_phone: "", public_fax: "", public_email: "",
    public_address: EMPTY_ADDRESS,
};

const normalizeInitial = (initial) => {
    const i = { ...EMPTY, ...(initial || {}) };
    i.public_address = { ...EMPTY_ADDRESS, ...(initial?.public_address || {}) };
    return i;
};

export default function ProfessionalEditor({ tax, initial, onClose, onSaved, selfMode }) {
    const [form, setForm] = useState(() => normalizeInitial(initial));
    const [aop, setAop] = useState([]);
    const [saving, setSaving] = useState(false);
    const [regError, setRegError] = useState(false);
    const [confirmLeave, setConfirmLeave] = useState(false);
    const baseline = useRef(JSON.stringify(normalizeInitial(initial)));
    const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));
    const updAddr = (k, v) => setForm((f) => ({ ...f, public_address: { ...f.public_address, [k]: v } }));

    const dirty = JSON.stringify(form) !== baseline.current;

    // Warn on browser/tab close or reload while there are unsaved changes.
    useEffect(() => {
        const h = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
        window.addEventListener("beforeunload", h);
        return () => window.removeEventListener("beforeunload", h);
    }, [dirty]);

    // Guarded close: never close silently when there are unsaved edits.
    const attemptClose = () => { if (dirty) setConfirmLeave(true); else onClose(); };

    const areas = useMemo(() => tax.areas.filter((a) => !form.sphere_id || a.sphere_id === form.sphere_id), [tax.areas, form.sphere_id]);
    const specialties = useMemo(() => tax.specialties.filter((s) => !form.area_id || s.area_id === form.area_id), [tax.specialties, form.area_id]);
    const selArea = tax.areas.find((a) => a.id === form.area_id);
    const requiresReg = !!(selArea && selArea.required);

    // Load Areas of Practice whenever the specialty changes (only some specialties have a list).
    useEffect(() => {
        if (!form.specialty_id) { setAop([]); return; }
        api.get("/professionals/areas-of-practice", { params: { specialty_id: form.specialty_id } })
            .then(({ data }) => setAop(data)).catch(() => setAop([]));
    }, [form.specialty_id]);

    const save = async () => {
        if (!form.surname.trim()) { toast.error("Surname is required."); return; }
        if (requiresReg && !(form.registration_number || "").trim()) {
            setRegError(true);
            toast.error("A College / Professional Registration Number is required for this Professional Area."); return;
        }
        setRegError(false);
        setSaving(true);
        try {
            const payload = { ...form };
            if (selfMode) { await api.put("/professionals/me", payload); toast.success("Your professional profile was saved."); }
            else if (initial?.id) { await api.patch(`/professionals/${initial.id}`, payload); toast.success("Professional updated."); }
            else { await api.post("/professionals", payload); toast.success("Professional created."); }
            onSaved();
        } catch (e) { toast.error(formatErr(e)); }
        finally { setSaving(false); }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto" onClick={attemptClose} data-testid="prof-editor-modal">
            <div className="bg-white rounded-lg border border-slate-200 shadow-xl w-full max-w-4xl my-6" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
                    <h2 className="text-lg font-bold text-slate-900">{selfMode ? "My Professional Profile" : (initial?.id ? "Edit Professional" : "Add Professional")}{dirty && <span className="ml-2 text-xs font-normal text-amber-600" data-testid="prof-editor-dirty">• Unsaved changes</span>}</h2>
                    <button onClick={attemptClose} className="text-slate-400 hover:text-slate-700" data-testid="prof-editor-close"><X className="w-5 h-5" /></button>
                </div>
                <div className="p-5 space-y-4">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <Field label="Surname *"><Input data-testid="prof-surname" value={form.surname} onChange={(e) => upd("surname", e.target.value)} /></Field>
                        <Field label="First name"><Input data-testid="prof-first-name" value={form.first_name || ""} onChange={(e) => upd("first_name", e.target.value)} /></Field>
                        <Field label="Second name"><Input data-testid="prof-second-name" value={form.second_name || ""} onChange={(e) => upd("second_name", e.target.value)} /></Field>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <DepSelect label="Sphere" testid="prof-sphere" options={tax.spheres} value={form.sphere_id}
                            getLabel={(o) => o.name}
                            onChange={(v) => setForm((f) => ({ ...f, sphere_id: v, area_id: "", specialty_id: "" }))} />
                        <DepSelect label="Professional Area" testid="prof-area" options={areas} value={form.area_id} disabled={!form.sphere_id}
                            getLabel={(o) => o.name}
                            onChange={(v) => setForm((f) => ({ ...f, area_id: v, specialty_id: "" }))} />
                        <DepSelect label="Specialty" testid="prof-specialty" options={specialties} value={form.specialty_id} disabled={!form.area_id}
                            getLabel={(o) => o.name}
                            onChange={(v) => upd("specialty_id", v)} />
                    </div>

                    {requiresReg && (
                        <Field label="College / Professional Registration Number *">
                            <Input data-testid="prof-registration" className={regError && !(form.registration_number || "").trim() ? "border-red-500" : ""} value={form.registration_number || ""} onChange={(e) => upd("registration_number", e.target.value)} placeholder="Required for this Professional Area" />
                            {regError && !(form.registration_number || "").trim() && <p className="text-xs text-red-600 mt-1" data-testid="prof-registration-error">Registration number is required for this Professional Area.</p>}
                        </Field>
                    )}

                    {aop.length > 0 && (
                        <MultiSelect label={`Areas of Practice (${aop.length} available)`} testid="prof-aop" options={aop} grouped
                            values={form.areas_of_practice_ids} onChange={(v) => upd("areas_of_practice_ids", v)}
                            getLabel={(o) => o.name} placeholder="Search areas of practice…" />
                    )}

                    <MultiSelect label="Credentials" testid="prof-credentials" options={tax.credentials}
                        values={form.credential_ids} onChange={(v) => upd("credential_ids", v)}
                        getLabel={(o) => o.name} getSub={(o) => o.description}
                        placeholder="Search credentials…" />

                    <MultiSelect label="Languages" testid="prof-languages" options={tax.languages}
                        values={form.language_ids} onChange={(v) => upd("language_ids", v)}
                        getLabel={(o) => o.name} placeholder="Search languages…" />

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <MultiSelect label="Practice Type" testid="prof-practice-type" options={tax.practice_types}
                            values={form.practice_type_ids} onChange={(v) => upd("practice_type_ids", v)}
                            getLabel={(o) => o.name} placeholder="Search practice types…" />
                        <MultiSelect label="Ontario Primary Care Model" testid="prof-care-model" options={tax.primary_care_models}
                            values={form.primary_care_model_ids} onChange={(v) => upd("primary_care_model_ids", v)}
                            getLabel={(o) => o.name} placeholder="Search models…" />
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <Field label="Sex">
                            <select data-testid="prof-sex" className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white" value={form.sex || ""} onChange={(e) => upd("sex", e.target.value)}>
                                <option value="">—</option><option>Female</option><option>Male</option><option>Other</option>
                            </select>
                        </Field>
                        <Field label="Professorship"><Input data-testid="prof-professorship" value={form.professorship || ""} onChange={(e) => upd("professorship", e.target.value)} /></Field>
                        <Field label="Accepting patients">
                            <select data-testid="prof-accepting" className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
                                value={form.accepting_patients == null ? "" : form.accepting_patients ? "yes" : "no"}
                                onChange={(e) => upd("accepting_patients", e.target.value === "" ? null : e.target.value === "yes")}>
                                <option value="">—</option><option value="yes">Yes</option><option value="no">No</option>
                            </select>
                        </Field>
                    </div>

                    <div className="rounded-md border border-slate-200 bg-slate-50/60 p-3 space-y-3" data-testid="prof-public-contact">
                        <div>
                            <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">Public professional contact</div>
                            <p className="text-xs text-slate-500">Optional. Shown to VIen internal users in the directory. Separate from your login/account details — nothing is copied automatically.</p>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <Field label="Public phone"><Input data-testid="prof-public-phone" value={form.public_phone || ""} onChange={(e) => upd("public_phone", e.target.value)} placeholder="416-555-0100" /></Field>
                            <Field label="Public fax"><Input data-testid="prof-public-fax" value={form.public_fax || ""} onChange={(e) => upd("public_fax", e.target.value)} placeholder="416-555-0101" /></Field>
                            <Field label="Public email"><Input data-testid="prof-public-email" type="email" value={form.public_email || ""} onChange={(e) => upd("public_email", e.target.value)} placeholder="clinic@example.com" /></Field>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-6 gap-3">
                            <div className="sm:col-span-4"><Field label="Clinic / practice street address"><Input data-testid="prof-addr-street" value={form.public_address.street || ""} onChange={(e) => updAddr("street", e.target.value)} /></Field></div>
                            <div className="sm:col-span-2"><Field label="Unit / Suite"><Input data-testid="prof-addr-unit" value={form.public_address.unit || ""} onChange={(e) => updAddr("unit", e.target.value)} /></Field></div>
                            <div className="sm:col-span-2"><Field label="City"><Input data-testid="prof-addr-city" value={form.public_address.city || ""} onChange={(e) => updAddr("city", e.target.value)} /></Field></div>
                            <div className="sm:col-span-2"><Field label="Province"><Input data-testid="prof-addr-province" value={form.public_address.province || ""} onChange={(e) => updAddr("province", e.target.value)} /></Field></div>
                            <Field label="Postal code"><Input data-testid="prof-addr-postal" value={form.public_address.postal_code || ""} onChange={(e) => updAddr("postal_code", e.target.value.toUpperCase())} placeholder="A1A 1A1" /></Field>
                            <Field label="Country"><Input data-testid="prof-addr-country" value={form.public_address.country || ""} onChange={(e) => updAddr("country", e.target.value)} /></Field>
                        </div>
                    </div>
                </div>
                <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200 bg-slate-50">
                    <Button variant="outline" onClick={attemptClose} data-testid="prof-editor-cancel">Cancel</Button>
                    <Button className="bg-visita-greenDark hover:bg-emerald-800" onClick={save} disabled={saving} data-testid="prof-editor-save">
                        {saving ? "Saving…" : (selfMode ? "Save my profile" : (initial?.id ? "Save changes" : "Create Professional"))}
                    </Button>
                </div>
            </div>

            {confirmLeave && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" onClick={(e) => { e.stopPropagation(); }} data-testid="prof-editor-leave-guard">
                    <div className="bg-white rounded-lg shadow-xl w-full max-w-sm p-5" onClick={(e) => e.stopPropagation()}>
                        <h3 className="text-base font-bold text-slate-900">Leave without saving?</h3>
                        <p className="mt-1 text-sm text-slate-600">You have unsaved changes to this professional. Save them before leaving, or discard them.</p>
                        <div className="mt-4 flex flex-col gap-2">
                            <Button className="bg-visita-greenDark hover:bg-emerald-800" disabled={saving}
                                onClick={() => { setConfirmLeave(false); save(); }} data-testid="prof-leave-save">
                                {saving ? "Saving…" : "Save changes"}
                            </Button>
                            <Button variant="outline" onClick={() => setConfirmLeave(false)} data-testid="prof-leave-keep">Keep editing</Button>
                            <button className="text-xs text-rose-600 hover:underline mt-1" onClick={() => { setConfirmLeave(false); onClose(); }} data-testid="prof-leave-discard">Discard changes & close</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

function Field({ label, children }) {
    return (
        <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</label>
            <div className="mt-1">{children}</div>
        </div>
    );
}
