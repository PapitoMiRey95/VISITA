import { AlertTriangle } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { formatDate } from "../lib/date";

export const isSameDayConflict = (err) => err?.response?.status === 409 && err?.response?.data?.detail?.code === "SAME_DAY_EXISTS";

// Staff/physician/admin only: explicit override with a required reason (audited server-side).
export function SameDayOverride({ conflict, reason, setReason, busy, onConfirm, onCancel }) {
    const existing = conflict?.existing || [];
    return (
        <div className="bg-amber-50 border border-amber-300 rounded-sm p-3 space-y-2 text-sm" data-testid="same-day-override-panel">
            <div className="flex items-start gap-2 text-amber-900">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                <div>
                    <div className="font-bold">Patient already has an appointment on this day</div>
                    {existing.map((e) => (
                        <div key={e.id} className="text-xs" data-testid="same-day-existing">
                            {e.ref_number} · {formatDate(e.date)} {e.time} · {e.reason || "—"}
                        </div>
                    ))}
                    <div className="text-xs mt-1">Only one appointment per day is allowed. To book a second same-day appointment as a clinical exception, enter a reason. This action is audited.</div>
                </div>
            </div>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Override reason (required)" data-testid="same-day-override-reason" />
            <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={onCancel} data-testid="same-day-override-cancel">Choose another day</Button>
                <Button size="sm" disabled={busy || !reason.trim()} onClick={onConfirm}
                    className="bg-amber-600 hover:bg-amber-700 text-white" data-testid="same-day-override-confirm">
                    Book anyway (override)
                </Button>
            </div>
        </div>
    );
}
