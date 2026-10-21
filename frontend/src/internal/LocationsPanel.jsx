import { useEffect, useState } from "react";
import { toast } from "sonner";
import { MapPin, Plus, Pencil, Trash2, Phone, Printer } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { AddressFields, emptyAddress, useAddressOptions } from "../components/AddressFields";

// Shared locations manager: a professional's practice locations, or standalone referral destinations (no named physician).
const emptyLoc = (entityType) => ({ ...emptyAddress(), label: "", phone: "", fax: "", specialty: "", address_type: entityType === "destination" ? "HOSPITAL" : "PRACTICE", address_subtype: entityType === "destination" ? "REFERRAL_INTAKE" : "" });

export function useLocations(entityType, entityId) {
    const [rows, setRows] = useState([]);
    const load = () => api.get("/internal/locations", { params: { entity_type: entityType, entity_id: entityId || undefined } }).then(({ data }) => setRows(data)).catch(() => setRows([]));
    useEffect(() => { load(); }, [entityType, entityId]);  // eslint-disable-line react-hooks/exhaustive-deps
    return [rows, load];
}

export function LocationCard({ loc, onEdit, onRemove, compact = false }) {
    return (
        <div className="border border-slate-200 rounded-sm px-2.5 py-2 text-sm" data-testid="location-card">
            <div className="flex items-start gap-2">
                <MapPin className="w-4 h-4 mt-0.5 text-visita-green shrink-0" />
                <div className="flex-1 min-w-0">
                    <div className="font-semibold text-slate-800 break-words">{loc.label || loc.address_subtype_label || loc.address_type_label || "Location"}{loc.specialty && <span className="font-normal text-slate-500"> · {loc.specialty}</span>}</div>
                    <div className="text-slate-700 break-words" data-testid="location-line">{loc.display_line || "—"}</div>
                    <div className="flex flex-wrap gap-x-3 text-xs text-slate-500 mt-0.5">
                        {(loc.address_type_label || loc.address_subtype_label) && <span>{[loc.address_type_label, loc.address_subtype_label].filter(Boolean).join(" · ")}</span>}
                        {loc.phone && <span className="inline-flex items-center gap-1"><Phone className="w-3 h-3" />{loc.phone}</span>}
                        {loc.fax && <span className="inline-flex items-center gap-1"><Printer className="w-3 h-3" />Fax {loc.fax}</span>}
                    </div>
                </div>
                {!compact && onEdit && <button type="button" onClick={onEdit} data-testid="location-edit" className="text-slate-400 hover:text-slate-700"><Pencil className="w-3.5 h-3.5" /></button>}
                {!compact && onRemove && <button type="button" onClick={onRemove} data-testid="location-remove" className="text-slate-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>}
            </div>
        </div>
    );
}

export function LocationForm({ entityType, entityId, initial, onSaved, onCancel }) {
    const options = useAddressOptions();
    const [f, setF] = useState(initial ? { ...emptyLoc(entityType), ...initial } : emptyLoc(entityType));
    const [busy, setBusy] = useState(false);
    const isDest = entityType === "destination";
    const submit = async (e) => {
        e.preventDefault(); setBusy(true);
        try {
            const body = { ...f, entity_type: entityType, entity_id: entityId || null };
            const { data } = initial?.id ? await api.patch(`/internal/locations/${initial.id}`, body) : await api.post("/internal/locations", body);
            toast.success(initial?.id ? "Location updated." : "Location added."); onSaved(data);
        } catch (err) { toast.error(formatErr(err)); } finally { setBusy(false); }
    };
    return (
        <form onSubmit={submit} className="space-y-2 border border-slate-300 bg-slate-50 rounded-sm p-3" data-testid="location-form">
            <div className="grid grid-cols-6 gap-2">
                <div className={isDest ? "col-span-4" : "col-span-6"}><Label className="text-xs">{isDest ? "Destination name *" : "Location name"} <span className="text-slate-400 font-normal">{isDest ? "(e.g. Mount Sinai Hospital — Cardiology Referral Service)" : "(e.g. Downtown office)"}</span></Label>
                    <Input data-testid="location-label" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} /></div>
                {isDest && <div className="col-span-2"><Label className="text-xs">Specialty</Label><Input data-testid="location-specialty" value={f.specialty} onChange={(e) => setF({ ...f, specialty: e.target.value })} placeholder="Cardiology" /></div>}
            </div>
            <AddressFields value={f} onChange={(v) => setF({ ...f, ...v })} options={options} testid="location" />
            <div className="grid grid-cols-2 gap-2">
                <div><Label className="text-xs">Phone at this location</Label><Input data-testid="location-phone" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} placeholder="416-555-0100" /></div>
                <div><Label className="text-xs">Fax at this location</Label><Input data-testid="location-fax" value={f.fax} onChange={(e) => setF({ ...f, fax: e.target.value })} placeholder="416-555-0101" /></div>
            </div>
            <div className="flex justify-end gap-2">
                <Button type="button" size="sm" variant="outline" onClick={onCancel} data-testid="location-cancel">Cancel</Button>
                <Button type="submit" size="sm" disabled={busy} data-testid="location-save" className="bg-visita-green hover:bg-visita-greenDark text-white">{initial?.id ? "Save location" : "Add location"}</Button>
            </div>
        </form>
    );
}

export default function LocationsPanel({ entityType, entityId, title = "Locations", canEdit = true }) {
    const [rows, reload] = useLocations(entityType, entityId);
    const [editing, setEditing] = useState(null);  // null | "new" | loc
    const remove = async (loc) => {
        if (!window.confirm(`Remove "${loc.label || loc.display_line}"? It is kept in history, not deleted.`)) return;
        try { await api.delete(`/internal/locations/${loc.id}`); toast.success("Location removed."); reload(); } catch (err) { toast.error(formatErr(err)); }
    };
    return (
        <div className="space-y-2" data-testid={`locations-panel-${entityType}`}>
            <div className="flex items-center justify-between">
                <div className="text-xs uppercase tracking-wide text-slate-500 font-semibold flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> {title} ({rows.length})</div>
                {canEdit && editing === null && <Button size="sm" variant="outline" onClick={() => setEditing("new")} data-testid="location-add" className="h-7 text-xs border-visita-green text-visita-greenDark"><Plus className="w-3.5 h-3.5 mr-1" /> Add location</Button>}
            </div>
            {rows.length === 0 && editing === null && <p className="text-xs text-slate-400">No locations yet.</p>}
            {rows.map((l) => (editing && editing.id === l.id
                ? <LocationForm key={l.id} entityType={entityType} entityId={entityId} initial={l} onSaved={() => { setEditing(null); reload(); }} onCancel={() => setEditing(null)} />
                : <LocationCard key={l.id} loc={l} onEdit={canEdit ? () => setEditing(l) : null} onRemove={canEdit ? () => remove(l) : null} />))}
            {editing === "new" && <LocationForm entityType={entityType} entityId={entityId} onSaved={() => { setEditing(null); reload(); }} onCancel={() => setEditing(null)} />}
        </div>
    );
}
