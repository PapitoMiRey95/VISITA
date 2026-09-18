const MAP = {
    received: ["Received", "bg-slate-100 text-slate-600"],
    new: ["New", "bg-slate-100 text-slate-600"],
    open: ["Open", "bg-blue-100 text-blue-700"],
    under_review: ["Under Review", "bg-blue-100 text-blue-700"],
    waiting_physician: ["Waiting for Physician", "bg-purple-100 text-purple-700"],
    completed: ["Completed", "bg-emerald-100 text-emerald-700"],
    appointment_required: ["Appointment Required", "bg-amber-100 text-amber-700"],
    requested: ["Requested", "bg-amber-100 text-amber-700"],
    alternatives_offered: ["Alternatives Offered", "bg-sky-100 text-sky-700"],
    more_info_required: ["More Info Required", "bg-amber-100 text-amber-700"],
    more_info_requested: ["More Info Requested", "bg-amber-100 text-amber-700"],
    suggested: ["Time Suggested", "bg-amber-100 text-amber-700"],
    confirmed: ["Confirmed", "bg-emerald-100 text-emerald-700"],
    declined: ["Declined", "bg-red-100 text-red-700"],
    cancelled: ["Cancelled", "bg-slate-200 text-slate-600"],
};

export function StatusPill({ status }) {
    const [label, cls] = MAP[status] || [status, "bg-slate-100 text-slate-600"];
    return <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-semibold ${cls}`}>{label}</span>;
}
