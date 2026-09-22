import { useState } from "react";
import { toast } from "sonner";
import { Hospital, Phone, Pencil } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { ApptTypeBadge, apptTypeConfirmationLabel } from "./ApptTypeBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";

const CONFIRMED = ["confirmed", "rescheduled"];

// Clickable appointment-type badge that opens a small editor.
// Notifies the patient (server-side) only when a CONFIRMED appointment switches real types.
export function ApptTypeEditor({ appt, onSaved, size = "sm" }) {
    const [open, setOpen] = useState(false);
    const [pending, setPending] = useState(null); // type awaiting confirmation
    const [busy, setBusy] = useState(false);
    const current = appt?.appointment_type || null;

    const willNotify = (next) =>
        CONFIRMED.includes(appt?.status) && ["IN_CLINIC", "TELEPHONE"].includes(current) && next !== current;

    const save = async (next) => {
        setBusy(true);
        try {
            const { data } = await api.patch(`/internal/appointments/${appt.id}/type`, { appointment_type: next });
            toast.success(`Appointment type set to ${apptTypeConfirmationLabel(next)}.`);
            setOpen(false); setPending(null);
            onSaved?.(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const choose = (next) => {
        if (next === current) { setOpen(false); return; }
        if (willNotify(next)) { setPending(next); return; }
        save(next);
    };

    return (
        <>
            <button type="button" data-testid={`appt-type-edit-${appt.id}`} onClick={() => setOpen(true)}
                className="inline-flex items-center gap-1 group" title="Change appointment type">
                <ApptTypeBadge type={current} size={size} />
                <Pencil className="w-3 h-3 text-slate-400 group-hover:text-slate-600" />
            </button>

            <Dialog open={open} onOpenChange={(o) => { if (!o) { setOpen(false); setPending(null); } }}>
                <DialogContent className="max-w-sm" data-testid="appt-type-editor-dialog">
                    <DialogHeader><DialogTitle>Appointment Type</DialogTitle></DialogHeader>
                    {!pending ? (
                        <div className="space-y-3">
                            <p className="text-sm text-slate-500">{appt.patient_name}</p>
                            <div className="grid grid-cols-2 gap-3">
                                {[
                                    { v: "IN_CLINIC", title: "In-Clinic", Icon: Hospital },
                                    { v: "TELEPHONE", title: "Telephone", Icon: Phone },
                                ].map(({ v, title, Icon }) => {
                                    const on = current === v;
                                    return (
                                        <button key={v} type="button" data-testid={`appt-type-set-${v}`} disabled={busy}
                                            onClick={() => choose(v)}
                                            className={`text-left rounded-xl border p-3 transition-colors ${on
                                                ? "border-visita-green bg-emerald-50 ring-1 ring-visita-green"
                                                : "border-slate-200 bg-white hover:border-visita-green"}`}>
                                            <div className="flex items-center gap-2 font-bold text-slate-800">
                                                <Icon className="w-4 h-4 text-visita-greenDark" /> {title}
                                            </div>
                                            {on && <div className="text-[11px] text-slate-500 mt-1">Current</div>}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-4 text-sm">
                            <p className="text-slate-700">
                                Change this <b>confirmed</b> appointment to a <b>{apptTypeConfirmationLabel(pending)}</b>?
                                The patient will be notified by portal and email. The date and time stay the same.
                            </p>
                            <div className="flex gap-2 justify-end">
                                <Button variant="outline" disabled={busy} onClick={() => setPending(null)} data-testid="appt-type-confirm-cancel">Back</Button>
                                <Button disabled={busy} onClick={() => save(pending)} data-testid="appt-type-confirm-save"
                                    className="bg-visita-green hover:bg-visita-greenDark text-white">
                                    {busy ? "Saving…" : "Change & Notify Patient"}
                                </Button>
                            </div>
                        </div>
                    )}
                </DialogContent>
            </Dialog>
        </>
    );
}
