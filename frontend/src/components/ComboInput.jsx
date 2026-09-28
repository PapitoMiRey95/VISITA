import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Input } from "./ui/input";

// Searchable + typeable combo. Free-text is always allowed (value === what's typed);
// suggestions are convenience only. Keyboard: ArrowUp/Down navigate, Enter selects,
// Escape closes. Suggestions are ranked by the caller (patient → physician → catalog → vocab).
export const ComboInput = ({ value, onChange, options = [], placeholder, testId, disabled, className }) => {
    const [open, setOpen] = useState(false);
    const [hi, setHi] = useState(-1);
    const boxRef = useRef(null);
    const q = (value || "").toLowerCase().trim();

    const filtered = (open
        ? options.filter((o) => !q || o.value.toLowerCase().includes(q))
        : []
    ).slice(0, 20);

    useEffect(() => {
        const h = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
        document.addEventListener("mousedown", h);
        return () => document.removeEventListener("mousedown", h);
    }, []);

    const pick = (v) => { onChange(v); setOpen(false); setHi(-1); };

    const onKey = (e) => {
        if (!open && e.key === "ArrowDown") { setOpen(true); return; }
        if (!open) return;
        if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, filtered.length - 1)); }
        else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
        else if (e.key === "Enter") { if (hi >= 0 && filtered[hi]) { e.preventDefault(); pick(filtered[hi].value); } }
        else if (e.key === "Escape") { setOpen(false); }
    };

    return (
        <div className="relative" ref={boxRef}>
            <Input
                data-testid={testId}
                value={value || ""}
                disabled={disabled}
                placeholder={placeholder}
                autoComplete="off"
                className={`pr-7 ${className || ""}`}
                onChange={(e) => { onChange(e.target.value); setOpen(true); setHi(-1); }}
                onFocus={() => setOpen(true)}
                onKeyDown={onKey}
            />
            <ChevronDown className="w-3.5 h-3.5 absolute right-2 top-2.5 text-slate-400 pointer-events-none" />
            {open && filtered.length > 0 && (
                <div className="absolute z-50 mt-1 w-full bg-white border border-slate-200 rounded-sm shadow-lg max-h-56 overflow-auto" data-testid={testId ? `${testId}-list` : undefined}>
                    {filtered.map((o, idx) => (
                        <button
                            type="button"
                            key={`${o.value}-${idx}`}
                            onMouseDown={(e) => { e.preventDefault(); pick(o.value); }}
                            className={`w-full text-left px-3 py-1.5 text-sm flex items-center justify-between gap-2 ${idx === hi ? "bg-slate-100" : "hover:bg-slate-50"}`}
                        >
                            <span className="truncate">{o.value}</span>
                            {o.source && <span className="text-[10px] uppercase tracking-wide text-slate-400 shrink-0">{o.source}</span>}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
};
