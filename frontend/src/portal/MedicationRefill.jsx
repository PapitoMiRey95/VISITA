import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Pill, Camera, Upload, Plane, ChevronLeft, Check, Search } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { Card } from "./shared";

/**
 * Smart medication refill. Works for the signed-in patient and (with onBehalfOf)
 * for a delegate acting on behalf of a managed patient — the on_behalf_of query
 * param is always server-verified against the delegate's RX_REQUESTS grant.
 */
export default function MedicationRefill({ onBehalfOf = null, onSubmitted }) {
    const { t } = useTranslation(["requests"]);
    const params = onBehalfOf ? { on_behalf_of: onBehalfOf } : undefined;

    const medsQ = useQuery({
        queryKey: ["portal-medications", onBehalfOf || "self"],
        queryFn: async () => (await api.get("/portal/medications", { params })).data,
    });
    const meds = medsQ.data?.medications || [];
    const pharmacyLabel = medsQ.data?.pharmacy_label || "";

    const [view, setView] = useState("list"); // list | photo
    const [selected, setSelected] = useState(() => new Set());
    const [supplyMode, setSupplyMode] = useState("standard"); // standard | longer
    const [months, setMonths] = useState(1); // 1/2/3 standard, 4/5/6 longer, 0 = other
    const [otherText, setOtherText] = useState("");
    const [travelNote, setTravelNote] = useState("");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);
    const detailRef = useRef(null);

    const toggle = (id) => setSelected((prev) => {
        const next = new Set(prev);
        next.has(id) ? next.delete(id) : next.add(id);
        return next;
    });

    const pickOnly = (id) => {
        setSelected(new Set([id]));
        setTimeout(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    };

    useEffect(() => {
        // Reset supply numbers sensibly when switching modes.
        setMonths(supplyMode === "longer" ? 4 : 1);
        setOtherText("");
    }, [supplyMode]);

    const canSubmit = selected.size > 0 && !busy;

    const submitRefill = async () => {
        if (selected.size === 0) return toast.error(t("rx.selectAtLeastOne"));
        setBusy(true);
        try {
            const longer = supplyMode === "longer";
            const body = {
                medication_ids: Array.from(selected),
                supply_type: supplyMode,
                requested_months: months === 0 ? null : months,
                requested_supply_text: longer && months === 0 ? (otherText.trim() || null) : null,
                travel_note: longer ? (travelNote.trim() || null) : null,
                patient_note: note.trim() || null,
            };
            await api.post("/portal/refill-requests", body, { params });
            toast.success(t("rx.submitted"));
            setSelected(new Set());
            setSupplyMode("standard"); setMonths(1); setOtherText(""); setTravelNote(""); setNote("");
            onSubmitted && onSubmitted();
        } catch (e) {
            toast.error(formatErr(e));
        } finally {
            setBusy(false);
        }
    };

    if (medsQ.isLoading) return <p className="text-slate-400 text-sm" data-testid="medications-loading">{t("rx.loading", "Loading…")}</p>;

    if (view === "photo") {
        return <PhotoReview params={params} onBack={() => setView("list")} onSubmitted={onSubmitted} />;
    }

    return (
        <div className="space-y-5" data-testid="medication-refill">
            {/* Your Medicines — read-only */}
            <Card data-testid="your-medicines-card">
                <div className="flex items-center gap-2 mb-1">
                    <Pill className="w-5 h-5 text-emerald-500" />
                    <h2 className="font-bold text-slate-800">{t("rx.yourMedicines")}</h2>
                </div>
                <p className="text-xs text-slate-500 mb-3">{t("rx.readOnlyHint")}</p>

                {meds.length === 0 ? (
                    <p className="text-sm text-slate-500" data-testid="no-medications">{t("rx.noMeds")}</p>
                ) : (
                    <div className="space-y-2.5">
                        <p className="text-sm font-semibold text-slate-700">{t("rx.selectMeds")}</p>
                        {meds.map((m) => {
                            const on = selected.has(m.id);
                            return (
                                <button
                                    key={m.id}
                                    type="button"
                                    data-testid={`medicine-card-${m.id}`}
                                    onClick={() => toggle(m.id)}
                                    className={`w-full text-left flex items-start gap-3 p-3 rounded-xl border transition ${on ? "border-emerald-500 bg-emerald-50" : "border-slate-200 bg-white hover:border-slate-300"}`}
                                >
                                    <span className={`mt-0.5 w-5 h-5 rounded-md border flex items-center justify-center flex-shrink-0 ${on ? "bg-emerald-500 border-emerald-500" : "border-slate-300"}`}>
                                        {on && <Check className="w-3.5 h-3.5 text-white" />}
                                    </span>
                                    <span className="flex-1 min-w-0">
                                        <span className="block font-bold text-slate-800">{m.drug} {m.strength}</span>
                                        {m.directions && <span className="block text-sm text-slate-500">{m.directions}</span>}
                                        <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-700">{t("rx.active")}</span>
                                    </span>
                                    <span
                                        role="button"
                                        tabIndex={0}
                                        data-testid={`medicine-refill-${m.id}`}
                                        onClick={(e) => { e.stopPropagation(); pickOnly(m.id); }}
                                        onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); pickOnly(m.id); } }}
                                        className="text-xs font-bold text-emerald-700 underline underline-offset-2 flex-shrink-0 self-center"
                                    >
                                        {t("rx.requestRefill")}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                )}

                <button
                    type="button"
                    data-testid="med-not-listed"
                    onClick={() => setView("photo")}
                    className="mt-4 text-sm font-semibold text-portal-blue underline underline-offset-2"
                >
                    {t("rx.notListed")}
                </button>
            </Card>

            <RequestDifferentMedication params={params} onSubmitted={onSubmitted} />

            {/* Refill details appear once a medicine is selected */}
            {selected.size > 0 && (
                <Card data-testid="refill-details">
                    <div ref={detailRef} />
                    <div className="space-y-4">
                        <div>
                            <Label className="font-semibold text-slate-700">{t("rx.howMuch")}</Label>
                            <div className="flex gap-2 mt-2">
                                {[1, 2, 3].map((m) => (
                                    <Choice key={m} testid={`supply-${m}`} active={supplyMode === "standard" && months === m}
                                        onClick={() => { setSupplyMode("standard"); setMonths(m); }}>
                                        {t("rx.monthN", { count: m })}
                                    </Choice>
                                ))}
                            </div>
                            <button type="button" data-testid="supply-longer"
                                onClick={() => setSupplyMode("longer")}
                                className={`mt-2 w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border font-semibold text-sm transition ${supplyMode === "longer" ? "bg-portal-blue text-white border-portal-blue" : "bg-white text-slate-600 border-slate-200"}`}>
                                <Plane className="w-4 h-4" /> {t("rx.longer")}
                            </button>
                        </div>

                        {supplyMode === "longer" && (
                            <div className="space-y-3 rounded-xl bg-slate-50 border border-slate-200 p-3" data-testid="longer-supply-block">
                                <Label className="font-semibold text-slate-700">{t("rx.howMuchLonger")}</Label>
                                <div className="flex gap-2">
                                    {[4, 5, 6].map((m) => (
                                        <Choice key={m} testid={`supply-${m}`} active={months === m} onClick={() => setMonths(m)}>
                                            {t("rx.monthN", { count: m })}
                                        </Choice>
                                    ))}
                                    <Choice testid="supply-other" active={months === 0} onClick={() => setMonths(0)}>{t("rx.other")}</Choice>
                                </div>
                                {months === 0 && (
                                    <Input data-testid="supply-other-text" value={otherText} onChange={(e) => setOtherText(e.target.value)} placeholder={t("rx.otherPlaceholder")} />
                                )}
                                <div>
                                    <Label className="text-sm text-slate-600">{t("rx.travelNote")}</Label>
                                    <Textarea data-testid="travel-note" className="mt-1" rows={2} value={travelNote} onChange={(e) => setTravelNote(e.target.value)} />
                                </div>
                                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2">{t("rx.longerDisclaimer")}</p>
                            </div>
                        )}

                        <div className="rounded-xl bg-portal-blue/5 border border-portal-blue/20 p-3" data-testid="refill-destination">
                            <p className="text-xs font-bold uppercase tracking-wide text-portal-blueDark/70">{t("rx.sendTo")}</p>
                            <p className="text-sm font-semibold text-slate-800 mt-0.5">{pharmacyLabel}</p>
                        </div>

                        <div>
                            <Label className="font-semibold text-slate-700">{t("rx.noteLabel")}</Label>
                            <Textarea data-testid="refill-note" className="mt-1" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
                        </div>

                        <Button data-testid="refill-submit" disabled={!canSubmit} onClick={submitRefill}
                            className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                            {busy ? t("rx.submitting") : t("rx.submit")}
                        </Button>
                    </div>
                </Card>
            )}
        </div>
    );
}

function PhotoReview({ params, onBack, onSubmitted }) {
    const { t } = useTranslation(["requests"]);
    const [file, setFile] = useState(null);
    const [medName, setMedName] = useState("");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);
    const camRef = useRef(null);
    const fileRef = useRef(null);

    const submit = async () => {
        if (!file) return toast.error(t("rx.photoNeedFile"));
        setBusy(true);
        try {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("medication_name", medName.trim());
            fd.append("patient_note", note.trim());
            await api.post("/portal/prescriptions/photo", fd, { params, headers: { "Content-Type": "multipart/form-data" } });
            toast.success(t("rx.photoSubmitted"));
            onSubmitted && onSubmitted();
            onBack();
        } catch (e) {
            toast.error(formatErr(e));
        } finally {
            setBusy(false);
        }
    };

    return (
        <Card data-testid="photo-review">
            <button type="button" data-testid="photo-back" onClick={onBack} className="flex items-center gap-1 text-sm font-semibold text-slate-500 mb-3">
                <ChevronLeft className="w-4 h-4" /> {t("rx.backToList")}
            </button>
            <h2 className="font-bold text-slate-800">{t("rx.photoTitle")}</h2>
            <p className="text-sm text-slate-500 mt-1 mb-4">{t("rx.photoHint")}</p>

            <input ref={camRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} data-testid="photo-camera-input" />
            <input ref={fileRef} type="file" accept="image/*,application/pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} data-testid="photo-file-input" />

            <div className="grid grid-cols-2 gap-2">
                <Button type="button" variant="outline" data-testid="photo-take" onClick={() => camRef.current?.click()} className="h-12 rounded-xl">
                    <Camera className="w-4 h-4 mr-1.5" /> {t("rx.takePhoto")}
                </Button>
                <Button type="button" variant="outline" data-testid="photo-upload" onClick={() => fileRef.current?.click()} className="h-12 rounded-xl">
                    <Upload className="w-4 h-4 mr-1.5" /> {t("rx.uploadImage")}
                </Button>
            </div>
            {file && <p className="text-xs text-emerald-700 mt-2" data-testid="photo-filename">{t("rx.fileChosen", { name: file.name })}</p>}

            <div className="mt-4 space-y-3">
                <div>
                    <Label className="font-semibold text-slate-700">{t("rx.optionalName")}</Label>
                    <Input data-testid="photo-med-name" className="mt-1" value={medName} onChange={(e) => setMedName(e.target.value)} />
                </div>
                <div>
                    <Label className="font-semibold text-slate-700">{t("rx.noteLabel")}</Label>
                    <Textarea data-testid="photo-note" className="mt-1" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
                </div>
                <Button data-testid="photo-submit" disabled={!file || busy} onClick={submit}
                    className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                    {busy ? t("rx.submitting") : t("rx.photoSubmit")}
                </Button>
            </div>
        </Card>
    );
}

const Choice = ({ active, onClick, children, testid }) => (
    <button type="button" data-testid={testid} onClick={onClick}
        className={`flex-1 py-2.5 rounded-xl border font-semibold text-sm transition ${active ? "bg-portal-blue text-white border-portal-blue" : "bg-white text-slate-600 border-slate-200"}`}>
        {children}
    </button>
);

/**
 * Shared Smart Medication Search for Prescription Requests — used identically by a
 * patient (effectivePatient = self) and an authorized caregiver (effectivePatient =
 * managed patient, via the on_behalf_of param). Type-ahead from the first character,
 * HARD max of 5 server-enforced suggestions, generic + brand matching, patient-med
 * prioritization, and a "can't find it" manual free-text fallback whose text is
 * preserved EXACTLY and flagged for physician review.
 */
function RequestDifferentMedication({ params, onSubmitted }) {
    const { t } = useTranslation(["requests"]);
    const [term, setTerm] = useState("");
    const [results, setResults] = useState([]);
    const [open, setOpen] = useState(false);
    const [picked, setPicked] = useState(null);
    const [manual, setManual] = useState(false);
    const [manualText, setManualText] = useState("");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);
    const tRef = useRef(null);

    const runSearch = (q) => {
        setTerm(q); setPicked(null);
        if (tRef.current) clearTimeout(tRef.current);
        if (!q.trim()) { setResults([]); setOpen(false); return; }
        tRef.current = setTimeout(async () => {
            try {
                const { data } = await api.get("/portal/medication-search", { params: { ...(params || {}), q } });
                setResults((data || []).slice(0, 5));
                setOpen(true);
            } catch { setResults([]); }
        }, 180);
    };

    const choose = (r) => { setPicked(r); setTerm(r.label); setOpen(false); };

    const reset = () => { setTerm(""); setResults([]); setPicked(null); setManual(false); setManualText(""); setNote(""); };

    const submit = async () => {
        const isManual = manual;
        const name = isManual ? manualText.trim() : (picked?.label || "").trim();
        if (!name) return toast.error(isManual ? t("rx.enterMedName", "Enter the medication name.") : t("rx.pickMed", "Select a medication first."));
        setBusy(true);
        try {
            await api.post("/portal/prescription-requests", {
                medication_name: name,
                medication_entry_source: isManual ? "MANUAL" : "CATALOG",
                drug: isManual ? null : picked?.drug,
                brand: isManual ? null : picked?.brand,
                patient_note: note.trim() || null,
            }, { params });
            toast.success(t("rx.requestSubmitted", "Prescription request submitted for physician review."));
            reset();
            onSubmitted && onSubmitted();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const canSubmit = !busy && (manual ? manualText.trim().length > 0 : !!picked);

    return (
        <Card data-testid="request-different-medication">
            <div className="flex items-center gap-2 mb-1">
                <Search className="w-5 h-5 text-portal-blue" />
                <h2 className="font-bold text-slate-800">{t("rx.requestDifferentTitle", "Request a different medication")}</h2>
            </div>
            <p className="text-xs text-slate-500 mb-3">{t("rx.requestDisclaimer", "Submitting this request does not mean your prescription has been approved. Your physician will review your request.")}</p>

            {!manual && (
                <div className="relative">
                    <Label className="font-semibold text-slate-700">{t("rx.medication", "Medication")}</Label>
                    <Input
                        data-testid="med-search-input"
                        className="mt-1"
                        value={term}
                        autoComplete="off"
                        onChange={(e) => runSearch(e.target.value)}
                        onFocus={() => { if (results.length) setOpen(true); }}
                        placeholder={t("rx.medSearchPlaceholder", "Start typing a medication name…")}
                    />
                    {open && results.length > 0 && (
                        <div data-testid="med-search-results" className="absolute z-30 left-0 right-0 mt-1 bg-white border border-slate-200 rounded-xl shadow-lg overflow-hidden">
                            {results.map((r, idx) => (
                                <button
                                    key={`${r.label}-${idx}`}
                                    type="button"
                                    data-testid={`med-search-option-${idx}`}
                                    onClick={() => choose(r)}
                                    className="w-full text-left px-3 py-3 min-h-[48px] hover:bg-portal-blue/5 border-b border-slate-100 last:border-b-0 flex items-center justify-between gap-2"
                                >
                                    <span className="font-semibold text-slate-800 truncate">{r.label}</span>
                                    {r.source === "patient" && (
                                        <span className="text-[10px] font-bold uppercase bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded-full flex-shrink-0">{t("rx.yourMed", "Your med")}</span>
                                    )}
                                </button>
                            ))}
                        </div>
                    )}
                    {picked && (
                        <div data-testid="med-search-selected" className="mt-2 flex items-center justify-between bg-portal-blue/5 border border-portal-blue/20 rounded-lg px-3 py-2">
                            <span className="text-sm font-semibold text-slate-800">{picked.label}</span>
                            <button type="button" data-testid="med-search-clear" onClick={reset} className="text-xs font-semibold text-slate-500 underline">{t("rx.change", "Change")}</button>
                        </div>
                    )}
                </div>
            )}

            <label className="mt-3 flex items-center gap-2 cursor-pointer select-none" data-testid="med-cant-find-toggle">
                <input type="checkbox" checked={manual} onChange={(e) => { setManual(e.target.checked); setPicked(null); setTerm(""); setResults([]); setOpen(false); }} className="w-4 h-4" />
                <span className="text-sm font-semibold text-slate-700">{t("rx.cantFind", "I can't find my medication")}</span>
            </label>

            {manual && (
                <div className="mt-2" data-testid="med-manual-block">
                    <Label className="font-semibold text-slate-700">{t("rx.medication", "Medication name")}</Label>
                    <Input data-testid="med-manual-input" className="mt-1" value={manualText} onChange={(e) => setManualText(e.target.value)} placeholder={t("rx.manualPlaceholder", "e.g. the exact name on your bottle")} />
                    <p className="text-xs text-slate-500 mt-1">{t("rx.manualHelper", "Enter the medication name as it appears on your bottle, package, or pharmacy label.")}</p>
                </div>
            )}

            <div className="mt-3">
                <Label className="font-semibold text-slate-700">{t("rx.noteLabel")}</Label>
                <Textarea data-testid="med-request-note" className="mt-1" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>

            <Button data-testid="med-request-submit" disabled={!canSubmit} onClick={submit}
                className="mt-3 w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                {busy ? t("rx.submitting") : t("rx.submitRequest", "Submit request")}
            </Button>
        </Card>
    );
}
