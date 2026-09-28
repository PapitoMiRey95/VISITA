import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Building2, Search, ShieldCheck, ShieldAlert, Ban, RotateCcw } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { formatDate } from "../lib/date";
import { useAuth } from "../context/AuthContext";
import PharmacyAccountsAdmin from "./PharmacyAccountsAdmin";

const STATUSES = ["UNVERIFIED", "VERIFIED", "FLAGGED", "SUSPENDED"];
const STATUS_BADGE = {
    UNVERIFIED: "bg-slate-100 text-slate-600",
    VERIFIED: "bg-emerald-100 text-emerald-700",
    FLAGGED: "bg-amber-100 text-amber-800",
    SUSPENDED: "bg-red-100 text-red-700",
};

export default function Organizations() {
    const { user } = useAuth();
    const [rows, setRows] = useState([]);
    const [types, setTypes] = useState([]);
    const [q, setQ] = useState("");
    const [fType, setFType] = useState("");
    const [fStatus, setFStatus] = useState("");
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const params = {};
            if (q.trim()) params.q = q.trim();
            if (fType) params.type = fType;
            if (fStatus) params.status = fStatus;
            const { data } = await api.get("/internal/organizations", { params });
            setRows(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, [q, fType, fStatus]);

    useEffect(() => { api.get("/partner/org-types").then(({ data }) => setTypes(data.types || [])).catch(() => {}); }, []);
    useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);

    const setStatus = async (org, status) => {
        try {
            await api.post(`/internal/organizations/${org.id}/verification`, { status });
            toast.success(`${org.organization_name} → ${status}`);
            load();
        } catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="space-y-4" data-testid="organizations-page">
            <div className="flex items-center gap-2">
                <Building2 className="w-5 h-5 text-visita-greenDark" />
                <h1 className="text-xl font-bold text-slate-900">Organizations</h1>
                <span className="text-sm text-slate-400" data-testid="org-count">({rows.length})</span>
            </div>

            {user?.role === "admin" && <PharmacyAccountsAdmin />}

            <div className="flex flex-wrap gap-2 items-center">
                <div className="relative flex-1 min-w-[220px]">
                    <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <Input data-testid="org-search" className="pl-8" placeholder="Search name, email, city…" value={q} onChange={(e) => setQ(e.target.value)} />
                </div>
                <Select value={fType || "all"} onValueChange={(v) => setFType(v === "all" ? "" : v)}>
                    <SelectTrigger className="w-56" data-testid="org-filter-type"><SelectValue placeholder="All types" /></SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All types</SelectItem>
                        {types.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                    </SelectContent>
                </Select>
                <Select value={fStatus || "all"} onValueChange={(v) => setFStatus(v === "all" ? "" : v)}>
                    <SelectTrigger className="w-44" data-testid="org-filter-status"><SelectValue placeholder="All statuses" /></SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All statuses</SelectItem>
                        {STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                </Select>
            </div>

            <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
                <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                        <tr>
                            <th className="text-left px-3 py-2">Organization</th>
                            <th className="text-left px-3 py-2">Type</th>
                            <th className="text-left px-3 py-2">Contact</th>
                            <th className="text-left px-3 py-2">Location</th>
                            <th className="text-left px-3 py-2">Registered</th>
                            <th className="text-left px-3 py-2">Profile</th>
                            <th className="text-left px-3 py-2">Status</th>
                            <th className="text-right px-3 py-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading && <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-400">Loading…</td></tr>}
                        {!loading && rows.length === 0 && <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-400">No organizations found.</td></tr>}
                        {!loading && rows.map((o) => (
                            <tr key={o.id} className="border-t border-slate-100 align-top" data-testid={`org-row-${o.id}`}>
                                <td className="px-3 py-2">
                                    <div className="font-semibold text-slate-800">{o.organization_name}</div>
                                    <div className="text-xs text-slate-400">{o.email}{o.possible_duplicate && <span className="ml-1 text-amber-600 font-semibold">· possible duplicate</span>}</div>
                                    <div className="text-[10px] uppercase tracking-widest text-slate-400 mt-0.5">{o.source}</div>
                                </td>
                                <td className="px-3 py-2 text-slate-600">{o.organization_type}</td>
                                <td className="px-3 py-2 text-slate-600">{o.contact_first_name} {o.contact_last_name}<div className="text-xs text-slate-400">{o.phone}</div></td>
                                <td className="px-3 py-2 text-slate-600">{[o.city, o.province].filter(Boolean).join(", ")}</td>
                                <td className="px-3 py-2 text-slate-600">{o.created_at ? formatDate(o.created_at.slice(0, 10)) : "—"}</td>
                                <td className="px-3 py-2 text-slate-600">{o.profile_completeness}%</td>
                                <td className="px-3 py-2">
                                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${STATUS_BADGE[o.verification_status]}`} data-testid={`org-status-${o.id}`}>{o.verification_status}</span>
                                </td>
                                <td className="px-3 py-2">
                                    <div className="flex justify-end gap-1">
                                        {o.verification_status !== "VERIFIED" && (
                                            <Button size="sm" variant="outline" className="h-8 text-emerald-700 border-emerald-200" data-testid={`org-verify-${o.id}`} onClick={() => setStatus(o, "VERIFIED")}>
                                                <ShieldCheck className="w-4 h-4 mr-1" /> Verify
                                            </Button>
                                        )}
                                        {o.verification_status !== "FLAGGED" && (
                                            <Button size="sm" variant="outline" className="h-8 text-amber-700 border-amber-200" data-testid={`org-flag-${o.id}`} onClick={() => setStatus(o, "FLAGGED")}>
                                                <ShieldAlert className="w-4 h-4 mr-1" /> Flag
                                            </Button>
                                        )}
                                        {o.verification_status !== "SUSPENDED" ? (
                                            <Button size="sm" variant="outline" className="h-8 text-red-700 border-red-200" data-testid={`org-suspend-${o.id}`} onClick={() => setStatus(o, "SUSPENDED")}>
                                                <Ban className="w-4 h-4 mr-1" /> Suspend
                                            </Button>
                                        ) : (
                                            <Button size="sm" variant="outline" className="h-8 text-slate-700" data-testid={`org-reactivate-${o.id}`} onClick={() => setStatus(o, "UNVERIFIED")}>
                                                <RotateCcw className="w-4 h-4 mr-1" /> Reactivate
                                            </Button>
                                        )}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
