import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import { Plus, X, Ban, ChevronDown, ChevronRight } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { DEFAULT_SERVICE_CATALOG, SERVICE_CATEGORIES, CLASSIFICATIONS, applyOmaCatalog } from "../lib/billing";
import { useUnsavedGuard } from "./unsavedGuard";

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
    const [billingOpen, setBillingOpen] = useState(false);
    const baselineRef = useRef("");
    const { setGuard } = useUnsavedGuard();

    const load = useCallback(async () => {
        const [s, a] = await Promise.all([api.get("/admin/settings"), api.get("/admin/availability")]);
        const nextSettings = s.data.settings || {};
        const nextTemplates = s.data.templates || {};
        const nextAvail = a.data || {};
        setSettings(nextSettings);
        setTemplates(nextTemplates);
        setAvail(nextAvail);
        baselineRef.current = JSON.stringify({ settings: nextSettings, templates: nextTemplates, avail: nextAvail });
        // deps empty: api is a stable import; s/a are local; setters are stable.
    }, []);

    useEffect(() => { load(); }, [load]);

    const save = useCallback(async () => {
        setBusy(true);
        try {
            await api.put("/admin/settings", { settings, templates });
            await api.put("/admin/availability", avail);
            baselineRef.current = JSON.stringify({ settings, templates, avail });
            toast.success("Settings saved.");
            return true;
        } catch (e) { toast.error(formatErr(e)); return false; } finally { setBusy(false); }
    }, [settings, templates, avail]);

    const dirty = avail !== null && JSON.stringify({ settings, templates, avail }) !== baselineRef.current;

    useEffect(() => {
        setGuard({ dirty, save });
        return () => setGuard({ dirty: false, save: null });
    }, [dirty, save, setGuard]);

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
            </div>

            <div className="bg-white border border-slate-300 rounded-sm p-4 mb-4 space-y-3" data-testid="direct-billing-card">
                <button type="button" data-testid="db-toggle" onClick={() => setBillingOpen((o) => !o)}
                    className="w-full flex items-center justify-between text-left">
                    <h2 className="font-semibold text-slate-700">Direct 3rd Party Billing</h2>
                    {billingOpen ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
                </button>
                {billingOpen && (<>
                <div className="max-w-xs">
                    <Label className="text-xs">Time-based hourly rate (CAD)</Label>
                    <Input type="number" min="0" step="0.01" data-testid="db-hourly-rate"
                        value={settings.direct_billing_hourly_rate ?? ""}
                        onChange={(e) => setSettings({ ...settings, direct_billing_hourly_rate: e.target.value === "" ? null : Number(e.target.value) })} />
                    <p className="text-[11px] text-slate-400 mt-1">Used for new time-based bills. Existing invoices keep the rate snapshotted at creation.</p>
                </div>
                <div>
                    <div className="flex items-center justify-between">
                        <Label className="text-xs">Predefined services (Set Service billing)</Label>
                        <div className="flex items-center gap-3">
                            <button type="button" data-testid="db-load-catalog"
                                onClick={() => setSettings((s) => {
                                    const existing = new Set((s.direct_billing_services || []).map((r) => r.code));
                                    const additions = DEFAULT_SERVICE_CATALOG.filter((r) => !existing.has(r.code)).map((r) => ({ ...r }));
                                    return { ...s, direct_billing_services: [...(s.direct_billing_services || []), ...additions] };
                                })}
                                className="text-xs text-visita-greenDark font-semibold hover:underline">Load default catalogue</button>
                            <button type="button" data-testid="db-apply-oma"
                                onClick={() => setSettings((s) => ({ ...s, direct_billing_services: applyOmaCatalog(s.direct_billing_services || []) }))}
                                className="text-xs text-sky-700 font-semibold hover:underline">Apply OMA 2026 fees</button>
                            <button type="button" data-testid="db-add-service"
                                onClick={() => setSettings((s) => ({ ...s, direct_billing_services: [...(s.direct_billing_services || []), { code: `CUSTOM_${Date.now()}`, category: "OTHER", description: "", amount: "", billing_classification: "PATIENT_THIRD_PARTY_BILLABLE", active: true, note: "" }] }))}
                                className="text-xs text-visita-green flex items-center gap-1"><Plus className="w-3 h-3" /> Add</button>
                        </div>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1">Amounts are not preset — set a fee per service. "No Charge" services stay visible for reference but cannot generate an invoice.</p>
                    <div className="space-y-1.5 mt-2">
                        {(settings.direct_billing_services || []).length === 0 && <p className="text-xs text-slate-400">No services yet. Use "Load default catalogue" to start.</p>}
                        {(settings.direct_billing_services || []).map((row, i) => {
                            const setRow = (patch) => setSettings((s) => ({ ...s, direct_billing_services: s.direct_billing_services.map((r, j) => j === i ? { ...r, ...patch } : r) }));
                            return (
                                <div key={row.code || i} className="flex flex-wrap items-center gap-1.5 border border-slate-100 rounded-sm p-1.5" data-testid={`db-service-${i}`}>
                                    <label className="flex items-center gap-1 w-14 shrink-0" title="Active">
                                        <input type="checkbox" checked={row.active !== false} onChange={(e) => setRow({ active: e.target.checked })} data-testid={`db-active-${i}`} />
                                        <span className="text-[10px] text-slate-500">Active</span>
                                    </label>
                                    <Input placeholder="Description" className="h-8 text-xs flex-1 min-w-[12rem]" value={row.description || ""} onChange={(e) => setRow({ description: e.target.value })} />
                                    <select className="h-8 text-xs border border-slate-200 rounded-sm px-1 w-32" value={row.billing_type || "SET_SERVICE"} onChange={(e) => setRow({ billing_type: e.target.value })} data-testid={`db-type-${i}`}>
                                        <option value="SET_SERVICE">Set Service</option>
                                        <option value="TIME_BASED">Time-Based</option>
                                    </select>
                                    <select className="h-8 text-xs border border-slate-200 rounded-sm px-1 w-40" value={row.category || "OTHER"} onChange={(e) => setRow({ category: e.target.value })}>
                                        {SERVICE_CATEGORIES.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
                                    </select>
                                    <select className="h-8 text-xs border border-slate-200 rounded-sm px-1 w-44" value={row.billing_classification || "PATIENT_THIRD_PARTY_BILLABLE"} onChange={(e) => setRow({ billing_classification: e.target.value })} data-testid={`db-class-${i}`}>
                                        {CLASSIFICATIONS.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
                                    </select>
                                    {row.billing_type === "TIME_BASED" ? (
                                        <Input placeholder="Min fee" type="number" min="0" step="0.01" className="h-8 text-xs w-24" value={row.minimum_fee ?? ""} onChange={(e) => setRow({ minimum_fee: e.target.value })} data-testid={`db-min-${i}`} title="Minimum fee" />
                                    ) : (
                                        <Input placeholder="Clinic fee" type="number" min="0" step="0.01" className="h-8 text-xs w-24" value={row.amount ?? ""} onChange={(e) => setRow({ amount: e.target.value })} data-testid={`db-amount-${i}`} title="Clinic fee" />
                                    )}
                                    {(row.oma_suggested_amount || row.hourly_rate_override) ? (
                                        <span className="text-[10px] text-sky-700 whitespace-nowrap" title="OMA 2026 suggested — not mandatory">OMA {row.hourly_rate_override ? `$${row.hourly_rate_override}/hr` : `$${row.oma_suggested_amount}`}</span>
                                    ) : null}
                                    <button type="button" onClick={() => setSettings((s) => ({ ...s, direct_billing_services: s.direct_billing_services.filter((_, j) => j !== i) }))} className="text-slate-400 hover:text-red-500"><X className="w-4 h-4" /></button>
                                </div>
                            );
                        })}
                    </div>
                </div>
                </>)}
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
