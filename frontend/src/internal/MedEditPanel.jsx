import { useEffect, useState } from "react";
import { Trash2, Plus, X, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { ComboInput } from "../components/ComboInput";
import {
    FORM_OPTIONS, ATTRIBUTE_OPTIONS, ROUTE_OPTIONS, FREQUENCY_OPTIONS, TIMING_OPTIONS,
    DOSE_AMOUNTS, DURATION_UNITS, REFILL_OPTIONS, ACTION_OPTIONS, EYE_SIDES, EAR_SIDES,
    suggestRoute, doseUnitsForForm, quantityUnitsForForm,
    isOphthalmic, isOtic, isInjectable, isPatch, isTopical,
} from "../lib/rxVocab";

const toOpts = (arr, source) => (arr || []).map((v) => (typeof v === "string" ? { value: v } : { value: v.value, source: v.source || source }));

// Merge suggestion lists (already ranked) then vocabulary; de-dupe by lowercased value.
const merge = (...lists) => {
    const seen = new Set(); const out = [];
    for (const list of lists) for (const o of list) {
        const k = (o.value || "").toLowerCase();
        if (k && !seen.has(k)) { seen.add(k); out.push(o); }
    }
    return out;
};

const Field = ({ label, children }) => (
    <div><Label className="text-xs">{label}</Label>{children}</div>
);

export const MedEditPanel = ({ m, i, setMed, removeMed, toggleEdit, fieldSuggest = {}, drugOptions = [], ensureDrugSuggest }) => {
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
    const routeSuggested = suggestRoute(m.form);
    const routeOpts = merge(toOpts(sug.routes), routeSuggested ? [{ value: routeSuggested, source: "suggested" }] : [], toOpts(ROUTE_OPTIONS));
    const sigOpts = merge(toOpts(sug.sigs));
    const qtyUnitOpts = merge(toOpts(sug.quantity_units), toOpts(quantityUnitsForForm(m.form)));
    const doseUnitOpts = merge(toOpts(doseUnitsForForm(m.form)));

    const set = (k, v) => setMed(i, k, v);
    const isPrn = /\bprn\b/i.test(m.sig || "") || /prn/i.test(freq);

    const addAttr = (v) => {
        const val = (v || "").trim(); if (!val) return;
        const cur = m.attributes || [];
        if (!cur.some((a) => a.toLowerCase() === val.toLowerCase())) set("attributes", [...cur, val]);
    };
    const removeAttr = (a) => set("attributes", (m.attributes || []).filter((x) => x !== a));

    const insertSig = () => {
        const parts = [dose, doseUnit, freq.split(" / ")[0], timing].map((x) => (x || "").trim()).filter(Boolean);
        if (!parts.length) return;
        const chunk = parts.join(" ");
        set("sig", (m.sig || "").trim() ? `${m.sig.trim()} ${chunk}` : chunk);
        setDose(""); setDoseUnit(""); setFreq(""); setTiming("");
    };

    const more = !!m._moreOpen;

    return (
        <div className="space-y-3" data-testid="med-edit-panel">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <Field label="Medication / Drug"><ComboInput testId="sendrx-drug" value={m.drug} onChange={(v) => set("drug", v)} options={merge(toOpts(drugOptions))} placeholder="Start typing a medication…" /></Field>
                <Field label="Strength"><ComboInput testId="sendrx-strength" value={m.strength} onChange={(v) => set("strength", v)} options={strengthOpts} placeholder="e.g. 10 mg or 16 mg / 12.5 mg" /></Field>
                <Field label="Dosage form"><ComboInput testId="sendrx-form" value={m.form} onChange={(v) => set("form", v)} options={formOpts} placeholder="tablet, capsule, eye drops…" /></Field>
                <Field label="Action"><ComboInput testId="sendrx-action" value={m.action} onChange={(v) => set("action", v)} options={merge(toOpts(ACTION_OPTIONS))} placeholder="None" /></Field>
            </div>

            <div>
                <Label className="text-xs">Formulation attributes</Label>
                {(m.attributes || []).length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-1" data-testid="sendrx-attrs">
                        {(m.attributes || []).map((a) => (
                            <Badge key={a} variant="secondary" className="gap-1 font-normal">{a}<button type="button" onClick={() => removeAttr(a)} className="hover:text-red-600"><X className="w-3 h-3" /></button></Badge>
                        ))}
                    </div>
                )}
                <ComboInput testId="sendrx-attr-add" value="" onChange={addAttr} options={attrOpts} placeholder="Add attribute (e.g. film-coated)…" />
            </div>

            <div>
                <Label className="text-xs">Directions / SIG</Label>
                <Input data-testid="sendrx-sig" value={m.sig || ""} onChange={(e) => set("sig", e.target.value)} placeholder="Type freely, e.g. 1 tablet HS" />
                <div className="mt-1.5 bg-slate-50 border border-slate-200 rounded-sm p-2">
                    <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">Quick build (optional)</div>
                    <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 items-end">
                        <ComboInput testId="sig-dose" value={dose} onChange={setDose} options={merge(toOpts(DOSE_AMOUNTS))} placeholder="Dose" />
                        <ComboInput testId="sig-dose-unit" value={doseUnit} onChange={setDoseUnit} options={doseUnitOpts} placeholder="Unit" />
                        <ComboInput testId="sig-freq" value={freq} onChange={setFreq} options={merge(toOpts(FREQUENCY_OPTIONS))} placeholder="Frequency" />
                        <ComboInput testId="sig-timing" value={timing} onChange={setTiming} options={merge(toOpts(TIMING_OPTIONS))} placeholder="Timing" />
                        <Button type="button" size="sm" variant="outline" data-testid="sig-insert" onClick={insertSig}><Plus className="w-3.5 h-3.5 mr-1" />Insert</Button>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <Field label="Qty"><Input data-testid="sendrx-qty" value={m.quantity || ""} onChange={(e) => set("quantity", e.target.value)} /></Field>
                <Field label="Qty unit"><ComboInput testId="sendrx-qty-unit" value={m.quantity_unit} onChange={(v) => set("quantity_unit", v)} options={qtyUnitOpts} placeholder="tablet, mL…" /></Field>
                <Field label="Refills"><ComboInput testId="sendrx-refills" value={m.refills} onChange={(v) => set("refills", v)} options={merge(toOpts(REFILL_OPTIONS))} placeholder="0" /></Field>
            </div>

            <button type="button" data-testid="sendrx-more-toggle" onClick={() => set("_moreOpen", !more)} className="text-xs text-slate-500 inline-flex items-center gap-1 hover:text-slate-700">
                {more ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />} More Rx Details
            </button>

            {more && (
                <div className="border border-slate-200 rounded-sm p-3 space-y-2" data-testid="sendrx-more">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <Field label="Route"><ComboInput testId="sendrx-route" value={m.route} onChange={(v) => set("route", v)} options={routeOpts} placeholder={routeSuggested ? `Suggested: ${routeSuggested}` : "Route"} /></Field>
                        <div className="grid grid-cols-2 gap-2">
                            <Field label="Duration"><Input data-testid="sendrx-duration" value={m.duration_value || ""} onChange={(e) => set("duration_value", e.target.value)} placeholder="e.g. 7" /></Field>
                            <Field label="Unit"><ComboInput testId="sendrx-duration-unit" value={m.duration_unit} onChange={(v) => set("duration_unit", v)} options={merge(toOpts(DURATION_UNITS))} placeholder="days" /></Field>
                        </div>
                        <Field label="Concentration"><Input value={m.concentration || ""} onChange={(e) => set("concentration", e.target.value)} placeholder="e.g. 250 mg / 5 mL" /></Field>
                        {isPrn && <Field label="PRN reason"><Input data-testid="sendrx-prn" value={m.prn_reason || ""} onChange={(e) => set("prn_reason", e.target.value)} placeholder="e.g. for pain" /></Field>}
                        {isOphthalmic(m.form) && <Field label="Eye"><ComboInput testId="sendrx-eye" value={m.eye} onChange={(v) => set("eye", v)} options={merge(toOpts(EYE_SIDES))} placeholder="Right / Left / Both" /></Field>}
                        {isOtic(m.form) && <Field label="Ear"><ComboInput testId="sendrx-ear" value={m.ear} onChange={(v) => set("ear", v)} options={merge(toOpts(EAR_SIDES))} placeholder="Right / Left / Both" /></Field>}
                        {isPatch(m.form) && <Field label="Application interval"><Input value={m.interval || ""} onChange={(e) => set("interval", e.target.value)} placeholder="e.g. every 72 hours" /></Field>}
                        {isTopical(m.form) && <Field label="Body site"><Input value={m.site || ""} onChange={(e) => set("site", e.target.value)} placeholder="e.g. affected area" /></Field>}
                        {isInjectable(m.form) && <Field label="Concentration / device"><Input value={m.device || ""} onChange={(e) => set("device", e.target.value)} placeholder="e.g. prefilled pen" /></Field>}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 border-t border-slate-100 pt-2">
                        <div className="sm:col-span-3 text-[10px] uppercase tracking-wide text-slate-400">Product (optional, future Health Canada / DIN ready)</div>
                        <Field label="Brand / product"><Input value={m.brand || ""} onChange={(e) => set("brand", e.target.value)} /></Field>
                        <Field label="Generic / ingredient"><Input value={m.generic || ""} onChange={(e) => set("generic", e.target.value)} /></Field>
                        <Field label="DIN"><Input value={m.din || ""} onChange={(e) => set("din", e.target.value)} /></Field>
                        <Field label="Manufacturer"><Input value={m.manufacturer || ""} onChange={(e) => set("manufacturer", e.target.value)} /></Field>
                    </div>
                </div>
            )}

            <Field label="Additional instructions"><Input data-testid="sendrx-additional" value={m.additional_instructions || ""} onChange={(e) => set("additional_instructions", e.target.value)} /></Field>
            <Field label="Physician note (optional)"><Input value={m.note || ""} onChange={(e) => set("note", e.target.value)} /></Field>
            {m.original_text && <div className="text-[11px] text-slate-400">Original: {m.original_text}</div>}
            <div className="flex justify-end gap-2">
                <button onClick={() => removeMed(i)} data-testid="sendrx-remove-med-edit" className="text-xs text-red-600 inline-flex items-center gap-1"><Trash2 className="w-3.5 h-3.5" /> Remove</button>
                <Button size="sm" variant="outline" onClick={() => toggleEdit(i)}>Done</Button>
            </div>
        </div>
    );
};
