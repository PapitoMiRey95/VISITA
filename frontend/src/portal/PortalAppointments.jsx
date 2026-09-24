import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { CalendarClock, CheckCircle2, AlertTriangle, Phone, X, Clock, CalendarDays, Hospital } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { usePortal, StatusPill, Card, PendingBanner } from "./shared";
import { EmergencyNotice } from "../components/EmergencyNotice";
import { ApptTypeBadge, apptTypeConfirmationLabel } from "../components/ApptTypeBadge";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { Calendar } from "../components/ui/calendar";
import { formatDate } from "../lib/date";

const isoOf = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const dateFromIso = (s) => {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
};

// Reason values are sent to the backend and MUST remain in English.
const REASON_OPTIONS = [
    "New Medical Concern", "Follow-Up", "Discuss Test Results", "Medication Review",
    "Prescription / Refill", "Bloodwork Review", "Imaging Review", "Referral Discussion",
    "Forms / Documentation", "Annual Physical", "Other",
];
const NOTE_MAX = 200;

export default function PortalAppointments() {
    const { overview, refetch } = usePortal();
    const { t } = useTranslation(["requests", "common"]);
    const nav = useNavigate();
    const p = overview.data?.patient;
    const verified = p?.verification_status === "verified";
    const hasFee = !!p?.has_outstanding_fee;
    const list = overview.data?.appointments || [];

    const slotsQ = useQuery({
        queryKey: ["slots"],
        queryFn: async () => (await api.get("/availability/slots", { params: { days: 60 } })).data,
        enabled: verified,
        staleTime: 0,                    // availability is time-sensitive — never serve stale
        refetchOnMount: "always",        // fetch current availability every time the page opens
        refetchOnWindowFocus: true,
    });
    const slots = slotsQ.data?.slots || [];

    // Group available slots by date -> only these dates are selectable.
    const { byDate, availableDates, minDate, maxDate } = useMemo(() => {
        const map = {};
        for (const s of slots) {
            (map[s.date] = map[s.date] || []).push(s);
        }
        const keys = Object.keys(map).sort();
        return {
            byDate: map,
            availableDates: new Set(keys),
            minDate: keys.length ? dateFromIso(keys[0]) : new Date(),
            maxDate: keys.length ? dateFromIso(keys[keys.length - 1]) : undefined,
        };
        // deps: only `slots` matters. dateFromIso is a stable module helper; map/keys are local.
    }, [slots]);

    const [selDate, setSelDate] = useState(null);     // Date object
    const [selSlot, setSelSlot] = useState(null);     // slot object
    const [apptType, setApptType] = useState("IN_CLINIC");     // IN_CLINIC | TELEPHONE (default In-Clinic)
    const [reason, setReason] = useState("");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);

    const [selecting, setSelecting] = useState({});
    const [reschedId, setReschedId] = useState(null);
    const [reschedPick, setReschedPick] = useState("");

    const selIso = selDate ? isoOf(selDate) : null;
    const dayTimes = selIso ? (byDate[selIso] || []) : [];

    const pickDate = (d) => {
        if (!d) return;
        setSelDate(d);
        setSelSlot(null);
        slotsQ.refetch();   // re-verify current open slots for the chosen date
    };

    const submit = async (e) => {
        e.preventDefault();
        if (!selSlot) return toast.error(t("requests:appointments.toasts.selectDateTime"));
        if (!apptType) return toast.error(t("requests:appointments.toasts.selectType"));
        if (!reason.trim()) return toast.error(t("requests:appointments.toasts.enterReason"));
        setBusy(true);
        try {
            // Re-check the slot is still open right before submitting (it may have been taken).
            const fresh = (await slotsQ.refetch()).data?.slots || [];
            const stillOpen = fresh.some((s) => s.date === selSlot.date && s.time === selSlot.time);
            if (!stillOpen) {
                setSelSlot(null);
                toast.error(t("requests:appointments.toasts.noLongerAvailable"));
                return;
            }
            await api.post("/portal/appointments", {
                reason: reason.trim(), patient_note: note || undefined,
                appointment_type: apptType,
                options: [{ date: selSlot.date, time: selSlot.time, label: selSlot.label, display: selSlot.display }],
            });
            toast.success(t("requests:appointments.toasts.requestSubmitted"));
            setSelDate(null); setSelSlot(null); setApptType("IN_CLINIC"); setReason(""); setNote("");
            refetch();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const confirmSlot = async (apptId) => {
        const index = selecting[apptId];
        if (index === undefined) return toast.error(t("requests:appointments.toasts.selectTime"));
        try {
            await api.post(`/portal/appointments/${apptId}/select`, { index });
            toast.success(t("requests:appointments.toasts.confirmed"));
            refetch();
        } catch (err) { toast.error(formatErr(err)); }
    };

    const cancelAppt = async (id) => {
        if (!window.confirm(t("requests:appointments.toasts.confirmCancel"))) return;
        try {
            await api.post(`/portal/appointments/${id}/cancel`);
            toast.success(t("requests:appointments.toasts.cancelled"));
            refetch();
        } catch (err) { toast.error(formatErr(err)); }
    };

    const submitReschedule = async (id) => {
        if (reschedPick === "") return toast.error(t("requests:appointments.toasts.chooseNewTime"));
        const slot = slots[Number(reschedPick)];
        try {
            await api.post(`/portal/appointments/${id}/reschedule`, {
                date: slot.date, time: slot.time, label: slot.label, display: slot.display,
            });
            toast.success(t("requests:appointments.toasts.rescheduled"));
            setReschedId(null); setReschedPick("");
            refetch();
        } catch (err) { toast.error(formatErr(err)); }
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">{t("requests:appointments.title")}</h1>
            <EmergencyNotice />
            {p && <PendingBanner status={p.verification_status} />}

            {hasFee && (
                <div data-testid="outstanding-fee-banner" className="bg-red-50 border border-red-200 text-red-800 rounded-xl p-4 text-sm flex gap-2">
                    <AlertTriangle className="w-5 h-5 flex-shrink-0" />
                    <div>
                        <p className="font-bold mb-1">{t("requests:appointments.feeTitle")}</p>
                        {t("requests:appointments.feeBody")}
                        <div className="mt-2">
                            <Button size="sm" variant="outline" data-testid="fee-contact-clinic" onClick={() => nav("/portal/messages")}>
                                <Phone className="w-4 h-4 mr-1" /> {t("requests:appointments.contactClinic")}
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {verified && !hasFee && (
                <Card>
                    <form onSubmit={submit} className="space-y-5" data-testid="appointment-form">
                        {/* Step 1 — Date */}
                        <div>
                            <div className="flex items-center gap-2 mb-2">
                                <span className="w-6 h-6 rounded-full bg-portal-blue text-white text-xs font-bold flex items-center justify-center">1</span>
                                <Label className="font-semibold text-slate-700">{t("requests:appointments.step1")}</Label>
                            </div>
                            <p className="text-xs text-slate-500 mb-2">{t("requests:appointments.step1Hint")}</p>
                            {slotsQ.isLoading && <p className="text-sm text-slate-400">{t("requests:appointments.loadingDates")}</p>}
                            {!slotsQ.isLoading && availableDates.size === 0 && (
                                <p className="text-sm text-amber-700">{t("requests:appointments.noDates")}</p>
                            )}
                            {availableDates.size > 0 && (
                                <div className="inline-block rounded-2xl border border-slate-200 bg-white" data-testid="appt-calendar">
                                    <Calendar
                                        mode="single"
                                        selected={selDate || undefined}
                                        onSelect={pickDate}
                                        onMonthChange={() => slotsQ.refetch()}
                                        fromDate={minDate}
                                        toDate={maxDate}
                                        defaultMonth={minDate}
                                        disabled={(d) => !availableDates.has(isoOf(d))}
                                        modifiers={{ available: (d) => availableDates.has(isoOf(d)) }}
                                        modifiersClassNames={{ available: "font-semibold text-portal-blue" }}
                                    />
                                </div>
                            )}
                        </div>

                        {/* Step 2 — Time */}
                        {selDate && (
                            <div data-testid="appt-time-section">
                                <div className="flex items-center gap-2 mb-2">
                                    <span className="w-6 h-6 rounded-full bg-portal-blue text-white text-xs font-bold flex items-center justify-center">2</span>
                                    <Label className="font-semibold text-slate-700">{t("requests:appointments.step2")}</Label>
                                </div>
                                <p className="text-xs text-slate-500 mb-2 flex items-center gap-1">
                                    <CalendarDays className="w-3.5 h-3.5" /> {formatDate(selIso)} · America/Toronto
                                </p>
                                {dayTimes.length === 0 && <p className="text-sm text-amber-700">{t("requests:appointments.noTimesLeft")}</p>}
                                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                                    {dayTimes.map((s) => {
                                        const on = selSlot && selSlot.time === s.time && selSlot.date === s.date;
                                        return (
                                            <button type="button" key={s.time} data-testid={`appt-time-${s.time}`} onClick={() => setSelSlot(s)}
                                                className={`h-10 rounded-xl border text-sm font-semibold transition-colors ${on
                                                    ? "bg-portal-blue text-white border-portal-blue"
                                                    : "bg-white text-slate-700 border-slate-200 hover:border-portal-blue"}`}>
                                                {s.label}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* Step 3 — Appointment type + Reason */}
                        {selSlot && (
                            <div data-testid="appt-reason-section">
                                <div className="flex items-center gap-2 mb-2">
                                    <span className="w-6 h-6 rounded-full bg-portal-blue text-white text-xs font-bold flex items-center justify-center">3</span>
                                    <Label className="font-semibold text-slate-700">{t("requests:appointments.appointmentType")}</Label>
                                </div>
                                <div className="grid grid-cols-2 gap-3 mb-4" data-testid="appt-type-select">
                                    {[
                                        { v: "IN_CLINIC", title: t("requests:appointments.inClinic"), Icon: Hospital, desc: t("requests:appointments.inClinicDesc") },
                                        { v: "TELEPHONE", title: t("requests:appointments.telephone"), Icon: Phone, desc: t("requests:appointments.telephoneDesc") },
                                    ].map(({ v, title, Icon, desc }) => {
                                        const on = apptType === v;
                                        return (
                                            <button type="button" key={v} data-testid={`appt-type-${v}`} onClick={() => setApptType(v)}
                                                className={`text-left rounded-xl border p-3 transition-colors ${on
                                                    ? "border-portal-blue bg-sky-50 ring-1 ring-portal-blue"
                                                    : "border-slate-200 bg-white hover:border-portal-blue"}`}>
                                                <div className="flex items-center gap-2 font-bold text-slate-800">
                                                    <Icon className="w-4 h-4 text-portal-blue" /> {title}
                                                </div>
                                                <p className="text-xs text-slate-500 mt-1">{desc}</p>
                                            </button>
                                        );
                                    })}
                                </div>

                                <div className="flex items-center gap-2 mb-2">
                                    <span className="w-6 h-6 rounded-full bg-portal-blue text-white text-xs font-bold flex items-center justify-center">4</span>
                                    <Label className="font-semibold text-slate-700">{t("requests:appointments.reasonLabel")}</Label>
                                </div>
                                <select required value={reason} onChange={(e) => setReason(e.target.value)} data-testid="appt-reason"
                                    className="w-full border border-slate-200 rounded-xl h-11 px-2 bg-white">
                                    <option value="">{t("requests:appointments.reasonPlaceholder")}</option>
                                    {REASON_OPTIONS.map((r) => <option key={r} value={r}>{t(`requests:appointments.reasons.${r}`)}</option>)}
                                </select>
                                {reason === "Other" && (
                                    <p className="text-xs text-slate-500 mt-1" data-testid="appt-other-hint">
                                        {t("requests:appointments.otherHint")}
                                    </p>
                                )}
                                <div className="mt-3">
                                    <div className="flex items-center justify-between">
                                        <Label className="font-semibold text-slate-700">{t("requests:appointments.shortNoteOptional")}</Label>
                                        <span className="text-xs text-slate-400" data-testid="appt-note-counter">{note.length} / {NOTE_MAX}</span>
                                    </div>
                                    <Textarea className="mt-1" value={note} maxLength={NOTE_MAX} data-testid="appt-note"
                                        onChange={(e) => setNote(e.target.value.slice(0, NOTE_MAX))} />
                                    <p className="text-xs text-slate-400 mt-1">
                                        {t("requests:appointments.longerMessagePre")}{" "}
                                        <button type="button" onClick={() => nav("/portal/messages")} data-testid="appt-note-messages-link"
                                            className="text-portal-blue font-semibold underline">{t("requests:appointments.messagesLink")}</button>{" "}{t("requests:appointments.longerMessagePost")}
                                    </p>
                                </div>
                            </div>
                        )}

                        {/* Step 4 — Review + Submit */}
                        {selSlot && (
                            <div className="bg-sky-50 border border-sky-200 rounded-xl p-3" data-testid="appt-review">
                                <div className="flex items-center gap-2 text-sky-900 font-bold text-sm mb-1">
                                    <Clock className="w-4 h-4" /> {t("requests:appointments.review")}
                                </div>
                                <div className="text-sm text-slate-700">
                                    <div><span className="text-slate-500">{t("requests:appointments.when")}</span> <span className="font-semibold" data-testid="appt-review-when">{formatDate(selSlot.date)} {t("requests:appointments.at")} {selSlot.label}</span></div>
                                    {apptType && <div className="mt-1"><span className="text-slate-500">{t("requests:appointments.type")}</span> <span className="font-semibold" data-testid="appt-review-type">{apptTypeConfirmationLabel(apptType)}</span></div>}
                                    {reason.trim() && <div className="mt-1"><span className="text-slate-500">{t("requests:appointments.reason")}</span> <span className="font-semibold">{t(`requests:appointments.reasons.${reason.trim()}`, reason.trim())}</span></div>}
                                </div>
                                <p className="text-xs text-slate-500 mt-2" data-testid="appt-not-confirmed-note">{t("requests:appointments.notConfirmedNote")}</p>
                            </div>
                        )}

                        <Button type="submit" disabled={busy || !selSlot || !apptType || !reason.trim()} data-testid="appt-submit"
                            className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white text-base">
                            {busy ? t("requests:appointments.submitting") : t("requests:appointments.submit")}
                        </Button>
                    </form>
                </Card>
            )}

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">{t("requests:appointments.yourRequests")}</h2>
                {list.length === 0 && <p className="text-slate-500 text-sm">{t("requests:appointments.noRequests")}</p>}
                {list.map((a) => (
                    <Card key={a.id} className="p-4" data-testid="appt-card">
                        <div className="flex justify-between items-start gap-2">
                            <div>
                                <div className="font-bold text-slate-800">{a.reason}</div>
                                <div className="text-sm text-slate-500">{a.ref_number}</div>
                                <div className="mt-1.5"><ApptTypeBadge type={a.appointment_type} /></div>
                            </div>
                            <StatusPill status={a.status} />
                        </div>

                        {(a.raw_status === "confirmed" || a.raw_status === "rescheduled") && a.confirmed_display && (
                            <div className="mt-2 space-y-2">
                                <div className="flex items-center gap-2 text-emerald-700 font-semibold text-sm">
                                    <CheckCircle2 className="w-4 h-4" /> {a.confirmed_display}
                                </div>

                                {a.can_self_modify && reschedId !== a.id && (
                                    <div className="flex gap-2" data-testid={`appt-actions-${a.id}`}>
                                        <Button size="sm" variant="outline" data-testid={`patient-reschedule-${a.id}`}
                                            onClick={() => { setReschedId(a.id); setReschedPick(""); }}>
                                            <CalendarClock className="w-4 h-4 mr-1" /> {t("requests:appointments.reschedule")}
                                        </Button>
                                        <Button size="sm" variant="outline" className="text-red-600 border-red-200"
                                            data-testid={`patient-cancel-${a.id}`} onClick={() => cancelAppt(a.id)}>
                                            <X className="w-4 h-4 mr-1" /> {t("requests:appointments.cancel")}
                                        </Button>
                                    </div>
                                )}

                                {a.can_self_modify && reschedId === a.id && (
                                    <div className="bg-sky-50 border border-sky-200 rounded-xl p-3" data-testid={`reschedule-picker-${a.id}`}>
                                        <Label className="text-xs text-slate-600">{t("requests:appointments.chooseNewTime")}</Label>
                                        <select data-testid={`reschedule-select-${a.id}`} value={reschedPick} onChange={(e) => setReschedPick(e.target.value)}
                                            className="w-full border border-slate-200 rounded-xl h-11 px-2 mt-1 bg-white">
                                            <option value="">{t("requests:appointments.selectTime")}</option>
                                            {slots.map((s, idx) => <option key={`${s.date}-${s.time}`} value={idx}>{s.display}</option>)}
                                        </select>
                                        <div className="flex gap-2 mt-2">
                                            <Button size="sm" data-testid={`reschedule-confirm-${a.id}`} onClick={() => submitReschedule(a.id)}
                                                className="bg-portal-blue hover:bg-portal-blueDark text-white">{t("requests:appointments.confirmNewTime")}</Button>
                                            <Button size="sm" variant="ghost" onClick={() => setReschedId(null)}>{t("requests:appointments.back")}</Button>
                                        </div>
                                    </div>
                                )}

                                {!a.can_self_modify && (
                                    <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-900" data-testid={`within-24h-notice-${a.id}`}>
                                        <div className="flex items-center gap-2 font-bold mb-1">
                                            <AlertTriangle className="w-4 h-4" /> {t("requests:appointments.within24Title")}
                                        </div>
                                        {t("requests:appointments.within24Body")}
                                        <div className="mt-2">
                                            <Button size="sm" variant="outline" data-testid={`contact-clinic-${a.id}`} onClick={() => nav("/portal/messages")}>
                                                <Phone className="w-4 h-4 mr-1" /> {t("requests:appointments.contactClinic")}
                                            </Button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {a.raw_status === "alternatives_offered" && (
                            <div className="mt-3 bg-sky-50 border border-sky-200 rounded-xl p-3" data-testid="offered-slots">
                                <div className="flex items-center gap-2 text-sky-800 font-bold text-sm mb-2">
                                    <CalendarClock className="w-4 h-4" /> {t("requests:appointments.selectApptTime")}
                                </div>
                                <p className="text-xs text-slate-600 mb-2">{t("requests:appointments.notAvailableChoose")}</p>
                                <div className="space-y-2">
                                    {(a.offered_slots || []).map((s, idx) => (
                                        <label key={s.display || idx} data-testid={`offer-option-${idx}`}
                                            className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer ${selecting[a.id] === idx ? "border-portal-blue bg-white" : "border-slate-200 bg-white"}`}>
                                            <input type="radio" name={`sel-${a.id}`} checked={selecting[a.id] === idx}
                                                onChange={() => setSelecting({ ...selecting, [a.id]: idx })} />
                                            <span className="font-semibold text-slate-800">{s.display}</span>
                                        </label>
                                    ))}
                                </div>
                                <Button onClick={() => confirmSlot(a.id)} data-testid={`confirm-slot-${a.id}`}
                                    className="mt-3 w-full h-11 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white">
                                    {t("requests:appointments.confirmThisTime")}
                                </Button>
                            </div>
                        )}

                        {a.staff_note && a.raw_status !== "alternatives_offered" && (
                            <div className="text-sm text-slate-600 mt-2">{t("requests:appointments.note")} {a.staff_note}</div>
                        )}
                    </Card>
                ))}
            </div>
        </div>
    );
}
