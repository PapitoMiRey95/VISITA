import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { X, Search, ShieldCheck, Trash2, UserPlus } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";

// Admin-only: grant/revoke EDIT_PROFILE authorization for a Professional Profile.
// Never creates users; grants only from existing VIen user records.
export default function AuthorizedEditors({ profile, onClose }) {
    const [editors, setEditors] = useState([]);
    const [loading, setLoading] = useState(true);
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try { const { data } = await api.get(`/professionals/${profile.id}/editors`); setEditors(data); }
        catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, [profile.id]);
    useEffect(() => { load(); }, [load]);

    const search = async () => {
        if (!q.trim()) { setResults([]); return; }
        setSearching(true);
        try { const { data } = await api.get("/professionals/authz/user-search", { params: { q: q.trim() } }); setResults(data); }
        catch (e) { toast.error(formatErr(e)); } finally { setSearching(false); }
    };
    useEffect(() => { const t = setTimeout(search, 300); return () => clearTimeout(t); }, [q]); // eslint-disable-line

    const grant = async (u) => {
        setBusy(true);
        try {
            await api.post(`/professionals/${profile.id}/editors`, { user_id: u.id, organization_id: u.organization_id || null });
            toast.success(`${u.name || u.email} can now edit this profile.`);
            setQ(""); setResults([]); load();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const revoke = async (authId) => {
        setBusy(true);
        try { await api.delete(`/professionals/${profile.id}/editors/${authId}`); toast.success("Authorization revoked."); load(); }
        catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const activeUserIds = new Set(editors.map((e) => e.user_id));

    return (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto" onClick={onClose} data-testid="prof-editors-modal">
            <div className="bg-white rounded-lg border border-slate-200 shadow-xl w-full max-w-lg my-6" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
                    <div>
                        <h2 className="text-lg font-bold text-slate-900">Authorized Editors</h2>
                        <p className="text-xs text-slate-500">{profile.display_name || profile.surname} — grant EDIT_PROFILE to specific VIen users only.</p>
                    </div>
                    <button onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="prof-editors-close"><X className="w-5 h-5" /></button>
                </div>

                <div className="p-5 space-y-4">
                    <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Active editors</div>
                        {loading ? <div className="text-sm text-slate-400">Loading…</div>
                            : editors.length === 0 ? <div className="text-sm text-slate-400" data-testid="prof-editors-empty">No delegated editors. Only Admin and the linked professional can edit.</div>
                            : (
                                <div className="space-y-1.5" data-testid="prof-editors-list">
                                    {editors.map((e) => (
                                        <div key={e.id} className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2" data-testid="prof-editor-row">
                                            <div className="min-w-0">
                                                <div className="text-sm font-semibold text-slate-800 truncate">{e.user_name || e.user_email || e.user_id}</div>
                                                <div className="text-xs text-slate-500 truncate">
                                                    {e.user_role}{e.organization_name ? ` · ${e.organization_name}` : ""} · <span className="font-mono">{e.permission_level}</span>
                                                </div>
                                            </div>
                                            <Button size="sm" variant="ghost" className="text-rose-600 hover:bg-rose-50" disabled={busy}
                                                onClick={() => revoke(e.id)} data-testid={`prof-editor-revoke-${e.user_id}`}>
                                                <Trash2 className="w-3.5 h-3.5" />
                                            </Button>
                                        </div>
                                    ))}
                                </div>
                            )}
                    </div>

                    <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Add an editor</div>
                        <div className="relative">
                            <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                            <Input className="pl-8" placeholder="Search existing VIen users by name or email…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="prof-editor-user-search" />
                        </div>
                        {searching && <div className="text-xs text-slate-400 mt-1">Searching…</div>}
                        {results.length > 0 && (
                            <div className="mt-2 border border-slate-200 rounded-md divide-y max-h-56 overflow-y-auto" data-testid="prof-editor-search-results">
                                {results.map((u) => (
                                    <div key={u.id} className="flex items-center justify-between px-3 py-2">
                                        <div className="min-w-0">
                                            <div className="text-sm font-semibold text-slate-800 truncate">{u.name || u.email}</div>
                                            <div className="text-xs text-slate-500 truncate">{u.role}{u.organization_name ? ` · ${u.organization_name}` : ""} · {u.email}</div>
                                        </div>
                                        {activeUserIds.has(u.id)
                                            ? <Badge variant="secondary" className="gap-1 text-emerald-700"><ShieldCheck className="w-3 h-3" /> Authorized</Badge>
                                            : <Button size="sm" variant="outline" disabled={busy} onClick={() => grant(u)} data-testid={`prof-editor-grant-${u.id}`}><UserPlus className="w-3.5 h-3.5 mr-1" /> Grant edit</Button>}
                                    </div>
                                ))}
                            </div>
                        )}
                        <p className="text-[11px] text-slate-400 mt-2">Organization membership never grants edit access on its own — each editor is authorized here explicitly.</p>
                    </div>
                </div>
            </div>
        </div>
    );
}
