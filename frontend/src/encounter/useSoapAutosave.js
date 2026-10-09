import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

const FIELDS = ["subjective", "objective", "assessment", "plan"];

/* Server-backed SOAP autosave: debounce 1.5s, save on blur, explicit flush() for Exit.
   No localStorage. State: idle | dirty | saving | saved | failed */
export function useSoapAutosave(visitId, initial) {
    const [soap, setSoap] = useState(() => ({ subjective: "", objective: "", assessment: "", plan: "", ...(initial || {}) }));
    const [state, setState] = useState("idle");
    const [savedAt, setSavedAt] = useState(initial?.last_saved_at || null);
    const lastSaved = useRef({ ...soap });
    const timer = useRef(null);
    const inflight = useRef(null);

    const diff = useCallback((cur) => {
        const d = {};
        FIELDS.forEach((k) => { if (cur[k] !== lastSaved.current[k]) d[k] = cur[k]; });
        return d;
    }, []);

    const save = useCallback(async (cur) => {
        const d = diff(cur);
        if (!Object.keys(d).length) { setState((s) => (s === "dirty" ? "saved" : s)); return true; }
        setState("saving");
        const p = api.patch(`/internal/visits/${visitId}/soap`, d)
            .then(({ data }) => { lastSaved.current = { ...lastSaved.current, ...d }; setSavedAt(data.last_saved_at || savedAt); setState("saved"); return true; })
            .catch(() => { setState("failed"); return false; });
        inflight.current = p;
        return p;
    }, [visitId, diff, savedAt]);

    const soapRef = useRef(soap);
    soapRef.current = soap;

    const onChange = (k, v) => {
        const next = { ...soapRef.current, [k]: v };
        setSoap(next);
        setState("dirty");
        clearTimeout(timer.current);
        timer.current = setTimeout(() => save(soapRef.current), 1500);
    };
    const onBlur = () => { clearTimeout(timer.current); save(soapRef.current); };

    /* Explicit helper insertion: append (never overwrite) then run the normal autosave path. */
    const insertText = (sections) => {
        const cur = soapRef.current;
        const next = { ...cur };
        Object.entries(sections).forEach(([k, text]) => {
            if (!FIELDS.includes(k) || !text) return;
            next[k] = cur[k] && cur[k].trim() ? `${cur[k].replace(/\s+$/, "")}\n\n${text}` : text;
        });
        setSoap(next);
        soapRef.current = next;
        setState("dirty");
        clearTimeout(timer.current);
        timer.current = setTimeout(() => save(soapRef.current), 1500);
    };

    const flush = useCallback(async () => {
        clearTimeout(timer.current);
        if (inflight.current) await inflight.current;
        return save(soapRef.current);
    }, [save]);

    useEffect(() => () => clearTimeout(timer.current), []);
    return { soap, onChange, onBlur, insertText, state, savedAt, flush };
}
