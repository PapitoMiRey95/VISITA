import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import { Paperclip, Upload, Trash2, Loader2, FileText, Image as ImageIcon, Send, Lock, CheckCircle2, X } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useInvalidate } from "./hooks";
import { Button } from "../components/ui/button";
import { formatDateTime } from "../lib/date";
import { RESULT_TAXONOMY } from "../lib/resultTaxonomy";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
const SHARE_ROLES = ["staff", "physician", "admin"];

// Shared internal attachment panel for imaging / bloodwork / message records.
// PDF/JPG/PNG, 15 MB max. Files are private and served via authenticated routes.
// Attachments default to INTERNAL (staff/physician only). An explicit
// "Share with Patient & Complete" action releases a single document to the patient.
export default function Attachments({ entityType, entityId, onChanged }) {
    const { user } = useAuth();
    const invalidate = useInvalidate();
    const canShare = SHARE_ROLES.includes(user?.role);
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [sharingId, setSharingId] = useState(null);
    const [shareTarget, setShareTarget] = useState(null);
    const [shareForm, setShareForm] = useState({ category: "", subtype: "", reviewedBy: "", notify: true });
    const inputRef = useRef(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get(`/internal/${entityType}/${entityId}/attachments`);
            setItems(data);
        } catch (e) { toast.error(formatErr(e)); } finally { setLoading(false); }
    }, [entityType, entityId]);

    useEffect(() => { load(); }, [load]);

    const onPick = async (e) => {
        const file = e.target.files?.[0];
        if (inputRef.current) inputRef.current.value = "";
        if (!file) return;
        if (file.size > 15 * 1024 * 1024) { toast.error("File too large. Maximum size is 15 MB."); return; }
        setUploading(true);
        try {
            const fd = new FormData();
            fd.append("file", file);
            await api.post(`/internal/${entityType}/${entityId}/attachments`, fd,
                { headers: { "Content-Type": "multipart/form-data" } });
            toast.success("File attached (internal — not visible to patient).");
            await load();
        } catch (err) { toast.error(formatErr(err)); } finally { setUploading(false); }
    };

    const view = async (att) => {
        try { await openAttachment(`/internal/attachments/${att.id}/download`); }
        catch (err) { toast.error(formatErr(err)); }
    };

    const remove = async (att) => {
        try {
            await api.delete(`/internal/attachments/${att.id}`);
            toast.success("File removed.");
            await load();
        } catch (err) { toast.error(formatErr(err)); }
    };

    const openShare = (att) => {
        setShareForm({ category: "", subtype: "", reviewedBy: user?.role === "physician" ? (user?.name || "") : "", notify: true });
        setShareTarget(att);
    };

    const confirmShare = async () => {
        const att = shareTarget;
        if (!shareForm.category) { toast.error("Select a result category."); return; }
        if (!shareForm.reviewedBy.trim()) { toast.error("Enter the reviewing physician's name."); return; }
        const cat = RESULT_TAXONOMY.find((c) => c.value === shareForm.category);
        setSharingId(att.id);
        try {
            await api.post(`/internal/attachments/${att.id}/share`, {
                complete: entityType === "imaging",
                result_category: cat?.label || shareForm.category,
                result_subtype: shareForm.subtype || null,
                reviewed_by: shareForm.reviewedBy.trim(),
                notify: shareForm.notify,
            });
            toast.success(shareForm.notify ? "Result released to patient. Patient notified." : "Result released to patient.");
            setShareTarget(null);
            await load();
            invalidate();
            onChanged && onChanged();
        } catch (err) { toast.error(formatErr(err)); } finally { setSharingId(null); }
    };

    const isImg = (ct) => (ct || "").startsWith("image/");

    return (
        <div className="border border-slate-200 rounded p-2.5" data-testid="attachments-panel">
            <div className="flex items-center justify-between mb-2">
                <div className="text-xs uppercase tracking-wider text-slate-500 flex items-center gap-1">
                    <Paperclip className="w-3.5 h-3.5" /> Attachments
                </div>
                <input ref={inputRef} type="file" accept={ACCEPT} className="hidden"
                    data-testid="attachment-file-input" onChange={onPick} />
                <Button size="sm" variant="outline" disabled={uploading} data-testid="attachment-upload-btn"
                    onClick={() => inputRef.current?.click()} className="h-7 border-visita-green text-visita-greenDark">
                    {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5 mr-1" />}
                    {uploading ? "Uploading…" : "Attach PDF / JPG / PNG"}
                </Button>
            </div>

            {loading && <div className="text-xs text-slate-400 py-2">Loading…</div>}
            {!loading && items.length === 0 && (
                <div className="text-xs text-slate-400 py-2" data-testid="attachments-empty">No files attached yet.</div>
            )}

            <div className="space-y-1.5">
                {items.map((att) => (
                    <div key={att.id} data-testid={`attachment-row-${att.id}`}
                        className="bg-slate-50 border border-slate-100 rounded px-2 py-1.5">
                        <div className="flex items-center gap-2">
                            {isImg(att.content_type) ? <ImageIcon className="w-4 h-4 text-slate-400 shrink-0" /> : <FileText className="w-4 h-4 text-slate-400 shrink-0" />}
                            <button data-testid={`attachment-view-${att.id}`} onClick={() => view(att)}
                                className="flex-1 min-w-0 text-left text-xs text-visita-greenDark hover:underline truncate">
                                {att.original_filename || "attachment"}
                            </button>
                            {att.shared_with_patient ? (
                                <span data-testid={`attachment-badge-shared-${att.id}`} className="inline-flex items-center gap-1 text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 shrink-0">
                                    <CheckCircle2 className="w-3 h-3" /> Shared
                                </span>
                            ) : (
                                <span data-testid={`attachment-badge-internal-${att.id}`} className="inline-flex items-center gap-1 text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-slate-200 text-slate-600 shrink-0">
                                    <Lock className="w-3 h-3" /> Internal
                                </span>
                            )}
                            {!att.shared_with_patient && (
                                <button data-testid={`attachment-remove-${att.id}`} onClick={() => remove(att)}
                                    className="text-slate-400 hover:text-red-600 shrink-0" title="Remove">
                                    <Trash2 className="w-3.5 h-3.5" />
                                </button>
                            )}
                        </div>
                        <div className="flex items-center justify-between gap-2 mt-1 pl-6">
                            <span className="text-[10px] text-slate-400">
                                {att.shared_with_patient
                                    ? `Shared by ${att.shared_by || "—"} · ${att.shared_at ? formatDateTime(att.shared_at) : ""}`
                                    : `${att.uploaded_by ? `${att.uploaded_by} · ` : ""}${att.uploaded_at ? formatDateTime(att.uploaded_at) : ""}`}
                            </span>
                            {canShare && !att.shared_with_patient && (
                                <Button size="sm" variant="outline" disabled={sharingId === att.id}
                                    data-testid={`attachment-share-${att.id}`} onClick={() => openShare(att)}
                                    className="h-7 border-visita-green text-visita-greenDark">
                                    {sharingId === att.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5 mr-1" />}
                                    Review &amp; Release
                                </Button>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            {shareTarget && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" data-testid="share-dialog"
                    onClick={(e) => { if (e.target === e.currentTarget) setShareTarget(null); }}>
                    <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-4">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="font-bold text-slate-900 text-sm">Review &amp; Release to Patient</h3>
                            <button onClick={() => setShareTarget(null)} data-testid="share-dialog-close" className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
                        </div>
                        <p className="text-xs text-slate-500 mb-3 truncate">{shareTarget.original_filename}</p>

                        <label className="block text-xs font-semibold text-slate-600 mb-1">Result / report category</label>
                        <select data-testid="share-category" value={shareForm.category}
                            onChange={(e) => setShareForm((f) => ({ ...f, category: e.target.value, subtype: "" }))}
                            className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm mb-3">
                            <option value="">Select category…</option>
                            {RESULT_TAXONOMY.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                        </select>

                        {shareForm.category && (
                            <>
                                <label className="block text-xs font-semibold text-slate-600 mb-1">Subtype</label>
                                <select data-testid="share-subtype" value={shareForm.subtype}
                                    onChange={(e) => setShareForm((f) => ({ ...f, subtype: e.target.value }))}
                                    className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm mb-3">
                                    <option value="">(Optional) select subtype…</option>
                                    {(RESULT_TAXONOMY.find((c) => c.value === shareForm.category)?.subtypes || []).map((s) => <option key={s} value={s}>{s}</option>)}
                                </select>
                            </>
                        )}

                        <label className="block text-xs font-semibold text-slate-600 mb-1">Reviewed by physician</label>
                        <input data-testid="share-reviewed-by" value={shareForm.reviewedBy}
                            onChange={(e) => setShareForm((f) => ({ ...f, reviewedBy: e.target.value }))}
                            placeholder="Dr. Pablo Aguayo"
                            className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm mb-3" />

                        <label className="flex items-center gap-2 text-sm text-slate-700 mb-4">
                            <input type="checkbox" data-testid="share-notify" checked={shareForm.notify}
                                onChange={(e) => setShareForm((f) => ({ ...f, notify: e.target.checked }))} />
                            Notify the patient (generic message — never discloses normal/abnormal)
                        </label>

                        <div className="flex justify-end gap-2">
                            <Button size="sm" variant="outline" onClick={() => setShareTarget(null)}>Cancel</Button>
                            <Button size="sm" disabled={sharingId === shareTarget.id} data-testid="share-confirm"
                                onClick={confirmShare} className="bg-visita-green hover:bg-visita-greenDark text-white">
                                {sharingId === shareTarget.id ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Send className="w-3.5 h-3.5 mr-1" />}
                                Release{entityType === "imaging" ? " & Complete" : ""}
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
