import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, Search, Check, X, Loader2, Copy } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import MatchComparison from "./MatchComparison";

const STATUS_STYLE = {
    PENDING: "bg-amber-100 text-amber-700",
    APPROVED: "bg-emerald-100 text-emerald-700",
    DECLINED: "bg-slate-200 text-slate-600",
};

export default function PortalAccessRequests() {
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [active, setActive] = useState(null); // request being approved

    const load = async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/internal/portal-access-requests");
            setRows(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    };
    useEffect(() => { load(); }, []);

    const pending = rows.filter((r) => r.status === "PENDING");
    const reviewed = rows.filter((r) => r.status !== "PENDING");

    const decline = async (r) => {
        try {
            await api.post(`/internal/portal-access-requests/${r.id}/decline`, {});
            toast.success("Request declined.");
            load();
        } catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="p-6 max-w-4xl mx-auto" data-testid="portal-access-requests-page">
            <div className="flex items-center gap-2 mb-1">
                <ShieldCheck className="w-6 h-6 text-portal-blueDark" />
                <h1 className="text-2xl font-bold text-slate-900">Portal Access Requests</h1>
            </div>
            <p className="text-sm text-slate-500 mb-6">Caregivers requesting to help manage a patient's portal. Approve to grant delegate access; decline to leave no access.</p>

            {loading ? (
                <div className="text-slate-400 py-12 text-center"><Loader2 className="w-6 h-6 animate-spin mx-auto" /></div>
            ) : (
                <>
                    <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500 mb-2">Pending ({pending.length})</h2>
                    {pending.length === 0 && <p className="text-slate-400 text-sm mb-6" data-testid="no-pending-requests">No pending requests.</p>}
                    <div className="space-y-3 mb-8">
                        {pending.map((r) => (
                            <RequestCard key={r.id} r={r} onApprove={() => setActive(r)} onDecline={() => decline(r)} />
                        ))}
                    </div>

                    {reviewed.length > 0 && (
                        <>
                            <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500 mb-2">Reviewed</h2>
                            <div className="space-y-3">
                                {reviewed.map((r) => <RequestCard key={r.id} r={r} reviewed />)}
                            </div>
                        </>
                    )}
                </>
            )}

            {active && <ApproveDialog req={active} onClose={() => setActive(null)} onDone={() => { setActive(null); load(); }} />}
        </div>
    );
}

function RequestCard({ r, onApprove, onDecline, reviewed }) {
    return (
        <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm" data-testid={`access-request-${r.id}`}>
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <div className="font-bold text-slate-900">{r.requester_name || "Unknown"} <span className="text-slate-400 font-normal">· {r.ref_number || "—"}</span></div>
                    <div className="text-sm text-slate-600">Wants to help: <span className="font-semibold">{r.patient_first_name} {r.patient_last_name}</span> (DOB {r.patient_date_of_birth || "—"})</div>
                    <div className="text-sm text-slate-500 mt-0.5">{r.relationship || "—"} · {r.authorization_basis || "—"}</div>
                    <div className="text-xs text-slate-400 mt-0.5">{r.requester_email || "—"} · {r.requester_phone || "—"}</div>
                    {r.note && <div className="text-xs text-slate-500 mt-1 italic">“{r.note}”</div>}
                </div>
                <span className={`px-2 py-0.5 rounded-full text-xs font-bold flex-shrink-0 ${STATUS_STYLE[r.status] || "bg-slate-100 text-slate-500"}`}>{r.status || "UNKNOWN"}</span>
            </div>
            {!reviewed && (
                <div className="flex gap-2 mt-3">
                    <Button size="sm" data-testid={`approve-${r.id}`} onClick={onApprove} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                        <Check className="w-4 h-4 mr-1" /> Approve access
                    </Button>
                    <Button size="sm" variant="outline" data-testid={`decline-${r.id}`} onClick={onDecline} className="text-rose-600 border-rose-200 hover:bg-rose-50">
                        <X className="w-4 h-4 mr-1" /> Decline
                    </Button>
                </div>
            )}
        </div>
    );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtDob(d) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d || "");
    return m ? `${m[1]} ${MONTHS[+m[2] - 1]} - ${m[3]}` : (d || "—");
}

function ApproveDialog({ req, onClose, onDone }) {
    const fullName = `${req.patient_first_name || ""} ${req.patient_last_name || ""}`.trim();
    const [q, setQ] = useState(fullName || (req.patient_last_name || "").trim());
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [picked, setPicked] = useState(null);
    const [cmp, setCmp] = useState(null);
    const [cmpLoading, setCmpLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [temp, setTemp] = useState(null);

    const runSearch = async (term) => {
        const { data } = await api.get("/internal/portal-access-requests/candidates", { params: { q: term } });
        return data;
    };
    const search = async () => {
        setSearching(true); setPicked(null);
        try { setResults(await runSearch(q)); }
        catch (e) { toast.error(formatErr(e)); }
        finally { setSearching(false); }
    };
    useEffect(() => {
        // Prefill with the submitted name; fall back to last name if nothing matches.
        (async () => {
            setSearching(true);
            try {
                let data = fullName ? await runSearch(fullName) : [];
                if (data.length === 0 && req.patient_last_name) {
                    setQ(req.patient_last_name.trim());
                    data = await runSearch(req.patient_last_name.trim());
                }
                setResults(data);
            } catch (e) { toast.error(formatErr(e)); }
            finally { setSearching(false); }
        })();
        // eslint-disable-next-line
    }, []);

    useEffect(() => {
        if (!picked) { setCmp(null); return; }
        let ok = true;
        setCmpLoading(true);
        api.get(`/internal/portal-access-requests/${req.id}/compare`, { params: { patient_id: picked.id } })
            .then(({ data }) => { if (ok) setCmp(data); })
            .catch((e) => { if (ok) { setCmp(null); toast.error(formatErr(e)); } })
            .finally(() => { if (ok) setCmpLoading(false); });
        return () => { ok = false; };
    }, [picked, req.id]);

    const approve = async () => {
        if (!picked) { toast.error("Select the matching patient first."); return; }
        setBusy(true);
        try {
            const { data } = await api.post(`/internal/portal-access-requests/${req.id}/approve`, { patient_id: picked.id });
            if (data.temp_password) { setTemp(data.temp_password); toast.success("Access granted. Share the one-time password."); }
            else { toast.success("Access granted."); onDone(); }
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" data-testid="approve-dialog">
            <div className="bg-white rounded-2xl p-8 w-full max-w-2xl max-h-[90vh] overflow-auto">
                {temp ? (
                    <div className="text-center">
                        <ShieldCheck className="w-10 h-10 text-emerald-500 mx-auto mb-2" />
                        <h3 className="font-bold text-lg text-slate-900">Caregiver account created</h3>
                        <p className="text-sm text-slate-500 mt-1">Share this one-time password with the caregiver. It won't be shown again — they must change it at first login.</p>
                        <div className="mt-4 flex items-center justify-center gap-2">
                            <code data-testid="temp-password" className="px-3 py-2 bg-slate-100 rounded-lg font-mono font-bold text-slate-900">{temp}</code>
                            <Button size="sm" variant="outline" onClick={() => { navigator.clipboard?.writeText(temp); toast.success("Copied"); }}><Copy className="w-4 h-4" /></Button>
                        </div>
                        <Button data-testid="temp-done" onClick={onDone} className="mt-5 bg-portal-blue text-white">Done</Button>
                    </div>
                ) : (
                    <>
                        <h3 className="font-bold text-lg text-slate-900 mb-1">Approve: match the patient</h3>
                        <p className="text-sm text-slate-500 mb-3">Requested for <b>{req.patient_first_name} {req.patient_last_name}</b> (DOB {req.patient_date_of_birth}). Confirm the correct patient — never approve on name alone.</p>
                        <div className="flex gap-2">
                            <div className="relative flex-1">
                                <Search className="w-4 h-4 text-slate-400 absolute left-2 top-3" />
                                <Input data-testid="approve-patient-search" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} className="pl-8" placeholder="Name, last name first name, or VISITA PIN" />
                            </div>
                            <Button data-testid="approve-patient-search-btn" onClick={search} variant="outline" disabled={searching}>Search</Button>
                        </div>
                        <p className="mt-1.5 text-xs text-slate-400" data-testid="approve-search-pin-hint">Tip: enter a numeric <span className="font-semibold text-slate-500">VISITA PIN</span> for an exact match, or type a name.</p>
                        <div className="mt-3 space-y-2 max-h-80 overflow-auto" data-testid="approve-results">
                            {results.map((p) => {
                                const noPortal = !p.patient_id;
                                return (
                                    <button key={p.id} data-testid={`approve-pick-${p.id}`} onClick={() => setPicked(p)}
                                        className={`w-full text-left rounded-xl border p-3 transition ${picked?.id === p.id ? "border-portal-blue bg-portal-blue/5" : "border-slate-200 hover:border-slate-300"}`}>
                                        <div className="flex items-center justify-between gap-2">
                                            <div className="font-bold text-slate-900">{(p.last_name || "").toUpperCase()}, {p.first_name}</div>
                                            {noPortal && <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 flex-shrink-0" data-testid={`no-portal-${p.id}`}>No portal account</span>}
                                        </div>
                                        <div className="text-xs text-slate-500">DOB: {fmtDob(p.date_of_birth)}</div>
                                        <div className="text-xs text-slate-500">PIN: {p.visita_patient_id || "—"}</div>
                                    </button>
                                );
                            })}
                            {searching && <p className="text-sm text-slate-400">Searching…</p>}
                            {!searching && results.length === 0 && <p className="text-sm text-slate-400" data-testid="approve-no-matches">No matches.</p>}
                        </div>

                        {picked && (
                            <MatchComparison cmp={cmp} loading={cmpLoading} />
                        )}
                        {picked && !picked.patient_id && (
                            <p className="mt-2 text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2" data-testid="no-portal-hint">
                                This is an active clinic patient without a portal login. Approving will create a secure portal record linked to their existing VISITA identity (PIN {picked.visita_patient_id || "—"}) so you can grant caregiver access. The patient won't receive a login and isn't required to register.
                            </p>
                        )}

                        <div className="flex justify-end gap-2 mt-5">
                            <Button variant="outline" onClick={onClose}>Cancel</Button>
                            <Button data-testid="approve-confirm" disabled={!picked || busy} onClick={approve} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Approve & grant access"}
                            </Button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
