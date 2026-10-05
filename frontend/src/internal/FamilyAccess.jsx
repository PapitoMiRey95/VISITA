import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Users, Plus, X, Shield, Trash2, Search, Copy } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";

const PERM_LABEL = {
    APPOINTMENTS: "Appointments", RX_REQUESTS: "Rx requests",
    DOCUMENTS: "Documents", REQUEST_STATUS: "Request status",
    HEALTH_CARD_UPDATE: "Health Card update",
};

export default function FamilyAccess({ patient }) {
    const pid = patient?.patient_id;
    const [grants, setGrants] = useState([]);
    const [opts, setOpts] = useState({ relationships: [], consent_types: [], permissions: [] });
    const [adding, setAdding] = useState(false);
    const [tempPw, setTempPw] = useState(null);

    const load = useCallback(() => {
        if (!pid) return;
        api.get(`/internal/patients/${pid}/delegates`).then(({ data }) => setGrants(data)).catch(() => setGrants([]));
    }, [pid]);

    useEffect(() => { load(); }, [load]);
    useEffect(() => { api.get("/internal/delegate-options").then(({ data }) => setOpts(data)).catch(() => {}); }, []);

    const revoke = async (g) => {
        try { await api.post(`/internal/patients/${pid}/delegates/${g.id}/revoke`); toast.success("Access revoked."); load(); }
        catch (e) { toast.error(formatErr(e)); }
    };

    if (!pid) return null;

    return (
        <div className="mt-6 border-t border-slate-200 pt-4" data-testid="family-access-section">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-bold text-slate-800 flex items-center gap-1.5"><Users className="w-4 h-4 text-visita-greenDark" /> Family / Caregiver Access</h3>
                {!adding && <Button size="sm" variant="outline" data-testid="family-add-btn" onClick={() => { setAdding(true); setTempPw(null); }}><Plus className="w-4 h-4 mr-1" /> Add access</Button>}
            </div>

            {tempPw && (
                <div className="mb-3 p-2 rounded bg-amber-50 border border-amber-200 text-xs" data-testid="family-temp-pw">
                    New caregiver temporary password (shown once): <span className="font-mono font-bold">{tempPw}</span>
                    <button className="ml-2 text-amber-700" onClick={() => { navigator.clipboard.writeText(tempPw); toast.success("Copied."); }}><Copy className="w-3 h-3 inline" /></button>
                </div>
            )}

            {grants.length === 0 && !adding && <p className="text-xs text-slate-400">No family or caregiver access granted.</p>}

            <div className="space-y-2">
                {grants.map((g) => (
                    <div key={g.id} data-testid="family-grant-row" className={`p-2.5 rounded-sm border text-sm ${g.active ? "border-slate-200 bg-white" : "border-slate-100 bg-slate-50 opacity-70"}`}>
                        <div className="flex items-center justify-between">
                            <div>
                                <span className="font-semibold text-slate-800">{g.delegate_name || g.delegate_email}</span>
                                <span className="text-slate-500"> · {g.relationship}{g.relationship === "Other" && g.relationship_other ? ` (${g.relationship_other})` : ""}</span>
                                <span className={`ml-2 text-[10px] font-bold px-1.5 py-0.5 rounded ${g.active ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-500"}`} data-testid="family-grant-status">{g.active ? "Active" : "Revoked"}</span>
                            </div>
                            {g.active && <button data-testid="family-revoke-btn" onClick={() => revoke(g)} className="text-red-500 hover:text-red-700" title="Revoke"><Trash2 className="w-4 h-4" /></button>}
                        </div>
                        <div className="flex flex-wrap gap-1 mt-1">
                            {(g.permissions || []).map((p) => <span key={p} className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded inline-flex items-center gap-1"><Shield className="w-2.5 h-2.5" />{PERM_LABEL[p] || p}</span>)}
                        </div>
                        <div className="text-[10px] text-slate-400 mt-1">Granted {g.granted_at ? new Date(g.granted_at).toLocaleDateString() : ""} · Basis: {g.consent_type}</div>
                    </div>
                ))}
            </div>

            {adding && <AddForm pid={pid} opts={opts} onClose={() => setAdding(false)} onSaved={(pw) => { setAdding(false); setTempPw(pw || null); load(); }} />}
        </div>
    );
}

function AddForm({ pid, opts, onClose, onSaved }) {
    const [mode, setMode] = useState("existing"); // existing | caregiver
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [picked, setPicked] = useState(null);
    const [cgName, setCgName] = useState(""); const [cgEmail, setCgEmail] = useState("");
    const [relationship, setRelationship] = useState("");
    const [relOther, setRelOther] = useState("");
    const [perms, setPerms] = useState([]);
    const [consent, setConsent] = useState("");
    const [busy, setBusy] = useState(false);

    const search = async () => {
        if (q.trim().length < 2) return;
        try { const { data } = await api.get("/internal/user-search", { params: { q } }); setResults(data); }
        catch (e) { toast.error(formatErr(e)); }
    };
    const togglePerm = (p) => setPerms((v) => v.includes(p) ? v.filter((x) => x !== p) : [...v, p]);

    const save = async () => {
        if (!relationship) return toast.error("Select a relationship.");
        if (!perms.length) return toast.error("Select at least one permission.");
        if (!consent) return toast.error("Select an authorization basis.");
        const body = { relationship, relationship_other: relOther, permissions: perms, consent_type: consent };
        if (mode === "existing") { if (!picked) return toast.error("Select a user."); body.delegate_user_id = picked.id; }
        else { if (!cgName.trim() || !cgEmail.trim()) return toast.error("Enter caregiver name and email."); body.new_caregiver = { name: cgName, email: cgEmail }; }
        setBusy(true);
        try {
            const { data } = await api.post(`/internal/patients/${pid}/delegates`, body);
            toast.success("Access granted.");
            onSaved(data.temp_password);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <div className="mt-3 p-3 rounded-sm border border-visita-green/40 bg-visita-green/5 space-y-3" data-testid="family-add-form">
            <div className="flex items-center justify-between">
                <div className="flex gap-1 text-xs">
                    <button data-testid="family-mode-existing" onClick={() => setMode("existing")} className={`px-2 py-1 rounded ${mode === "existing" ? "bg-visita-green text-white" : "bg-white border border-slate-200"}`}>Existing VIen user</button>
                    <button data-testid="family-mode-caregiver" onClick={() => setMode("caregiver")} className={`px-2 py-1 rounded ${mode === "caregiver" ? "bg-visita-green text-white" : "bg-white border border-slate-200"}`}>New caregiver</button>
                </div>
                <button onClick={onClose}><X className="w-4 h-4 text-slate-400" /></button>
            </div>

            {mode === "existing" ? (
                <div>
                    <div className="flex gap-2">
                        <Input data-testid="family-search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search patients / caregivers by name or email" onKeyDown={(e) => e.key === "Enter" && search()} />
                        <Button type="button" variant="outline" onClick={search} data-testid="family-search-btn"><Search className="w-4 h-4" /></Button>
                    </div>
                    {results.map((r) => (
                        <button key={r.id} data-testid="family-search-result" onClick={() => { setPicked(r); setResults([]); setQ(r.name); }} className="block w-full text-left text-sm px-2 py-1 hover:bg-white rounded">
                            {r.name} <span className="text-slate-400">· {r.email} · {r.role}</span>
                        </button>
                    ))}
                    {picked && <div className="text-xs text-emerald-700 mt-1">Selected: <b>{picked.name}</b> ({picked.email})</div>}
                </div>
            ) : (
                <div className="grid grid-cols-2 gap-2">
                    <Input data-testid="family-cg-name" value={cgName} onChange={(e) => setCgName(e.target.value)} placeholder="Caregiver full name" />
                    <Input data-testid="family-cg-email" value={cgEmail} onChange={(e) => setCgEmail(e.target.value)} placeholder="Caregiver email" />
                    <p className="col-span-2 text-[11px] text-slate-500">A caregiver-only login is created (no patient chart). They set their password on first sign-in.</p>
                </div>
            )}

            <div className="grid grid-cols-2 gap-2">
                <select data-testid="family-relationship" className="rounded-md border border-slate-300 px-2 py-2 text-sm bg-white" value={relationship} onChange={(e) => setRelationship(e.target.value)}>
                    <option value="">Relationship…</option>
                    {opts.relationships.map((r) => <option key={r}>{r}</option>)}
                </select>
                <select data-testid="family-consent" className="rounded-md border border-slate-300 px-2 py-2 text-sm bg-white" value={consent} onChange={(e) => setConsent(e.target.value)}>
                    <option value="">Authorization basis…</option>
                    {opts.consent_types.map((c) => <option key={c}>{c}</option>)}
                </select>
            </div>
            {relationship === "Other" && <Input data-testid="family-rel-other" value={relOther} onChange={(e) => setRelOther(e.target.value)} placeholder="Describe relationship (optional)" />}

            <div>
                <div className="text-xs font-semibold text-slate-600 mb-1">Permissions</div>
                <div className="flex flex-wrap gap-2">
                    {opts.permissions.map((p) => (
                        <label key={p} data-testid={`family-perm-${p}`} className="text-xs flex items-center gap-1 cursor-pointer">
                            <input type="checkbox" checked={perms.includes(p)} onChange={() => togglePerm(p)} /> {PERM_LABEL[p] || p}
                        </label>
                    ))}
                </div>
            </div>

            <div className="flex gap-2">
                <Button data-testid="family-save-btn" disabled={busy} onClick={save} className="bg-visita-green hover:bg-visita-greenDark text-white">{busy ? "Saving…" : "Grant access"}</Button>
                <Button variant="outline" onClick={onClose}>Cancel</Button>
            </div>
        </div>
    );
}
