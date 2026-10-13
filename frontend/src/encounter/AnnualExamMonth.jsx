import { useEffect, useState } from "react";
import { Apple, Pencil } from "lucide-react";
import { api, formatErr } from "../lib/api";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/* Visit New — 🍎 Annual Physical Exam month. Canonical on patient_directory; physician edits are audited.
   Never auto-set from the visit date. */
export function AnnualExamMonth({ patientRef, canEdit }) {
    const [data, setData] = useState(null);
    const [editing, setEditing] = useState(false);
    const [err, setErr] = useState("");

    useEffect(() => {
        if (!patientRef) return;
        api.get(`/internal/patients/${patientRef}/annual-exam-month`).then(({ data: d }) => setData(d)).catch(() => setData(null));
    }, [patientRef]);

    const save = async (value) => {
        setErr("");
        try {
            const { data: d } = await api.put(`/internal/patients/${patientRef}/annual-exam-month`, { annual_exam_month: value || null });
            setData(d); setEditing(false);
        } catch (e) { setErr(formatErr(e)); }
    };

    if (!data) return null;
    const month = data.annual_exam_month;
    return (
        <div className="px-2 py-1 border-t border-slate-200 flex items-center gap-1.5 text-xs" data-testid="annual-exam-month">
            <Apple className="w-3.5 h-3.5 text-red-600 shrink-0" aria-hidden="true" />
            <span className="font-bold uppercase tracking-wide text-[10px] text-slate-500">Annual:</span>
            {editing ? (
                <select autoFocus defaultValue={month || ""} onChange={(e) => save(e.target.value)} onBlur={() => setEditing(false)} data-testid="annual-exam-month-select"
                    className="h-6 text-xs rounded-sm border border-slate-300 bg-white px-1 focus:outline-none focus:ring-2 focus:ring-cyan-500">
                    <option value="">—</option>
                    {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
            ) : (
                <span className={`font-semibold ${month ? "text-slate-900" : "text-slate-400"}`} data-testid="annual-exam-month-value">{month || "—"}</span>
            )}
            {canEdit && data.editable && !editing && (
                <button type="button" onClick={() => setEditing(true)} aria-label="Edit annual exam month" data-testid="annual-exam-month-edit"
                    className="ml-auto text-slate-400 hover:text-visita-ribbon"><Pencil className="w-3 h-3" /></button>
            )}
            {err && <span className="text-[10px] text-red-700" data-testid="annual-exam-month-error">{err}</span>}
        </div>
    );
}
