// Patient name display helpers.
// Convention across internal (staff/admin/physician) views: last names are ALWAYS
// uppercase and first names are Title Case, shown as "LASTNAMES, First Names".

export const titleCaseName = (s) =>
    (s || "").trim().toLowerCase().replace(/(^|[\s'\-])([\p{L}])/gu, (_, sep, ch) => sep + ch.toUpperCase());

// Format from separate first/last fields (last uppercase, first title case).
export function formatLastFirst(lastName, firstName) {
    const last = (lastName || "").trim().toUpperCase();
    const first = titleCaseName(firstName || "");
    if (last && first) return `${last}, ${first}`;
    return last || first || "—";
}

// Format from a patient-like object; falls back to full_name when parts are missing.
export function formatPatientName(p) {
    if (!p) return "—";
    const last = (p.last_name || "").trim().toUpperCase();
    const first = titleCaseName(p.first_name || "");
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
