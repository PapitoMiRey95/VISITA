import { useCallback, useEffect, useState } from "react";
import { Stethoscope, Scissors, AlertTriangle, Pencil } from "lucide-react";
import { api } from "../lib/api";
import { HistoryDrawer } from "./HistoryDrawer";

/* Right-column longitudinal clinical history (PMHx / PSHx / Allergies). Read-only compact lists +
   per-section [Manage] drawer. Never touches the current Visit. */

export function useHistoryDomain(patientRef, domain) {
    const [items, setItems] = useState(null);
    const reload = useCallback(() => {
        if (!patientRef) return;
        api.get(`/internal/patients/${encodeURIComponent(patientRef)}/${domain}`)
            .then(({ data }) => setItems(data.items)).catch(() => setItems([]));
    }, [patientRef, domain]);
    useEffect(() => { reload(); }, [reload]);
    return [items, reload];
}

const fmtDate = (d) => d || null;

export function HistorySection({ title, Icon, domain, patientRef, canEdit, testid, warn, children, items, reload, hint }) {
    const [open, setOpen] = useState(false);
    const active = (items || []).filter((i) => i.status === "ACTIVE").length;
    const danger = warn && active > 0;
    return (
        <section className={`bg-white border rounded-sm ${danger ? "border-red-400 ring-1 ring-red-300" : "border-slate-300"}`} data-testid={testid}
            data-active-count={active}>
            <div className={`flex items-center gap-1.5 px-2 py-1 border-b text-[11px] font-bold uppercase tracking-wide ${danger ? "bg-red-50 border-red-200 text-red-800" : "border-slate-200 text-slate-600"}`}>
                <Icon className="w-3.5 h-3.5" /> {title}
                {items && <span className="normal-case font-medium opacity-70">{items.filter((i) => i.status !== "ARCHIVED").length}</span>}
                {canEdit && (
                    <button type="button" onClick={() => setOpen(true)} data-testid={`${testid}-manage`}
                        className="ml-auto inline-flex items-center gap-1 h-5 px-1.5 rounded-sm text-[10px] normal-case font-semibold tracking-normal text-visita-ribbon hover:bg-visita-bg border border-transparent hover:border-slate-300">
                        <Pencil className="w-3 h-3" /> Manage
                    </button>
                )}
            </div>
            <div className="px-2 py-1 text-sm">
                {!items ? <div className="text-[11px] text-slate-400">Loading…</div>
                    : !items.length ? <div className="text-[11px] text-slate-400 italic" data-testid={`${testid}-empty`}>{hint}</div>
                        : children(items)}
            </div>
            {open && <HistoryDrawer domain={domain} title={title} patientRef={patientRef} items={items} onClose={() => setOpen(false)} onChanged={reload} />}
        </section>
    );
}

const Row = ({ muted, children, testid }) => (
    <div className={`py-0.5 border-b last:border-0 border-slate-100 text-[11px] leading-snug ${muted ? "text-slate-400" : "text-slate-800"}`} data-testid={testid}>{children}</div>
);

export function PmhxSection({ patientRef, canEdit }) {
    const [items, reload] = useHistoryDomain(patientRef, "conditions");
    return (
        <HistorySection title="Past medical Hx" Icon={Stethoscope} domain="conditions" patientRef={patientRef} canEdit={canEdit} testid="ctx-pmhx"
            items={items} reload={reload} hint="No past medical history recorded in VIen yet.">
            {(rows) => rows.map((c) => (
                <Row key={c.id} muted={c.status !== "ACTIVE"} testid={`pmhx-row-${c.id}`}>
                    <span className="font-semibold">{c.display_text}</span>
                    {fmtDate(c.onset_date) && <span className="text-slate-500"> · {c.onset_date}</span>}
                    {c.status !== "ACTIVE" && <span className="uppercase text-[9px] font-bold ml-1">{c.status}</span>}
                </Row>
            ))}
        </HistorySection>
    );
}

export function PshxSection({ patientRef, canEdit }) {
    const [items, reload] = useHistoryDomain(patientRef, "surgeries");
    return (
        <HistorySection title="Past surgical Hx" Icon={Scissors} domain="surgeries" patientRef={patientRef} canEdit={canEdit} testid="ctx-pshx"
            items={items} reload={reload} hint="No surgical history recorded in VIen yet.">
            {(rows) => rows.filter((s) => s.status === "ACTIVE").map((s) => (
                <Row key={s.id} testid={`pshx-row-${s.id}`}>
                    <span className="font-semibold">{s.procedure_text}</span>
                    {[s.procedure_date, s.surgeon_or_provider || s.facility].filter(Boolean).map((x) => <span key={x} className="text-slate-500"> · {x}</span>)}
                </Row>
            ))}
        </HistorySection>
    );
}

export function AllergySection({ patientRef, canEdit }) {
    const [items, reload] = useHistoryDomain(patientRef, "allergies");
    return (
        <HistorySection title="Allergies" Icon={AlertTriangle} domain="allergies" patientRef={patientRef} canEdit={canEdit} testid="ctx-allergies" warn
            items={items} reload={reload} hint="No allergy data recorded in VIen yet.">
            {(rows) => rows.map((a) => (
                <Row key={a.id} muted={a.status !== "ACTIVE"} testid={`allergy-row-${a.id}`}>
                    <span className={`font-bold ${a.status === "ACTIVE" ? "text-red-800" : ""}`}>{a.allergen}</span>
                    <span className="text-slate-500"> · {a.allergy_type}</span>
                    {(a.reaction || a.severity) && <span className="text-slate-700"> — {[a.reaction, a.severity?.replace("_", "-")].filter(Boolean).join(", ")}</span>}
                    {a.status !== "ACTIVE" && <span className="uppercase text-[9px] font-bold ml-1">Inactive</span>}
                </Row>
            ))}
        </HistorySection>
    );
}
