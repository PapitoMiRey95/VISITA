import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Contact, Search, ShieldCheck, UserRound, X, Info } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";

// Shared VIen Professionals module (Dr. Aguayo's Professional Construct) — Phase 1:
// directory search/list + read-only profile. ONE Professional Profile model reused for
// both Directory Contacts and VIen Users; the only difference is VIen access. Taxonomy
// (Sphere/Area/Specialty/Credentials/Languages) is pending the authoritative Access import.
export default function Professionals() {
    const { user } = useAuth();
    const canEdit = user?.role === "admin"; // Create/Edit/access mgmt = Admin only (Phase 1)
    const [q, setQ] = useState("");
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [taxImported, setTaxImported] = useState(false);
    const [selected, setSelected] = useState(null);

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

    useEffect(() => { api.get("/professionals/taxonomy").then(({ data }) => setTaxImported(!!data.imported)).catch(() => {}); }, []);
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

            {!taxImported && (
                <div className="flex items-start gap-2 bg-sky-50 border border-sky-200 rounded-sm p-3 text-sm text-sky-900" data-testid="prof-taxonomy-notice">
                    <Info className="w-4 h-4 mt-0.5 shrink-0" />
                    <div>Classification taxonomy (Sphere → Area → Specialty), Credentials, Languages and Practice Type are pending import from Dr. Aguayo's source Professional taxonomy. Directory search/view is active now; the full smart editor unlocks after the taxonomy import.</div>
                </div>
            )}

            <div className="flex flex-wrap gap-2 items-center">
                <div className="relative flex-1 min-w-[240px]">
                    <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <Input data-testid="prof-search" className="pl-8" placeholder="Search by name or registration #…" value={q} onChange={(e) => setQ(e.target.value)} />
                </div>
                {canEdit && (
                    <Button variant="outline" disabled title="Available after the taxonomy import" data-testid="prof-add-disabled">
                        + Add Professional
                    </Button>
                )}
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
                        {!loading && rows.length === 0 && <tr><td colSpan={4} className="px-3 py-8 text-center text-slate-400">No professionals found. The directory populates once profiles are added / imported.</td></tr>}
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

            {selected && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setSelected(null)} data-testid="prof-profile-modal">
                    <div className="bg-white rounded-lg border border-slate-200 shadow-xl w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-start justify-between">
                            <div>
                                <h2 className="text-lg font-bold text-slate-900" data-testid="prof-profile-name">{selected.display_name || selected.surname}</h2>
                                <div className="mt-1">
                                    {selected.has_vien_access
                                        ? <Badge className="bg-emerald-100 text-emerald-700 gap-1"><ShieldCheck className="w-3 h-3" /> VIen User</Badge>
                                        : <Badge variant="secondary" className="gap-1 text-slate-600"><UserRound className="w-3 h-3" /> Directory Contact</Badge>}
                                </div>
                            </div>
                            <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-slate-700" data-testid="prof-profile-close"><X className="w-5 h-5" /></button>
                        </div>
                        <dl className="mt-4 space-y-2 text-sm">
                            <Row label="Surname">{selected.surname}</Row>
                            <Row label="First name">{selected.first_name}</Row>
                            <Row label="Second name">{selected.second_name}</Row>
                            <Row label="Registration #">{selected.registration_number}</Row>
                            <Row label="Sex">{selected.sex}</Row>
                            <Row label="Professorship">{selected.professorship}</Row>
                            <Row label="Accepting patients">{selected.accepting_patients == null ? "—" : selected.accepting_patients ? "Yes" : "No"}</Row>
                            <Row label="Waiting list">{selected.waiting_list == null ? "—" : selected.waiting_list ? "Yes" : "No"}</Row>
                        </dl>
                        <p className="mt-4 text-xs text-slate-400">Classification, credentials & languages appear here once the taxonomy is imported and the editor is enabled.</p>
                    </div>
                </div>
            )}
        </div>
    );
}

function Row({ label, children }) {
    return (
        <div className="flex justify-between gap-4 border-b border-slate-100 pb-1.5">
            <dt className="text-slate-400 text-xs uppercase tracking-wide">{label}</dt>
            <dd className="text-slate-800 text-right">{children || "—"}</dd>
        </div>
    );
}
