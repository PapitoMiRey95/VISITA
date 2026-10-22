import { api } from "../lib/api";

/* Same-patient shell prefetch for Enter Encounter. Holds at most ONE patient's
   /internal/visits/ready promise; any other patient_ref replaces/clears it. */
const MAX_AGE_MS = 60_000;
const GRACE_MS = 1500;
let entry = null; // { ref, promise, at }

export function prefetchReady(ref) {
    if (!ref) return null;
    const fresh = entry && entry.ref === ref && Date.now() - entry.at < MAX_AGE_MS && !(entry.takenAt && Date.now() - entry.takenAt > GRACE_MS);
    if (fresh) return entry.promise;
    const promise = api.get("/internal/visits/ready", { params: { patient_ref: ref } }).then(({ data }) => data);
    promise.catch(() => { if (entry && entry.promise === promise) entry = null; });
    entry = { ref, promise, at: Date.now() };
    return promise;
}

/* Returns the cached promise for exactly this ref, else null. Consumed once (a short grace window
   tolerates React StrictMode's double effect); re-entering later always fetches fresh state. */
export function takeReady(ref) {
    if (!entry || entry.ref !== ref || Date.now() - entry.at >= MAX_AGE_MS) { entry = null; return null; }
    if (entry.takenAt && Date.now() - entry.takenAt > GRACE_MS) { entry = null; return null; }
    entry.takenAt = entry.takenAt || Date.now();
    return entry.promise;
}

export function clearReady(ref) {
    if (!ref || (entry && entry.ref === ref)) entry = null;
}
