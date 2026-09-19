import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Plus, X, Ban } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

const SETTING_FIELDS = [
    ["clinic_name", "Clinic name"],
    ["physician_name", "Physician name"],
    ["clinic_phone", "Clinic phone"],
    ["clinic_address", "Clinic address"],
    ["office_hours", "Office hours"],
];

const TEMPLATE_FIELDS = [
    ["smart_routing_intro", "Smart routing intro"],
    ["referral_delay", "Referral delay / neutral message"],
    ["new_referral_notice", "New referral notice"],
    ["appointment_required", "Appointment required message"],
    ["prescription_received", "Prescription received message"],
    ["emergency_notice", "Emergency notice"],
    ["portal_disclaimer", "Portal disclaimer"],
];

const DAYS = [["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"], ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"]];

const to12 = (t) => {
    if (!t) return "";
    const [h, m] = String(t).split(":").map(Number);
    const ap = h < 12 ? "AM" : "PM";
    return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${ap}`;
};

export default function Settings() {
    const [settings, setSettings] = useState({});
    const [templates, setTemplates] = useState({});
    const [avail, setAvail] = useState(null);
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        const [s, a] = await Promise.all([api.get("/admin/settings"), api.get("/admin/availability")]);
        setSettings(s.data.settings || {});
        setTemplates(s.data.templates || {});
        setAvail(a.data || {});
    }, []);

    useEffect(() => { load(); }, [load]);

    const save = async () => {
        setBusy(true);
        try {
            await api.put("/admin/settings", { settings, templates });
            await api.put("/admin/availability", avail);
            toast.success("Settings saved.");
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const setDay = (key, field, value) =>
        setAvail((a) => ({ ...a, days: { ...a.days, [key]: { ...a.days[key], [field]: value } } }));
    const addRow = (listKey, row) => setAvail((a) => ({ ...a, [listKey]: [...(a[listKey] || []), row] }));
    const rmRow = (listKey, idx) => setAvail((a) => ({ ...a, [listKey]: a[listKey].filter((_, i) => i !== idx) }));
    const setRow = (listKey, idx, field, value) =>
        setAvail((a) => ({ ...a, [listKey]: a[listKey].map((r, i) => (i === idx ? { ...r, [field]: value } : r)) }));

    const reloadAvail = async () => {
        const a = await api.get("/admin/availability");
        setAvail(a.data || {});
    };
    const unblockDay = async (date) => {
        try {
            await api.post("/internal/calendar/unblock-day", { date });
            toast.success(`Day unblocked — ${formatDate(date)}.`);
            await reloadAvail();
        } catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="animate-fade-in max-w-3xl">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Clinic Settings, Availability & Templates</h1>
            <p className="text-sm text-slate-500 mb-4">Configure clinic info, physician availability, and default patient-facing messages.</p>

            <div className="bg-white border border-slate-300 rounded-sm p-4 mb-4 space-y-3">
                <h2 className="font-semibold text-slate-700">Clinic information</h2>
                {SETTING_FIELDS.map(([k, label]) => (
                    <div key={k}>
                        <Label className="text-xs">{label}</Label>
                        <Input value={settings[k] || ""} onChange={(e) => setSettings({ ...settings, [k]: e.target.value })} data-testid={`setting-${k}`} />
                    </div>
                ))}
            </div>

            {avail && (() => {
                const bp = avail.blocked_periods || [];
                const blockedDates = [...new Set(bp.filter((b) => b.block_day).map((b) => b.date))].sort();
                return (
                <div className="bg-white border border-slate-300 rounded-sm p-4 mb-4 space-y-4" data-testid="availability-card">
                    <h2 className="font-semibold text-slate-700">Physician Availability ({avail.timezone || "America/Toronto"})</h2>

                    <div>
                        <Label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Weekly availability</Label>
                        <div className="flex items-center gap-2 mt-1 mb-2">
                            <Label className="text-xs">Appointment duration (min)</Label>
                            <Input type="number" className="w-24 h-8" value={avail.appointment_duration || 30}
                                onChange={(e) => setAvail({ ...avail, appointment_duration: Number(e.target.value) })} data-testid="avail-duration" />
                        </div>
                        <div className="space-y-1">
                            {DAYS.map(([key, label]) => {
                                const d = avail.days?.[key] || {};
                                return (
                                    <div key={key} className="flex items-center gap-2 text-sm" data-testid={`avail-day-${key}`}>
                                        <label className="flex items-center gap-1.5 w-32">
                                            <input type="checkbox" checked={!!d.enabled} onChange={(e) => setDay(key, "enabled", e.target.checked)} data-testid={`avail-${key}-enabled`} />
                                            <span className={d.enabled ? "font-semibold text-slate-800" : "text-slate-400"}>{label}</span>
                                        </label>
                                        <Input type="time" className="h-8 w-32" value={d.start || "11:30"} disabled={!d.enabled} onChange={(e) => setDay(key, "start", e.target.value)} />
                                        <span className="text-slate-400">to</span>
                                        <Input type="time" className="h-8 w-32" value={d.end || "16:30"} disabled={!d.enabled} onChange={(e) => setDay(key, "end", e.target.value)} />
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    <div data-testid="daily-break-section">
                        <Label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Daily break</Label>
                        <div className="flex items-center gap-3 text-sm bg-slate-50 border border-slate-200 rounded-sm px-2 py-1 mt-1" data-testid="daily-break-row">
                            <span className="font-semibold text-slate-800 w-40">Mon–Thu</span>
                            <span className="text-slate-600">{to12(avail.break_start)}–{to12(avail.break_end)}</span>
                        </div>
                        <p className="text-[11px] text-slate-400 mt-1">Recurring — patients are never offered this time.</p>
                    </div>

                    <div data-testid="blocked-days-section">
                        <Label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Blocked days</Label>
                        <div className="space-y-1 mt-1">
                            {blockedDates.length === 0 && <p className="text-xs text-slate-400">No fully-blocked days. Use "Block Day" on the Calendar.</p>}
                            {blockedDates.map((date) => (
                                <div key={date} className="flex items-center gap-2 text-sm bg-red-50 border border-red-200 rounded-sm px-2 py-1" data-testid={`blocked-day-${date}`}>
                                    <Ban className="w-3.5 h-3.5 text-red-500" />
                                    <span className="font-semibold text-slate-800 w-40">{formatDate(date)}</span>
                                    <span className="text-xs text-red-700 flex-1">Day Blocked</span>
                                    <Button size="sm" variant="outline" className="h-7 text-xs" data-testid={`unblock-day-${date}`} onClick={() => unblockDay(date)}>Unblock</Button>
                                </div>
                            ))}
                        </div>
                    </div>

                    <ListEditor title="Vacations (date ranges)" listKey="vacations" rows={avail.vacations || []}
                        cols={[["start", "date"], ["end", "date"], ["reason", "text"]]} add={() => addRow("vacations", { start: "", end: "", reason: "" })} rm={rmRow} set={setRow} testid="vacations" />
                    <ListEditor title="Closures (single dates)" listKey="closures" rows={avail.closures || []}
                        cols={[["date", "date"], ["reason", "text"]]} add={() => addRow("closures", { date: "", reason: "" })} rm={rmRow} set={setRow} testid="closures" />
                </div>
                );
            })()}

            <div className="bg-white border border-slate-300 rounded-sm p-4 mb-4 space-y-3">
                <h2 className="font-semibold text-slate-700">Message templates</h2>
                {TEMPLATE_FIELDS.map(([k, label]) => (
                    <div key={k}>
                        <Label className="text-xs">{label}</Label>
                        <Textarea rows={2} value={templates[k] || ""} onChange={(e) => setTemplates({ ...templates, [k]: e.target.value })} data-testid={`template-${k}`} />
                    </div>
                ))}
            </div>

            <Button onClick={save} disabled={busy} data-testid="settings-save" className="bg-visita-green hover:bg-visita-greenDark text-white">
                {busy ? "Saving…" : "Save All Settings"}
            </Button>
        </div>
    );
}

function ListEditor({ title, listKey, rows, cols, add, rm, set, testid }) {
    return (
        <div>
            <div className="flex items-center justify-between">
                <Label className="text-xs">{title}</Label>
                <button onClick={add} data-testid={`add-${testid}`} className="text-xs text-visita-green flex items-center gap-1"><Plus className="w-3 h-3" /> Add</button>
            </div>
            <div className="space-y-1 mt-1">
                {rows.map((r, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                        {cols.map(([field, type]) => (
                            <Input key={field} type={type} placeholder={field} className="h-8 text-xs" value={r[field] || ""} onChange={(e) => set(listKey, i, field, e.target.value)} />
                        ))}
                        <button onClick={() => rm(listKey, i)} className="text-slate-400 hover:text-red-500"><X className="w-4 h-4" /></button>
                    </div>
                ))}
            </div>
        </div>
    );
}
