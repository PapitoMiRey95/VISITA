import { useState } from "react";
import { Sparkles, Check, AlertTriangle, Plus, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";

// Inline colours: badges/cards must stay readable under the internal dark theme (class remaps)
const BADGE = {
    ALREADY_ON_LIST: [{ background: "#d1fae5", color: "#065f46" }, "Already on list"], ADD_MISSING: [{ background: "#e0f2fe", color: "#075985" }, "Missing · add"],
    POSSIBLE_DOSE_CHANGE: [{ background: "#fde68a", color: "#78350f" }, "Possible dose change"], SIG_DIFFERENCE: [{ background: "#fde68a", color: "#78350f" }, "SIG difference"],
    POSSIBLE_RESTART: [{ background: "#fde68a", color: "#78350f" }, "Previously stopped · restart?"], REVIEW_REQUIRED: [{ background: "#ffe4e6", color: "#9f1239" }, "Review required"],
};
const CARD_PLAIN = { background: "#fff", borderColor: "#e2e8f0", color: "#0f172a" };
const CARD_WARN = { background: "#fffbeb", borderColor: "#fcd34d", color: "#0f172a" };
const DEFAULT_DECISION = { ALREADY_ON_LIST: "skip", ADD_MISSING: "add", POSSIBLE_DOSE_CHANGE: "flag", SIG_DIFFERENCE: "flag", POSSIBLE_RESTART: "flag", REVIEW_REQUIRED: "skip" };
const OPTIONS = {
    ALREADY_ON_LIST: [["skip", "No change"]],
    ADD_MISSING: [["add", "Add to list"], ["skip", "Don't add"]],
    POSSIBLE_DOSE_CHANGE: [["flag", "Keep current · flag for review"], ["replace", "Replace (stop current, add new)"], ["add_both", "Add both"], ["skip", "Ignore"]],
    SIG_DIFFERENCE: [["flag", "Keep current SIG · flag"], ["update_sig", "Update SIG"], ["skip", "Ignore"]],
    POSSIBLE_RESTART: [["flag", "Flag for review"], ["restart", "Restart medication"], ["skip", "Ignore"]],
    REVIEW_REQUIRED: [["skip", "Discard"], ["add", "Add as edited"]],
};
const VERB = { add: "will add", add_both: "will add (keeping current)", skip: "no change", flag: "flag for review", replace: "replace current", update_sig: "update SIG", restart: "restart" };
const label = (m) => [m.drug, m.strength].filter(Boolean).join(" ");

function Card({ row, onChange }) {
    const [badgeStyle, text] = BADGE[row.classification];
    const m = row.med; const cur = row.match;
    const set = (k, v) => onChange({ ...row, med: { ...m, [k]: v } });
    return (
        <div className="rounded-sm border p-2.5" style={row.classification === "ADD_MISSING" || row.classification === "ALREADY_ON_LIST" ? CARD_PLAIN : CARD_WARN} data-testid={`smart-card-${row.idx}`} data-classification={row.classification}>
            <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-bold" style={{ color: "#1e293b" }}>{m.drug} <span className="font-normal" style={{ color: "#64748b" }}>{m.strength}{m.form ? ` · ${m.form}` : ""}{m.sig ? ` · ${m.sig}` : ""}</span></div>
                <span className="text-[10px] px-1.5 py-0.5 rounded font-bold whitespace-nowrap" style={badgeStyle} data-testid={`smart-card-badge-${row.idx}`}>{text}</span>
            </div>
            {cur && row.classification !== "ALREADY_ON_LIST" && <div className="text-xs mt-1" style={{ color: "#475569" }}>Current: <b>{cur.strength}{cur.unit && !/[a-z]/i.test(cur.strength || "") ? ` ${cur.unit}` : ""}</b> · {cur.sig || "—"}{cur.active === false ? " (stopped)" : ""} → Pasted: <b>{m.strength}</b> · {m.sig || "—"}</div>}
            {row.reasons?.length > 0 && <div className="text-xs text-rose-700 mt-1">{row.reasons.join("; ")}</div>}
            {row.decision !== "skip" && (
                <div className="grid grid-cols-4 gap-1 mt-2">
                    <Input value={m.drug || ""} onChange={(e) => set("drug", e.target.value)} className="h-7 text-xs" placeholder="Drug" data-testid={`smart-card-drug-${row.idx}`} />
                    <Input value={m.strength || ""} onChange={(e) => set("strength", e.target.value)} className="h-7 text-xs" placeholder="Strength" />
                    <Input value={m.form || ""} onChange={(e) => set("form", e.target.value)} className="h-7 text-xs" placeholder="Form" />
                    <Input value={m.sig || ""} onChange={(e) => set("sig", e.target.value)} className="h-7 text-xs" placeholder="SIG" />
                </div>
            )}
            <div className="flex flex-wrap items-center gap-1.5 mt-2">
                {OPTIONS[row.classification].map(([v, t]) => (
                    <button key={v} type="button" onClick={() => onChange({ ...row, decision: v })} data-testid={`smart-card-decision-${row.idx}-${v}`}
                        className={`text-xs px-2.5 py-1 rounded-sm border font-semibold ${row.decision === v ? "bg-[#0b2545] text-white border-[#0b2545] shadow-sm" : "bg-white border-slate-300 text-slate-700 hover:bg-slate-100"}`}>{t}</button>
                ))}
                {["add", "add_both", "replace", "restart"].includes(row.decision) && (
                    <button type="button" onClick={() => onChange({ ...row, portal_visible: !row.portal_visible })} className="ml-auto text-[11px] text-slate-600 inline-flex items-center gap-1" data-testid={`smart-card-visible-${row.idx}`}>
                        {row.portal_visible ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />} {row.portal_visible ? "Visible in Patient Portal" : "Hidden from Patient Portal"}
                    </button>
                )}
            </div>
        </div>
    );
}

/* Smart Medication Entry: paste → organize (parser + reconciliation) → review cards → summary → apply confirmed changes only. */
export function SmartMedPaste({ patientId, onApplied, onClose }) {
    const [text, setText] = useState("");
    const [rows, setRows] = useState(null);
    const [stage, setStage] = useState("paste"); // paste | review | summary
    const [busy, setBusy] = useState(false);
    const organize = async () => {
        setBusy(true);
        try {
            const { data } = await api.post(`/internal/patients/${patientId}/medications/organize`, { text });
            if (!data.items.length) { toast.error("No medications recognised in the pasted text."); return; }
            setRows(data.items.map((it, idx) => ({ idx, med: it.parsed, classification: it.classification, match: it.match, reasons: it.reasons, decision: DEFAULT_DECISION[it.classification], portal_visible: true })));
            setStage("review");
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const apply = async () => {
        setBusy(true);
        try {
            const { data } = await api.post(`/internal/patients/${patientId}/medications/reconcile`, {
                source: "MEDICATION_RECONCILIATION",
                decisions: rows.map((r) => ({ med: r.med, classification: r.classification, decision: r.decision, match_id: r.match?.id || null, portal_visible: r.portal_visible })),
            });
            toast.success(`${data.applied.length} change(s) applied · ${data.flagged.length} flagged · ${data.skipped.length} unchanged`);
            onApplied?.(data); onClose?.();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const changes = rows?.filter((r) => ["add", "add_both", "replace", "update_sig", "restart"].includes(r.decision)).length || 0;
    const flags = rows?.filter((r) => r.decision === "flag").length || 0;
    return (
        <div className="border border-slate-700 bg-slate-800 text-slate-100 rounded-sm p-3 mb-3" data-testid="smart-paste-panel">
            <div className="flex items-center justify-between mb-2">
                <div className="text-xs font-bold text-slate-100 inline-flex items-center gap-1"><Sparkles className="w-3.5 h-3.5 text-sky-300" /> Paste & Organize</div>
                <div className="text-[11px] text-slate-400">Updates the medication list only — no prescription, nothing sent to a pharmacy.</div>
            </div>
            {stage === "paste" && (<>
                <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} placeholder={"One medication per line, e.g.\nMetformin 500 mg BID\nRamipril 10 mg OD"} className="font-mono text-xs bg-white" data-testid="smart-paste-text" />
                <div className="flex justify-end gap-2 mt-2"><Button size="sm" variant="outline" onClick={onClose}>Cancel</Button><Button size="sm" disabled={busy || !text.trim()} onClick={organize} data-testid="smart-paste-organize">{busy ? "Organizing…" : "Organize →"}</Button></div>
            </>)}
            {stage === "review" && rows && (<>
                <div className="space-y-2">{rows.map((r) => <Card key={r.idx} row={r} onChange={(nr) => setRows(rows.map((x) => (x.idx === nr.idx ? nr : x)))} />)}</div>
                <div className="flex justify-between gap-2 mt-3"><Button size="sm" variant="outline" onClick={() => setStage("paste")}>Back</Button><Button size="sm" onClick={() => setStage("summary")} data-testid="smart-paste-review-next">Review summary →</Button></div>
            </>)}
            {stage === "summary" && rows && (<>
                <div className="rounded-sm border p-3 text-sm space-y-1" style={CARD_PLAIN} data-testid="smart-paste-summary">
                    {rows.map((r) => (
                        <div key={r.idx} style={{ color: r.decision === "skip" ? (r.classification === "ALREADY_ON_LIST" ? "#047857" : "#475569") : r.decision === "flag" ? "#b45309" : "#0369a1" }} data-testid={`smart-summary-${r.idx}`}>
                            {r.decision === "skip" && r.classification === "ALREADY_ON_LIST" ? <Check className="inline w-3.5 h-3.5 mr-1" /> : r.decision === "flag" ? <AlertTriangle className="inline w-3.5 h-3.5 mr-1" /> : <Plus className="inline w-3.5 h-3.5 mr-1" />}
                            {label(r.med)} — {r.classification === "ALREADY_ON_LIST" ? "already on list" : BADGE[r.classification][1].toLowerCase()} · {VERB[r.decision]}
                        </div>
                    ))}
                    <div className="text-[11px] pt-2 border-t" style={{ color: "#64748b", borderColor: "#f1f5f9" }}>Source: MEDICATION_RECONCILIATION · recorded with your name and time · existing medications are never silently overwritten.</div>
                </div>
                <div className="flex justify-between gap-2 mt-3"><Button size="sm" variant="outline" onClick={() => setStage("review")}>Back</Button>
                    <Button size="sm" disabled={busy} onClick={apply} data-testid="smart-paste-apply">{busy ? "Saving…" : `Apply ${changes} change${changes === 1 ? "" : "s"}${flags ? ` · flag ${flags}` : ""}`}</Button></div>
            </>)}
        </div>
    );
}
