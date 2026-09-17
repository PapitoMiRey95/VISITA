import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
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

export default function Settings() {
    const [settings, setSettings] = useState({});
    const [templates, setTemplates] = useState({});
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        const { data } = await api.get("/admin/settings");
        setSettings(data.settings || {});
        setTemplates(data.templates || {});
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    const save = async () => {
        setBusy(true);
        try {
            await api.put("/admin/settings", { settings, templates });
            toast.success("Settings saved.");
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <div className="animate-fade-in max-w-3xl">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Clinic Settings & Message Templates</h1>
            <p className="text-sm text-slate-500 mb-4">Configure clinic information and the default patient-facing messages.</p>

            <div className="bg-white border border-slate-300 rounded-sm p-4 mb-4 space-y-3">
                <h2 className="font-semibold text-slate-700">Clinic information</h2>
                {SETTING_FIELDS.map(([k, label]) => (
                    <div key={k}>
                        <Label className="text-xs">{label}</Label>
                        <Input value={settings[k] || ""} onChange={(e) => setSettings({ ...settings, [k]: e.target.value })} data-testid={`setting-${k}`} />
                    </div>
                ))}
            </div>

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
                {busy ? "Saving…" : "Save Settings"}
            </Button>
        </div>
    );
}
