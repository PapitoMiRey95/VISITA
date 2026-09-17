import { AlertTriangle } from "lucide-react";

export function EmergencyNotice({ text }) {
    return (
        <div
            data-testid="emergency-notice"
            className="bg-amber-50 text-amber-900 text-sm p-3 rounded-lg border border-amber-200 flex items-start gap-2"
        >
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5 text-amber-600" />
            <p className="leading-snug">
                {text ||
                    "This portal is not monitored continuously and should not be used for emergencies. If you are experiencing a medical emergency, call 911 or go to the nearest Emergency Department."}
            </p>
        </div>
    );
}
