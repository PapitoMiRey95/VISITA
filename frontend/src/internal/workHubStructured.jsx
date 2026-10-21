import { PhoneForwarded } from "lucide-react";
import { Label } from "../components/ui/label";
import { Chip } from "./workHubParts";

// Structured clinical follow-up controls. All option lists come from GET /internal/work/meta `catalog` (backend is the single source).
const SELECT_CLS = "w-full h-9 rounded-sm border border-slate-300 bg-white px-2 text-sm";
const hasOther = (v) => (Array.isArray(v) ? v.includes("OTHER") : v === "OTHER");

export const emptyStructured = () => ({ reason_code: "", detail: {}, clinic_action: "" });

function DetailField({ def, value, onChange }) {
    if (def.multi) {
        const sel = value || [];
        const toggle = (code) => onChange(sel.includes(code) ? sel.filter((c) => c !== code) : [...sel, code]);  // preserves selection order
        return (
            <div data-testid={`work-detail-${def.field}`}>
                <Label className="text-xs">{def.label} <span className="text-slate-400 font-normal">(select all that apply)</span></Label>
                <div className="flex flex-wrap gap-1 mt-1">
                    {def.options.map((o) => (
                        <button key={o.code} type="button" data-testid={`work-detail-${def.field}-${o.code.toLowerCase()}`} aria-pressed={sel.includes(o.code)} onClick={() => toggle(o.code)}
                            className={`rounded-sm border px-2 py-0.5 text-xs transition-colors ${sel.includes(o.code) ? "border-visita-green bg-visita-green text-white font-semibold" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>{o.label}</button>
                    ))}
                </div>
            </div>
        );
    }
    return (
        <div><Label className="text-xs">{def.label}</Label>
            <select data-testid={`work-detail-${def.field}`} value={value || ""} onChange={(e) => onChange(e.target.value)} className={SELECT_CLS}>
                <option value="">— Select —</option>
                {def.options.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select></div>
    );
}

// Type-specific Reason / Details → Clinic action (progressive disclosure: only shown for the six clinical types).
export function StructuredFields({ category, catalog, value, onChange }) {
    if (!catalog || !catalog.clinical_types.includes(category)) return null;
    const details = catalog.details[category] || [];
    const reasons = catalog.reasons[category] || [];
    const set = (patch) => onChange({ ...value, ...patch });
    const setDetail = (field, v) => set({ detail: { ...value.detail, [field]: v } });
    const showOther = details.some((d) => hasOther(value.detail[d.field]));
    return (
        <div className="rounded-sm border border-slate-200 bg-slate-50 p-2 space-y-2" data-testid="work-structured">
            {details.length > 0 && (
                <div className={`grid grid-cols-1 ${details.length > 1 ? "sm:grid-cols-2" : ""} gap-2`}>
                    {details.map((d) => <DetailField key={d.field} def={d} value={value.detail[d.field]} onChange={(v) => setDetail(d.field, v)} />)}
                </div>
            )}
            {showOther && (
                <div><Label className="text-xs">Specify</Label>
                    <input data-testid="work-detail-other" value={value.detail.other_text || ""} onChange={(e) => setDetail("other_text", e.target.value)} maxLength={300} placeholder="e.g. PET scan · Forearm · Vitamin D"
                        className={SELECT_CLS} /></div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div><Label className="text-xs">Reason / Details</Label>
                    <select data-testid="work-reason" value={value.reason_code} onChange={(e) => set({ reason_code: e.target.value })} className={SELECT_CLS}>
                        <option value="">— Select —</option>
                        {reasons.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
                    </select></div>
                <div><Label className="text-xs">Clinic action <span className="text-slate-400 font-normal">(optional)</span></Label>
                    <select data-testid="work-clinic-action" value={value.clinic_action} onChange={(e) => set({ clinic_action: e.target.value })} className={SELECT_CLS}>
                        <option value="">— None —</option>
                        {catalog.clinic_actions.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
                    </select></div>
            </div>
        </div>
    );
}

// Body sent to POST /internal/work for the structured part (omits blanks so old-style payloads stay identical).
export function structuredBody(category, catalog, v) {
    if (!catalog || !catalog.clinical_types.includes(category)) return {};
    const detail = Object.fromEntries(Object.entries(v.detail).filter(([, x]) => (Array.isArray(x) ? x.length : x)));
    return { ...(v.reason_code ? { reason_code: v.reason_code } : {}), ...(Object.keys(detail).length ? { clinical_detail: detail } : {}), ...(v.clinic_action ? { clinic_action: v.clinic_action } : {}) };
}
export const structuredEnough = (v) => Boolean(v.reason_code || Object.values(v.detail).some((x) => (Array.isArray(x) ? x.length : x && x !== "")));

// ---- Card / detail presentation (reads label snapshots stored on the item; old items without them render nothing) ----
const isTransfer = (item) => item.clinic_action === "CALL_TRANSFER_ON_ARRIVAL" || item.reason_code === "CALL_TRANSFER_ON_ARRIVAL";

export function StructuredSummary({ item, testid }) {
    if (!item.structured_summary) return null;
    return <span data-testid={testid} className="text-[11px] text-slate-800 uppercase tracking-wide font-bold truncate">· {item.structured_summary}</span>;
}
export function ReasonLine({ item, testid, className = "" }) {
    if (!item.reason_label || item.reason_code === item.referral_subtype || item.reason_code === "CALL_TRANSFER_ON_ARRIVAL") return null;  // shown as badge/chip instead
    return <div data-testid={testid} className={`text-sm font-medium text-slate-900 ${className}`}>{item.reason_label}</div>;
}
// "Put through to me when I arrive" is visually distinct from ordinary booking/calling instructions.
export function ClinicActionChip({ item, testid }) {
    if (!item.clinic_action_label) return null;
    if (isTransfer(item)) return <Chip tone="bg-fuchsia-600 text-white border-fuchsia-700" testid={testid}><PhoneForwarded className="w-3 h-3 mr-1" />{item.clinic_action_label}</Chip>;
    return <Chip tone="bg-sky-50 text-sky-800 border-sky-300" testid={testid}>{item.clinic_action_label}</Chip>;
}
export function TransferReasonChip({ item, testid }) {
    if (item.reason_code !== "CALL_TRANSFER_ON_ARRIVAL" || item.clinic_action === "CALL_TRANSFER_ON_ARRIVAL") return null;
    return <Chip tone="bg-fuchsia-600 text-white border-fuchsia-700" testid={testid}><PhoneForwarded className="w-3 h-3 mr-1" />{item.reason_label}</Chip>;
}
// Message is hidden on cards when it was auto-generated from the structured fields (would repeat them).
export const showMessage = (item) => !(item.message_auto && (item.reason_label || item.structured_summary));
