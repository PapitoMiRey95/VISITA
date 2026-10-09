import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Stethoscope, Play, Hospital, Phone, Video, Users, HeartPulse } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDateTime } from "../lib/date";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";

export const ENCOUNTER_TYPES = [
    { value: "IN_CLINIC", label: "Regular / In-Clinic", Icon: Hospital },
    { value: "TELEPHONE", label: "Telephone", Icon: Phone },
    { value: "VIDEO", label: "Video", Icon: Video },
    { value: "PROXY", label: "Proxy", Icon: Users },
    { value: "PHYSICAL", label: "Physical", Icon: HeartPulse },
];
export const encounterTypeLabel = (v) => ENCOUNTER_TYPES.find((t) => t.value === v)?.label || v || "—";

export function patientRefOf(p) {
    if (!p) return null;
    return p.directory_id ? `directory:${p.directory_id}` : p.patient_id ? `patient:${p.patient_id}` : null;
}

/* Physician-only Start / Resume Encounter control for the selected patient card. */
export function StartEncounterButton({ patient }) {
    const nav = useNavigate();
    const ref = patientRefOf(patient);
    const [active, setActive] = useState(null);
    const [checking, setChecking] = useState(false);
    const [typeOpen, setTypeOpen] = useState(false);
    const [resumeOpen, setResumeOpen] = useState(false);
    const [type, setType] = useState("IN_CLINIC");
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        let alive = true;
        setActive(null);
        if (!ref) return undefined;
        api.get("/internal/visits/active", { params: { patient_ref: ref } })
            .then(({ data }) => { if (alive) setActive(data.active); })
            .catch(() => {});
        return () => { alive = false; };
    }, [ref]);

    const resume = async (visitId) => {
        setBusy(true);
        try {
            await api.post(`/internal/visits/${visitId}/resume`);
            nav(`/internal/encounter/${visitId}`);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    const onStart = async () => {
        setChecking(true);
        try {
            const { data } = await api.get("/internal/visits/active", { params: { patient_ref: ref } });
            if (data.active) { setActive(data.active); setResumeOpen(true); } else { setType("IN_CLINIC"); setTypeOpen(true); }
        } catch (e) { toast.error(formatErr(e)); } finally { setChecking(false); }
    };

    const onContinue = async () => {
        setBusy(true);
        try {
            const { data } = await api.post("/internal/visits", {
                patient_ref: ref, patient_id: patient.patient_id || null, directory_id: patient.directory_id || null,
                encounter_type: type, source: "patients",
            });
            setTypeOpen(false);
            nav(`/internal/encounter/${data.id}`);
        } catch (e) {
            const d = e?.response?.data?.detail;
            if (e?.response?.status === 409 && d?.visit_id) { setTypeOpen(false); setActive({ id: d.visit_id, ref_number: d.ref_number }); setResumeOpen(true); }
            else toast.error(formatErr(e));
        } finally { setBusy(false); }
    };

    if (!ref) return null;
    return (
        <div className="flex flex-col items-start gap-0.5 shrink-0" data-testid="encounter-controls">
            {active ? (
                <>
                    <Button size="sm" disabled={busy} data-testid="resume-encounter-btn" onClick={() => resume(active.id)}
                        className="bg-visita-ribbon hover:bg-[#162c49] text-white">
                        <Play className="w-3.5 h-3.5 mr-1" /> Resume Encounter
                    </Button>
                    <span className="text-[11px] text-amber-700 font-medium whitespace-nowrap" data-testid="encounter-in-progress-since">
                        Encounter in progress since {formatDateTime(active.started_at)}
                    </span>
                </>
            ) : (
                <Button size="sm" disabled={checking} data-testid="start-encounter-btn" onClick={onStart}
                    className="bg-visita-ribbon hover:bg-[#162c49] text-white">
                    <Stethoscope className="w-3.5 h-3.5 mr-1" /> Start Encounter
                </Button>
            )}

            <Dialog open={typeOpen} onOpenChange={(o) => { if (!busy) setTypeOpen(o); }}>
                <DialogContent className="max-w-md" data-testid="encounter-type-dialog">
                    <DialogHeader>
                        <DialogTitle>Select Encounter Type</DialogTitle>
                        <DialogDescription>Choose how this encounter is taking place. Nothing is created until you press Continue.</DialogDescription>
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
                        <Button variant="outline" disabled={busy} data-testid="encounter-type-cancel" onClick={() => setTypeOpen(false)}>Cancel</Button>
                        <Button disabled={busy} data-testid="encounter-type-continue" onClick={onContinue} className="bg-visita-ribbon hover:bg-[#162c49] text-white">Continue</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={resumeOpen} onOpenChange={setResumeOpen}>
                <DialogContent className="max-w-sm" data-testid="encounter-active-dialog">
                    <DialogHeader>
                        <DialogTitle>Encounter already in progress</DialogTitle>
                        <DialogDescription>An encounter is already in progress for this patient{active?.ref_number ? ` (${active.ref_number})` : ""}.</DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" data-testid="encounter-active-cancel" onClick={() => setResumeOpen(false)}>Cancel</Button>
                        <Button disabled={busy} data-testid="encounter-active-resume" onClick={() => resume(active.id)} className="bg-visita-ribbon hover:bg-[#162c49] text-white">Resume Encounter</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
