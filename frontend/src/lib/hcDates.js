// Shared helpers for OHIP Health Card date fields (Issue Date + Expiry Date).
// Stored/submitted values are ISO "YYYY-MM-DD". Display uses VIsita standard
// "YYYY Mon - DD".
export const MONTHS = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];
export const MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function daysInMonth(year, month0) {
    return new Date(year, month0 + 1, 0).getDate(); // handles leap years
}

export function displayHcDate(iso) {
    if (!iso) return "";
    const [y, m, d] = String(iso).split("-").map(Number);
    if (!y || !m || !d) return "";
    return `${y} ${MON_ABBR[m - 1]} - ${String(d).padStart(2, "0")}`;
}

// Expiry derives its month/day from the patient's DOB and only varies by year.
// Feb-29 DOB rule: for a non-leap expiry year, clamp Feb 29 -> Feb 28.
// This rule is enforced identically on the backend (see server.py derive_expiry_iso).
export function deriveExpiryISO(dobIso, year) {
    if (!dobIso || !year) return "";
    const parts = String(dobIso).split("-").map(Number);
    const m = parts[1]; // 1-based month
    let d = parts[2];
    if (!m || !d) return "";
    const dim = daysInMonth(year, m - 1);
    if (d > dim) d = dim; // Feb 29 -> Feb 28 on non-leap years
    return `${year}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}
