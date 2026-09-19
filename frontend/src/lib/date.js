// Global VIen EMR date display: "YYYY Mon - DD" (month ALWAYS as 3-letter English).
// Storage stays ISO; this only formats for display.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parse(value) {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "string") {
        const m = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (m) {
            return {
                y: +m[1], mo: +m[2], d: +m[3],
                hasTime: /[T ]\d{2}:\d{2}/.test(value),
                dt: new Date(value),
            };
        }
    }
    const dt = value instanceof Date ? value : new Date(value);
    if (isNaN(dt.getTime())) return null;
    return { y: dt.getFullYear(), mo: dt.getMonth() + 1, d: dt.getDate(), hasTime: true, dt };
}

// "2026 Sep - 18" — safe for date-only strings (no timezone shift).
export function formatDate(value) {
    const p = parse(value);
    if (!p) return "";
    return `${p.y} ${MONTHS[p.mo - 1]} - ${String(p.d).padStart(2, "0")}`;
}

// "2026 Sep - 18 · 3:05 PM" — uses local time for the time portion.
export function formatDateTime(value) {
    const p = parse(value);
    if (!p) return "";
    if (!p.hasTime) return formatDate(value);
    const dt = p.dt;
    const base = `${dt.getFullYear()} ${MONTHS[dt.getMonth()]} - ${String(dt.getDate()).padStart(2, "0")}`;
    let h = dt.getHours();
    const min = String(dt.getMinutes()).padStart(2, "0");
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return `${base} · ${h}:${min} ${ampm}`;
}
