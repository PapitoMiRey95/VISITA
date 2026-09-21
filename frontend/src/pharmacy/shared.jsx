import { useRef, useState } from "react";
import { toast } from "sonner";
import { Search, Camera, Upload, X, FileText } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";

export function PatientSearch({ onSelect, testidPrefix = "rx" }) {
    const [query, setQuery] = useState("");
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [searched, setSearched] = useState(false);

    const run = async (e) => {
        e?.preventDefault();
        const q = query.trim();
        if (q.length < 2) { toast.error("Enter at least 2 characters."); return; }
        setSearching(true);
        try {
            const { data } = await api.get("/pharmacy/patients/search", { params: { q } });
            setResults(data);
            setSearched(true);
        } catch (err) { toast.error(formatErr(err)); } finally { setSearching(false); }
    };

    return (
        <div>
            <form onSubmit={run} className="flex gap-2">
                <div className="relative flex-1">
                    <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                    <Input data-testid={`${testidPrefix}-search`} value={query} onChange={(e) => setQuery(e.target.value)}
                        placeholder="Patient name or VISITA PIN / ID" className="pl-8" />
                </div>
                <Button type="submit" disabled={searching} data-testid={`${testidPrefix}-search-btn`}>
                    {searching ? "…" : "Search"}
                </Button>
            </form>
            <div className="mt-3 divide-y border border-slate-200 rounded-sm max-h-80 overflow-y-auto">
                {!searched && <div className="px-3 py-4 text-slate-400 text-sm">Search by patient name or VISITA PIN / ID.</div>}
                {searched && results.length === 0 && <div className="px-3 py-4 text-slate-400 text-sm">No matching patients found.</div>}
                {results.map((r) => (
                    <button key={r.id} data-testid={`${testidPrefix}-result`} onClick={() => onSelect(r)}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex justify-between gap-2">
                        <span className="font-semibold">{r.full_name}</span>
                        <span className="text-slate-500 text-xs">
                            {r.visita_patient_id ? `PIN ${r.visita_patient_id}` : "—"} · DOB {formatDate(r.date_of_birth)}
                        </span>
                    </button>
                ))}
            </div>
        </div>
    );
}

function IdRow({ label, children }) {
    return (
        <div className="flex justify-between gap-3 border-b border-slate-100 py-1.5">
            <span className="text-slate-400 text-xs uppercase tracking-wide whitespace-nowrap">{label}</span>
            <span className="text-slate-800 text-right text-sm">{children || "—"}</span>
        </div>
    );
}

export function IdentityCard({ p }) {
    return (
        <div className="bg-white border border-slate-300 rounded-sm p-4" data-testid="pharmacy-identity-card">
            <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">Patient identity</div>
            <IdRow label="Name">{p.full_name}</IdRow>
            <IdRow label="VISITA PIN / ID">{p.visita_patient_id}</IdRow>
            <IdRow label="DOB">{formatDate(p.date_of_birth)}</IdRow>
            <IdRow label="Home">{p.home_phone}</IdRow>
            <IdRow label="Cell">{p.cell_phone}</IdRow>
            <IdRow label="Address">{p.address_full}</IdRow>
            <IdRow label="Health Card">
                {p.health_card_number ? `${p.health_card_number}${p.health_card_version_code ? " " + p.health_card_version_code : ""}` : "—"}
            </IdRow>
        </div>
    );
}

export function AttachmentPicker({ file, onChange, testidPrefix = "rx" }) {
    const cameraRef = useRef(null);
    const fileRef = useRef(null);
    const [preview, setPreview] = useState(null);

    const pick = (f) => {
        if (!f) return;
        const okType = /\.(pdf|jpe?g|png)$/i.test(f.name) || /(pdf|jpeg|png|jpg)/i.test(f.type);
        if (!okType) { toast.error("Only JPG, PNG, or PDF files are accepted."); return; }
        if (f.size > 15 * 1024 * 1024) { toast.error("File too large. Maximum size is 15 MB."); return; }
        onChange(f);
        if (f.type.startsWith("image/")) {
            const url = URL.createObjectURL(f);
            setPreview(url);
        } else {
            setPreview(null);
        }
    };

    const clear = () => { onChange(null); setPreview(null); if (cameraRef.current) cameraRef.current.value = ""; if (fileRef.current) fileRef.current.value = ""; };

    return (
        <div>
            <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden"
                data-testid={`${testidPrefix}-camera-input`} onChange={(e) => pick(e.target.files?.[0])} />
            <input ref={fileRef} type="file" accept=".pdf,image/png,image/jpeg" className="hidden"
                data-testid={`${testidPrefix}-file-input`} onChange={(e) => pick(e.target.files?.[0])} />

            {!file ? (
                <div className="flex gap-2">
                    <Button type="button" variant="outline" className="flex-1" data-testid={`${testidPrefix}-take-photo`}
                        onClick={() => cameraRef.current?.click()}>
                        <Camera className="w-4 h-4 mr-1" /> Take Photo
                    </Button>
                    <Button type="button" variant="outline" className="flex-1" data-testid={`${testidPrefix}-upload-file`}
                        onClick={() => fileRef.current?.click()}>
                        <Upload className="w-4 h-4 mr-1" /> Upload JPG / PNG / PDF
                    </Button>
                </div>
            ) : (
                <div className="border border-slate-200 rounded-sm p-3 flex items-center gap-3" data-testid={`${testidPrefix}-file-preview`}>
                    {preview ? (
                        <img src={preview} alt="attachment preview" className="w-16 h-16 object-cover rounded-sm border border-slate-200" />
                    ) : (
                        <FileText className="w-10 h-10 text-slate-400" />
                    )}
                    <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-slate-800 truncate">{file.name}</div>
                        <div className="text-xs text-slate-400">{(file.size / 1024).toFixed(0)} KB</div>
                    </div>
                    <button type="button" onClick={clear} data-testid={`${testidPrefix}-remove-file`}
                        className="text-slate-400 hover:text-red-600"><X className="w-4 h-4" /></button>
                </div>
            )}
        </div>
    );
}
