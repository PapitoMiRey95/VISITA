import { useState, useMemo, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Calendar, Check, X } from "lucide-react";
import { deriveExpiryISO } from "../lib/hcDates";

// Controlled Health Card EXPIRY DATE picker. Requires a confirmed DOB. The user
// selects ONLY the expiry YEAR (current year through current year + 5); the
// month + day are derived from the patient's DOB. Feb-29 DOB on a non-leap
// expiry year clamps to Feb 28 (see deriveExpiryISO). Emits ISO "YYYY-MM-DD".
export function ExpiryPicker({ value, onChange, dob, testid = "expiry" }) {
    const { t } = useTranslation("common");
    const MON_ABBR = t("pickers.monthsAbbr", { returnObjects: true });
    const dispHc = (iso) => {
        if (!iso) return "";
        const [y, m, d] = String(iso).split("-").map(Number);
        if (!y || !m || !d) return "";
        return `${y} ${MON_ABBR[m - 1]} - ${String(d).padStart(2, "0")}`;
    };
    const disabled = !dob;
    const [open, setOpen] = useState(false);
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
            if (y) { setYear(y); setConfirming(true); }
        }
    }, [open, value]);

    const derived = year ? deriveExpiryISO(dob, year) : "";

    const finish = () => {
        onChange(derived);
        setOpen(false);
        setConfirming(false);
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

            {open && !disabled && (
                <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4" data-testid={`${testid}-modal`}>
                    <div className="w-full sm:max-w-md bg-white rounded-t-2xl sm:rounded-2xl shadow-xl max-h-[88vh] flex flex-col animate-fade-in">
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
                        ) : (
                            <div className="text-center py-8 px-4" data-testid={`${testid}-confirm`}>
                                <p className="text-sm text-slate-500 mb-1">{t("pickers.expiryTitle")}</p>
                                <p className="text-3xl font-extrabold text-slate-900 mb-6" data-testid={`${testid}-confirm-value`}>
                                    {derived ? dispHc(derived) : `${year} ${MON_ABBR[0]}`}
                                </p>
                                <div className="flex gap-3 justify-center">
                                    <button type="button" data-testid={`${testid}-change`} onClick={() => setConfirming(false)}
                                        className="px-5 h-11 rounded-lg border border-slate-300 font-semibold text-slate-700 hover:bg-slate-50">
                                        {t("pickers.change")}
                                    </button>
                                    <button type="button" data-testid={`${testid}-confirm-btn`} onClick={finish}
                                        className="px-5 h-11 rounded-lg bg-portal-blue hover:bg-portal-blueDark text-white font-semibold inline-flex items-center gap-2">
                                        <Check className="w-4 h-4" /> {t("pickers.confirm")}
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </>
    );
}
