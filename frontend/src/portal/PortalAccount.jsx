import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { LogOut, BellRing, IdCard, Phone, CreditCard, AlertTriangle, Clock, Mail, MapPin, User } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { usePortal, Card } from "./shared";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";

const SEX_OPTIONS = ["Male", "Female", "X"];

const TYPE_LABEL = { ohip: "OHIP Patient", private: "Private / Uninsured", tourist: "Tourist / Visitor" };

const HC_BADGE = {
    VALID: "bg-emerald-100 text-emerald-700",
    EXPIRING_SOON: "bg-amber-100 text-amber-800",
    EXPIRED: "bg-red-100 text-red-700",
    INCOMPLETE: "bg-slate-100 text-slate-500",
};
const HC_LABEL = { VALID: "Valid", EXPIRING_SOON: "Expiring soon", EXPIRED: "Expired", INCOMPLETE: "Incomplete" };

export default function PortalAccount() {
    const nav = useNavigate();
    const { user, logout } = useAuth();
    const { overview, refetch } = usePortal();
    const p = overview.data?.patient;
    const notes = overview.data?.notifications || [];

    const [editPhone, setEditPhone] = useState(false);
    const [phone, setPhone] = useState("");
    const [editSex, setEditSex] = useState(false);
    const [sex, setSex] = useState("");
    const [editAddr, setEditAddr] = useState(false);
    const [addr, setAddr] = useState({ address: "", unit: "", city: "", province: "", postal_code: "" });
    const [hcOpen, setHcOpen] = useState(false);
    const [hc, setHc] = useState({ health_card_number: "", health_card_version: "", health_card_issue_date: "", health_card_expiry_date: "" });
    const [busy, setBusy] = useState(false);

    const markRead = async () => {
        await api.post("/portal/notifications/read");
        toast.success("Notifications marked as read.");
        refetch();
    };

    const savePhone = async () => {
        setBusy(true);
        try {
            await api.post("/portal/profile/phone", { phone });
            toast.success("Phone number updated.");
            setEditPhone(false); refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const saveSex = async () => {
        if (!sex) return toast.error("Please select your sex.");
        setBusy(true);
        try {
            await api.post("/portal/profile/sex", { sex });
            toast.success("Sex updated.");
            setEditSex(false); refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const openAddr = () => {
        setAddr({
            address: p?.address || "", unit: p?.unit || "", city: p?.city || "",
            province: p?.province || "", postal_code: p?.postal_code || "",
        });
        setEditAddr(true);
    };

    const saveAddress = async () => {
        setBusy(true);
        try {
            await api.post("/portal/profile/address", addr);
            toast.success("Address updated.");
            setEditAddr(false); refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const submitHc = async () => {
        const num = hc.health_card_number.replace(/\D/g, "");
        const ver = hc.health_card_version.replace(/[^A-Za-z]/g, "");
        if (num.length !== 10) return toast.error("Health Card number must be exactly 10 digits.");
        if (ver.length !== 2) return toast.error("Version Code must be exactly 2 letters.");
        setBusy(true);
        try {
            await api.post("/portal/profile/health-card", hc);
            toast.success("Health Card updated.");
            setHcOpen(false); refetch();
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const hcStatus = p?.health_card_status;

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Account</h1>

            <Card>
                <div className="text-lg font-extrabold text-slate-900">{p ? `${p.first_name} ${p.last_name}` : user?.name}</div>
                <div className="text-sm text-slate-500">{user?.email}</div>
                <div className="mt-3 flex flex-wrap gap-2 text-sm">
                    <span className="px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold">{TYPE_LABEL[p?.patient_type] || "Patient"}</span>
                    <span className={`px-2.5 py-0.5 rounded-full font-semibold ${p?.verification_status === "verified" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                        {p?.verification_status === "verified" ? "Verified" : "Verification pending"}
                    </span>
                </div>
            </Card>

            {p && !p.sex && !editSex && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 flex items-start gap-3" data-testid="acct-sex-prompt">
                    <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
                    <div className="flex-1">
                        <div className="font-bold text-amber-900">Please add your sex</div>
                        <div className="text-sm text-amber-800">This information is required for your medical record.</div>
                        <button data-testid="acct-sex-prompt-set" className="mt-2 text-portal-blueDark text-sm font-bold"
                            onClick={() => { setSex(""); setEditSex(true); }}>Set now</button>
                    </div>
                </div>
            )}

            <Card>
                <div className="font-bold text-slate-700 mb-1">My Information</div>

                <Row icon={IdCard} label="VISITA PIN" testid="acct-pin">{p?.visita_patient_id || "Not assigned"}</Row>

                <div className="py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-slate-500 text-sm"><Phone className="w-4 h-4" /> Cell Phone</div>
                        {!editPhone && <button data-testid="acct-edit-phone" className="text-portal-blueDark text-sm font-bold" onClick={() => { setPhone(p?.phone || ""); setEditPhone(true); }}>Edit</button>}
                    </div>
                    {!editPhone ? (
                        <div className="font-semibold text-slate-800 mt-0.5" data-testid="acct-phone">{p?.phone || "—"}</div>
                    ) : (
                        <div className="flex gap-2 mt-1">
                            <Input data-testid="acct-phone-input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(416) 555-0000" />
                            <Button data-testid="acct-phone-save" disabled={busy} onClick={savePhone} className="bg-portal-blue text-white">Save</Button>
                            <Button variant="outline" onClick={() => setEditPhone(false)}>Cancel</Button>
                        </div>
                    )}
                </div>

                {p?.email && <Row icon={Mail} label="Email" testid="acct-email">{p.email}</Row>}

                <div className="py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-slate-500 text-sm"><User className="w-4 h-4" /> Sex <span className="text-red-500">*</span></div>
                        {!editSex && <button data-testid="acct-edit-sex" className="text-portal-blueDark text-sm font-bold" onClick={() => { setSex(p?.sex || ""); setEditSex(true); }}>{p?.sex ? "Edit" : "Add"}</button>}
                    </div>
                    {!editSex ? (
                        <div className="font-semibold text-slate-800 mt-0.5" data-testid="acct-sex">{p?.sex || "Not set"}</div>
                    ) : (
                        <div className="flex gap-2 mt-1">
                            <Select value={sex} onValueChange={setSex}>
                                <SelectTrigger data-testid="acct-sex-trigger" className="flex-1"><SelectValue placeholder="Select sex" /></SelectTrigger>
                                <SelectContent>
                                    {SEX_OPTIONS.map((o) => <SelectItem key={o} value={o} data-testid={`acct-sex-opt-${o}`}>{o}</SelectItem>)}
                                </SelectContent>
                            </Select>
                            <Button data-testid="acct-sex-save" disabled={busy} onClick={saveSex} className="bg-portal-blue text-white">Save</Button>
                            <Button variant="outline" onClick={() => setEditSex(false)}>Cancel</Button>
                        </div>
                    )}
                </div>

                <div className="py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-slate-500 text-sm"><MapPin className="w-4 h-4" /> Address</div>
                        {!editAddr && <button data-testid="acct-edit-address" className="text-portal-blueDark text-sm font-bold" onClick={openAddr}>{(p?.address || p?.city) ? "Edit" : "Add"}</button>}
                    </div>
                    {!editAddr ? (
                        <div className="font-semibold text-slate-800 mt-0.5" data-testid="acct-address">
                            {[[p?.address, p?.unit ? `#${p.unit}` : ""].filter(Boolean).join(" "),
                              [p?.city, p?.province].filter(Boolean).join(", "),
                              p?.postal_code].filter(Boolean).join(" · ") || "—"}
                        </div>
                    ) : (
                        <div className="mt-1 space-y-2">
                            <div className="grid grid-cols-3 gap-2">
                                <div className="col-span-2"><Label className="text-xs">Street address</Label><Input data-testid="acct-address-street" value={addr.address} onChange={(e) => setAddr({ ...addr, address: e.target.value })} placeholder="123 Main St" /></div>
                                <div><Label className="text-xs">Unit / Apt</Label><Input data-testid="acct-address-unit" value={addr.unit} onChange={(e) => setAddr({ ...addr, unit: e.target.value })} placeholder="Optional" /></div>
                            </div>
                            <div className="grid grid-cols-3 gap-2">
                                <div><Label className="text-xs">City</Label><Input data-testid="acct-address-city" value={addr.city} onChange={(e) => setAddr({ ...addr, city: e.target.value })} /></div>
                                <div><Label className="text-xs">Province</Label><Input data-testid="acct-address-province" value={addr.province} onChange={(e) => setAddr({ ...addr, province: e.target.value })} placeholder="ON" /></div>
                                <div><Label className="text-xs">Postal code</Label><Input data-testid="acct-address-postal" value={addr.postal_code} onChange={(e) => setAddr({ ...addr, postal_code: e.target.value })} placeholder="A1A 1A1" /></div>
                            </div>
                            <div className="flex gap-2">
                                <Button data-testid="acct-address-save" disabled={busy} onClick={saveAddress} className="bg-portal-blue text-white">Save</Button>
                                <Button variant="outline" onClick={() => setEditAddr(false)}>Cancel</Button>
                            </div>
                        </div>
                    )}
                </div>

                <div className="py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-slate-500 text-sm"><CreditCard className="w-4 h-4" /> Health Card</div>
                        {hcStatus && <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${HC_BADGE[hcStatus]}`} data-testid="acct-hc-badge">{HC_LABEL[hcStatus]}</span>}
                    </div>
                    <div className="font-semibold text-slate-800 mt-0.5 tracking-wide" data-testid="acct-hc">{p?.health_card_display || "Not on file"}</div>
                    <div className="text-xs text-slate-500 mt-0.5">
                        Issue: {p?.health_card_issue_date ? formatDate(p.health_card_issue_date) : "—"} · Expiry: {p?.health_card_expiry_date ? formatDate(p.health_card_expiry_date) : "—"}
                    </div>
                    {(!p?.health_card_issue_date || !p?.health_card_expiry_date) && (
                        <div className="text-xs text-slate-500 mt-1">Health Card information incomplete.</div>
                    )}
                    {hcStatus === "EXPIRING_SOON" && (
                        <div className="mt-2 flex items-start gap-2 text-sm bg-amber-50 border border-amber-200 text-amber-900 rounded-lg p-2" data-testid="acct-hc-warn-soon">
                            <Clock className="w-4 h-4 mt-0.5 shrink-0" /> Your Health Card will expire soon. Please update your Health Card information after renewal.
                        </div>
                    )}
                    {hcStatus === "EXPIRED" && (
                        <div className="mt-2 flex items-start gap-2 text-sm bg-red-50 border border-red-200 text-red-800 rounded-lg p-2" data-testid="acct-hc-warn-expired">
                            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> Your Health Card appears to be expired. Please update your Health Card information.
                        </div>
                    )}
                    {!hcOpen ? (
                        <button data-testid="acct-hc-update" className="text-portal-blueDark text-sm font-bold mt-2" onClick={() => setHcOpen(true)}>Update Health Card</button>
                    ) : (
                        <div className="mt-2 space-y-2 border-t border-slate-100 pt-2">
                            <div className="grid grid-cols-3 gap-2">
                                <div className="col-span-2">
                                    <Label className="text-xs">Health Card Number</Label>
                                    <Input data-testid="acct-hc-number" value={hc.health_card_number} onChange={(e) => setHc({ ...hc, health_card_number: e.target.value })} placeholder="1234 567 890" />
                                </div>
                                <div>
                                    <Label className="text-xs">Version</Label>
                                    <Input data-testid="acct-hc-version" value={hc.health_card_version} onChange={(e) => setHc({ ...hc, health_card_version: e.target.value.toUpperCase() })} placeholder="XX" maxLength={2} />
                                </div>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                <div><Label className="text-xs">Issue Date</Label><Input type="date" data-testid="acct-hc-issue" value={hc.health_card_issue_date} onChange={(e) => setHc({ ...hc, health_card_issue_date: e.target.value })} /></div>
                                <div><Label className="text-xs">Expiry Date</Label><Input type="date" data-testid="acct-hc-expiry" value={hc.health_card_expiry_date} onChange={(e) => setHc({ ...hc, health_card_expiry_date: e.target.value })} /></div>
                            </div>
                            <div className="flex gap-2">
                                <Button data-testid="acct-hc-submit" disabled={busy} onClick={submitHc} className="bg-portal-blue text-white">Save Health Card</Button>
                                <Button variant="outline" onClick={() => setHcOpen(false)}>Cancel</Button>
                            </div>
                        </div>
                    )}
                </div>
            </Card>

            <Card>
                <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2 font-bold text-slate-700"><BellRing className="w-5 h-5 text-portal-blue" /> Notifications</div>
                    {notes.some((n) => !n.read) && <button onClick={markRead} data-testid="mark-read" className="text-sm text-portal-blueDark font-bold">Mark all read</button>}
                </div>
                {notes.length === 0 && <p className="text-slate-500 text-sm">No notifications.</p>}
                <div className="space-y-2">
                    {notes.map((n) => (
                        <div key={n.id} className={`text-sm rounded-lg p-3 border ${n.read ? "border-slate-100 bg-white" : "border-portal-blue/30 bg-portal-blue/5"}`}>
                            <div className="font-bold text-slate-800">{n.title}</div>
                            <div className="text-slate-600">{n.body}</div>
                        </div>
                    ))}
                </div>
            </Card>

            <Button onClick={() => { logout(); nav("/login"); }} data-testid="account-logout"
                variant="outline" className="w-full h-12 rounded-xl border-slate-300 text-slate-700">
                <LogOut className="w-4 h-4 mr-2" /> Sign out
            </Button>
        </div>
    );
}

function Row({ icon: Icon, label, children, testid }) {
    return (
        <div className="py-2 border-t border-slate-100 first:border-t-0">
            <div className="flex items-center gap-2 text-slate-500 text-sm"><Icon className="w-4 h-4" /> {label}</div>
            <div className="font-semibold text-slate-800 mt-0.5" data-testid={testid}>{children}</div>
        </div>
    );
}
