// Single source of truth for Ontario Health Card / OHIP display + input masking.
// Display standard: "#### ### ### XX" (10 digits grouped 4-3-3, then 2-letter
// version). Spaces are DISPLAY/INPUT-MASK ONLY — never stored. The backend keeps
// the normalized 10-digit number and the 2-letter version separately.

export function normalizeHealthCardInput(s) {
    return String(s || "").replace(/\D/g, "").slice(0, 10);
}

export function formatHealthCardNumber(value) {
    const d = normalizeHealthCardInput(value);
    if (d.length <= 4) return d;
    if (d.length <= 7) return `${d.slice(0, 4)} ${d.slice(4)}`;
    return `${d.slice(0, 4)} ${d.slice(4, 7)} ${d.slice(7)}`;
}

export function formatHealthCardWithVersion(number, version) {
    const num = formatHealthCardNumber(number);
    const ver = String(version || "").replace(/[^A-Za-z]/g, "").toUpperCase();
    return [num, ver].filter(Boolean).join(" ");
}
