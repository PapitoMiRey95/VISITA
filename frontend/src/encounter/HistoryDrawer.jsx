import { useState } from "react";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Sheet, SheetContent, SheetTitle, SheetDescription } from "../components/ui/sheet";
import { Button } from "../components/ui/button";

const SEV = ["MILD", "MODERATE", "SEVERE", "LIFE_THREATENING"];
const CFG = {
    conditions: {
        required: "display_text", statuses: ["ACTIVE", "RESOLVED", "HISTORICAL"],
        fields: [
            { k: "display_text", label: "Condition", required: true },
            { k: "onset_date", label: "Onset (YYYY, YYYY-MM or YYYY-MM-DD)" },
            { k: "resolved_date", label: "Resolved date" },
            { k: "notes", label: "Notes", area: true },
        ],
        line: (r) => r.display_text,
    },
    surgeries: {
        required: "procedure_text", statuses: ["ACTIVE", "ARCHIVED"], statusLabel: { ACTIVE: "Current", ARCHIVED: "Archived (entered in error)" },
        fields: [
            { k: "procedure_text", label: "Procedure", required: true },
            { k: "procedure_date", label: "Date (YYYY, YYYY-MM or YYYY-MM-DD)" },
            { k: "facility", label: "Facility" },
            { k: "surgeon_or_provider", label: "Surgeon / provider" },
            { k: "notes", label: "Notes", area: true },
        ],
        line: (r) => r.procedure_text,
    },
    allergies: {
        required: "allergen", statuses: ["ACTIVE", "INACTIVE"],
        fields: [
            { k: "allergen", label: "Allergen", required: true },
            { k: "allergy_type", label: "Type", required: true, options: ["DRUG", "ENVIRONMENTAL", "FOOD", "OTHER"] },
            { k: "reaction", label: "Reaction" },
            { k: "severity", label: "Severity", options: SEV, optional: true },
            { k: "notes", label: "Notes", area: true },
        ],
        line: (r) => `${r.allergen} · ${r.allergy_type}`,
    },
};

const inputCls = "w-full h-7 px-2 text-xs rounded-sm border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500";

function Field({ f, value, onChange }) {
    const v = value ?? "";
    if (f.options) {
        return (
            <select value={v} onChange={(e) => onChange(e.target.value || null)} className={inputCls} data-testid={`hx-field-${f.k}`}>
                <option value="">{f.optional ? "— not specified —" : "Select…"}</option>
                {f.options.map((o) => <option key={o} value={o}>{o.replace("_", "-")}</option>)}
            </select>
        );
    }
    if (f.area) return <textarea value={v} onChange={(e) => onChange(e.target.value)} rows={2} className={`${inputCls} h-auto py-1`} data-testid={`hx-field-${f.k}`} />;
    return <input value={v} onChange={(e) => onChange(e.target.value)} className={inputCls} data-testid={`hx-field-${f.k}`} />;
}

function HistoryForm({ domain, initial, onSaved, onCancel, patientRef }) {
    const cfg = CFG[domain];
    const [form, setForm] = useState(() => initial || {});
    const [busy, setBusy] = useState(false);
    const editing = Boolean(initial?.id);
    const save = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const body = Object.fromEntries(cfg.fields.map((f) => [f.k, form[f.k] ?? null]));
            if (editing) body.status = form.status;
            const url = `/internal/patients/${encodeURIComponent(patientRef)}/${domain}`;
            await (editing ? api.patch(`${url}/${initial.id}`, body) : api.post(url, body));
            toast.success(editing ? "Updated." : "Added.");
            onSaved();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };
    return (
        <form onSubmit={save} className="border border-visita-ribbon/40 bg-visita-bg rounded-sm p-2 flex flex-col gap-1.5" data-testid="hx-form">
            {cfg.fields.map((f) => (
                <label key={f.k} className="text-[10px] font-semibold text-slate-600 uppercase tracking-wide flex flex-col gap-0.5">
                    <span>{f.label}{f.required && <span className="text-red-600"> *</span>}</span>
                    <Field f={f} value={form[f.k]} onChange={(v) => setForm((s) => ({ ...s, [f.k]: v }))} />
                </label>
            ))}
            {editing && (
                <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wide flex flex-col gap-0.5">Status
                    <select value={form.status} onChange={(e) => setForm((s) => ({ ...s, status: e.target.value }))} className={inputCls} data-testid="hx-field-status">
                        {cfg.statuses.map((s) => <option key={s} value={s}>{(cfg.statusLabel || {})[s] || s}</option>)}
                    </select>
                </label>
            )}
            <div className="flex gap-2 justify-end pt-1">
                <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={onCancel} data-testid="hx-form-cancel">Cancel</Button>
                <Button type="submit" size="sm" className="h-7 text-xs bg-visita-ribbon hover:bg-visita-ribbon/90" disabled={busy} data-testid="hx-form-save">{busy ? "Saving…" : editing ? "Save changes" : "Add"}</Button>
            </div>
        </form>
    );
}

export function HistoryDrawer({ domain, title, patientRef, items, onClose, onChanged }) {
    const cfg = CFG[domain];
    const [mode, setMode] = useState(null); // null | "add" | record
    const done = () => { setMode(null); onChanged(); };
    return (
        <Sheet open onOpenChange={(o) => { if (!o) onClose(); }}>
            <SheetContent side="right" className="w-[420px] sm:max-w-[420px] p-0 bg-white flex flex-col" data-testid={`hx-drawer-${domain}`}>
                <div className="px-3 py-2 border-b border-slate-200">
                    <SheetTitle className="text-sm font-bold uppercase tracking-wide text-slate-700">Manage · {title}</SheetTitle>
                    <SheetDescription className="text-[11px] text-slate-500">Longitudinal patient history. Records are never deleted — use status.</SheetDescription>
                </div>
                <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2 text-xs">
                    {mode === "add" ? <HistoryForm domain={domain} patientRef={patientRef} onSaved={done} onCancel={() => setMode(null)} />
                        : <Button size="sm" className="h-7 text-xs self-start bg-visita-ribbon hover:bg-visita-ribbon/90" onClick={() => setMode("add")} data-testid="hx-add-btn"><Plus className="w-3 h-3 mr-1" /> Add</Button>}
                    <div className="border border-slate-200 rounded-sm divide-y divide-slate-100" data-testid="hx-drawer-list">
                        {!items?.length && <div className="p-2 text-slate-400 italic">No records yet.</div>}
                        {(items || []).map((r) => mode?.id === r.id ? (
                            <div key={r.id} className="p-1"><HistoryForm domain={domain} patientRef={patientRef} initial={r} onSaved={done} onCancel={() => setMode(null)} /></div>
                        ) : (
                            <button key={r.id} type="button" onClick={() => setMode(r)} data-testid={`hx-item-${r.id}`}
                                className={`w-full text-left px-2 py-1.5 hover:bg-visita-bg flex items-start gap-2 ${r.status !== "ACTIVE" ? "text-slate-400" : "text-slate-800"}`}>
                                <span className="flex-1 leading-snug"><span className="font-semibold">{cfg.line(r)}</span>
                                    {[r.onset_date, r.procedure_date, r.reaction, r.severity?.replace("_", "-")].filter(Boolean).map((x) => <span key={x} className="text-slate-500"> · {x}</span>)}
                                </span>
                                <span className="text-[9px] font-bold uppercase shrink-0 pt-0.5">{(cfg.statusLabel || {})[r.status]?.split(" ")[0] || r.status}</span>
                            </button>
                        ))}
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    );
}
