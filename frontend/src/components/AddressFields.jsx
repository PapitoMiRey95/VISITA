import { useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { api } from "../lib/api";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Button } from "./ui/button";

// ONE reusable VIen address-entry system (Dr. Aguayo's pools):
//   Street Number · Address (street name) · Address Type (Avenue…) · Address Subtype (East/North/South/West) · Unit · Postal Code · City · Province
// Server-backed autocomplete (no giant dropdowns). Postal Code Pool assists City/Province; unknown postal never blocks.
// internal=true → "+ Add Postal Code" / "+ Add Address" write to the shared pools. internal=false (patients) → read-only lookup.
const SELECT = "flex h-9 w-full rounded-sm border border-slate-300 bg-white px-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500";
export const emptyAddress = () => ({ street_number: "", street_name: "", street_type: "", street_direction: "", unit: "", postal_code: "", city: "", province: "ON", country: "Canada" });
export const assembleStreet = (a) => { const core = [a.street_number, a.street_name, a.street_type, a.street_direction].map((x) => (x || "").trim()).filter(Boolean).join(" "); return a.unit?.trim() ? (core ? `${core}, ${a.unit.trim()}` : a.unit.trim()) : core; };
export const normPostal = (p) => (p || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();

// Lightweight server-backed autocomplete (favourites arrive first from the API).
function Suggest({ value, onChange, onPick, fetcher, testid, placeholder, minChars = 1, addLabel, onAdd }) {
    const [items, setItems] = useState([]); const [open, setOpen] = useState(false); const box = useRef(null);
    useEffect(() => {
        if (!open || value.trim().length < minChars) { setItems([]); return; }
        const t = setTimeout(() => fetcher(value.trim()).then((rows) => setItems(rows || [])).catch(() => setItems([])), 150);
        return () => clearTimeout(t);
    }, [value, open, fetcher, minChars]);
    useEffect(() => { const h = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); }; document.addEventListener("mousedown", h); return () => document.removeEventListener("mousedown", h); }, []);
    const exact = items.some((i) => i.name.toLowerCase() === value.trim().toLowerCase());
    return (
        <div ref={box} className="relative">
            <Input data-testid={testid} value={value} onChange={(e) => { onChange(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} placeholder={placeholder} autoComplete="off" />
            {open && (items.length > 0 || (onAdd && value.trim().length >= 2 && !exact)) && (
                <div className="absolute z-30 mt-1 w-full max-h-52 overflow-y-auto rounded-sm border border-slate-300 bg-white shadow-lg text-sm" data-testid={`${testid}-list`}>
                    {items.map((i) => <button type="button" key={i.name} onMouseDown={() => { onPick(i); setOpen(false); }} className="w-full text-left px-2 py-1.5 hover:bg-slate-100 flex justify-between"><span>{i.name}</span>{i.favourite && <span className="text-[10px] text-visita-greenDark">★</span>}</button>)}
                    {onAdd && value.trim().length >= 2 && !exact && <button type="button" data-testid={`${testid}-add`} onMouseDown={() => { onAdd(value.trim()); setOpen(false); }} className="w-full text-left px-2 py-1.5 text-visita-greenDark hover:bg-slate-100 inline-flex items-center gap-1"><Plus className="w-3 h-3" /> {addLabel} “{value.trim()}”</button>}
                </div>
            )}
        </div>
    );
}

export function useProvinces(internal = true) {
    const [prov, setProv] = useState([]);
    useEffect(() => { if (internal) api.get("/internal/address/provinces").then(({ data }) => setProv(data.provinces)).catch(() => {}); }, [internal]);
    return prov;
}

// Postal → City/Province assistance shared by every form (patients use the public endpoint).
// `latest` is a ref to the most recent form value so an async lookup never resurrects stale fields
// (the earlier "Boulevard, ON" bug: a postal response built from a pre-typing snapshot wiped Street No./Address).
export function usePostalAssist({ latest, onChange, internal, touched }) {
    const [hint, setHint] = useState(null);
    const lookup = async (raw) => {
        const n = normPostal(raw);
        if (n.length !== 6) { setHint(null); return; }
        try {
            const { data } = await api.get(internal ? "/internal/address/postal-lookup" : "/public/address/postal-lookup", { params: { postal: n } });
            const cur = latest.current;
            const next = { ...cur, postal_code: data.postal_code };
            if (data.found) {
                if (!touched.current.city || !cur.city) next.city = data.city;
                if (!touched.current.province || !cur.province) next.province = data.province;
                if (!cur.country) next.country = "Canada";
                setHint({ kind: "found", postal: data.postal_code, city: data.city, province: data.province });
            } else setHint({ kind: "unknown", postal: data.postal_code });
            onChange(next);
        } catch { setHint(null); }
    };
    return { hint, setHint, lookup };
}

// Shared postal hint + trusted "+ Add Postal Code" panel (same master-pool endpoint everywhere).
function PostalHint({ hint, setHint, value, internal, testid }) {
    const [addPostal, setAddPostal] = useState(false);
    const savePostal = async () => {
        try { await api.post("/internal/address/postal-codes", { postal_code: value.postal_code, city: value.city, province: value.province }); setAddPostal(false); setHint({ kind: "added", postal: value.postal_code }); }
        catch (e) { setHint({ kind: "error", msg: e?.response?.data?.detail || "Could not save postal code." }); }
    };
    if (!hint) return null;
    return (<>
        <div className="col-span-6 text-[11px] flex flex-wrap items-center gap-2" data-testid={`${testid}-postal-hint`}>
            {hint.kind === "found" && <span className="text-emerald-700">✓ City and Province suggested from {hint.postal} ({hint.city}, {hint.province}) — edit if this address differs.</span>}
            {hint.kind === "unknown" && <><span className="text-slate-500">{hint.postal} is not in the Postal Code Pool yet — enter City and Province manually.</span>
                {internal && !addPostal && <Button type="button" size="sm" variant="outline" data-testid={`${testid}-add-postal`} onClick={() => setAddPostal(true)} className="h-6 px-2 text-[11px] border-visita-green text-visita-greenDark"><Plus className="w-3 h-3 mr-1" /> Add Postal Code</Button>}</>}
            {hint.kind === "added" && <span className="text-emerald-700">{hint.postal} saved to the Postal Code Pool — future lookups will suggest {value.city}, {value.province}.</span>}
            {hint.kind === "error" && <span className="text-red-600">{hint.msg}</span>}
        </div>
        {addPostal && (
            <div className="col-span-6 flex flex-wrap items-center gap-2 rounded-sm border border-slate-300 bg-slate-50 p-2 text-xs" data-testid={`${testid}-add-postal-panel`}>
                <span className="font-semibold">Add {value.postal_code} → {value.city || "City?"}, {value.province || "Province?"}</span>
                <Button type="button" size="sm" disabled={!value.city || !value.province} data-testid={`${testid}-add-postal-save`} onClick={savePostal} className="h-6 px-2 text-[11px] bg-visita-green hover:bg-visita-greenDark text-white">Save to pool</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setAddPostal(false)} className="h-6 px-2 text-[11px]">Cancel</Button>
            </div>
        )}
    </>);
}

function ProvinceField({ value, provinces, onChange, testid }) {
    return provinces.length ? (
        <select data-testid={testid} value={value || ""} onChange={(e) => onChange(e.target.value)} className={SELECT}>
            {provinces.map((p) => <option key={p.code} value={p.code}>{p.code} — {p.name}</option>)}
        </select>
    ) : <Input data-testid={testid} value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} placeholder="ON" />;
}

// Patient demographics (internal staff entry): Postal first → Street Address (free text, unchanged storage) → Unit → City → Province → Country.
// Same pools, lookup, hint and "+ Add Postal Code" as AddressFields; no professional-location concepts.
export function PatientAddressFields({ value, onChange, internal = true, testid = "paddr", labels = {} }) {
    const touched = useRef({ city: false, province: false });
    const latest = useRef(value); latest.current = value;
    const provinces = useProvinces(internal);
    const { hint, setHint, lookup } = usePostalAssist({ latest, onChange, internal, touched });
    const set = (k, v) => { const next = { ...latest.current, [k]: v }; latest.current = next; onChange(next); };
    const cities = (q) => api.get("/internal/address/cities", { params: { q, province: value.province || undefined } }).then((r) => r.data);
    return (
        <div className="grid grid-cols-6 gap-2" data-testid={`${testid}-fields`}>
            <div className="col-span-3 sm:col-span-2"><Label className="text-xs">{labels.postal || "Postal Code"}</Label>
                <Input data-testid={`${testid}-postal`} value={value.postal_code || ""} maxLength={7} placeholder="M6E 4H1"
                    onChange={(e) => { const v = e.target.value.toUpperCase(); set("postal_code", v); if (normPostal(v).length === 6) lookup(v); }} onBlur={(e) => lookup(e.target.value)} /></div>
            <div className="col-span-6 sm:col-span-4 text-[11px] text-slate-500 self-end pb-2">Enter the postal code first — City and Province are suggested from the Postal Code Pool.</div>
            <PostalHint hint={hint} setHint={setHint} value={value} internal={internal} testid={testid} />
            <div className="col-span-4"><Label className="text-xs">{labels.address || "Street Address"}</Label><Input data-testid={`${testid}-address`} value={value.address || ""} onChange={(e) => set("address", e.target.value)} placeholder="1214 Lansdowne Avenue" /></div>
            <div className="col-span-2"><Label className="text-xs">{labels.unit || "Unit / Apt."}</Label><Input data-testid={`${testid}-unit`} value={value.unit || ""} onChange={(e) => set("unit", e.target.value)} placeholder="Suite 203" /></div>
            <div className="col-span-3 sm:col-span-2"><Label className="text-xs">{labels.city || "City"}</Label>
                {internal ? <Suggest testid={`${testid}-city`} value={value.city || ""} onChange={(v) => { touched.current.city = true; set("city", v); }} onPick={(i) => { touched.current.city = true; set("city", i.name); }} fetcher={cities} minChars={1} placeholder="Toronto York" />
                    : <Input data-testid={`${testid}-city`} value={value.city || ""} onChange={(e) => { touched.current.city = true; set("city", e.target.value); }} />}</div>
            <div className="col-span-3 sm:col-span-2"><Label className="text-xs">{labels.province || "Province"}</Label>
                <ProvinceField testid={`${testid}-province`} value={value.province} provinces={provinces} onChange={(v) => { touched.current.province = true; set("province", v); }} /></div>
            <div className="col-span-6 sm:col-span-2"><Label className="text-xs">{labels.country || "Country"}</Label><Input data-testid={`${testid}-country`} value={value.country || ""} onChange={(e) => set("country", e.target.value)} /></div>
        </div>
    );
}

export function AddressFields({ value, onChange, internal = true, showStreetNumber = true, showUnit = true, requireAddress = true, testid = "addr" }) {
    const touched = useRef({ city: false, province: false });
    const latest = useRef(value); latest.current = value;
    const provinces = useProvinces(internal);
    const { hint, setHint, lookup } = usePostalAssist({ latest, onChange, internal, touched });
    const set = (k, v) => { const next = { ...latest.current, [k]: v }; latest.current = next; onChange(next); };
    const streets = (q) => api.get("/internal/address/streets", { params: { q } }).then((r) => r.data);
    const types = (q) => api.get("/internal/address/street-types", { params: { q } }).then((r) => r.data);
    const cities = (q) => api.get("/internal/address/cities", { params: { q, province: value.province || undefined } }).then((r) => r.data);
    const [dirs, setDirs] = useState([]);
    useEffect(() => { if (internal) api.get("/internal/address/street-directions").then(({ data }) => setDirs(data)).catch(() => {}); }, [internal]);
    const preview = assembleStreet(value);
    return (
        <div className="grid grid-cols-6 gap-2" data-testid={`${testid}-fields`}>
            {showStreetNumber && <div className="col-span-2 sm:col-span-1"><Label className="text-xs">Street No.</Label><Input data-testid={`${testid}-number`} value={value.street_number} onChange={(e) => set("street_number", e.target.value)} placeholder="1214" /></div>}
            <div className={showStreetNumber ? "col-span-4 sm:col-span-3" : "col-span-6 sm:col-span-4"}><Label className="text-xs">Address{requireAddress && " *"} <span className="text-slate-400 font-normal">(street name)</span></Label>
                <Suggest testid={`${testid}-street`} value={value.street_name} onChange={(v) => set("street_name", v)} onPick={(i) => set("street_name", i.name)} fetcher={streets} minChars={2} placeholder="Lansdowne"
                    addLabel="Add Address" onAdd={internal ? (name) => api.post("/internal/address/streets", { name }).then(() => set("street_name", name)).catch(() => set("street_name", name)) : null} /></div>
            <div className="col-span-3 sm:col-span-2"><Label className="text-xs">Address Type <span className="text-slate-400 font-normal">(Avenue, Road…)</span></Label>
                <Suggest testid={`${testid}-street-type`} value={value.street_type} onChange={(v) => set("street_type", v)} onPick={(i) => set("street_type", i.name)} fetcher={types} minChars={0} placeholder="Avenue" /></div>
            <div className="col-span-3 sm:col-span-2"><Label className="text-xs">Address Subtype <span className="text-slate-400 font-normal">(direction, optional)</span></Label>
                <select data-testid={`${testid}-direction`} value={value.street_direction || ""} onChange={(e) => set("street_direction", e.target.value)} className={SELECT}>
                    <option value="">— None —</option>{(dirs.length ? dirs : ["East", "North", "South", "West"].map((n) => ({ name: n }))).map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
                </select></div>
            {showUnit && <div className="col-span-3 sm:col-span-2"><Label className="text-xs">Unit / Suite</Label><Input data-testid={`${testid}-unit`} value={value.unit} onChange={(e) => set("unit", e.target.value)} placeholder="Suite 410A" /></div>}
            <div className="col-span-3 sm:col-span-2"><Label className="text-xs">Postal Code</Label>
                <Input data-testid={`${testid}-postal`} value={value.postal_code} maxLength={7} placeholder="M6E 4H1"
                    onChange={(e) => { const v = e.target.value.toUpperCase(); set("postal_code", v); if (normPostal(v).length === 6) lookup(v); }} onBlur={(e) => lookup(e.target.value)} /></div>
            <div className="col-span-3 sm:col-span-2"><Label className="text-xs">City *</Label>
                {internal ? <Suggest testid={`${testid}-city`} value={value.city} onChange={(v) => { touched.current.city = true; set("city", v); }} onPick={(i) => { touched.current.city = true; set("city", i.name); }} fetcher={cities} minChars={1} placeholder="Toronto York" />
                    : <Input data-testid={`${testid}-city`} value={value.city} onChange={(e) => { touched.current.city = true; set("city", e.target.value); }} />}</div>
            <div className="col-span-3 sm:col-span-2"><Label className="text-xs">Province *</Label>
                <ProvinceField testid={`${testid}-province`} value={value.province} provinces={provinces} onChange={(v) => { touched.current.province = true; set("province", v); }} /></div>
            <PostalHint hint={hint} setHint={setHint} value={value} internal={internal} testid={testid} />
            {preview && <div className="col-span-6 text-xs text-slate-600" data-testid={`${testid}-preview`}>Address line: <span className="font-medium text-slate-800">{[preview, value.city, value.province, value.postal_code].filter((x) => (x || "").trim()).join(", ")}</span></div>}
        </div>
    );
}
