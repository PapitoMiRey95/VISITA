import { useEffect, useRef, useState } from "react";
import { Search, Wand2, X, ChevronDown, ChevronUp, Star } from "lucide-react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";

const SECTIONS = [["subjective", "S", "subjective_text"], ["objective", "O", "objective_text"], ["plan", "P", "plan_text"]];

/* SOAP helper combobox + preview + explicit insert. Never writes the note itself; insertion goes through onInsert
   (the existing SOAP autosave). */
export function SoapHelperTool({ visitId, patientRef, onInsert }) {
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [open, setOpen] = useState(false);
    const [hi, setHi] = useState(0);
    const [sel, setSel] = useState(null);
    const [collapsed, setCollapsed] = useState(false);
    const [patientSex, setPatientSex] = useState(null);
    const [profile, setProfile] = useState(null);
    const timer = useRef(null);
    const box = useRef(null);

    useEffect(() => {
        clearTimeout(timer.current);
        timer.current = setTimeout(() => {
            // visit_id lets the server filter by the CANONICAL visit encounter_type (no separate frontend type state)
            api.get("/internal/soap-helpers", { params: { search: q, patient_ref: patientRef, visit_id: visitId || undefined } })
                .then(({ data }) => { setResults(data.helpers); setPatientSex(data.patient_sex); setProfile(data.template_profile); setHi(0); })
                .catch(() => setResults([]));
        }, 250);
        return () => clearTimeout(timer.current);
    }, [q, patientRef, visitId]);

    useEffect(() => {
        const h = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
        document.addEventListener("mousedown", h);
        return () => document.removeEventListener("mousedown", h);
    }, []);

    const pick = async (r) => {
        setOpen(false);
        try {
            const { data } = await api.get(`/internal/soap-helpers/${r.id}`);
            setSel(data); setCollapsed(false); setQ("");
        } catch (e) { toast.error(formatErr(e)); }
    };

    const onKey = (e) => {
        if (!open && (e.key === "ArrowDown" || e.key === "Enter")) { setOpen(true); return; }
        if (e.key === "ArrowDown") { e.preventDefault(); setHi((i) => Math.min(i + 1, results.length - 1)); }
        else if (e.key === "ArrowUp") { e.preventDefault(); setHi((i) => Math.max(i - 1, 0)); }
        else if (e.key === "Enter" && results[hi]) { e.preventDefault(); pick(results[hi]); }
        else if (e.key === "Escape") setOpen(false);
    };

    const isLegacy = sel?.source_type === "LEGACY_TABDIAGTEXT";
    /* Content available per section. Legacy tabDiagText = one undifferentiated Text: physician picks Sbj/Obj/Pln; SOP disabled.
       VIen structured templates = their own subjective/objective/plan components; SOP distributes each to its field. */
    const legacyText = isLegacy ? (sel.template_text || "").trim() : "";
    const content = !sel ? {} : isLegacy
        ? Object.fromEntries(SECTIONS.map(([k]) => [k, legacyText]))
        : Object.fromEntries(SECTIONS.map(([k, , f]) => [k, (sel[f] || "").trim()]).filter(([, t]) => t));
    const avail = SECTIONS.filter(([k]) => content[k]);
    const sopEnabled = Boolean(sel) && !isLegacy && avail.length > 0;
    const doInsert = (payload) => {
        const keys = Object.keys(payload);
        if (!keys.length) return;
        onInsert(payload); // append-only, same autosave path
        api.post(`/internal/visits/${visitId}/helper-used`, { helper_id: sel.id, sections_inserted: keys }).catch(() => {});
        toast.success(`Appended to ${keys.map((k) => ({ subjective: "Sbj", objective: "Obj", plan: "Pln" })[k]).join(" + ")} from ${sel.name}`);
    };
    const insertOne = (k) => doInsert(content[k] ? { [k]: content[k] } : {});
    const insertSOP = () => { if (sopEnabled) doInsert(Object.fromEntries(avail.map(([k]) => [k, content[k]]))); };

    return (
        <section className="bg-white border border-slate-300 rounded-sm" data-testid="soap-helper-tool">
            <div className="flex items-center gap-1.5 px-2 py-1 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-600">
                <Wand2 className="w-3.5 h-3.5 shrink-0" /> <span className="whitespace-nowrap">SOAP Temp.</span>
                {profile && <span className="ml-1 whitespace-nowrap normal-case tracking-normal font-semibold text-[10px] px-1 rounded-sm bg-visita-bg text-visita-ribbon border border-slate-300" data-testid="template-profile" data-profile={profile.key || "GENERAL"}>{profile.label}</span>}
                {patientSex === null && <span className="ml-auto normal-case font-medium text-[10px] text-slate-400 truncate" title="Patient sex not on record — only unfiltered templates are shown" data-testid="helper-sex-unknown">sex-filtered hidden</span>}
            </div>
            <div className="p-2 space-y-2">
                <div className="relative" ref={box}>
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                    <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKey}
                        placeholder="Search / select template…" data-testid="helper-search" role="combobox" aria-expanded={open}
                        className="w-full h-7 pl-7 pr-2 text-xs rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-visita-ribbon" />
                    {open && (
                        <ul className="absolute z-30 mt-0.5 w-full max-h-56 overflow-y-auto bg-white border border-slate-300 rounded-sm shadow-lg text-xs" role="listbox" data-testid="helper-results">
                            {!results.length ? <li className="px-2 py-1.5 text-slate-400 italic" data-testid="helper-no-results">No templates found.</li> : results.map((r, i) => (
                                <li key={r.id} role="option" aria-selected={i === hi} onMouseDown={() => pick(r)} onMouseEnter={() => setHi(i)}
                                    data-testid={`helper-option-${r.key}`}
                                    className={`px-2 py-1 cursor-pointer flex items-center gap-2 ${i === hi ? "bg-visita-bg" : ""}`}>
                                    <span className="min-w-0 flex-1">
                                        <span className="font-semibold truncate block">{r.favorite && <Star className="inline w-3 h-3 -mt-0.5 mr-0.5 text-amber-500" fill="currentColor" data-testid="helper-favorite" />}{r.name}</span>
                                        {r.description && <span className="block text-[10px] text-slate-500 truncate" data-testid="helper-description">{r.description}</span>}
                                    </span>
                                    <span className="ml-auto flex gap-0.5 text-[9px] font-bold text-slate-500 shrink-0">
                                        {r.source_type === "LEGACY_TABDIAGTEXT" && <span className="px-1 bg-amber-50 text-amber-800 rounded-sm" title="Legacy tabDiagText template">TXT</span>}
                                        {r.has_subjective && <span className="px-1 bg-slate-100 rounded-sm">S</span>}
                                        {r.has_objective && <span className="px-1 bg-slate-100 rounded-sm">O</span>}
                                        {r.has_plan && <span className="px-1 bg-slate-100 rounded-sm">P</span>}
                                        {r.sex_filter !== "ANY" && <span className="px-1 bg-cyan-50 text-cyan-800 rounded-sm">{r.sex_filter[0]}</span>}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                {sel && (
                    <div className="border border-slate-200 rounded-sm bg-slate-50" data-testid="helper-preview">
                        <div className="flex items-center gap-1 px-2 py-1 border-b border-slate-200">
                            <span className="text-xs font-bold text-slate-800 truncate" data-testid="helper-preview-name">{sel.favorite && <Star className="inline w-3 h-3 -mt-0.5 mr-0.5 text-amber-500" fill="currentColor" />}{sel.name}</span>
                            {sel.source_type === "LEGACY_TABHXTMPSOAP_F" && <span className="text-[9px] font-bold px-1 rounded-sm bg-slate-100 text-slate-600 shrink-0" title={`Access tabHxTmpSOAP_F · ID ${sel.legacy_id_raw}`}>ACCESS</span>}
                            {sel.synthetic_sample && <span className="text-[9px] font-bold px-1 rounded-sm bg-amber-100 text-amber-800">SYNTHETIC</span>}
                            <button type="button" className="ml-auto text-slate-500 hover:text-slate-800" onClick={() => setCollapsed((c) => !c)} data-testid="helper-preview-toggle" aria-label="Toggle preview">
                                {collapsed ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
                            </button>
                            <button type="button" className="text-slate-500 hover:text-slate-800" onClick={() => setSel(null)} data-testid="helper-preview-close" aria-label="Clear template"><X className="w-3.5 h-3.5" /></button>
                        </div>
                        {!collapsed && (
                            <div className="px-2 py-1.5 space-y-1.5 max-h-48 overflow-y-auto">
                                {sel.description && <div className="text-[10px] text-slate-500 italic" data-testid="helper-preview-description">{sel.description}</div>}
                                {isLegacy && (
                                    <div className="text-[11px] text-slate-700 whitespace-pre-wrap leading-snug" data-testid="helper-preview-legacy">
                                        {sel.template_text}
                                        {sel.pmhx_description && <div className="text-[10px] text-slate-400 mt-0.5">PMHx: {sel.pmhx_description}</div>}
                                        <div className="text-[10px] text-slate-400 mt-0.5">Legacy tabDiagText #{sel.legacy_id} · choose Sbj, Obj or Pln</div>
                                    </div>
                                )}
                                {!isLegacy && avail.map(([k, letter]) => (
                                    <div key={k} className="flex gap-1.5 text-[11px]" data-testid={`helper-preview-${k}`}>
                                        <span className="inline-flex shrink-0 w-4 h-4 items-center justify-center rounded-sm bg-slate-500 text-white text-[10px] font-bold">{letter}</span>
                                        <span className="whitespace-pre-wrap text-slate-700 leading-snug">{content[k]}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="flex flex-wrap gap-1 px-2 py-1.5 border-t border-slate-200" data-testid="helper-insert-actions">
                            {[["subjective", "Sbj", "Append to Subjective"], ["objective", "Obj", "Append to Objective"], ["plan", "Pln", "Append to Plan"]].map(([k, lbl, tip]) => (
                                <button key={k} type="button" onClick={() => insertOne(k)} disabled={!content[k]} title={content[k] ? tip : "Template has no content for this section"}
                                    data-testid={`helper-insert-${k}`}
                                    className="h-6 min-w-[44px] px-2 text-[11px] font-bold rounded-sm border border-visita-ribbon text-visita-ribbon hover:bg-visita-bg disabled:opacity-40 disabled:cursor-not-allowed">{lbl}</button>
                            ))}
                            <button type="button" onClick={insertSOP} disabled={!sopEnabled} data-testid="helper-insert-sop" data-enabled={sopEnabled ? "true" : "false"}
                                title={sopEnabled ? `Append ${avail.map(([, l]) => l).join(" + ")} to their sections` : "SOP requires a template with Subjective, Objective and/or Plan components."}
                                className="h-6 min-w-[48px] px-2 text-[11px] font-bold rounded-sm bg-visita-ribbon text-white hover:bg-[#162c49] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-visita-ribbon">SOP</button>
                            <span className="ml-auto self-center text-[10px] text-slate-400">Appends — never replaces your text</span>
                        </div>
                    </div>
                )}
            </div>
        </section>
    );
}
