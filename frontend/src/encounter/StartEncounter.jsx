import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DoorOpen, Hospital, Phone, Video, Users, ClipboardList } from "lucide-react";
import { api } from "../lib/api";
import { formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";

export const ENCOUNTER_TYPES = [
    { value: "IN_CLINIC", label: "Regular / In-Clinic", Icon: Hospital },
    { value: "TELEPHONE", label: "Telephone", Icon: Phone },
    { value: "VIDEO", label: "Video", Icon: Video },
    { value: "PROXY", label: "Proxy", Icon: Users },
    { value: "ADMIN", label: "Admin", Icon: ClipboardList },
];
export const encounterTypeLabel = (v) => ENCOUNTER_TYPES.find((t) => t.value === v)?.label || v || "—";

export function patientRefOf(p) {
    if (!p) return null;
    return p.directory_id ? `directory:${p.directory_id}` : p.patient_id ? `patient:${p.patient_id}` : null;
}

/* Single encounter-type picker. Opened ONLY when a NEW visit is being started. Nothing is created until Continue. */
export function EncounterTypeDialog({ open, busy, onCancel, onContinue }) {
    const [type, setType] = useState("IN_CLINIC");
    useEffect(() => { if (open) setType("IN_CLINIC"); }, [open]);
    return (
        <Dialog open={open} onOpenChange={(o) => { if (!o && !busy) onCancel(); }}>
            <DialogContent className="max-w-md" data-testid="encounter-type-dialog">
                <DialogHeader>
                    <DialogTitle>Select Encounter Type</DialogTitle>
                    <DialogDescription>Choose how this visit is taking place. Nothing is created until you press Continue.</DialogDescription>
                </DialogHeader>
                <div className="grid grid-cols-1 gap-1.5" role="radiogroup">
                    {ENCOUNTER_TYPES.map(({ value, label, Icon }) => (
                        <button key={value} type="button" role="radio" aria-checked={type === value} onClick={() => setType(value)}
                            data-testid={`encounter-type-${value}`}
                            className={`flex items-center gap-3 rounded-sm border px-3 py-2 text-left text-sm transition-colors ${type === value ? "border-visita-ribbon bg-visita-bg font-semibold text-visita-ribbon" : "border-slate-300 hover:bg-slate-50"}`}>
                            <Icon className="w-4 h-4" /> {label}
                        </button>
                    ))}
                </div>
                <DialogFooter>
                    <Button variant="outline" disabled={busy} data-testid="encounter-type-cancel" onClick={onCancel}>Cancel</Button>
                    <Button disabled={busy} data-testid="encounter-type-continue" onClick={() => onContinue(type)} className="bg-visita-ribbon hover:bg-[#162c49] text-white">Continue</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

/* Physician-only: ENTER the Encounter workspace. Starts nothing — the visit/timer is started inside. */
export function StartEncounterButton({ patient }) {
    const nav = useNavigate();
    const ref = patientRefOf(patient);
    const [active, setActive] = useState(null);

    useEffect(() => {
        let alive = true;
        setActive(null);
        if (!ref) return undefined;
        api.get("/internal/visits/active", { params: { patient_ref: ref } })
            .then(({ data }) => { if (alive) setActive(data.active); })
            .catch(() => {});
        return () => { alive = false; };
    }, [ref]);

    if (!ref) return null;
    return (
        <div className="flex flex-col items-start gap-0.5 shrink-0" data-testid="encounter-controls">
            <Button size="sm" data-testid="enter-encounter-btn" onClick={() => nav(`/internal/encounter?patient_ref=${encodeURIComponent(ref)}`)}
                className="bg-visita-ribbon hover:bg-[#162c49] text-white">
                <DoorOpen className="w-3.5 h-3.5 mr-1" /> Enter Encounter
            </Button>
            {active && (
                <span className="text-[11px] text-amber-700 font-medium whitespace-nowrap" data-testid="encounter-in-progress-since">
                    {active.timer_state === "PAUSED" ? "Visit paused" : "Visit in progress"} · since {formatDateTime(active.started_at)}
                </span>
            )}
        </div>
    );
}
