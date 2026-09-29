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
                </div>
            )}
        </div>
    );
}

const EMPTY = {
    surname: "", first_name: "", second_name: "", sex: "",
    sphere_id: "", area_id: "", specialty_id: "",
    credential_ids: [], language_ids: [], areas_of_practice_ids: [],
    practice_type_ids: [], primary_care_model_ids: [],
    registration_number: "", professorship: "",
    accepting_patients: null, waiting_list: null,
};

export default function ProfessionalEditor({ tax, initial, onClose, onSaved }) {
    const [form, setForm] = useState(() => ({ ...EMPTY, ...(initial || {}) }));
    const [aop, setAop] = useState([]);
    const [saving, setSaving] = useState(false);
    const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));

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
            toast.error("A College / Professional Registration Number is required for this Area."); return;
        }
        setSaving(true);
        try {
            const payload = { ...form };
            if (initial?.id) await api.patch(`/professionals/${initial.id}`, payload);
            else await api.post("/professionals", payload);
            toast.success(initial?.id ? "Professional updated." : "Professional created.");
            onSaved();
        } catch (e) { toast.error(formatErr(e)); }
        finally { setSaving(false); }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto" onClick={onClose} data-testid="prof-editor-modal">
            <div className="bg-white rounded-lg border border-slate-200 shadow-xl w-full max-w-4xl my-6" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
                    <h2 className="text-lg font-bold text-slate-900">{initial?.id ? "Edit Professional" : "Add Professional"}</h2>
                    <button onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="prof-editor-close"><X className="w-5 h-5" /></button>
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
                        <DepSelect label="Area" testid="prof-area" options={areas} value={form.area_id} disabled={!form.sphere_id}
                            getLabel={(o) => o.name}
                            onChange={(v) => setForm((f) => ({ ...f, area_id: v, specialty_id: "" }))} />
                        <DepSelect label="Specialty" testid="prof-specialty" options={specialties} value={form.specialty_id} disabled={!form.area_id}
                            getLabel={(o) => o.speciality_returned || o.speciality}
                            onChange={(v) => upd("specialty_id", v)} />
                    </div>

                    {requiresReg && (
                        <Field label="College / Professional Registration Number *">
                            <Input data-testid="prof-registration" value={form.registration_number || ""} onChange={(e) => upd("registration_number", e.target.value)} placeholder="Required for this Area" />
                        </Field>
                    )}

                    {aop.length > 0 && (
                        <MultiSelect label={`Areas of Practice (${aop.length} available)`} testid="prof-aop" options={aop} grouped
                            values={form.areas_of_practice_ids} onChange={(v) => upd("areas_of_practice_ids", v)}
                            getLabel={(o) => o.name} placeholder="Search areas of practice…" />
                    )}

                    <MultiSelect label="Credentials" testid="prof-credentials" options={tax.credentials}
                        values={form.credential_ids} onChange={(v) => upd("credential_ids", v)}
                        getLabel={(o) => o.credentials_returned || o.credentials} getSub={(o) => o.desc}
                        placeholder="Search credentials…" />

                    <MultiSelect label="Languages" testid="prof-languages" options={tax.languages}
                        values={form.language_ids} onChange={(v) => upd("language_ids", v)}
                        getLabel={(o) => o.language} placeholder="Search languages…" />

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
                </div>
                <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200 bg-slate-50">
                    <Button variant="outline" onClick={onClose} data-testid="prof-editor-cancel">Cancel</Button>
                    <Button className="bg-visita-greenDark hover:bg-emerald-800" onClick={save} disabled={saving} data-testid="prof-editor-save">
                        {saving ? "Saving…" : (initial?.id ? "Save changes" : "Create Professional")}
                    </Button>
                </div>
            </div>
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
