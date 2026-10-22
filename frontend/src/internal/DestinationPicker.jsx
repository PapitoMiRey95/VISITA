import { useEffect, useState } from "react";
import { MapPin } from "lucide-react";
import { api } from "../lib/api";
import { Label } from "../components/ui/label";

// Referral destination picker: any saved location (named specialist office, or hospital / specialty intake with no physician).
// Selecting one fills the referral's Specialist/Clinic + Destination fax from THAT location's contact details.
export function DestinationPicker({ onPick }) {
    const [rows, setRows] = useState([]);
    const [value, setValue] = useState("");
    useEffect(() => { api.get("/internal/locations").then(({ data }) => setRows(data.filter((l) => l.fax || l.address))).catch(() => setRows([])); }, []);
    if (rows.length === 0) return null;
    const label = (l) => `${l.entity_name ? `${l.entity_name} — ` : ""}${l.label || l.location_subtype_label || l.location_type_label || "Location"}${l.specialty ? ` (${l.specialty})` : ""} · ${l.city || ""}${l.fax ? ` · Fax ${l.fax}` : " · no fax on file"}`;
    return (
        <div className="md:col-span-2">
            <Label className="text-xs flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> Pick a saved destination <span className="text-slate-400 font-normal">(fills Specialist / Clinic and fax from that location)</span></Label>
            <select data-testid="ref-destination-picker" value={value} className="flex h-9 w-full rounded-sm border border-slate-300 bg-white px-2 text-sm"
                onChange={(e) => { setValue(e.target.value); const l = rows.find((x) => x.id === e.target.value); if (l) onPick(l); }}>
                <option value="">— Type manually or choose —</option>
                {rows.map((l) => <option key={l.id} value={l.id}>{label(l)}</option>)}
            </select>
        </div>
    );
}
