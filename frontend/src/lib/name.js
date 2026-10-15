// Patient name display helpers.
// Convention across internal (staff/admin/physician) views: last names are ALWAYS
// uppercase and first names are Title Case, shown as "LASTNAMES, First Names".

export const titleCaseName = (s) =>
    (s || "").trim().toLowerCase().replace(/(^|[\s'\-])([\p{L}])/gu, (_, sep, ch) => sep + ch.toUpperCase());

// Live-normalize a patient surname field as they type: uppercase (accents,
// apostrophes, hyphens, and compound surnames preserved), strip leading spaces,
// and collapse accidental repeated spaces. A single trailing space is allowed so
// users can type compound surnames. Never rejects lowercase input.
export function normalizeSurnameInput(value) {
    return (value || "").replace(/^\s+/, "").replace(/\s{2,}/g, " ").toUpperCase();
}

// Format from separate first/last fields (last uppercase, first title case).
export function formatLastFirst(lastName, firstName) {
    const last = (lastName || "").trim().toUpperCase();
    const first = titleCaseName(firstName || "");
    if (last && first) return `${last}, ${first}`;
    return last || first || "—";
}

// Format from a patient-like object; falls back to full_name when parts are missing.
// Includes optional middle_name / second_last_name when present (supplemental
// identity fields); legacy records without them are unaffected.
// Canonical clinical full-name formatter: "LAST NAME(S), First Name(s)". Preserves compound
// surnames and all given names; appends middle_name / second_last_name only when they add
// tokens not already present in the base field (never duplicates, never invents).
const joinParts = (base, extra) => {
    const b = (base || "").trim().split(/\s+/).filter(Boolean);
    const e = (extra || "").trim().split(/\s+/).filter(Boolean);
    const bu = new Set(b.map((t) => t.toUpperCase()));
    return (e.length && e.every((t) => bu.has(t.toUpperCase())) ? b : [...b, ...e]).join(" ");
};
export function formatPatientName(p) {
    if (!p) return "—";
    const last = joinParts(p.last_name, p.second_last_name).toUpperCase();
    const first = titleCaseName(joinParts(p.first_name, p.middle_name));
    if (last && first) return `${last}, ${first}`;
    return last || first || p.full_name || "—";
}

// Format an already-combined backend name string. Backend builds patient_name /
// full_name as "Last, First", so uppercase only the segment before the comma and
// preserve the first/middle names. Comma-less/free-text values are left untouched.
export function formatCombinedName(name) {
    if (!name) return "—";
    const s = String(name).trim();
    const i = s.indexOf(",");
    if (i === -1) return s;
    const last = s.slice(0, i).trim().toUpperCase();
    const first = s.slice(i + 1).trim();
    return first ? `${last}, ${first}` : last;
}
