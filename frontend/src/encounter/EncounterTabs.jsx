/* Reusable Encounter tab shell. Tabs live INSIDE the patient/Encounter context (no sidebar navigation). */
export const ENCOUNTER_TABS = [
    { key: "visit_new", label: "Visit New" },
    { key: "visit_hx", label: "Visit Hx" },
    { key: "pmhx", label: "PMHx / PSHx / Risks" },
];

export function EncounterTabs({ value, onChange }) {
    return (
        <nav className="flex items-stretch gap-0 px-2 bg-[#0f2a44] border-t border-white/10" data-testid="encounter-tabs" role="tablist">
            {ENCOUNTER_TABS.map((t) => {
                const active = t.key === value;
                return (
                    <button key={t.key} type="button" role="tab" aria-selected={active} onClick={() => onChange(t.key)} data-testid={`encounter-tab-${t.key}`}
                        className={`px-3 h-7 text-[11px] font-bold tracking-wide whitespace-nowrap border-b-2 transition-colors ${active ? "border-cyan-300 text-white bg-white/10" : "border-transparent text-white/70 hover:text-white hover:bg-white/5"}`}>
                        {t.label}
                    </button>
                );
            })}
        </nav>
    );
}
