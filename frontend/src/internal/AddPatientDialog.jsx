import { useState } from "react";
import { toast } from "sonner";
import { UserPlus, AlertTriangle } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { HealthCardNumberInput } from "../components/HealthCardNumberInput";
import { IssueDatePicker } from "../components/IssueDatePicker";
import { ExpiryPicker } from "../components/ExpiryPicker";

const EMPTY = { first_name: "", last_name: "", date_of_birth: "", sex: "", email: "", home_phone: "", phone: "", address: "", unit: "", city: "", province: "ON", postal_code: "", country: "Canada", health_card_number: "", health_card_version: "", health_card_issue_date: "", health_card_expiry_date: "" };
const SELECT = "flex h-9 w-full rounded-sm border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500";

// Staff manual registration — same fields as the portal registration; creates an ACTIVE directory record with a VIen PIN (no portal login).
export function AddPatientDialog({ open, onClose, onCreated }) {
    const [f, setF] = useState(EMPTY);
    const [busy, setBusy] = useState(false);
    const [dupWarning, setDupWarning] = useState(null);
    const set = (k) => (v) => setF((s) => ({ ...s, [k]: v?.target ? v.target.value : v }));
    const close = () => { setF(EMPTY); setDupWarning(null); onClose(); };
    const submit = async (allowDuplicate = false) => {
        setBusy(true);
        try {
            const { data } = await api.post("/internal/patient-directory", { ...f, allow_duplicate: allowDuplicate });
            toast.success(`Patient added — VIen PIN ${data.visita_patient_id}.`);
            onCreated(data); close();
        } catch (err) {
            const msg = formatErr(err);
            if (err?.response?.status === 409 && /same name and date of birth/i.test(msg)) setDupWarning(msg); else toast.error(msg);
        } finally { setBusy(false); }
    };
    const required = f.first_name.trim() && f.last_name.trim() && f.date_of_birth && f.sex && (f.phone.trim() || f.home_phone.trim());
    return (
        <Dialog open={open} onOpenChange={(o) => !o && close()}>
            <DialogContent className="max-w-2xl font-plex max-h-[92vh] overflow-y-auto" data-testid="add-patient-dialog">
                <DialogHeader><DialogTitle className="flex items-center gap-2 text-lg"><UserPlus className="w-5 h-5" /> Add patient manually</DialogTitle>
                    <p className="text-xs text-slate-500">Creates the patient's clinic record with a VIen PIN. No portal login is created — the patient can claim it later.</p></DialogHeader>
                <form onSubmit={(e) => { e.preventDefault(); submit(false); }} className="space-y-3 text-sm">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        <div className="col-span-2"><Label className="text-xs">First Name(s) *</Label><Input data-testid="add-first-name" value={f.first_name} onChange={set("first_name")} required /></div>
                        <div className="col-span-2"><Label className="text-xs">Last Name(s) *</Label><Input data-testid="add-last-name" value={f.last_name} onChange={set("last_name")} required /></div>
                        <div className="col-span-2"><Label className="text-xs">Date of Birth *</Label><Input type="date" data-testid="add-dob" value={f.date_of_birth} onChange={set("date_of_birth")} required /></div>
                        <div className="col-span-2"><Label className="text-xs">Sex *</Label>
                            <select data-testid="add-sex" value={f.sex} onChange={set("sex")} className={SELECT} required>
                                <option value="">— Select —</option><option value="Female">Female</option><option value="Male">Male</option><option value="X">X</option>
                            </select></div>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        <div className="col-span-2"><Label className="text-xs">Cell Phone *</Label><Input data-testid="add-phone" value={f.phone} onChange={set("phone")} placeholder="(416) 555-0100" /></div>
                        <div className="col-span-2"><Label className="text-xs">Home Phone</Label><Input data-testid="add-home-phone" value={f.home_phone} onChange={set("home_phone")} /></div>
                        <div className="col-span-4"><Label className="text-xs">Email</Label><Input type="email" data-testid="add-email" value={f.email} onChange={set("email")} /></div>
                    </div>
                    <div className="grid grid-cols-6 gap-2">
                        <div className="col-span-4"><Label className="text-xs">Street Address</Label><Input data-testid="add-address" value={f.address} onChange={set("address")} /></div>
                        <div className="col-span-2"><Label className="text-xs">Unit</Label><Input data-testid="add-unit" value={f.unit} onChange={set("unit")} /></div>
                        <div className="col-span-3 sm:col-span-2"><Label className="text-xs">City</Label><Input data-testid="add-city" value={f.city} onChange={set("city")} /></div>
                        <div className="col-span-3 sm:col-span-1"><Label className="text-xs">Province</Label><Input data-testid="add-province" value={f.province} onChange={set("province")} /></div>
                        <div className="col-span-3 sm:col-span-2"><Label className="text-xs">Postal Code</Label><Input data-testid="add-postal" value={f.postal_code} onChange={set("postal_code")} /></div>
                        <div className="col-span-3 sm:col-span-1"><Label className="text-xs">Country</Label><Input data-testid="add-country" value={f.country} onChange={set("country")} /></div>
                    </div>
                    <div className="border border-slate-200 rounded-sm p-2.5 space-y-2">
                        <div className="text-[11px] uppercase tracking-wide text-slate-500 font-semibold">Health card (optional)</div>
                        <div className="grid grid-cols-3 gap-2">
                            <div className="col-span-2"><Label className="text-xs">Number (10 digits)</Label><HealthCardNumberInput data-testid="add-hcn" value={f.health_card_number} onChange={set("health_card_number")} placeholder="2245 881 830" /></div>
                            <div><Label className="text-xs">Version</Label><Input data-testid="add-hcv" value={f.health_card_version} maxLength={2} onChange={(e) => setF((s) => ({ ...s, health_card_version: e.target.value.toUpperCase() }))} /></div>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            <div><Label className="text-xs">Issue Date</Label><IssueDatePicker testid="add-hc-issue" value={f.health_card_issue_date} onChange={set("health_card_issue_date")} /></div>
                            <div><Label className="text-xs">Expiry Date</Label><ExpiryPicker testid="add-hc-expiry" value={f.health_card_expiry_date} onChange={set("health_card_expiry_date")} dob={f.date_of_birth} /></div>
                        </div>
                    </div>
                    {dupWarning && (
                        <div className="flex flex-wrap items-center gap-2 rounded-sm border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900" data-testid="add-patient-duplicate">
                            <AlertTriangle className="w-4 h-4 shrink-0" /><span className="flex-1 min-w-[12rem]">{dupWarning}</span>
                            <Button type="button" size="sm" variant="outline" disabled={busy} data-testid="add-patient-force" onClick={() => submit(true)} className="h-7 text-xs border-amber-400 text-amber-900">Add anyway</Button>
                        </div>
                    )}
                    <div className="flex justify-end gap-2 pt-1">
                        <Button type="button" variant="outline" onClick={close} data-testid="add-patient-cancel">Cancel</Button>
                        <Button type="submit" disabled={busy || !required} data-testid="add-patient-submit" className="bg-visita-green hover:bg-visita-greenDark text-white"><UserPlus className="w-4 h-4 mr-1" /> Add patient</Button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}
