import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarCheck } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Label } from "../components/ui/label";

// Per-physician patient-facing booking types. Saves immediately per toggle (backend-enforced on booking).
export function BookingTypesCard() {
    const [data, setData] = useState(null);
    const [busy, setBusy] = useState(null);
    const load = async () => { try { setData((await api.get("/admin/booking-types")).data); } catch (e) { toast.error(formatErr(e)); } };
    useEffect(() => { load(); }, []);
    if (!data || data.physicians.length === 0) return null;

    const toggle = async (ph, field, key) => {
        const next = ph[field].includes(key) ? ph[field].filter((k) => k !== key) : [...ph[field], key];
        setBusy(ph.physician_user_id + key);
        try {
            await api.put(`/admin/booking-types/${ph.physician_user_id}`, { patient_booking_types: ph.patient_booking_types, caregiver_booking_types: ph.caregiver_booking_types, [field]: next });
            toast.success("Booking types saved.");
            await load();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(null); }
    };
    const Check = ({ ph, field, item }) => {
        const on = ph[field].includes(item.key);
        const id = `bt-${ph.physician_user_id}-${item.key}`;
        return (
            <label htmlFor={id} className="flex items-center gap-2 text-sm cursor-pointer select-none">
                <input id={id} type="checkbox" checked={on} disabled={busy === ph.physician_user_id + item.key} onChange={() => toggle(ph, field, item.key)}
                    data-testid={`booking-type-${item.key.toLowerCase()}`} className="h-4 w-4 accent-[#2e7d32]" />
                <span className={on ? "font-semibold text-slate-800" : "text-slate-500"}>{item.label}</span>
            </label>
        );
    };

    return (
        <div className="bg-white border border-slate-300 rounded-sm p-4 mb-4 space-y-3" data-testid="booking-types-card">
            <h2 className="font-semibold text-slate-700 flex items-center gap-2"><CalendarCheck className="w-4 h-4 text-visita-green" /> Patient booking types</h2>
            <p className="text-xs text-slate-500">What patients (and caregivers) may book online per physician. Internal calendar scheduling and existing appointments are not affected.</p>
            {data.physicians.map((ph) => (
                <div key={ph.physician_user_id} data-testid="booking-types-physician" className="border border-slate-200 rounded-sm p-3 grid grid-cols-1 sm:grid-cols-[180px_1fr_1fr] gap-3 items-start">
                    <div className="font-semibold text-sm text-slate-800">{ph.physician_name}</div>
                    <div>
                        <Label className="text-[11px] uppercase tracking-wide text-slate-500">Patient Portal</Label>
                        <div className="mt-1 space-y-1">{data.patient_types.map((it) => <Check key={it.key} ph={ph} field="patient_booking_types" item={it} />)}</div>
                    </div>
                    <div>
                        <Label className="text-[11px] uppercase tracking-wide text-slate-500">Caregiver Portal</Label>
                        <div className="mt-1 space-y-1">{data.caregiver_types.map((it) => <Check key={it.key} ph={ph} field="caregiver_booking_types" item={it} />)}</div>
                    </div>
                </div>
            ))}
        </div>
    );
}
