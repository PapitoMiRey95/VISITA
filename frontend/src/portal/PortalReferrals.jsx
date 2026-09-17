import { useNavigate } from "react-router-dom";
import { Calendar } from "lucide-react";
import { usePortal, StatusPill, Card } from "./shared";

export default function PortalReferrals() {
    const nav = useNavigate();
    const { overview, cfg } = usePortal();
    const refs = overview.data?.referrals || [];
    const delay = cfg.data?.templates?.referral_delay;
    const newNotice = cfg.data?.templates?.new_referral_notice;

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">Referral Status</h1>

            <Card className="border-violet-200 bg-violet-50/40">
                <h2 className="font-bold text-slate-800 mb-1">Need a new referral?</h2>
                <p className="text-sm text-slate-600 mb-3">{newNotice ||
                    "A medical appointment may be required before a new referral can be issued."}</p>
                <button data-testid="new-referral-request-appt" onClick={() => nav("/portal/appointments")}
                    className="w-full h-12 rounded-xl bg-portal-blue hover:bg-portal-blueDark text-white font-bold flex items-center justify-center gap-2">
                    <Calendar className="w-5 h-5" /> Request an Appointment
                </button>
            </Card>

            <div className="space-y-3">
                <h2 className="font-bold text-slate-700">Your referrals</h2>
                {refs.length === 0 && <p className="text-slate-500 text-sm">You have no referrals on file.</p>}
                {refs.map((r) => (
                    <Card key={r.id} className="p-4" data-testid="referral-status-item">
                        <div className="flex justify-between items-start gap-2">
                            <div className="font-bold text-slate-800">{r.specialty}</div>
                            <StatusPill status={r.status} />
                        </div>
                        {r.last_updated && (
                            <div className="text-xs text-slate-400 mt-1">
                                LAST UPDATED: {new Date(r.last_updated).toLocaleString()}
                            </div>
                        )}
                        <p className="text-sm text-slate-600 mt-2 leading-snug">{delay}</p>
                    </Card>
                ))}
            </div>
        </div>
    );
}
