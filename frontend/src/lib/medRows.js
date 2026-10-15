// Stable per-row identity for editable medication lists. React keys must not be array
// indexes here: MedEditPanel / PharmacyMedCard hold local dose/frequency/timing state, so an
// index key would re-attach that state to the wrong medication after a middle-row delete.
let seq = 0;
const newUid = () => (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `med-${Date.now()}-${++seq}`);

export const withUids = (rows) => (rows || []).map((m) => (m && m._uid ? m : { ...m, _uid: newUid() }));

export const useMedRows = (useState, useCallback) => {
    const [meds, setRaw] = useState([]);
    const setMeds = useCallback((v) => setRaw((s) => withUids(typeof v === "function" ? v(s) : v)), []);
    return [meds, setMeds];
};
