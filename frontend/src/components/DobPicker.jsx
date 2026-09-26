import { useState, useMemo, useEffect } from "react";
import { Calendar, ChevronLeft, Check, X } from "lucide-react";

// Controlled, mobile-first Date of Birth picker. Enforces Year -> Month -> Day
// -> Confirm order, ages MIN_AGE..MAX_AGE inclusive, and emits an ISO
// "YYYY-MM-DD" string (stored format unchanged). Display uses VIsita standard
// "YYYY Mon - DD". No native mobile date spinner is used.
const MIN_AGE = 17;
const MAX_AGE = 99;
const MONTHS = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];
const MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function daysInMonth(year, month0) {
    return new Date(year, month0 + 1, 0).getDate(); // handles leap years
}

function displayDob(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-").map(Number);
    if (!y || !m || !d) return "";
    return `${y} ${MON_ABBR[m - 1]} - ${String(d).padStart(2, "0")}`;
}

export function DobPicker({ value, onChange, testid = "dob" }) {
    const today = useMemo(() => new Date(), []);
    // Valid DOB range for ages MIN_AGE..MAX_AGE inclusive.
    const maxYear = today.getFullYear() - MIN_AGE;      // youngest allowed birth year
    const minYear = today.getFullYear() - MAX_AGE - 1;  // oldest allowed birth year (edge handled by day check)

    const [open, setOpen] = useState(false);
    const [stepIdx, setStepIdx] = useState(0); // 0=year 1=month 2=day 3=confirm
    const [year, setYear] = useState(null);
    const [month, setMonth] = useState(null); // 0-based
    const [day, setDay] = useState(null);

    // Preload from existing value when opening.
    useEffect(() => {
        if (open && value) {
            const [y, m, d] = value.split("-").map(Number);
            if (y) { setYear(y); setMonth(m - 1); setDay(d); }
        }
    }, [open, value]);

    const years = useMemo(() => {
        const arr = [];
        for (let y = maxYear; y >= minYear; y--) arr.push(y);
        return arr;
    }, [maxYear, minYear]);

    // A DOB is only valid if the resulting age is within range for the exact month/day.
    const ageOf = (y, m0, d) => {
        const t = today;
        let age = t.getFullYear() - y;
        if (t.getMonth() < m0 || (t.getMonth() === m0 && t.getDate() < d)) age -= 1;
        return age;
    };

    const finish = () => {
        const iso = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
        onChange(iso);
        setOpen(false);
        setStepIdx(0);
    };

    const reset = () => { setStepIdx(0); };
    const back = () => setStepIdx((s) => Math.max(0, s - 1));

    const dayCount = year != null && month != null ? daysInMonth(year, month) : 31;
    const days = Array.from({ length: dayCount }, (_, i) => i + 1);

    const StepDot = ({ i, label }) => (
        <div className="flex items-center gap-1.5">
            <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${stepIdx >= i ? "bg-portal-blue text-white" : "bg-slate-200 text-slate-500"}`}>{i + 1}</span>
            <span className={`text-xs font-semibold ${stepIdx >= i ? "text-portal-blueDark" : "text-slate-400"}`}>{label}</span>
        </div>
    );

    return (
        <>
            <button type="button" data-testid={`${testid}-trigger`} onClick={() => setOpen(true)}
                className="w-full flex items-center justify-between rounded-lg border border-slate-300 bg-white px-3 h-11 text-left text-sm hover:border-portal-blue transition-colors">
                <span className={value ? "text-slate-900 font-semibold" : "text-slate-400"}>
                    {value ? displayDob(value) : "Select date of birth"}
                </span>
                <Calendar className="w-4 h-4 text-slate-400" />
            </button>

            {open && (
                <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4" data-testid={`${testid}-modal`}>
                    <div className="w-full sm:max-w-md bg-white rounded-t-2xl sm:rounded-2xl shadow-xl max-h-[88vh] flex flex-col animate-fade-in">
                        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                            <div className="flex items-center gap-2">
                                {stepIdx > 0 && (
                                    <button type="button" data-testid={`${testid}-back`} onClick={back} className="text-slate-500 hover:text-portal-blueDark p-1 -ml-1">
                                        <ChevronLeft className="w-5 h-5" />
                                    </button>
                                )}
                                <h3 className="font-bold text-slate-900">Date of Birth</h3>
                            </div>
                            <button type="button" data-testid={`${testid}-close`} onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700 p-1">
                                <X className="w-5 h-5" />
                            </button>
                        </div>

                        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-100 overflow-x-auto">
                            <StepDot i={0} label="Year" /><span className="text-slate-300">›</span>
                            <StepDot i={1} label="Month" /><span className="text-slate-300">›</span>
                            <StepDot i={2} label="Day" />
                        </div>

                        <div className="overflow-y-auto p-4 flex-1">
                            {stepIdx === 0 && (
                                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2" data-testid={`${testid}-years`}>
                                    {years.map((y) => (
                                        <button key={y} type="button" data-testid={`${testid}-year-${y}`}
                                            onClick={() => { setYear(y); setDay(null); setStepIdx(1); }}
                                            className={`h-12 rounded-lg text-base font-semibold border transition-colors ${year === y ? "bg-portal-blue text-white border-portal-blue" : "bg-white text-slate-700 border-slate-200 hover:border-portal-blue"}`}>
                                            {y}
                                        </button>
                                    ))}
                                </div>
                            )}
                            {stepIdx === 1 && (
                                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2" data-testid={`${testid}-months`}>
                                    {MONTHS.map((mn, i) => (
                                        <button key={mn} type="button" data-testid={`${testid}-month-${i}`}
                                            onClick={() => { setMonth(i); setDay(null); setStepIdx(2); }}
                                            className={`h-12 rounded-lg text-base font-semibold border transition-colors ${month === i ? "bg-portal-blue text-white border-portal-blue" : "bg-white text-slate-700 border-slate-200 hover:border-portal-blue"}`}>
                                            {mn}
                                        </button>
                                    ))}
                                </div>
                            )}
                            {stepIdx === 2 && (
                                <div className="grid grid-cols-5 sm:grid-cols-7 gap-2" data-testid={`${testid}-days`}>
                                    {days.map((d) => {
                                        const invalid = ageOf(year, month, d) < MIN_AGE || ageOf(year, month, d) > MAX_AGE;
                                        return (
                                            <button key={d} type="button" disabled={invalid} data-testid={`${testid}-day-${d}`}
                                                onClick={() => { setDay(d); setStepIdx(3); }}
                                                className={`h-12 rounded-lg text-base font-semibold border transition-colors ${day === d ? "bg-portal-blue text-white border-portal-blue" : invalid ? "bg-slate-50 text-slate-300 border-slate-100 cursor-not-allowed" : "bg-white text-slate-700 border-slate-200 hover:border-portal-blue"}`}>
                                                {d}
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                            {stepIdx === 3 && (
                                <div className="text-center py-6" data-testid={`${testid}-confirm`}>
                                    <p className="text-sm text-slate-500 mb-1">Date of Birth</p>
                                    <p className="text-3xl font-extrabold text-slate-900 mb-6" data-testid={`${testid}-confirm-value`}>
                                        {year} {MON_ABBR[month]} - {String(day).padStart(2, "0")}
                                    </p>
                                    <div className="flex gap-3 justify-center">
                                        <button type="button" data-testid={`${testid}-change`} onClick={reset}
                                            className="px-5 h-11 rounded-lg border border-slate-300 font-semibold text-slate-700 hover:bg-slate-50">
                                            Change
                                        </button>
                                        <button type="button" data-testid={`${testid}-confirm-btn`} onClick={finish}
                                            className="px-5 h-11 rounded-lg bg-portal-blue hover:bg-portal-blueDark text-white font-semibold inline-flex items-center gap-2">
                                            <Check className="w-4 h-4" /> Confirm
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
