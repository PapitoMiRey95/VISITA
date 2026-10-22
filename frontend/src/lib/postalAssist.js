import { api } from "./api";

// Shared Postal Code Pool assistance for patient/demographic forms (additive; existing fields unchanged).
// fill(form, patch) → returns updated form with City/Province suggested ONLY when blank; never overwrites typed values.
const norm = (p) => (p || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
export async function postalAssist(postal, form, { internal = false } = {}) {
    const n = norm(postal);
    if (n.length !== 6) return null;
    try {
        const { data } = await api.get(internal ? "/internal/address/postal-lookup" : "/public/address/postal-lookup", { params: { postal: n } });
        const next = { ...form, postal_code: data.postal_code };
        if (data.found) {
            if (!form.city?.trim()) next.city = data.city;
            if (!form.province?.trim()) next.province = data.province;
        }
        return { found: data.found, next, city: data.city, province: data.province };
    } catch { return null; }
}
// Patient-side only: unknown postal → review candidate (master pool is never written from patient input).
export async function queuePostalCandidate(form) {
    const n = norm(form.postal_code);
    if (n.length !== 6 || !form.city?.trim() || !form.province?.trim()) return;
    try { await api.post("/public/address/postal-candidate", { postal_code: n, city: form.city.trim(), province: form.province.trim() }); } catch { /* best effort */ }
}
