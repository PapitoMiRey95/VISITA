import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

// VIen standard professional/location address entry: Address · Type · Subtype · Postal Code · City · Province.
// Postal Code Pool assists (suggests City/Province) but never blocks; user-confirmed values are never overwritten.
const SELECT = "flex h-9 w-full rounded-sm border border-slate-300 bg-white px-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500";
export const emptyAddress = () => ({ address: "", address_type: "PRACTICE", address_subtype: "", postal_code: "", city: "", province: "", country: "Canada" });

export function useAddressOptions() {
    const [opts, setOpts] = useState({ address_types: [], address_subtypes: [] });
    useEffect(() => { api.get("/internal/address/options").then(({ data }) => setOpts(data)).catch(() => {}); }, []);
    return opts;
}

export function AddressFields({ value, onChange, options, requireAddress = true, testid = "addr" }) {
    const [hint, setHint] = useState(null);  // { kind: "found" | "unknown", postal }
    const touched = useRef({ city: false, province: false });  // user-confirmed → never auto-replaced
    const set = (k, v) => onChange({ ...value, [k]: v });
    const lookup = async (raw) => {
        const n = (raw || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
        if (n.length !== 6) { setHint(null); return; }
        try {
            const { data } = await api.get("/internal/address/postal-lookup", { params: { postal: n } });
            if (data.found) {
                const next = { ...value, postal_code: data.postal_code };
                if (!touched.current.city || !value.city) next.city = data.city;
                if (!touched.current.province || !value.province) next.province = data.province;
                onChange(next); setHint({ kind: "found", postal: data.postal_code });
            } else { onChange({ ...value, postal_code: data.postal_code }); setHint({ kind: "unknown", postal: data.postal_code }); }
        } catch { setHint(null); }
    };
    return (
        <div className="grid grid-cols-6 gap-2" data-testid={`${testid}-fields`}>
            <div className="col-span-6"><Label className="text-xs">Address{requireAddress && " *"}</Label>
                <Input data-testid={`${testid}-address`} value={value.address} onChange={(e) => set("address", e.target.value)} placeholder="e.g. 2425 Bloor Street West, Suite 410A" /></div>
            <div className="col-span-3"><Label className="text-xs">Address Type</Label>
                <select data-testid={`${testid}-type`} value={value.address_type || ""} onChange={(e) => set("address_type", e.target.value)} className={SELECT}>
                    <option value="">— Select —</option>{options.address_types.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
                </select></div>
            <div className="col-span-3"><Label className="text-xs">Address Subtype <span className="text-slate-400 font-normal">(optional)</span></Label>
                <select data-testid={`${testid}-subtype`} value={value.address_subtype || ""} onChange={(e) => set("address_subtype", e.target.value)} className={SELECT}>
                    <option value="">— None —</option>{options.address_subtypes.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
                </select></div>
            <div className="col-span-2"><Label className="text-xs">Postal Code</Label>
                <Input data-testid={`${testid}-postal`} value={value.postal_code} onChange={(e) => { set("postal_code", e.target.value.toUpperCase()); if (e.target.value.replace(/\W/g, "").length >= 6) lookup(e.target.value); }} onBlur={(e) => lookup(e.target.value)} placeholder="A1A 1A1" maxLength={7} /></div>
            <div className="col-span-2"><Label className="text-xs">City *</Label>
                <Input data-testid={`${testid}-city`} value={value.city} onChange={(e) => { touched.current.city = true; set("city", e.target.value); }} /></div>
            <div className="col-span-2"><Label className="text-xs">Province *</Label>
                <Input data-testid={`${testid}-province`} value={value.province} onChange={(e) => { touched.current.province = true; set("province", e.target.value); }} placeholder="ON" /></div>
            {hint && (
                <div className={`col-span-6 text-[11px] ${hint.kind === "found" ? "text-emerald-700" : "text-slate-500"}`} data-testid={`${testid}-postal-hint`}>
                    {hint.kind === "found" ? `City and Province suggested from postal code ${hint.postal} — edit if this address differs.` : `Postal code ${hint.postal} isn't in the pool yet — enter City and Province manually; it will be remembered.`}
                </div>
            )}
        </div>
    );
}
