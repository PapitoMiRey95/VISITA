import { useEffect, useState } from "react";
import { Trash2, Plus, X, ChevronDown, ChevronRight, Pencil, AlertTriangle } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { ComboInput } from "../components/ComboInput";
import {
    FORM_OPTIONS, ATTRIBUTE_OPTIONS, FREQUENCY_OPTIONS, TIMING_OPTIONS,
    DOSE_AMOUNTS, quantityUnitsForForm, doseUnitsForForm,
} from "../lib/rxVocab";

const ACTION_STYLE = {
    HOLD: "bg-red-100 text-red-700", STOP: "bg-red-100 text-red-700", DISCONTINUE: "bg-red-100 text-red-700",
    START: "bg-emerald-100 text-emerald-700", CONTINUE: "bg-sky-100 text-sky-700",
};

const toOpts = (arr, source) => (arr || []).map((v) => (typeof v === "string" ? { value: v } : { value: v.value, source: v.source || source }));
const merge = (...lists) => {
    const seen = new Set(); const out = [];
    for (const list of lists) for (const o of list) {
        const k = (o.value || "").toLowerCase();
        if (k && !seen.has(k)) { seen.add(k); out.push(o); }
    }
    return out;
};
const Field = ({ label, children }) => (<div><Label className="text-xs">{label}</Label>{children}</div>);

// Smart pharmacy medication card. Reuses the shared ComboInput + controlled vocab
// (same tooling as the physician editor) but shows pharmacy renewal fields.
// Free text is always allowed; selecting never forces a closed list.
export function PharmacyMedCard({ m, i, setMed, removeMed, toggleEdit, fieldSuggest = {}, drugOptions = [], ensureDrugSuggest }) {
    const [dose, setDose] = useState("");
    const [doseUnit, setDoseUnit] = useState("");
    const [freq, setFreq] = useState("");
    const [timing, setTiming] = useState("");

    const drugKey = (m.drug || "").toLowerCase().trim();
    useEffect(() => { if (drugKey && ensureDrugSuggest) ensureDrugSuggest(drugKey); }, [drugKey, ensureDrugSuggest]);

    const sug = fieldSuggest[drugKey] || {};
    const strengthOpts = merge(toOpts(sug.strengths));
    const formOpts = merge(toOpts(sug.forms), toOpts(FORM_OPTIONS));
    const attrOpts = merge(toOpts(sug.attributes), toOpts(ATTRIBUTE_OPTIONS));
    const sigOpts = merge(toOpts(sug.sigs));
    const qtyUnitOpts = merge(toOpts(sug.quantity_units), toOpts(quantityUnitsForForm(m.form)));
    const manuOpts = merge(toOpts(sug.manufacturers));
    const doseUnitOpts = merge(toOpts(doseUnitsForForm(m.form)));

    const set = (k, v) => setMed(i, k, v);
    const more = !!m._moreOpen;

    const addAttr = (v) => {
        const val = (v || "").trim(); if (!val) return;
        const cur = m.attributes || [];
        if (!cur.some((a) => a.toLowerCase() === val.toLowerCase())) set("attributes", [...cur, val]);
    };
    const removeAttr = (a) => set("attributes", (m.attributes || []).filter((x) => x !== a));

    const insertSig = () => {
        const parts = [dose, doseUnit, freq.split(" / ")[0], timing].map((x) => (x || "").trim()).filter(Boolean);
        if (!parts.length) return;
        set("sig", (m.sig || "").trim() ? `${m.sig.trim()} ${parts.join(" ")}` : parts.join(" "));
        setDose(""); setDoseUnit(""); setFreq(""); setTiming("");
    };

    if (!m._editing) {
        return (
            <div className="border border-slate-200 rounded-sm p-3" data-testid="pharm-med-card">
                <div className="flex items-start justify-between gap-3">
                    <div className="text-sm flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-slate-400 text-xs font-semibold">{i + 1}.</span>
                            <span className="font-semibold text-slate-800">{[m.drug || "(medication?)", m.strength].filter(Boolean).join(" ")}</span>
                            {m.action ? <span className={`px-1.5 py-0.5 rounded-sm text-[10px] font-bold tracking-wide ${ACTION_STYLE[m.action] || "bg-slate-100 text-slate-600"}`} data-testid="pharm-action-badge">{m.action}</span> : null}
                        </div>
                        <div className="text-slate-500 text-xs mt-0.5">{[m.form, ...(m.attributes || [])].filter(Boolean).join(" · ") || "—"}</div>
                        {m.sig ? <div className="text-slate-700 text-xs mt-1"><span className="text-slate-400 uppercase mr-1">SIG</span>{m.sig}</div> : null}
                        {(m.quantity || m.days_supply || m.requested_duration) ? (
                            <div className="text-slate-600 text-xs mt-0.5">
                                {m.quantity ? `Qty ${m.quantity}${m.quantity_unit ? ` ${m.quantity_unit}` : ""}` : ""}
                                {m.quantity && (m.days_supply || m.requested_duration) ? " · " : ""}
                                {m.days_supply ? `${m.days_supply} days supply` : ""}
                                {m.days_supply && m.requested_duration ? " · " : ""}
                                {m.requested_duration ? `Renew: ${m.requested_duration}` : ""}
                            </div>
                        ) : null}
                        {(m.existing_rx_number || m.last_filled_date || m.manufacturer || m.current_refills) ? (
                            <div className="text-slate-400 text-[11px] mt-0.5 flex flex-wrap gap-x-3">
                                {m.existing_rx_number ? <span>Rx# {m.existing_rx_number}</span> : null}
                                {m.last_filled_date ? <span>Last filled {m.last_filled_date}</span> : null}
                                {m.current_refills ? <span>Refills left: {m.current_refills}</span> : null}
                                {m.manufacturer ? <span>Mfr: {m.manufacturer}</span> : null}
                            </div>
                        ) : null}
                        {m.pharmacy_note ? <div className="text-slate-500 text-[11px] mt-0.5"><span className="text-slate-400">Note:</span> {m.pharmacy_note}</div> : null}
                        {(m.needs_review || []).length > 0 && <div className="text-amber-600 text-[11px] mt-1 inline-flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> Review: {m.needs_review.join(", ")}</div>}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        <button onClick={() => toggleEdit(i)} data-testid="pharm-edit-med" className="text-xs text-slate-500 hover:underline inline-flex items-center gap-1"><Pencil className="w-3.5 h-3.5" /> Edit</button>
                        <button onClick={() => removeMed(i)} data-testid="pharm-remove-med" className="text-slate-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="border border-slate-200 rounded-sm p-3 space-y-3" data-testid="pharm-med-edit">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <Field label="Medication / Drug"><ComboInput testId="pharm-drug" value={m.drug} onChange={(v) => set("drug", v)} options={merge(toOpts(drugOptions))} placeholder="Start typing a medication…" /></Field>
                <Field label="Strength"><ComboInput testId="pharm-strength" value={m.strength} onChange={(v) => set("strength", v)} options={strengthOpts} placeholder="e.g. 10 mg" /></Field>
                <Field label="Dosage form"><ComboInput testId="pharm-form" value={m.form} onChange={(v) => set("form", v)} options={formOpts} placeholder="tablet, capsule, eye drops…" /></Field>
                <Field label="Qty"><div className="grid grid-cols-2 gap-2"><Input data-testid="pharm-qty" value={m.quantity || ""} onChange={(e) => set("quantity", e.target.value)} placeholder="Qty" /><ComboInput testId="pharm-qty-unit" value={m.quantity_unit} onChange={(v) => set("quantity_unit", v)} options={qtyUnitOpts} placeholder="unit" /></div></Field>
            </div>

            <div>
                <Label className="text-xs">Formulation attributes</Label>
                {(m.attributes || []).length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-1" data-testid="pharm-attrs">
                        {(m.attributes || []).map((a) => (
                            <Badge key={a} variant="secondary" className="gap-1 font-normal">{a}<button type="button" onClick={() => removeAttr(a)} className="hover:text-red-600"><X className="w-3 h-3" /></button></Badge>
                        ))}
                    </div>
                )}
                <ComboInput testId="pharm-attr-add" value="" onChange={addAttr} options={attrOpts} placeholder="Add attribute (e.g. film-coated)…" />
            </div>

            <div>
                <Label className="text-xs">Directions / SIG</Label>
                {sigOpts.length > 0
                    ? <ComboInput testId="pharm-sig" value={m.sig} onChange={(v) => set("sig", v)} options={sigOpts} placeholder="Type freely, e.g. 1 tablet HS" />
                    : <Input data-testid="pharm-sig" value={m.sig || ""} onChange={(e) => set("sig", e.target.value)} placeholder="Type freely, e.g. 1 tablet HS" />}
                <div className="mt-1.5 bg-slate-50 border border-slate-200 rounded-sm p-2">
                    <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">Quick build (optional)</div>
                    <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 items-end">
                        <ComboInput testId="pharm-sig-dose" value={dose} onChange={setDose} options={merge(toOpts(DOSE_AMOUNTS))} placeholder="Dose" />
                        <ComboInput testId="pharm-sig-dose-unit" value={doseUnit} onChange={setDoseUnit} options={doseUnitOpts} placeholder="Unit" />
                        <ComboInput testId="pharm-sig-freq" value={freq} onChange={setFreq} options={merge(toOpts(FREQUENCY_OPTIONS))} placeholder="Frequency" />
                        <ComboInput testId="pharm-sig-timing" value={timing} onChange={setTiming} options={merge(toOpts(TIMING_OPTIONS))} placeholder="Timing" />
                        <Button type="button" size="sm" variant="outline" data-testid="pharm-sig-insert" onClick={insertSig}><Plus className="w-3.5 h-3.5 mr-1" />Insert</Button>
                    </div>
                </div>
            </div>

            <Field label="Requested renewal duration / quantity"><Input data-testid="pharm-requested-duration" value={m.requested_duration || ""} onChange={(e) => set("requested_duration", e.target.value)} placeholder="e.g. 3 months / 90 tablets" /></Field>

            <button type="button" data-testid="pharm-more-toggle" onClick={() => set("_moreOpen", !more)} className="text-xs text-slate-500 inline-flex items-center gap-1 hover:text-slate-700">
                {more ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />} More Rx Details
            </button>

            {more && (
                <div className="border border-slate-200 rounded-sm p-3 grid grid-cols-1 sm:grid-cols-2 gap-2" data-testid="pharm-more">
                    <Field label="Existing Rx #"><Input data-testid="pharm-rx-number" value={m.existing_rx_number || ""} onChange={(e) => set("existing_rx_number", e.target.value)} /></Field>
                    <Field label="Last Filled Date"><Input data-testid="pharm-last-filled" value={m.last_filled_date || ""} onChange={(e) => set("last_filled_date", e.target.value)} placeholder="YYYY-MM-DD" /></Field>
                    <Field label="Manufacturer"><ComboInput testId="pharm-manufacturer" value={m.manufacturer} onChange={(v) => set("manufacturer", v)} options={manuOpts} placeholder="e.g. Apotex" /></Field>
                    <Field label="Days Supply"><Input data-testid="pharm-days-supply" value={m.days_supply || ""} onChange={(e) => set("days_supply", e.target.value)} placeholder="e.g. 90" /></Field>
                    <Field label="Current # of refills"><Input data-testid="pharm-current-refills" value={m.current_refills || ""} onChange={(e) => set("current_refills", e.target.value)} placeholder="e.g. 0" /></Field>
                    <Field label="Pharmacy note (this medication)"><Input data-testid="pharm-med-note" value={m.pharmacy_note || ""} onChange={(e) => set("pharmacy_note", e.target.value)} /></Field>
                </div>
            )}

            {m.original_text && <div className="text-[11px] text-slate-400">Original: {m.original_text}</div>}
            <div className="flex justify-end gap-2">
                <button onClick={() => removeMed(i)} data-testid="pharm-remove-med-edit" className="text-xs text-red-600 inline-flex items-center gap-1"><Trash2 className="w-3.5 h-3.5" /> Remove</button>
                <Button size="sm" variant="outline" onClick={() => toggleEdit(i)}>Done</Button>
            </div>
        </div>
    );
}
