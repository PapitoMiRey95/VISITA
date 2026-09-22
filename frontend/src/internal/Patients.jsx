import { useState, useRef, useEffect } from "react";
import { toast } from "sonner";
import { UserSearch, Search, MapPin, Phone, IdCard, Building2, Lock, RefreshCw } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { formatDate } from "../lib/date";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";

function statusLabel(s) {
    if (!s) return "—";
    if (s === "PORTAL_PATIENT") return "VERIFIED — PORTAL PATIENT";
    return String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function Row({ label, children, testid }) {
    return (
        <div className="flex justify-between gap-4 border-b border-slate-100 py-2">
            <span className="text-slate-400 text-xs uppercase tracking-wide whitespace-nowrap">{label}</span>
            <span data-testid={testid} className="text-slate-800 text-right text-sm font-medium">{children || "—"}</span>
        </div>
    );
}

export default function Patients() {
    const [query, setQuery] = useState("");
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [searched, setSearched] = useState(false);
    const [showResults, setShowResults] = useState(false);
    const [selected, setSelected] = useState(null);
    const searchRef = useRef(null);

    // Close the results list when clicking outside the search area.
    useEffect(() => {
        function onDocClick(e) {
            if (searchRef.current && !searchRef.current.contains(e.target)) setShowResults(false);
        }
        document.addEventListener("mousedown", onDocClick);
        return () => document.removeEventListener("mousedown", onDocClick);
    }, []);

    const run = async (e) => {
        e?.preventDefault();
        const q = query.trim();
        if (q.length < 2) { toast.error("Enter at least 2 characters."); return; }
        setSearching(true);
        try {
            const { data } = await api.get("/internal/patient-lookup", { params: { q } });
            setResults(data);
            setSearched(true);
            if (data.length === 1) {
                setSelected(data[0]);
                setShowResults(false);
            } else {
                setShowResults(true);
            }
        } catch (err) { toast.error(formatErr(err)); } finally { setSearching(false); }
    };

    const pick = (r) => { setSelected(r); setShowResults(false); };

    return (
        <div className="animate-fade-in">
            <div className="flex items-center gap-2 mb-1">
                <UserSearch className="w-5 h-5 text-visita-green" />
                <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Patients</h1>
            </div>
            <p className="text-sm text-slate-500 mb-4 flex items-center gap-1">
                <Lock className="w-3.5 h-3.5" /> Read-only lookup — search by name, VISITA PIN / ID, health card number, or phone.
            </p>

            <div ref={searchRef} className="relative max-w-xl mb-4">
                <form onSubmit={run} className="flex gap-2">
                    <div className="relative flex-1">
                        <Search className="w-4 h-4 text-slate-400 absolute left-2 top-2.5" />
                        <Input data-testid="patient-lookup-search" value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            onFocus={() => { if (results.length) setShowResults(true); }}
                            placeholder="Name, VISITA PIN, health card #, or phone" className="pl-8" />
                    </div>
                    <Button type="submit" disabled={searching} data-testid="patient-lookup-search-btn">
                        {searching ? "…" : "Search"}
                    </Button>
                </form>

                {showResults && searched && (
                    <div data-testid="patient-lookup-results"
                        className="absolute z-20 mt-1 w-full bg-white border border-slate-300 rounded-sm shadow-lg divide-y max-h-[calc(100vh-13rem)] overflow-y-auto">
                        {results.length === 0 ? (
                            <div className="px-3 py-4 text-slate-400 text-sm">No matching patients found.</div>
                        ) : (
                            <>
                                <div className="px-3 py-1.5 text-[11px] uppercase tracking-wide text-slate-400 bg-slate-50">
                                    {results.length} match{results.length === 1 ? "" : "es"}
                                </div>
                                {results.map((r) => (
                                    <button key={r.id} data-testid="patient-lookup-result" onClick={() => pick(r)}
                                        className={`w-full text-left px-3 py-2.5 hover:bg-slate-50 ${selected?.id === r.id ? "bg-visita-greenLight" : ""}`}>
                                        <div className="font-semibold text-slate-800">{r.full_name}</div>
                                        <div className="text-xs text-slate-500">
                                            {r.visita_patient_id ? `PIN ${r.visita_patient_id}` : "PIN Not assigned"} · DOB {formatDate(r.date_of_birth)} · {statusLabel(r.patient_status)}
                                        </div>
                                    </button>
                                ))}
                            </>
                        )}
                    </div>
                )}
            </div>

            {!selected ? (
                <div className="bg-white border border-dashed border-slate-300 rounded-sm px-4 py-16 text-center text-slate-400 text-sm max-w-3xl">
                    Search above and select a patient to view their snapshot.
                </div>
            ) : (
                <div className="bg-white border border-slate-300 rounded-sm p-5 max-w-3xl" data-testid="patient-snapshot">
                    <div className="flex items-center justify-between mb-3">
                        <div>
                            <h2 className="text-lg font-bold text-slate-900">{selected.full_name}</h2>
                            <span className={`inline-block mt-1 px-2 py-0.5 rounded-sm text-xs ${selected.source === "portal" ? "bg-emerald-100 text-emerald-800 font-semibold" : "bg-slate-100 text-slate-600"}`}>{statusLabel(selected.patient_status)}</span>
                        </div>
                        <div className="flex items-center gap-3">
                            <span className="text-xs text-slate-400 flex items-center gap-1"><Lock className="w-3.5 h-3.5" /> Read-only</span>
                            <Button variant="outline" size="sm" data-testid="patient-change-btn"
                                onClick={() => { setShowResults(results.length > 0); searchRef.current?.querySelector("input")?.focus(); }}>
                                <RefreshCw className="w-3.5 h-3.5 mr-1" /> Change Patient
                            </Button>
                        </div>
                    </div>

                    <Row label="Full Name" testid="snap-name">{selected.full_name}</Row>
                    <Row label="VISITA PIN / ID" testid="snap-pin"><span className="inline-flex items-center gap-1"><IdCard className="w-3.5 h-3.5 text-slate-400" />{selected.visita_patient_id || "Not assigned"}</span></Row>
                    <Row label="DOB" testid="snap-dob">{formatDate(selected.date_of_birth)}</Row>
                    <Row label="Age" testid="snap-age">{selected.age != null ? `${selected.age}` : "—"}</Row>
                    <Row label="Home Phone" testid="snap-home">{selected.home_phone ? <span className="inline-flex items-center gap-1"><Phone className="w-3.5 h-3.5 text-slate-400" />{selected.home_phone}</span> : null}</Row>
                    <Row label="Cell Phone" testid="snap-cell">{selected.cell_phone ? <span className="inline-flex items-center gap-1"><Phone className="w-3.5 h-3.5 text-slate-400" />{selected.cell_phone}</span> : null}</Row>
                    <Row label="Address" testid="snap-address">{selected.address_full ? <span className="inline-flex items-center gap-1 text-right"><MapPin className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />{selected.address_full}</span> : null}</Row>
                    <Row label="Health Card" testid="snap-hcn">
                        {selected.health_card_number ? `${selected.health_card_number}${selected.health_card_version_code ? " " + selected.health_card_version_code : ""}` : null}
                    </Row>
                    <Row label="Directory Status" testid="snap-status">{statusLabel(selected.patient_status)}</Row>
                    <Row label="Current Pharmacy" testid="snap-pharmacy">{selected.current_pharmacy ? <span className="inline-flex items-center gap-1"><Building2 className="w-3.5 h-3.5 text-slate-400" />{selected.current_pharmacy}</span> : null}</Row>

                    <p className="text-xs text-slate-400 mt-4 leading-relaxed">
                        Demographic &amp; contact information only. Medication list and other approved VISITA information will appear here later.
                    </p>
                </div>
            )}
        </div>
    );
}
