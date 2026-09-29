import { useEffect, useState, useCallback, useMemo } from "react";
import { toast } from "sonner";
import { Contact, Search, ShieldCheck, UserRound, X, Pencil, Users } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import ProfessionalEditor from "./ProfessionalEditor";
import AuthorizedEditors from "./AuthorizedEditors";

// Shared VIen Professionals module (Dr. Aguayo's Professional Construct).
// ONE Professional Profile model reused for both Directory Contacts and VIen Users;
// the only difference is VIen access. Phase 2: taxonomy imported + smart editor.
export default function Professionals() {
    const { user } = useAuth();
    const canSelfEdit = user?.role === "physician" || user?.role === "admin"; // edit OWN profile
    const [q, setQ] = useState("");
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [tax, setTax] = useState(null);
    const [selected, setSelected] = useState(null);
    const [editing, setEditing] = useState(null); // {} for new, profile for edit
    const [selfProfile, setSelfProfile] = useState(undefined); // undefined=loading, null=none
    const [selfEditing, setSelfEditing] = useState(false);
    const [managingEditors, setManagingEditors] = useState(null);

    const loadSelf = useCallback(() => {
        if (!canSelfEdit) return;
        api.get("/professionals/me").then(({ data }) => setSelfProfile(data.profile)).catch(() => setSelfProfile(null));
    }, [canSelfEdit]);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/professionals", { params: q.trim() ? { q: q.trim() } : {} });
            setRows(data);
        } catch (e) {
            if (e?.response?.status === 401) toast.error("Your session has expired. Please sign in again.");
            else toast.error(formatErr(e));
        } finally { setLoading(false); }
    }, [q]);

    useEffect(() => { api.get("/professionals/taxonomy").then(({ data }) => setTax(data)).catch(() => {}); }, []);
    useEffect(() => { loadSelf(); }, [loadSelf]);
    useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);

    const openProfile = async (id) => {
        try { const { data } = await api.get(`/professionals/${id}`); setSelected(data); }
        catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="space-y-4" data-testid="professionals-page">
            <div className="flex items-center gap-2">
                <Contact className="w-5 h-5 text-visita-greenDark" />
                <h1 className="text-xl font-bold text-slate-900">Professionals</h1>
                <span className="text-sm text-slate-400" data-testid="prof-count">({rows.length})</span>
                <span className="ml-auto text-xs text-slate-400">Shared VIen Professional Directory</span>
            </div>

            {canSelfEdit && tax && (
                <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50/60 px-4 py-3" data-testid="prof-my-profile-card">
                    <div className="flex items-center gap-2 min-w-0">
                        <ShieldCheck className="w-4 h-4 text-visita-greenDark shrink-0" />
                        <div className="min-w-0">
                            <div className="text-sm font-semibold text-slate-800">My Professional Profile</div>
                            <div className="text-xs text-slate-500 truncate">
                                {selfProfile === undefined ? "Loading…"
                                    : selfProfile ? `${selfProfile.display_name || selfProfile.surname}${selfProfile.registration_number ? " · " + selfProfile.registration_number : ""}`
                                    : "You haven't set up your professional info yet."}
                            </div>
                        </div>
                    </div>
                    <Button variant="outline" className="border-visita-greenDark text-visita-greenDark hover:bg-emerald-100 shrink-0"
                        onClick={() => setSelfEditing(true)} disabled={!tax.imported} data-testid="prof-edit-my-profile">
                        <Pencil className="w-3.5 h-3.5 mr-1" /> {selfProfile ? "Update my info" : "Set up my profile"}
                    </Button>
                </div>
            )}

            <div className="flex flex-wrap gap-2 items-center">
                <div className="relative flex-1 min-w-[240px]">
                    <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <Input data-testid="prof-search" className="pl-8" placeholder="Search by name or registration #…" value={q} onChange={(e) => setQ(e.target.value)} />
                </div>
            </div>

            <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
                <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                        <tr>
                            <th className="text-left px-3 py-2">Professional</th>
                            <th className="text-left px-3 py-2">Registration #</th>
                            <th className="text-left px-3 py-2">VIen Access</th>
                            <th className="text-right px-3 py-2"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading && <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-400">Loading…</td></tr>}
                        {!loading && rows.length === 0 && <tr><td colSpan={4} className="px-3 py-8 text-center text-slate-400">No professionals found. Use “Add Professional” to create one.</td></tr>}
                        {!loading && rows.map((p) => (
                            <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer" data-testid="prof-row" onClick={() => openProfile(p.id)}>
                                <td className="px-3 py-2 font-semibold text-slate-800">{p.display_name || p.surname}{p.professorship ? <span className="ml-1 text-xs font-normal text-slate-400">· {p.professorship}</span> : null}</td>
                                <td className="px-3 py-2 text-slate-600">{p.registration_number || "—"}</td>
                                <td className="px-3 py-2">
                                    {p.has_vien_access
                                        ? <Badge className="bg-emerald-100 text-emerald-700 gap-1"><ShieldCheck className="w-3 h-3" /> VIen User</Badge>
                                        : <Badge variant="secondary" className="gap-1 text-slate-600"><UserRound className="w-3 h-3" /> Directory Contact</Badge>}
                                </td>
                                <td className="px-3 py-2 text-right"><button className="text-xs text-slate-500 hover:underline" data-testid="prof-view">View</button></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {selected && tax && (
                <ProfileView p={selected} tax={tax}
                    onClose={() => setSelected(null)}
                    onEdit={() => { setEditing(selected); setSelected(null); }}
                    onManageEditors={() => { setManagingEditors(selected); setSelected(null); }} />
            )}

            {editing && tax && (
                <ProfessionalEditor tax={tax} initial={editing.id ? editing : null}
                    onClose={() => setEditing(null)}
                    onSaved={() => { setEditing(null); load(); }} />
            )}

            {selfEditing && tax && (
                <ProfessionalEditor tax={tax} selfMode initial={selfProfile || null}
                    onClose={() => setSelfEditing(false)}
                    onSaved={() => { setSelfEditing(false); loadSelf(); load(); }} />
            )}

            {managingEditors && (
                <AuthorizedEditors profile={managingEditors} onClose={() => setManagingEditors(null)} />
            )}
        </div>
    );
}

function ProfileView({ p, tax, onClose, onEdit, onManageEditors }) {
    const [aopMap, setAopMap] = useState({});
    useEffect(() => {
        if (!p.specialty_id || !(p.areas_of_practice_ids || []).length) { setAopMap({}); return; }
        api.get("/professionals/areas-of-practice", { params: { specialty_id: p.specialty_id } })
            .then(({ data }) => setAopMap(Object.fromEntries(data.map((x) => [x.id, x.name]))))
            .catch(() => setAopMap({}));
    }, [p.specialty_id, p.areas_of_practice_ids]);
    const maps = useMemo(() => ({
        spheres: Object.fromEntries(tax.spheres.map((x) => [x.id, x.name])),
        areas: Object.fromEntries(tax.areas.map((x) => [x.id, x.name])),
        specialties: Object.fromEntries(tax.specialties.map((x) => [x.id, x.speciality_returned || x.speciality])),
        credentials: Object.fromEntries(tax.credentials.map((x) => [x.id, x.credentials_returned || x.credentials])),
        languages: Object.fromEntries(tax.languages.map((x) => [x.id, x.language])),
        practice_types: Object.fromEntries(tax.practice_types.map((x) => [x.id, x.name])),
        models: Object.fromEntries(tax.primary_care_models.map((x) => [x.id, x.name])),
    }), [tax]);
    const chips = (ids, m, testid) => (ids && ids.length)
        ? <div className="flex flex-wrap gap-1" data-testid={testid}>{ids.map((id) => <Badge key={id} variant="secondary" className="text-slate-700">{m[id] || id}</Badge>)}</div>
        : <span className="text-slate-400">—</span>;

    return (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto" onClick={onClose} data-testid="prof-profile-modal">
            <div className="bg-white rounded-lg border border-slate-200 shadow-xl w-full max-w-lg my-6" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-start justify-between px-5 py-3 border-b border-slate-200">
                    <div>
                        <h2 className="text-lg font-bold text-slate-900" data-testid="prof-profile-name">{p.display_name || p.surname}</h2>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                            {p.has_vien_access
                                ? <Badge className="bg-emerald-100 text-emerald-700 gap-1"><ShieldCheck className="w-3 h-3" /> VIen User</Badge>
                                : <Badge variant="secondary" className="gap-1 text-slate-600"><UserRound className="w-3 h-3" /> Directory Contact</Badge>}
                            {p.management_label && <Badge variant="outline" className="text-slate-600" data-testid="prof-management-badge">{p.management_label}</Badge>}
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {p.can_manage_editors && <Button size="sm" variant="outline" onClick={onManageEditors} data-testid="prof-manage-editors"><Users className="w-3.5 h-3.5 mr-1" /> Editors</Button>}
                        {p.can_edit && <Button size="sm" variant="outline" onClick={onEdit} data-testid="prof-edit"><Pencil className="w-3.5 h-3.5 mr-1" /> Edit</Button>}
                        <button onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="prof-profile-close"><X className="w-5 h-5" /></button>
                    </div>
                </div>
                <dl className="p-5 space-y-2 text-sm">
                    <Row label="Classification">{[maps.spheres[p.sphere_id], maps.areas[p.area_id], maps.specialties[p.specialty_id]].filter(Boolean).join(" → ") || <span className="text-slate-400">—</span>}</Row>
                    <Row label="Registration #">{p.registration_number}</Row>
                    <Row label="Credentials">{chips(p.credential_ids, maps.credentials, "prof-view-credentials")}</Row>
                    <Row label="Languages">{chips(p.language_ids, maps.languages, "prof-view-languages")}</Row>
                    <Row label="Areas of Practice">{
                        (p.areas_of_practice_ids || []).length && Object.keys(aopMap).length === 0
                            ? <span className="text-slate-400">Resolving…</span>
                            : chips(p.areas_of_practice_ids, aopMap, "prof-view-aop")
                    }</Row>
                    <Row label="Practice Type">{chips(p.practice_type_ids, maps.practice_types, "prof-view-practice")}</Row>
                    <Row label="Ontario Model">{chips(p.primary_care_model_ids, maps.models, "prof-view-model")}</Row>
                    <Row label="Sex">{p.sex}</Row>
                    <Row label="Professorship">{p.professorship}</Row>
                    <Row label="Accepting patients">{p.accepting_patients == null ? "—" : p.accepting_patients ? "Yes" : "No"}</Row>
                </dl>
            </div>
        </div>
    );
}

function Row({ label, children }) {
    return (
        <div className="flex justify-between gap-4 border-b border-slate-100 pb-1.5">
            <dt className="text-slate-400 text-xs uppercase tracking-wide shrink-0">{label}</dt>
            <dd className="text-slate-800 text-right">{children || "—"}</dd>
        </div>
    );
}
