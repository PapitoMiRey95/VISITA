import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { LogOut, BellRing, IdCard, Phone, CreditCard, AlertTriangle, Clock, Mail } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { usePortal, Card } from "./shared";
import { formatDate } from "../lib/date";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

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

    const submitHc = async () => {
        const num = hc.health_card_number.replace(/\D/g, "");
        const ver = hc.health_card_version.replace(/[^A-Za-z]/g, "");
        if (num.length !== 10) return toast.error("Health Card number must be exactly 10 digits.");
        if (ver.length !== 2) return toast.error("Version Code must be exactly 2 letters.");
        setBusy(true);
        try {
            await api.post("/portal/profile/health-card", hc);
            toast.success("Health Card update submitted for clinic verification.");
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
                    {p?.health_card_update_pending ? (
                        <div className="mt-2 text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-lg p-2" data-testid="acct-hc-pending">Update pending clinic verification.</div>
                    ) : !hcOpen ? (
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
                            <p className="text-xs text-slate-500">Your current Health Card stays active until the clinic verifies this update.</p>
                            <div className="flex gap-2">
                                <Button data-testid="acct-hc-submit" disabled={busy} onClick={submitHc} className="bg-portal-blue text-white">Submit for verification</Button>
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
