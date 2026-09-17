import { usePortal, StatusPill, Card } from "./shared";
import { Calendar, Pill, Scan, MessageSquare } from "lucide-react";

const ICONS = { Appointment: Calendar, Prescription: Pill, Imaging: Scan, Message: MessageSquare };

export default function PortalMyRequests() {
    const { overview } = usePortal();
    const reqs = overview.data?.requests || [];

    return (
        <div className="space-y-5 animate-fade-in">
            <h1 className="text-2xl font-bold text-slate-900">My Requests</h1>
            <p className="text-slate-500 text-sm -mt-2">A summary of everything you've sent to the clinic.</p>

            <div className="space-y-3">
                {reqs.length === 0 && <p className="text-slate-500 text-sm">You have not submitted any requests yet.</p>}
                {reqs.map((r) => {
                    const Icon = ICONS[r.type] || MessageSquare;
                    return (
                        <Card key={r.id} className="p-4 flex items-center gap-3" data-testid="my-request-item">
                            <div className="w-10 h-10 rounded-full bg-portal-blue/10 flex items-center justify-center flex-shrink-0">
                                <Icon className="w-5 h-5 text-portal-blue" />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="font-bold text-slate-800">{r.type} Request</div>
                                <div className="text-sm text-slate-500 truncate">
                                    {r.ref_number} · {new Date(r.created_at).toLocaleDateString()}
                                </div>
                            </div>
                            <StatusPill status={r.status} />
                        </Card>
                    );
                })}
            </div>
        </div>
    );
}
