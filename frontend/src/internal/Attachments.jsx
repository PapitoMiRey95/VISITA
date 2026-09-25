import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import { Paperclip, Upload, Trash2, Loader2, FileText, Image as ImageIcon } from "lucide-react";
import { api, formatErr, openAttachment } from "../lib/api";
import { Button } from "../components/ui/button";
import { formatDateTime } from "../lib/date";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

// Shared internal attachment panel for imaging / bloodwork / message records.
// PDF/JPG/PNG, 15 MB max. Files are private and served via authenticated routes.
export default function Attachments({ entityType, entityId }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
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
            toast.success("File attached.");
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
                        className="flex items-center gap-2 bg-slate-50 border border-slate-100 rounded px-2 py-1.5">
                        {isImg(att.content_type) ? <ImageIcon className="w-4 h-4 text-slate-400 shrink-0" /> : <FileText className="w-4 h-4 text-slate-400 shrink-0" />}
                        <button data-testid={`attachment-view-${att.id}`} onClick={() => view(att)}
                            className="flex-1 min-w-0 text-left text-xs text-visita-greenDark hover:underline truncate">
                            {att.original_filename || "attachment"}
                        </button>
                        <span className="text-[10px] text-slate-400 shrink-0">
                            {att.uploaded_by ? `${att.uploaded_by} · ` : ""}{att.uploaded_at ? formatDateTime(att.uploaded_at) : ""}
                        </span>
                        <button data-testid={`attachment-remove-${att.id}`} onClick={() => remove(att)}
                            className="text-slate-400 hover:text-red-600 shrink-0" title="Remove">
                            <Trash2 className="w-3.5 h-3.5" />
                        </button>
                    </div>
                ))}
            </div>
        </div>
    );
}
