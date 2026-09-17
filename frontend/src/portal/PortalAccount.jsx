import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { LogOut, BellRing } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { usePortal, Card } from "./shared";
import { Button } from "../components/ui/button";

const TYPE_LABEL = { ohip: "OHIP Patient", private: "Private / Uninsured", tourist: "Tourist / Visitor" };

export default function PortalAccount() {
    const nav = useNavigate();
    const { user, logout } = useAuth();
    const { overview, refetch } = usePortal();
    const p = overview.data?.patient;
    const notes = overview.data?.notifications || [];

    const markRead = async () => {
        await api.post("/portal/notifications/read");
        toast.success("Notifications marked as read.");
        refetch();
    };

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Account</h1>

            <Card>
                <div className="text-lg font-extrabold text-slate-900">{p ? `${p.first_name} ${p.last_name}` : user?.name}</div>
                <div className="text-sm text-slate-500">{user?.email}</div>
                <div className="mt-3 flex gap-2 text-sm">
                    <span className="px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold">{TYPE_LABEL[p?.patient_type] || "Patient"}</span>
                    <span className={`px-2.5 py-0.5 rounded-full font-semibold ${p?.verification_status === "verified" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                        {p?.verification_status === "verified" ? "Verified" : "Verification pending"}
                    </span>
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
