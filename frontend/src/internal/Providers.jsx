import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Stethoscope, Search, Building2, MapPin } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Input } from "../components/ui/input";

export default function Providers() {
    const [rows, setRows] = useState([]);
    const [q, setQ] = useState("");
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const params = {};
            if (q.trim()) params.q = q.trim();
            const { data } = await api.get("/internal/providers", { params });
            setRows(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, [q]);

    useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);

    return (
        <div className="space-y-4" data-testid="providers-page">
            <div className="flex items-center gap-2">
                <Stethoscope className="w-5 h-5 text-visita-greenDark" />
                <h1 className="text-xl font-bold text-slate-900">Providers</h1>
                <span className="text-sm text-slate-400" data-testid="provider-count">({rows.length})</span>
            </div>
            <p className="text-sm text-slate-500 -mt-2">
                Read-only registry of providers and their organization &amp; location affiliations. No patient information.
            </p>

            <div className="relative max-w-md">
                <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <Input data-testid="provider-search" className="pl-8"
                    placeholder="Search by provider, specialty, or organization…"
                    value={q} onChange={(e) => setQ(e.target.value)} />
            </div>

            {loading && <div className="text-slate-400 text-sm py-6 text-center">Loading…</div>}
            {!loading && rows.length === 0 && (
                <div className="text-slate-400 text-sm py-10 text-center bg-white rounded-lg border border-slate-200" data-testid="providers-empty">
                    No providers found.
                </div>
            )}

            <div className="grid gap-3 md:grid-cols-2">
                {!loading && rows.map((p) => (
                    <div key={p.id} className="bg-white rounded-lg border border-slate-200 p-4" data-testid={`provider-row-${p.id}`}>
                        <div className="flex items-start justify-between gap-2">
                            <div>
                                <div className="font-semibold text-slate-800" data-testid={`provider-name-${p.id}`}>{p.name}</div>
                                {p.specialties && <div className="text-sm text-slate-500">{p.specialties}</div>}
                            </div>
                            <code className="text-[10px] text-slate-400 bg-slate-50 px-1.5 py-0.5 rounded" data-testid={`provider-id-${p.id}`}>{p.id}</code>
                        </div>

                        {p.created_by_org_name && (
                            <div className="text-[11px] uppercase tracking-widest text-slate-400 mt-1">
                                Source: {p.created_by_org_name}
                            </div>
                        )}

                        <div className="mt-3 space-y-2">
                            {(p.affiliations || []).length === 0 && (
                                <div className="text-xs text-slate-400">No organization affiliations.</div>
                            )}
                            {(p.affiliations || []).map((a) => (
                                <div key={a.organization_id} className="rounded-md bg-slate-50 border border-slate-100 p-2.5">
                                    <div className="flex items-center gap-1.5 text-sm font-medium text-slate-700">
                                        <Building2 className="w-3.5 h-3.5 text-visita-greenDark" />
                                        {a.organization_name}
                                        {a.organization_type && <span className="text-xs text-slate-400 font-normal">· {a.organization_type}</span>}
                                    </div>
                                    {(a.locations || []).length > 0 ? (
                                        <ul className="mt-1 ml-1 space-y-0.5">
                                            {a.locations.map((l) => (
                                                <li key={l.id} className="flex items-center gap-1.5 text-xs text-slate-500">
                                                    <MapPin className="w-3 h-3 text-slate-400" />
                                                    {l.label}{l.where ? ` — ${l.where}` : ""}
                                                </li>
                                            ))}
                                        </ul>
                                    ) : (
                                        <div className="text-xs text-slate-400 mt-1 ml-1">No specific locations linked.</div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
