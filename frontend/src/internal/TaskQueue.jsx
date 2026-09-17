import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Check, Send } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { useInvalidate } from "./hooks";
import { useAuth } from "../context/AuthContext";
import { StatusPill } from "./statusPill";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";

export default function TaskQueue() {
    const { user } = useAuth();
    const physician = user?.role === "physician";
    const invalidate = useInvalidate();
    const [form, setForm] = useState({ patient_name: "", message: "" });
    const [busy, setBusy] = useState(false);

    const list = useQuery({ queryKey: ["queue", "/internal/tasks"], queryFn: async () => (await api.get("/internal/tasks")).data });
    const items = list.data || [];

    const create = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            await api.post("/internal/tasks", {
                recipient_role: physician ? "staff" : "physician",
                patient_name: form.patient_name || undefined,
                message: form.message,
            });
            toast.success(physician ? "Task sent to clinic staff." : "Message sent to physician.");
            setForm({ patient_name: "", message: "" });
            invalidate(); list.refetch();
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };

    const patch = async (id, body) => {
        try { await api.patch(`/internal/tasks/${id}`, body); invalidate(); list.refetch(); toast.success("Updated."); }
        catch (e) { toast.error(formatErr(e)); }
    };

    return (
        <div className="animate-fade-in max-w-3xl">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
                {physician ? "Intercom — Messages from Staff" : "Doctor Tasks & Intercom"}
            </h1>
            <p className="text-sm text-slate-500 mb-4">Internal communication between clinic staff and physician.</p>

            <form onSubmit={create} className="bg-white border border-slate-300 rounded-sm p-4 mb-5 space-y-3">
                <div className="font-semibold text-slate-700 flex items-center gap-2">
                    <Plus className="w-4 h-4 text-visita-green" /> {physician ? "New Task for Staff" : "New Message to Doctor"}
                </div>
                <div className="grid grid-cols-3 gap-2">
                    <div><Label className="text-xs">Patient (optional)</Label><Input value={form.patient_name} onChange={(e) => setForm({ ...form, patient_name: e.target.value })} data-testid="task-patient" /></div>
                    <div className="col-span-2"><Label className="text-xs">Message</Label><Input required value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} data-testid="task-message" /></div>
                </div>
                <Button type="submit" disabled={busy} data-testid="task-submit" className="bg-visita-green hover:bg-visita-greenDark text-white">Send</Button>
            </form>

            <div className="space-y-2">
                {items.length === 0 && <p className="text-slate-400 text-sm">No items.</p>}
                {items.map((t) => (
                    <div key={t.id} data-testid="task-item" className="bg-white border border-slate-300 rounded-sm p-3 flex items-start justify-between gap-3">
                        <div className="text-sm">
                            <div className="text-xs text-slate-500">{t.ref_number} · FROM: {t.sender_name}{t.patient_name ? ` · PATIENT: ${t.patient_name}` : ""}</div>
                            <div className="text-slate-800 font-medium mt-0.5">{t.message}</div>
                            <div className="mt-1"><StatusPill status={t.status} /></div>
                        </div>
                        <div className="flex flex-col gap-1.5">
                            {t.status !== "completed" && (
                                <Button size="sm" onClick={() => patch(t.id, { action: "complete" })} data-testid="task-complete" className="bg-visita-green hover:bg-visita-greenDark text-white h-8">
                                    <Check className="w-4 h-4 mr-1" /> Complete
                                </Button>
                            )}
                            {!physician && t.recipient_role === "staff" && t.status !== "completed" && (
                                <Button size="sm" variant="outline" onClick={() => patch(t.id, { action: "send_to_physician" })} data-testid="task-escalate" className="h-8">
                                    <Send className="w-4 h-4 mr-1" /> Send to Doctor
                                </Button>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
