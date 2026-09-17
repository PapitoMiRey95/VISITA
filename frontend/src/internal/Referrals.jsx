import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload, FileText, Download, Send, CheckCircle2, History } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function Referrals() {
    const { user } = useAuth();
    const canUpload = user?.role === "physician" || user?.role === "admin";
    const canFax = user?.role === "staff" || user?.role === "admin";
    const invalidate = useInvalidate();
    const [tab, setTab] = useState("active");
    const [file, setFile] = useState(null);
    const [meta, setMeta] = useState({ patient_name: "", specialty: "", specialist_name: "", clinic_name: "", fax_number: "" });
    const [busy, setBusy] = useState(false);
    const [q, setQ] = useState("");

    const active = useQuery({ queryKey: ["queue", "/internal/referrals"], queryFn: async () => (await api.get("/internal/referrals")).data });
    const history = useQuery({ queryKey: ["queue", "/internal/referrals/history", q], queryFn: async () => (await api.get("/internal/referrals/history", { params: { q: q || undefined } })).data, enabled: tab === "history" });

    const upload = async (e) => {
        e.preventDefault();
        if (!file) return toast.error("Please choose a PDF file.");
        setBusy(true);
        try {
            const fd = new FormData();
            fd.append("file", file);
            Object.entries(meta).forEach(([k, v]) => fd.append(k, v));
            await api.post("/internal/referrals", fd);
            toast.success("Referral uploaded — now Ready to Fax.");
            setFile(null); setMeta({ patient_name: "", specialty: "", specialist_name: "", clinic_name: "", fax_number: "" });
            invalidate(); active.refetch();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const getPdf = async (item, download) => {
        try {
            const res = await api.get(`/internal/referrals/${item.id}/download`, { responseType: "blob" });
            const url = URL.createObjectURL(res.data);
            if (download) {
                const a = document.createElement("a");
                a.href = url; a.download = `${item.original_filename || "referral"}.pdf`; a.click();
            } else {
                window.open(url, "_blank");
            }
            setTimeout(() => URL.revokeObjectURL(url), 15000);
        } catch (e) { toast.error(formatErr(e)); }
    };

    const markFaxed = async (item) => {
        try {
            await api.post(`/internal/referrals/${item.id}/fax`, {});
            toast.success("Marked as faxed. Referral moved to history.");
            invalidate(); active.refetch();
        } catch (e) { toast.error(formatErr(e)); }
    };

    const activeItems = active.data || [];

    return (
        <div className="animate-fade-in max-w-4xl">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Referrals — Ready to Fax</h1>
            <p className="text-sm text-slate-500 mb-4">Completed referral PDFs waiting to be faxed via Bell Online Fax.</p>

            {canUpload && (
                <form onSubmit={upload} className="bg-white border border-slate-300 rounded-sm p-4 mb-5 space-y-3">
                    <div className="font-semibold text-slate-700 flex items-center gap-2"><Upload className="w-4 h-4 text-visita-green" /> Referral Drop-Off (upload completed PDF from VISITA EMR)</div>
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                        <div><Label className="text-xs">Patient name</Label><Input value={meta.patient_name} onChange={(e) => setMeta({ ...meta, patient_name: e.target.value })} data-testid="ref-patient" /></div>
                        <div><Label className="text-xs">Specialty</Label><Input value={meta.specialty} onChange={(e) => setMeta({ ...meta, specialty: e.target.value })} data-testid="ref-specialty" /></div>
                        <div><Label className="text-xs">Specialist / Clinic</Label><Input value={meta.specialist_name} onChange={(e) => setMeta({ ...meta, specialist_name: e.target.value })} data-testid="ref-specialist" /></div>
                        <div><Label className="text-xs">Destination fax</Label><Input value={meta.fax_number} onChange={(e) => setMeta({ ...meta, fax_number: e.target.value })} data-testid="ref-fax" /></div>
                        <div className="md:col-span-2">
                            <Label className="text-xs">PDF file</Label>
                            <Input type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} data-testid="ref-file" />
                        </div>
                    </div>
                    <Button type="submit" disabled={busy} data-testid="ref-upload-submit" className="bg-visita-green hover:bg-visita-greenDark text-white">
                        {busy ? "Uploading…" : "Upload → Ready to Fax"}
                    </Button>
                </form>
            )}

            <div className="flex gap-1 mb-3">
                <button onClick={() => setTab("active")} data-testid="tab-active" className={`px-3 py-1.5 rounded-sm text-sm font-medium border ${tab === "active" ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-300"}`}>Ready to Fax ({activeItems.length})</button>
                <button onClick={() => setTab("history")} data-testid="tab-history" className={`px-3 py-1.5 rounded-sm text-sm font-medium border flex items-center gap-1 ${tab === "history" ? "bg-visita-green text-white border-visita-green" : "bg-white text-slate-600 border-slate-300"}`}><History className="w-4 h-4" /> Faxed History</button>
            </div>

            {tab === "active" && (
                <div className="space-y-2">
                    {activeItems.length === 0 && <p className="text-slate-400 text-sm">No referrals waiting to be faxed.</p>}
                    {activeItems.map((r) => (
                        <div key={r.id} data-testid="referral-item" className="bg-white border border-slate-300 rounded-sm p-3 flex items-center justify-between gap-3">
                            <div className="flex items-center gap-3 text-sm min-w-0">
                                <FileText className="w-8 h-8 text-visita-green flex-shrink-0" />
                                <div className="min-w-0">
                                    <div className="font-semibold text-slate-800">{r.patient_name} · {r.specialty || "Referral"}</div>
                                    <div className="text-slate-500 text-xs">{r.ref_number} · {r.specialist_name || ""} {r.clinic_name ? `(${r.clinic_name})` : ""} · Fax: {r.fax_number || "—"} · {r.referral_date}</div>
                                    <div className="text-xs text-emerald-600 font-semibold flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> PDF available</div>
                                </div>
                            </div>
                            <div className="flex gap-1.5 flex-shrink-0">
                                <Button size="sm" variant="outline" onClick={() => getPdf(r, false)} data-testid="ref-open">Open PDF</Button>
                                <Button size="sm" variant="outline" onClick={() => getPdf(r, true)} data-testid="ref-download"><Download className="w-4 h-4" /></Button>
                                {canFax && <Button size="sm" onClick={() => markFaxed(r)} data-testid="ref-mark-faxed" className="bg-visita-green hover:bg-visita-greenDark text-white"><Send className="w-4 h-4 mr-1" /> Mark as Faxed</Button>}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {tab === "history" && (
                <div>
                    <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search faxed referrals…" className="h-9 w-64 bg-white mb-3" data-testid="history-search" />
                    <div className="space-y-2">
                        {(history.data || []).length === 0 && <p className="text-slate-400 text-sm">No faxed referrals yet.</p>}
                        {(history.data || []).map((r) => (
                            <div key={r.id} className="bg-white border border-slate-300 rounded-sm p-3 flex items-center justify-between gap-3 text-sm">
                                <div>
                                    <div className="font-semibold text-slate-800">{r.patient_name} · {r.specialty || "Referral"}</div>
                                    <div className="text-slate-500 text-xs">{r.ref_number} · Faxed by {r.faxed_by} · {r.faxed_at ? new Date(r.faxed_at).toLocaleString() : ""}</div>
                                </div>
                                <Button size="sm" variant="outline" onClick={() => getPdf(r, false)}>Open PDF</Button>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
