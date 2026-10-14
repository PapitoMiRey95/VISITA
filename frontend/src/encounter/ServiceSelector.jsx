import { useEffect, useMemo, useRef, useState } from "react";
import { Search, Star, X, Plus, ClipboardList } from "lucide-react";
import { api, formatErr } from "../lib/api";

/* Visit New — Service (Sr / Sr Nº). Structured on visits.service = {primary, additional_codes[]}.
   REPLACE_PRIMARY rows replace the primary; APPEND_CODE rows (Q150, K055) append. Never auto-selected, never written to SOAP. */
export const srNumber = (svc) => {
    const codes = [svc?.primary?.service_code, ...(svc?.additional_codes || []).map((a) => a.service_code)].filter(Boolean);
    return codes.length ? codes.join(";") : null;
};

export function ServiceSelector({ visitId, initial, onChange }) {
    const [catalog, setCatalog] = useState([]);
    const [svc, setSvc] = useState(initial || { primary: null, additional_codes: [] });
    const [q, setQ] = useState("");
    const [open, setOpen] = useState(false);
    const [err, setErr] = useState("");
    const wrap = useRef(null);

    useEffect(() => { setSvc(initial || { primary: null, additional_codes: [] }); }, [initial]);
    useEffect(() => { api.get("/internal/service-catalog").then(({ data }) => setCatalog(data.items)).catch(() => setCatalog([])); }, []);
    useEffect(() => {
        const onDoc = (e) => { if (wrap.current && !wrap.current.contains(e.target)) setOpen(false); };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, []);

    const apply = (data) => { setSvc(data.service); onChange?.(data.service); };
    const call = async (fn) => { setErr(""); try { const { data } = await fn(); apply(data); } catch (e) { setErr(formatErr(e)); } };
    const select = (id) => { call(() => api.post(`/internal/visits/${visitId}/service/select`, { catalog_id: id })); setQ(""); setOpen(false); };
    const clearPrimary = () => call(() => api.delete(`/internal/visits/${visitId}/service/primary`));
    const removeAdd = (id) => call(() => api.delete(`/internal/visits/${visitId}/service/additional/${id}`));

    const items = useMemo(() => {
        const t = q.trim().toLowerCase();
        return t ? catalog.filter((c) => c.service_description.toLowerCase().includes(t) || c.service_code.toLowerCase().includes(t)) : catalog;
    }, [catalog, q]);
    const favs = items.filter((c) => c.favourite), rest = items.filter((c) => !c.favourite);
    const addIds = new Set((svc.additional_codes || []).map((a) => a.catalog_id));

    const Row = ({ c }) => (
        <li>
            <button type="button" onClick={() => select(c.id)} disabled={!visitId || addIds.has(c.id) || svc.primary?.catalog_id === c.id} data-testid={`service-option-${c.legacy_id_raw}`}
                className="w-full text-left px-2 py-1 hover:bg-visita-bg leading-snug flex items-baseline gap-2 disabled:opacity-40">
                {c.favourite && <Star className="w-3 h-3 text-amber-500 shrink-0 self-center" fill="currentColor" />}
                <span className="flex-1 font-semibold text-slate-800">{c.service_description}</span>
                <span className="shrink-0 font-mono text-[10px] text-slate-600">{c.selection_behavior === "APPEND_CODE" ? `+${c.service_code}` : c.service_code}</span>
            </button>
        </li>
    );

    return (
        <div className="px-2 py-1.5" data-testid="service-selector" ref={wrap}>
            <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-500 mb-1">
                <ClipboardList className="w-3 h-3" /> Service <span className="normal-case font-medium text-slate-400 tracking-normal">Sr · Sr Nº</span>
            </div>
            <div className="flex flex-wrap items-center gap-1 mb-1 min-h-[22px]" data-testid="service-selected">
                {svc.primary ? (
                    <span className="inline-flex items-center gap-1 text-xs border border-[#15803d] rounded-sm px-1.5 py-0.5 bg-emerald-50" data-testid="service-primary">
                        <span className="font-semibold text-slate-900">{svc.primary.service_description}</span>
                        <span className="font-mono text-[10px] text-slate-600">{svc.primary.service_code}</span>
                        <button type="button" onClick={clearPrimary} aria-label="Clear primary service" data-testid="service-primary-clear" className="text-slate-400 hover:text-red-700"><X className="w-3 h-3" /></button>
                    </span>
                ) : <span className="text-[10px] italic text-slate-400" data-testid="service-primary-empty">No primary service</span>}
                {(svc.additional_codes || []).map((a) => (
                    <span key={a.catalog_id} className="inline-flex items-center gap-1 text-[10px] border border-slate-300 rounded-sm px-1.5 py-0.5 bg-slate-50" data-testid={`service-addon-${a.service_code}`}>
                        <Plus className="w-2.5 h-2.5 text-slate-500" /><span className="font-mono font-semibold">{a.service_code}</span><span className="text-slate-500">{a.service_description}</span>
                        <button type="button" onClick={() => removeAdd(a.catalog_id)} aria-label={`Remove ${a.service_code}`} data-testid={`service-addon-remove-${a.service_code}`} className="text-slate-400 hover:text-red-700"><X className="w-3 h-3" /></button>
                    </span>
                ))}
            </div>
            <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                <input value={q} disabled={!visitId} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} placeholder="Search service / code…" data-testid="service-search-input"
                    className="w-full h-7 pl-7 pr-2 text-xs rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:bg-slate-50" />
            </div>
            {open && visitId && (
                <div className="mt-1 max-h-44 overflow-y-auto border border-slate-200 rounded-sm text-xs" data-testid="service-dropdown">
                    {favs.length > 0 && (<>
                        <div className="px-2 py-0.5 bg-slate-100 text-[9px] font-bold uppercase tracking-wide text-slate-500">Favourites</div>
                        <ul className="divide-y divide-slate-100" data-testid="service-favourites">{favs.map((c) => <Row key={c.id} c={c} />)}</ul>
                    </>)}
                    {rest.length > 0 && (<>
                        <div className="px-2 py-0.5 bg-slate-100 text-[9px] font-bold uppercase tracking-wide text-slate-500">All services</div>
                        <ul className="divide-y divide-slate-100" data-testid="service-all">{rest.map((c) => <Row key={c.id} c={c} />)}</ul>
                    </>)}
                    {!items.length && <div className="px-2 py-1 text-[10px] text-slate-400 italic" data-testid="service-no-results">No matching service.</div>}
                </div>
            )}
            {err && <div className="mt-1 text-[10px] text-red-700" data-testid="service-error">{err}</div>}
        </div>
    );
}

/* Access-style structured summary row: Sr | Dx | Sr Nº | Dx Nº (read-only, never free text, never "(idem)"). */
export function CodingRow({ service, diagnosis }) {
    const cells = [["Sr", service?.primary?.service_description], ["Dx", diagnosis?.diagnosis_text], ["Sr Nº", srNumber(service)], ["Dx Nº", diagnosis?.diagnosis_code]];
    return (
        <div className="grid grid-cols-[1fr_1fr_auto_auto] gap-x-3 px-2 py-1 text-[11px] bg-slate-50" data-testid="coding-row">
            {cells.map(([k, v]) => (
                <div key={k} className="min-w-0">
                    <div className="text-[9px] font-bold uppercase tracking-wide text-slate-500">{k}</div>
                    <div className={`truncate ${v ? "font-semibold text-slate-900" : "text-slate-400"} ${k.includes("Nº") ? "font-mono" : ""}`} data-testid={`coding-${k.replace(/\s|º/g, "").toLowerCase()}`} title={v || ""}>{v || "—"}</div>
                </div>
            ))}
        </div>
    );
}

/* Access-fidelity A band: single horizontal line of labelled boxes — Sr | Dx | Sr Nº | Dx Nº. Read-only structured summary. */
export function CodingBand({ service, diagnosis }) {
    const cells = [["Sr", service?.primary?.service_description, "flex-[1.3]"], ["Dx", diagnosis?.diagnosis_text, "flex-[1.3]"], ["Sr Nº", srNumber(service), "w-44"], ["Dx Nº", diagnosis?.diagnosis_code, "w-20"]];
    return (
        <div className="flex items-stretch h-6 text-[11px] bg-slate-100 divide-x divide-slate-400 border-b border-slate-400" data-testid="coding-band">
            {cells.map(([k, v, w]) => (
                <div key={k} className={`flex items-stretch min-w-0 ${w}`}>
                    <span className="px-1 flex items-center bg-slate-200 text-[10px] font-semibold text-slate-700 whitespace-nowrap border-r border-slate-400">{k}</span>
                    <span className={`flex-1 min-w-0 px-1.5 flex items-center truncate bg-white ${v ? "text-slate-900 font-medium" : "text-slate-400"} ${k.includes("Nº") ? "font-mono" : ""}`}
                        title={v || ""} data-testid={`band-${k.replace(/\s|º/g, "").toLowerCase()}`}>{v || "—"}</span>
                </div>
            ))}
        </div>
    );
}
