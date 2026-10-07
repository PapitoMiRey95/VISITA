import { useState } from "react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { formatDateTime } from "../lib/date";

// Timestamped internal appointment notes. Adding a note never changes status/time.
export function InternalNotes({ appt, onSaved }) {
    const [text, setText] = useState("");
    const [busy, setBusy] = useState(false);
    const notes = appt?.internal_notes || [];

    const add = async () => {
        if (!text.trim()) return;
        setBusy(true);
        try {
            const r = await api.patch(`/internal/appointments/${appt.id}`, { action: "note", internal_note: text.trim() });
            setText("");
            toast.success("Internal note added.");
            onSaved?.(r.data);
        } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };

    return (
        <div className="border-t border-slate-200 pt-2" data-testid="internal-notes">
            <Label className="text-xs">Internal notes (staff only)</Label>
            <div className="space-y-1 mt-1 max-h-32 overflow-y-auto">
                {notes.length === 0 && <div className="text-xs text-slate-400">No internal notes.</div>}
                {[...notes].reverse().map((n, i) => (
                    <div key={`${n.at}-${i}`} className="text-xs bg-slate-50 border border-slate-200 rounded-sm px-2 py-1" data-testid="internal-note-row">
                        <span className="text-slate-800">{n.note}</span>
                        <div className="text-[10px] text-slate-400">{n.by} · {n.at ? formatDateTime(n.at) : ""}</div>
                    </div>
                ))}
            </div>
            <div className="flex gap-2 mt-2 items-start">
                <Textarea rows={1} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Doctor advised patient may arrive later — no action needed." data-testid="internal-note-input" className="text-xs" />
                <Button size="sm" variant="outline" disabled={busy || !text.trim()} onClick={add} data-testid="internal-note-add">Add note</Button>
            </div>
        </div>
    );
}
