import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Pill, Camera, Upload, Plane, ChevronLeft, Check } from "lucide-react";
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
