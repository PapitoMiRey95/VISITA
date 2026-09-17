import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle,
} from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";

export default function Queue({ title, subtitle, endpoint, patchBase, searchPlaceholder, statuses = [], columns, detail, actions, replyEnabled = false }) {
    const { user } = useAuth();
    const invalidate = useInvalidate();
    const [q, setQ] = useState("");
    const [status, setStatus] = useState("");
    const [selected, setSelected] = useState(null);
    const [note, setNote] = useState("");
    const [reply, setReply] = useState("");
    const [busy, setBusy] = useState(false);

    const list = useQuery({
        queryKey: ["queue", endpoint, q, status],
        queryFn: async () => (await api.get(endpoint, { params: { q: q || undefined, status: status || undefined } })).data,
    });

    const open = (item) => { setSelected(item); setNote(""); setReply(""); };
    const close = () => setSelected(null);

    const run = async (body) => {
        setBusy(true);
        try {
            const payload = { ...body };
            if (note) payload.internal_note = note;
            if (reply) payload.patient_reply = reply;
            await api.patch(`${patchBase}/${selected.id}`, payload);
            toast.success("Updated.");
            invalidate();
            list.refetch();
            close();
        } catch (err) {
            toast.error(formatErr(err));
        } finally {
            setBusy(false);
        }
    };

    const items = list.data || [];
    const acts = selected ? actions(selected, user) : [];

    return (
        <div className="animate-fade-in">
            <div className="flex items-end justify-between mb-3">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{title}</h1>
                    <p className="text-sm text-slate-500">{subtitle}</p>
                </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 mb-3">
                <div className="relative">
                    <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                    <Input data-testid="queue-search" value={q} onChange={(e) => setQ(e.target.value)}
                        placeholder={searchPlaceholder || "Search…"} className="pl-8 h-9 w-64 bg-white" />
                </div>
                {statuses.length > 0 && (
                    <div className="flex gap-1">
                        <FilterChip active={status === ""} onClick={() => setStatus("")}>All</FilterChip>
                        {statuses.map((s) => (
                            <FilterChip key={s.value} active={status === s.value} onClick={() => setStatus(s.value)}>{s.label}</FilterChip>
                        ))}
                    </div>
                )}
            </div>

            <div className="bg-white border border-slate-300 rounded-sm overflow-hidden">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="bg-slate-100 text-left text-xs uppercase tracking-wider text-slate-600">
                            {columns.map((col, i) => <th key={i} className="px-3 py-2 font-medium">{col.header}</th>)}
                            <th className="px-3 py-2" />
                        </tr>
                    </thead>
                    <tbody>
                        {items.length === 0 && (
                            <tr><td colSpan={columns.length + 1} className="px-3 py-8 text-center text-slate-400">No items in this queue.</td></tr>
                        )}
                        {items.map((item) => (
                            <tr key={item.id} data-testid="queue-row"
                                className="border-b border-slate-200 even:bg-slate-50/60 hover:bg-visita-bg cursor-pointer"
                                onClick={() => open(item)}>
                                {columns.map((col, i) => <td key={i} className="px-3 py-2 align-top">{col.cell(item)}</td>)}
                                <td className="px-3 py-2 text-right">
                                    <Button size="sm" variant="ghost" className="h-7 text-visita-green" data-testid="queue-open">Open</Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <Dialog open={!!selected} onOpenChange={(o) => !o && close()}>
                <DialogContent className="max-w-lg font-plex">
                    {selected && (
                        <>
                            <DialogHeader>
                                <DialogTitle className="text-lg">{selected.ref_number} · {selected.patient_name}</DialogTitle>
                            </DialogHeader>
                            <div className="space-y-3 text-sm">
                                {detail(selected)}

                                {(selected.internal_notes || []).length > 0 && (
                                    <div className="bg-slate-50 border border-slate-200 rounded p-2">
                                        <div className="text-xs uppercase text-slate-500 mb-1">Internal notes</div>
                                        {selected.internal_notes.map((n, i) => (
                                            <div key={i} className="text-slate-700"><b>{n.by}:</b> {n.note}</div>
                                        ))}
                                    </div>
                                )}

                                {replyEnabled && (
                                    <div>
                                        <div className="text-xs uppercase text-slate-500 mb-1">Reply to patient (visible to patient)</div>
                                        <Textarea data-testid="patient-reply" value={reply} onChange={(e) => setReply(e.target.value)} rows={2} />
                                    </div>
                                )}

                                <div>
                                    <div className="text-xs uppercase text-slate-500 mb-1">Add internal note (staff only)</div>
                                    <Textarea data-testid="internal-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
                                </div>

                                <div className="flex flex-wrap gap-2 pt-1">
                                    {acts.map((a) => (
                                        <Button key={a.label} data-testid={a.testid} disabled={busy} onClick={() => run(a.body)}
                                            variant={a.variant || "default"}
                                            className={a.variant ? "" : "bg-visita-green hover:bg-visita-greenDark text-white"}>
                                            {a.label}
                                        </Button>
                                    ))}
                                </div>
                            </div>
                        </>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}

function FilterChip({ active, onClick, children }) {
    return (
        <button onClick={onClick} data-testid={`filter-${String(children).toLowerCase()}`}
            className={`px-2.5 py-1 rounded-sm text-xs font-medium border transition-colors duration-75 ${active ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-300 hover:bg-slate-50"}`}>
            {children}
        </button>
    );
}

export function KV({ label, children }) {
    return (
        <div className="flex gap-2">
            <span className="text-slate-500 w-28 flex-shrink-0">{label}</span>
            <span className="text-slate-800 font-medium">{children || "—"}</span>
        </div>
    );
}
