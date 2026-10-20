import { useState, useMemo, useEffect } from "react";
import { createPortal } from "react-dom";
import { useLockBodyScroll } from "../hooks/useLockBodyScroll";
import { useTranslation } from "react-i18next";
import { Calendar, Check, X } from "lucide-react";
import { deriveExpiryISO, daysInMonth } from "../lib/hcDates";

// Controlled Health Card EXPIRY DATE picker. Requires a confirmed DOB. The user
// selects ONLY the expiry YEAR (current year through current year + 5); the
// month + day are derived from the patient's DOB. Feb-29 DOB on a non-leap
// expiry year clamps to Feb 28 (see deriveExpiryISO). Emits ISO "YYYY-MM-DD".
export function ExpiryPicker({ value, onChange, dob, testid = "expiry" }) {
    const { t } = useTranslation("common");
    const MON_ABBR = t("pickers.monthsAbbr", { returnObjects: true });
    const MONTHS = t("pickers.monthsFull", { returnObjects: true });
    const dispHc = (iso) => {
        if (!iso) return "";
        const [y, m, d] = String(iso).split("-").map(Number);
        if (!y || !m || !d) return "";
        return `${y} ${MON_ABBR[m - 1]} - ${String(d).padStart(2, "0")}`;
    };
    const disabled = !dob;
    const [open, setOpen] = useState(false);
    useLockBodyScroll(open);
    const [year, setYear] = useState(null);
    const [confirming, setConfirming] = useState(false);

    const years = useMemo(() => {
        const now = new Date().getFullYear();
        const arr = [];
        for (let y = now; y <= now + 5; y++) arr.push(y);
        return arr;
    }, []);

    useEffect(() => {
        if (open && value) {
            const y = Number(String(value).split("-")[0]);
            if (y) {
                setYear(y); setConfirming(true);
                const [, m, d] = String(value).split("-").map(Number);
                setExact(deriveExpiryISO(dob, y) === value ? null : { step: "day", month: m - 1, day: d });
            }
        }
    }, [open, value]);

    const derived = year ? deriveExpiryISO(dob, year) : "";
    // Exception path: the printed card does not follow the DOB month/day — pick the exact month + day.
    const [exact, setExact] = useState(null); // null | {step:"month"|"day", month}
    const exactIso = exact?.month != null && exact?.day ? `${year}-${String(exact.month + 1).padStart(2, "0")}-${String(exact.day).padStart(2, "0")}` : "";

    const finish = () => {
        onChange(exactIso || derived);
        setOpen(false);
        setConfirming(false);
        setExact(null);
    };

    return (
        <>
            <button type="button" data-testid={`${testid}-trigger`} disabled={disabled}
                onClick={() => setOpen(true)}
                className={`w-full flex items-center justify-between rounded-lg border px-3 h-11 text-left text-sm transition-colors ${disabled ? "border-slate-200 bg-slate-50 cursor-not-allowed" : "border-slate-300 bg-white hover:border-portal-blue"}`}>
                <span className={value ? "text-slate-900 font-semibold" : "text-slate-400"}>
                    {value ? dispHc(value) : (disabled ? t("pickers.selectDob") : t("pickers.selectDate"))}
                </span>
                <Calendar className={`w-4 h-4 ${disabled ? "text-slate-300" : "text-slate-400"}`} />
            </button>
            {disabled && (
                <p className="mt-1 text-xs text-slate-400" data-testid={`${testid}-dob-hint`}>{t("pickers.selectDob")}</p>
            )}

            {open && !disabled && createPortal(
                <div style={{ pointerEvents: "auto" }} className="fixed inset-0 z-[60] flex items-start sm:items-center justify-center bg-black/50 px-3 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:p-4 overscroll-contain" data-testid={`${testid}-modal`}>
                    <div className="w-full sm:max-w-md bg-white rounded-2xl shadow-xl max-h-[min(78dvh,78vh)] sm:max-h-[88vh] flex flex-col animate-fade-in">
                        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                            <h3 className="font-bold text-slate-900">{t("pickers.expiryTitle")}</h3>
                            <button type="button" data-testid={`${testid}-close`} onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700 p-1">
                                <X className="w-5 h-5" />
                            </button>
                        </div>

                        {!confirming ? (
                            <div className="overflow-y-auto p-4 flex-1">
                                <p className="text-sm text-slate-500 mb-3">{t("pickers.expiryHint")}</p>
                                <div className="grid grid-cols-3 gap-2" data-testid={`${testid}-years`}>
                                    {years.map((y) => (
                                        <button key={y} type="button" data-testid={`${testid}-year-${y}`}
                                            onClick={() => { setYear(y); setConfirming(true); }}
                                            className={`h-12 rounded-lg text-base font-semibold border transition-colors ${year === y ? "bg-portal-blue text-white border-portal-blue" : "bg-white text-slate-700 border-slate-200 hover:border-portal-blue"}`}>
                                            {y}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ) : exact && !exact.day ? (
                            <div className="overflow-y-auto p-4 flex-1" data-testid={`${testid}-exact`}>
                                <p className="text-sm text-slate-500 mb-3">{t("pickers.exactHint")} <b>{year}</b></p>
                                {exact.month == null ? (
                                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2" data-testid={`${testid}-exact-months`}>
                                        {MONTHS.map((mn, i) => (
                                            <button key={mn} type="button" data-testid={`${testid}-exact-month-${i}`} onClick={() => setExact({ step: "day", month: i })}
                                                className="h-12 rounded-lg text-base font-semibold border bg-white text-slate-700 border-slate-200 hover:border-portal-blue">{mn}</button>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="grid grid-cols-5 sm:grid-cols-7 gap-2" data-testid={`${testid}-exact-days`}>
                                        {Array.from({ length: daysInMonth(year, exact.month) }, (_, i) => i + 1).map((d) => (
                                            <button key={d} type="button" data-testid={`${testid}-exact-day-${d}`} onClick={() => setExact({ ...exact, day: d })}
                                                className="h-12 rounded-lg text-base font-semibold border bg-white text-slate-700 border-slate-200 hover:border-portal-blue">{d}</button>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="text-center py-8 px-4" data-testid={`${testid}-confirm`}>
                                <p className="text-sm text-slate-500 mb-1">{t("pickers.expiryTitle")}</p>
                                <p className="text-3xl font-extrabold text-slate-900 mb-2" data-testid={`${testid}-confirm-value`}>
                                    {exactIso ? dispHc(exactIso) : derived ? dispHc(derived) : `${year} ${MON_ABBR[0]}`}
                                </p>
                                <p className="text-xs text-slate-500 mb-5" data-testid={`${testid}-confirm-note`}>{exactIso ? t("pickers.exactNote") : t("pickers.derivedNote")}</p>
                                <div className="flex gap-3 justify-center flex-wrap">
                                    <button type="button" data-testid={`${testid}-change`} onClick={() => { setConfirming(false); setExact(null); }}
                                        className="px-5 h-11 rounded-lg border border-slate-300 font-semibold text-slate-700 hover:bg-slate-50">
                                        {t("pickers.change")}
                                    </button>
                                    <button type="button" data-testid={`${testid}-confirm-btn`} onClick={finish}
                                        className="px-5 h-11 rounded-lg bg-portal-blue hover:bg-portal-blueDark text-white font-semibold inline-flex items-center gap-2">
                                        <Check className="w-4 h-4" /> {t("pickers.confirm")}
                                    </button>
                                </div>
                                {!exactIso && (
                                    <button type="button" data-testid={`${testid}-exact-btn`} onClick={() => setExact({ step: "month", month: null })}
                                        className="mt-4 text-xs font-semibold text-portal-blueDark underline underline-offset-2">{t("pickers.exactCta")}</button>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            , document.body)}
        </>
    );
}
