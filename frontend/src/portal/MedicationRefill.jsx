import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Pill, Camera, Upload, Plane, ChevronLeft, Check, Search, Package, Layers, Stethoscope, Phone, CalendarPlus } from "lucide-react";
import { Link } from "react-router-dom";
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
    const meds = useMemo(() => medsQ.data?.medications || [], [medsQ.data]);
    const previous = useMemo(() => medsQ.data?.previously_prescribed || [], [medsQ.data]);
    const pharmacyLabel = medsQ.data?.pharmacy_label || "";
    const clinicPhone = medsQ.data?.clinic_phone || "";

    const [view, setView] = useState("list"); // list | photo
    const [mode, setMode] = useState("selected"); // selected | all_regular | blister_pack | medication_change
    const [dueNudge, setDueNudge] = useState(null); // meds likely due but not selected (confirmation only — never auto-added)
    const [changeMedId, setChangeMedId] = useState("");
    const [selected, setSelected] = useState(() => new Set());
    const [extras, setExtras] = useState([]); // [{kind:'catalog'|'manual', label, drug, brand, text}]
    const [showPrevious, setShowPrevious] = useState(false);
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

    useEffect(() => {
        setMonths(supplyMode === "longer" ? 4 : 1);
        setOtherText("");
    }, [supplyMode]);

    const regular = useMemo(() => meds.filter((m) => m.regular), [meds]);
    const chooseMode = (m) => {
        setMode(m); setDueNudge(null);
        if (m === "all_regular" || m === "blister_pack") setSelected(new Set(regular.map((x) => x.id)));
        if (m === "medication_change") { setSelected(new Set()); setExtras([]); }
    };
    const total = selected.size + extras.length;
    const isChange = mode === "medication_change";
    const canSubmit = !busy && (isChange ? (note.trim().length > 0 || !!changeMedId) : total > 0);
    const byId = useMemo(() => Object.fromEntries([...meds, ...previous].map((m) => [m.id, m])), [meds, previous]);

    const submitRefill = async (skipNudge = false) => {
        if (!isChange && total === 0) return toast.error(t("rx.selectAtLeastOne"));
        if (!isChange && !skipNudge) {
            const missing = meds.filter((m) => m.likely_due && m.regular && !selected.has(m.id));
            if (missing.length) { setDueNudge(missing); return; }
        }
        setDueNudge(null);
        setBusy(true);
        try {
            const longer = supplyMode === "longer";
            const body = {
                request_mode: mode,
                items: [
                    ...(isChange ? (changeMedId ? [{ kind: "list", patient_medication_id: changeMedId }] : []) : Array.from(selected).map((id) => ({ kind: "list", patient_medication_id: id }))),
                    ...extras.map((x) => (x.kind === "manual" ? { kind: "manual", text: x.text } : { kind: "catalog", drug: x.drug, brand: x.brand, label: x.label })),
                ],
                supply_type: supplyMode,
                requested_months: months === 0 ? null : months,
                requested_supply_text: longer && months === 0 ? (otherText.trim() || null) : null,
                travel_note: longer ? (travelNote.trim() || null) : null,
                patient_note: note.trim() || null,
            };
            await api.post("/portal/rx-requests", body, { params });
            toast.success(isChange ? t("rx.changeSubmitted", "Medication change request sent to your doctor for review.") : t("rx.submitted"));
            setSelected(new Set()); setExtras([]); setMode("selected"); setChangeMedId("");
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

    const MedRow = ({ m, previousRow = false }) => {
        const on = selected.has(m.id);
        return (
            <button type="button" data-testid={`medicine-card-${m.id}`} onClick={() => toggle(m.id)}
                className={`w-full text-left flex items-start gap-3 p-3 rounded-xl border transition ${on ? "border-emerald-500 bg-emerald-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                <span className={`mt-0.5 w-5 h-5 rounded-md border flex items-center justify-center flex-shrink-0 ${on ? "bg-emerald-500 border-emerald-500" : "border-slate-300"}`}>
                    {on && <Check className="w-3.5 h-3.5 text-white" />}
                </span>
                <span className="flex-1 min-w-0">
                    <span className="block font-bold text-slate-800">{m.drug} {m.strength}</span>
                    {m.directions && <span className="block text-sm text-slate-500">{m.directions}</span>}
                    {!previousRow && m.due_on && <span className={`block text-xs mt-0.5 ${m.likely_due ? "text-amber-700 font-semibold" : "text-slate-400"}`} data-testid={`medicine-due-${m.id}`}>{m.likely_due ? t("rx.likelyDue", "Likely due — estimated around {{d}}", { d: m.due_on }) : t("rx.dueAround", "Covered until about {{d}}", { d: m.due_on })}</span>}
                    {previousRow
                        ? <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-slate-100 text-slate-600">{t("rx.previouslyPrescribed", "Previously prescribed through VIen")}{m.last_prescribed_at ? ` · ${String(m.last_prescribed_at).slice(0, 10)}` : ""}</span>
                        : <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-700">{t("rx.active")}</span>}
                </span>
            </button>
        );
    };

    return (
        <div className="space-y-5" data-testid="medication-refill">
            <Card data-testid="your-medicines-card">
                <div className="flex items-center gap-2 mb-1">
                    <Pill className="w-5 h-5 text-emerald-500" />
                    <h2 className="font-bold text-slate-800">{t("rx.yourMedicines")}</h2>
                </div>
                <p className="text-xs text-slate-500 mb-3">{t("rx.readOnlyHint")}</p>

                <div className="grid grid-cols-2 gap-2 mb-4" data-testid="rx-mode-chooser">
                    {[["selected", Pill, t("rx.modeSelected", "Selected medicines")], ["all_regular", Layers, t("rx.modeAllRegular", "All my regular medicines")],
                      ["blister_pack", Package, t("rx.modeBlister", "My blister pack")], ["medication_change", Stethoscope, t("rx.modeChange", "I need a medication change")]].map(([k, Icon, label]) => (
                        <button key={k} type="button" data-testid={`rx-mode-${k}`} onClick={() => chooseMode(k)}
                            className={`flex items-center gap-2 p-2.5 rounded-xl border text-left text-sm font-semibold transition ${mode === k ? "border-portal-blue bg-portal-blue/5 text-portal-blueDark" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}>
                            <Icon className="w-4 h-4 flex-shrink-0" /> <span className="leading-tight">{label}</span>
                        </button>
                    ))}
                </div>
                {(mode === "all_regular" || mode === "blister_pack") && (
                    <p className="text-xs text-portal-blueDark bg-portal-blue/5 border border-portal-blue/20 rounded-lg p-2 mb-3" data-testid="rx-mode-confirm-hint">
                        {mode === "blister_pack" ? t("rx.blisterHint", "These are the regular medicines VIen currently associates with your blister pack. Please confirm the list — untick anything that no longer belongs.") : t("rx.allRegularHint", "We pre-selected your regular medicines. Please confirm the list — untick anything you don't need.")}
                    </p>
                )}
                {isChange ? (
                    <div className="space-y-3" data-testid="medication-change-panel">
                        <p className="text-sm font-semibold text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2.5">{t("rx.changeNotice", "Medication changes require review by your doctor.")}</p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            <Button asChild variant="outline" className="h-11 rounded-xl" data-testid="change-book-appt"><Link to="/portal/appointments"><CalendarPlus className="w-4 h-4 mr-1.5" /> {t("rx.bookAppointment", "Book an appointment")}</Link></Button>
                            <Button asChild variant="outline" className="h-11 rounded-xl" disabled={!clinicPhone} data-testid="change-call-clinic"><a href={clinicPhone ? `tel:${clinicPhone.replace(/[^+\d]/g, "")}` : undefined}><Phone className="w-4 h-4 mr-1.5" /> <span className="truncate">{clinicPhone ? t("rx.callClinic", "Call the clinic · {{p}}", { p: clinicPhone }) : t("rx.callClinicNoPhone", "Call the clinic")}</span></a></Button>
                        </div>
                        <div>
                            <Label className="font-semibold text-slate-700">{t("rx.changeWhich", "Which medication does this concern? (optional)")}</Label>
                            <select data-testid="change-med-select" value={changeMedId} onChange={(e) => setChangeMedId(e.target.value)} className="mt-1 flex h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm">
                                <option value="">{t("rx.changeNotSure", "— Not sure / several —")}</option>
                                {[...meds, ...previous].map((m) => <option key={m.id} value={m.id}>{m.drug} {m.strength}</option>)}
                            </select>
                        </div>
                        <div>
                            <Label className="font-semibold text-slate-700">{t("rx.changeNote", "What would you like to change? (short note)")}</Label>
                            <Textarea data-testid="change-note" className="mt-1" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
                        </div>
                        <p className="text-xs text-slate-500">{t("rx.changeNoUpdate", "Your current medication list is not changed until your doctor actually prescribes the change.")}</p>
                        <Button data-testid="change-submit" disabled={!canSubmit} onClick={() => submitRefill(true)} className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">{busy ? t("rx.submitting") : t("rx.sendChange", "Send change request")}</Button>
                    </div>
                ) : meds.length === 0 ? (
                    <p className="text-sm text-slate-500" data-testid="no-medications">{t("rx.noMedsSelect", "We don't have any current medications on file for you yet. Use \"Find another medication\" below.")}</p>
                ) : (
                    <div className="space-y-2.5">
                        <p className="text-sm font-semibold text-slate-700">{t("rx.selectAllRenew", "Select all medicines you want renewed:")}</p>
                        {meds.map((m) => <MedRow key={m.id} m={m} />)}
                    </div>
                )}

                {previous.length > 0 && (
                    <div className="mt-4" data-testid="previously-prescribed">
                        <button type="button" data-testid="previously-toggle" onClick={() => setShowPrevious((v) => !v)}
                            className="text-sm font-semibold text-slate-600 underline underline-offset-2">
                            {showPrevious ? t("rx.hidePrevious", "Hide previously prescribed") : t("rx.showPrevious", "Previously prescribed through VIen ({{n}})", { n: previous.length })}
                        </button>
                        {showPrevious && (
                            <div className="space-y-2.5 mt-2">
                                <p className="text-xs text-slate-500">{t("rx.previousHint", "Older prescriptions issued through VIen. Select one only if you still take it — your doctor will review.")}</p>
                                {previous.map((m) => <MedRow key={m.id} m={m} previousRow />)}
                            </div>
                        )}
                    </div>
                )}
            </Card>

            {!isChange && <FindAnotherMedication params={params} extras={extras} setExtras={setExtras} onPhoto={() => setView("photo")} />}

            {!isChange && total > 0 && (
                <Card data-testid="refill-details">
                    <div ref={detailRef} />
                    <div className="space-y-4">
                        <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-3" data-testid="refill-summary">
                            <p className="text-xs font-bold uppercase tracking-wide text-emerald-700">{t("rx.requesting", "Requesting ({{n}})", { n: total })} · {mode === "blister_pack" ? t("rx.modeBlister", "My blister pack") : mode === "all_regular" ? t("rx.modeAllRegular", "All my regular medicines") : t("rx.modeSelected", "Selected medicines")}</p>
                            <ul className="mt-1 text-sm text-slate-800 space-y-0.5">
                                {Array.from(selected).map((id) => byId[id] && <li key={id} data-testid="summary-item">{byId[id].drug} {byId[id].strength}</li>)}
                                {extras.map((x, i) => <li key={`x${i}`} data-testid="summary-item">{x.kind === "manual" ? x.text : x.label}{x.kind === "manual" && <span className="ml-1 text-[10px] font-bold uppercase text-amber-700">{t("rx.manualFlag", "manual entry")}</span>}</li>)}
                            </ul>
                        </div>
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

                        {dueNudge && (
                            <div className="rounded-xl bg-amber-50 border border-amber-300 p-3 space-y-2" data-testid="due-nudge">
                                {dueNudge.map((m) => <p key={m.id} className="text-sm font-semibold text-amber-900">{t("rx.dueNudge", "You may also be due for {{m}}. Did you mean to include it?", { m: `${m.drug} ${m.strength}` })}</p>)}
                                <div className="flex gap-2">
                                    <Button type="button" size="sm" data-testid="due-nudge-add" onClick={() => { setSelected((prev) => new Set([...prev, ...dueNudge.map((m) => m.id)])); setDueNudge(null); }} className="rounded-xl bg-portal-blue text-white">{t("rx.dueAdd", "Yes, include it")}</Button>
                                    <Button type="button" size="sm" variant="outline" data-testid="due-nudge-skip" onClick={() => submitRefill(true)} className="rounded-xl">{t("rx.dueSkip", "No, continue without it")}</Button>
                                </div>
                            </div>
                        )}
                        <Button data-testid="refill-submit" disabled={!canSubmit} onClick={() => submitRefill(false)}
                            className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                            {busy ? t("rx.submitting") : t("rx.requestSelected", "Request selected refills ({{n}})", { n: total })}
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
 * Find another medication — catalog SEARCH/SELECT first (max 5 server-enforced suggestions), cart-style so several
 * different medicines can be added to the SAME request. "I can't find my medication" is the last resort: free text is
 * preserved exactly and flagged MANUAL ENTRY — REVIEW REQUIRED internally. Patient text never enters the catalog.
 */
function FindAnotherMedication({ params, extras, setExtras, onPhoto }) {
    const { t } = useTranslation(["requests"]);
    const [openSearch, setOpenSearch] = useState(false);
    const [term, setTerm] = useState("");
    const [results, setResults] = useState([]);
    const [open, setOpen] = useState(false);
    const [manual, setManual] = useState(false);
    const [manualText, setManualText] = useState("");
    const tRef = useRef(null);

    const runSearch = (q) => {
        setTerm(q);
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

    const addCatalog = (r) => {
        if (!extras.some((x) => x.kind === "catalog" && x.label === r.label)) setExtras([...extras, { kind: "catalog", label: r.label, drug: r.drug, brand: r.brand }]);
        setTerm(""); setResults([]); setOpen(false);
    };
    const addManual = () => {
        const text = manualText.trim();
        if (!text) return toast.error(t("rx.enterMedName", "Enter the medication name."));
        setExtras([...extras, { kind: "manual", text }]);
        setManualText(""); setManual(false);
    };
    const remove = (i) => setExtras(extras.filter((_, idx) => idx !== i));

    return (
        <Card data-testid="find-another-medication">
            <div className="flex items-center gap-2 mb-1">
                <Search className="w-5 h-5 text-portal-blue" />
                <h2 className="font-bold text-slate-800">{t("rx.cantFindTitle", "Can't find the medicine you need?")}</h2>
            </div>
            <p className="text-xs text-slate-500 mb-3">{t("rx.requestDisclaimer", "Submitting this request does not mean your prescription has been approved. Your physician will review your request.")}</p>

            {extras.length > 0 && (
                <ul className="space-y-1.5 mb-3" data-testid="extra-medications">
                    {extras.map((x, i) => (
                        <li key={i} data-testid={`extra-med-${i}`} className="flex items-center justify-between bg-portal-blue/5 border border-portal-blue/20 rounded-lg px-3 py-2">
                            <span className="text-sm font-semibold text-slate-800">{x.kind === "manual" ? x.text : x.label}
                                {x.kind === "manual" && <span className="ml-2 text-[10px] font-bold uppercase bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded-full">{t("rx.manualFlag", "manual entry")}</span>}</span>
                            <button type="button" data-testid={`extra-med-remove-${i}`} onClick={() => remove(i)} className="text-xs font-semibold text-slate-500 underline">{t("rx.remove", "Remove")}</button>
                        </li>
                    ))}
                </ul>
            )}

            {!openSearch ? (
                <Button type="button" variant="outline" data-testid="find-another-btn" onClick={() => setOpenSearch(true)} className="h-11 rounded-xl w-full">
                    <Search className="w-4 h-4 mr-1.5" /> {extras.length ? t("rx.addAnother", "Add another medication") : t("rx.findAnother", "Find another medication")}
                </Button>
            ) : (
                <div className="space-y-3">
                    {!manual && (
                        <div className="relative">
                            <Label className="font-semibold text-slate-700">{t("rx.medication", "Medication")}</Label>
                            <Input data-testid="med-search-input" className="mt-1" value={term} autoComplete="off"
                                onChange={(e) => runSearch(e.target.value)} onFocus={() => { if (results.length) setOpen(true); }}
                                placeholder={t("rx.medSearchPlaceholder", "Start typing a medication name…")} />
                            {open && results.length > 0 && (
                                <div data-testid="med-search-results" className="absolute z-30 left-0 right-0 mt-1 bg-white border border-slate-200 rounded-xl shadow-lg overflow-hidden">
                                    {results.map((r, idx) => (
                                        <button key={`${r.label}-${idx}`} type="button" data-testid={`med-search-option-${idx}`} onClick={() => addCatalog(r)}
                                            className="w-full text-left px-3 py-3 min-h-[48px] hover:bg-portal-blue/5 border-b border-slate-100 last:border-b-0 flex items-center justify-between gap-2">
                                            <span className="font-semibold text-slate-800 truncate">{r.label}</span>
                                            {r.source === "patient" && <span className="text-[10px] font-bold uppercase bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded-full flex-shrink-0">{t("rx.yourMed", "Your med")}</span>}
                                        </button>
                                    ))}
                                </div>
                            )}
                            <p className="text-xs text-slate-500 mt-1">{t("rx.searchHint", "Type a few letters and pick the medication from the list to add it to your request.")}</p>
                        </div>
                    )}

                    <label className="flex items-center gap-2 cursor-pointer select-none" data-testid="med-cant-find-toggle">
                        <input type="checkbox" checked={manual} onChange={(e) => { setManual(e.target.checked); setTerm(""); setResults([]); setOpen(false); }} className="w-4 h-4" />
                        <span className="text-sm font-semibold text-slate-700">{t("rx.cantFind", "I can't find my medication")}</span>
                    </label>

                    {manual && (
                        <div data-testid="med-manual-block">
                            <Label className="font-semibold text-slate-700">{t("rx.medication", "Medication name")}</Label>
                            <Input data-testid="med-manual-input" className="mt-1" value={manualText} onChange={(e) => setManualText(e.target.value)} placeholder={t("rx.manualPlaceholder", "e.g. the exact name on your bottle")} />
                            <p className="text-xs text-slate-500 mt-1">{t("rx.manualHelper", "Enter the medication name as it appears on your bottle, package, or pharmacy label.")}</p>
                            <Button type="button" data-testid="med-manual-add" disabled={!manualText.trim()} onClick={addManual} className="mt-2 h-10 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white">{t("rx.addToRequest", "Add to request")}</Button>
                        </div>
                    )}

                    <button type="button" data-testid="med-not-listed" onClick={onPhoto} className="text-sm font-semibold text-portal-blue underline underline-offset-2">
                        {t("rx.photoInstead", "Or send a photo of the label instead")}
                    </button>
                </div>
            )}
        </Card>
    );
}
