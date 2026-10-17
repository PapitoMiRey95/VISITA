import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { History, Rocket, Trash2, Undo2 } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { formatDateTime } from "../lib/date";

// Operator attribution: the development organization is shown; the real individual stays in actor_* / audit.
export const operatorLabel = (by, brand = "OAKMONT Developers") => (!by ? "" : by.role === "developer_ops" ? brand : by.name);

export function usePlatformConfigAdmin() {
    return useQuery({ queryKey: ["developer-platform-config"], queryFn: async () => (await api.get("/developer/platform-config")).data });
}

export const Card = ({ title, children, testid, right }) => (
    <section className="bg-slate-900/70 border border-slate-800 rounded-md p-5" data-testid={testid}>
        <div className="flex items-center justify-between mb-3"><h2 className="text-sm font-bold text-slate-200">{title}</h2>{right}</div>
        {children}
    </section>
);

export async function saveDraft(section, data) {
    await api.put("/developer/platform-config/draft", { section, data });
}

// Draft -> PUBLISH / discard, plus version history with ROLLBACK. Shared by Features and Public Site.
export function PublishBar({ cfg, onChanged }) {
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState(false);
    const draft = cfg?.draft;
    const act = async (fn, ok) => {
        setBusy(true);
        try { await fn(); toast.success(ok); setConfirm(""); onChanged(); } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <Card title="Publish" testid="pc-publish" right={<span className="text-xs text-slate-400">live v{cfg?.published?.version ?? 0}{draft ? " · DRAFT pending" : ""}</span>}>
            {!draft && <div className="text-xs text-slate-500 mb-2" data-testid="pc-no-draft">No draft changes. Edit Features or Public Site to create a draft.</div>}
            {draft && <div className="text-xs text-amber-300 mb-2" data-testid="pc-draft-info">Draft based on v{draft.based_on_version}, updated {formatDateTime(draft.updated_at)} by <span data-testid="pc-draft-by">{operatorLabel(draft.updated_by, cfg.published?.config?.branding?.operator_name)}</span>. Preview is shown in the editors below.</div>}
            <div className="flex flex-wrap items-center gap-2">
                <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Type PUBLISH" className="h-8 w-40 text-xs bg-slate-950 border-slate-700 text-slate-100" data-testid="pc-publish-confirm" />
                <Button size="sm" disabled={busy || !draft || confirm !== "PUBLISH"} onClick={() => act(() => api.post("/developer/platform-config/publish", { confirm }), "Platform configuration published")} className="bg-emerald-500 hover:bg-emerald-400 text-slate-900" data-testid="pc-publish-btn"><Rocket className="w-3.5 h-3.5 mr-1" /> Publish</Button>
                <Button size="sm" variant="outline" disabled={busy || !draft} onClick={() => act(() => api.delete("/developer/platform-config/draft"), "Draft discarded")} className="border-slate-600 text-slate-200" data-testid="pc-discard-btn"><Trash2 className="w-3.5 h-3.5 mr-1" /> Discard draft</Button>
            </div>
            <h3 className="text-xs font-bold text-slate-400 mt-4 mb-1 flex items-center gap-1"><History className="w-3.5 h-3.5" /> Version history</h3>
            <ul className="text-xs space-y-1" data-testid="pc-history">
                {(cfg?.history || []).map((h) => (
                    <li key={h.version} className="flex flex-wrap items-center gap-2 border-b border-slate-800 py-1" data-testid={`pc-history-v${h.version}`}>
                        <span className="font-mono">v{h.version}</span>
                        <span className={`px-1.5 rounded-sm font-bold ${h.status === "PUBLISHED" ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-700 text-slate-300"}`}>{h.status}</span>
                        <span className="text-slate-400">{formatDateTime(h.published_at)} · <span data-testid="pc-history-by">{h.published_by?.name === "system" ? "system" : operatorLabel(h.published_by, cfg.published?.config?.branding?.operator_name)}</span></span>
                        <span className="text-slate-500 truncate max-w-xs">{h.note}</span>
                        {h.status !== "PUBLISHED" && (
                            <Button size="sm" variant="ghost" disabled={busy || confirm !== "ROLLBACK"} title='Type ROLLBACK in the box above first' className="h-6 text-amber-300 ml-auto" data-testid={`pc-rollback-v${h.version}`}
                                onClick={() => act(() => api.post("/developer/platform-config/rollback", { confirm: "ROLLBACK", version: h.version }), `Rolled back to v${h.version}`)}>
                                <Undo2 className="w-3.5 h-3.5 mr-1" /> Restore
                            </Button>
                        )}
                    </li>
                ))}
            </ul>
            <div className="text-[11px] text-slate-500 mt-1">To restore a previous version type <b>ROLLBACK</b> in the confirmation box, then click Restore.</div>
        </Card>
    );
}
