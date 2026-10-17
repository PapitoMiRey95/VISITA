import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LogOut, RefreshCw, Megaphone, Wrench, Server } from "lucide-react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useSystemStatus } from "../components/SystemStatus";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { formatDateTime } from "../lib/date";
import { usePlatformConfigAdmin } from "./platformConfig";
import { FeaturesSection, PublicSiteSection } from "./sections";
import { DataOperations } from "./DataOperations";

const GOOD = new Set(["ONLINE", "CONNECTED", "READY"]);
const Indicator = ({ label, value }) => (
    <div className="flex items-center justify-between border-b border-slate-800 py-2" data-testid={`status-${label.toLowerCase().replace(/[^a-z]/g, "-")}`}>
        <span className="text-slate-400 text-sm">{label}</span>
        <span className={`text-xs font-bold px-2 py-0.5 rounded-sm ${GOOD.has(value) ? "bg-emerald-500/15 text-emerald-300" : value === "PENDING" ? "bg-slate-700 text-slate-300" : "bg-amber-500/20 text-amber-300"}`}>{value}</span>
    </div>
);

function Card({ icon: Icon, title, children, testid }) {
    return (
        <section className="bg-slate-900/70 border border-slate-800 rounded-md p-5" data-testid={testid}>
            <h2 className="text-sm font-bold text-slate-200 flex items-center gap-2 mb-3"><Icon className="w-4 h-4 text-emerald-400" /> {title}</h2>
            {children}
        </section>
    );
}

function Announcement({ current, onChanged }) {
    const [message, setMessage] = useState(current?.active ? current.message : "");
    const [type, setType] = useState(current?.type || "INFO");
    const [busy, setBusy] = useState(false);
    const publish = async () => {
        setBusy(true);
        try { await api.put("/developer/announcement", { message, type }); toast.success(current?.active ? "Announcement updated" : "Announcement published"); onChanged(); }
        catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const remove = async () => {
        setBusy(true);
        try { await api.delete("/developer/announcement"); toast.success("Announcement removed"); setMessage(""); onChanged(); }
        catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <Card icon={Megaphone} title="Global message" testid="dev-announcement">
            {current?.active && <div className="text-xs text-slate-400 mb-2" data-testid="dev-announcement-current">Live ({current.type}) since {formatDateTime(current.updated_at)}: “{current.message}”</div>}
            <Textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={2} placeholder="Scheduled maintenance tonight at 9:00 PM. Please save your work." className="bg-slate-950 border-slate-700 text-slate-100" data-testid="dev-announcement-message" />
            <div className="flex flex-wrap items-center gap-2 mt-2">
                {["INFO", "WARNING", "CRITICAL"].map((t) => (
                    <button key={t} type="button" onClick={() => setType(t)} data-testid={`dev-announcement-type-${t.toLowerCase()}`}
                        className={`px-2 py-1 rounded-sm text-xs font-bold border ${type === t ? "bg-emerald-500 text-slate-900 border-emerald-500" : "border-slate-700 text-slate-300"}`}>{t}</button>
                ))}
                <Button size="sm" disabled={busy || !message.trim()} onClick={publish} className="bg-emerald-500 hover:bg-emerald-400 text-slate-900" data-testid="dev-announcement-publish">{current?.active ? "Update" : "Publish"}</Button>
                {current?.active && <Button size="sm" variant="outline" disabled={busy} onClick={remove} className="border-slate-600 text-slate-200" data-testid="dev-announcement-remove">Remove</Button>}
            </div>
        </Card>
    );
}

function MaintenanceMode({ current, onChanged }) {
    const [message, setMessage] = useState(current?.message || "");
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState(false);
    const on = !!current?.on;
    const word = on ? "EXIT" : "ENTER";
    const toggle = async () => {
        setBusy(true);
        try { await api.post("/developer/maintenance-mode", { on: !on, message, confirm }); toast.success(on ? "Maintenance mode OFF" : "Maintenance mode ON"); setConfirm(""); onChanged(); }
        catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <Card icon={Wrench} title="Maintenance mode" testid="dev-maintenance">
            <div className="flex items-center gap-2 mb-3">
                <span className={`text-xs font-bold px-2 py-0.5 rounded-sm ${on ? "bg-amber-500 text-slate-900" : "bg-slate-700 text-slate-200"}`} data-testid="dev-maintenance-state">{on ? "ON" : "OFF"}</span>
                {on && <span className="text-xs text-slate-400">since {formatDateTime(current.since)}</span>}
            </div>
            <p className="text-xs text-slate-400 mb-2">The server stays alive. Normal users see a maintenance screen and clinical/business APIs return 503. Developer portal, login and health endpoints keep working.</p>
            <Textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={2} disabled={on} className="bg-slate-950 border-slate-700 text-slate-100" data-testid="dev-maintenance-message" />
            <div className="flex flex-wrap items-center gap-2 mt-2">
                <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={`Type ${word} to confirm`} className="h-8 w-48 text-xs bg-slate-950 border-slate-700 text-slate-100" data-testid="dev-maintenance-confirm" />
                <Button size="sm" disabled={busy || confirm !== word} onClick={toggle} data-testid="dev-maintenance-toggle"
                    className={on ? "bg-emerald-500 hover:bg-emerald-400 text-slate-900" : "bg-amber-500 hover:bg-amber-400 text-slate-900"}>
                    {on ? "EXIT MAINTENANCE MODE" : "ENTER MAINTENANCE MODE"}
                </Button>
            </div>
        </Card>
    );
}

const TABS = ["OVERVIEW", "FEATURES", "PUBLIC SITE", "OPERATIONS", "DATA OPS"];

function Overview({ d, pc }) {
    const live = pc?.published;
    const feats = live?.config?.features || {};
    const on = Object.values(feats).filter((v) => v === "ON").length, pilot = Object.values(feats).filter((v) => v === "PILOT").length;
    return (
        <div className="grid md:grid-cols-2 gap-5" data-testid="dev-overview">
            <Card icon={Server} title="Installation" testid="ov-install">
                {d && <>
                    <Indicator label="Application / API" value={d.api} /><Indicator label="Database" value={d.database} /><Indicator label="Storage" value={d.storage} /><Indicator label="Readiness" value={d.readiness} />
                    <div className="text-xs text-slate-500 mt-3">Environment <span className="text-slate-300 uppercase">{d.environment}</span> · release <span className="font-mono text-slate-300">{d.release?.commit || "n/a"}</span></div>
                </>}
            </Card>
            <Card icon={Megaphone} title="Platform configuration" testid="ov-config">
                <Indicator label="Live version" value={`v${live?.version ?? 0}`} />
                <Indicator label="Draft" value={pc?.draft ? "PENDING" : "NONE"} />
                <Indicator label="Features ON / PILOT" value={`${on} / ${pilot}`} />
                <Indicator label="Maintenance mode" value={d?.maintenance?.on ? "ON" : "OFF"} />
                <Indicator label="Global message" value={d?.announcement?.active ? d.announcement.type : "NONE"} />
                <p className="text-[11px] text-slate-500 mt-3">Operator controls the installation only. Organization admins manage their own clinic/pharmacy; users control their own appearance. Clinical records are never accessible from here.</p>
            </Card>
        </div>
    );
}

export default function DeveloperPortal() {
    const { user, logout } = useAuth();
    const sys = useSystemStatus();
    const [tab, setTab] = useState("OVERVIEW");
    const q = useQuery({ queryKey: ["developer-status"], queryFn: async () => (await api.get("/developer/status")).data, refetchInterval: 20000 });
    const pcq = usePlatformConfigAdmin();
    const d = q.data;
    const changed = () => { q.refetch(); sys.refresh(); pcq.refetch(); };
    return (
        <div className="min-h-screen bg-slate-950 text-slate-100 font-plex" data-testid="developer-portal">
            <header className="border-b border-slate-800 px-6 py-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <img src="/vien-logo.png" alt="" className="w-7 h-7" />
                    <div><div className="font-bold leading-tight">VIen Platform Control Center</div><div className="text-[11px] text-slate-500 uppercase tracking-wider">installation operator · {d?.environment || "…"}</div></div>
                </div>
                <div className="flex items-center gap-3 text-sm text-slate-400">
                    <span>{user?.name}</span>
                    <Button size="sm" variant="ghost" onClick={() => q.refetch()} className="text-slate-300" data-testid="dev-refresh"><RefreshCw className="w-4 h-4" /></Button>
                    <Button size="sm" variant="ghost" onClick={logout} className="text-slate-300" data-testid="dev-logout"><LogOut className="w-4 h-4 mr-1" /> Logout</Button>
                </div>
            </header>
            <nav className="border-b border-slate-800 px-6 flex gap-1" data-testid="dev-tabs">
                {TABS.map((t) => (
                    <button key={t} type="button" onClick={() => setTab(t)} data-testid={`dev-tab-${t.toLowerCase().replace(" ", "-")}`}
                        className={`px-3 py-2 text-xs font-bold tracking-wide border-b-2 -mb-px ${tab === t ? "border-emerald-400 text-emerald-300" : "border-transparent text-slate-500 hover:text-slate-300"}`}>{t}</button>
                ))}
            </nav>
            <main className="max-w-5xl mx-auto p-6">
                {tab === "OVERVIEW" && <Overview d={d} pc={pcq.data} />}
                {tab === "FEATURES" && <FeaturesSection cfg={pcq.data} onChanged={changed} />}
                {tab === "PUBLIC SITE" && pcq.data && <PublicSiteSection key={pcq.data.draft?.updated_at || pcq.data.published?.version} cfg={pcq.data} onChanged={changed} />}
                {tab === "DATA OPS" && <DataOperations cfg={pcq.data} onChanged={changed} />}
                {tab === "OPERATIONS" && (
                    <div className="grid md:grid-cols-2 gap-5" data-testid="dev-operations">
                        <Card icon={Server} title="System status" testid="dev-system-status">
                            {q.error && <div className="text-sm text-red-400">{formatErr(q.error)}</div>}
                            {d && (
                                <>
                                    <Indicator label="Application / API" value={d.api} />
                                    <Indicator label="Database" value={d.database} />
                                    <Indicator label="Storage" value={d.storage} />
                                    <Indicator label="Readiness" value={d.readiness} />
                                    <div className="text-xs text-slate-500 mt-3 space-y-0.5">
                                        <div>Environment: <span className="text-slate-300 uppercase">{d.environment}</span></div>
                                        <div>Release: <span className="text-slate-300 font-mono">{d.release?.commit || "n/a"}</span> · started {formatDateTime(d.release?.started_at)}</div>
                                    </div>
                                </>
                            )}
                        </Card>
                        {d && <MaintenanceMode key={String(d.maintenance?.on)} current={d.maintenance} onChanged={changed} />}
                        {d && <div className="md:col-span-2"><Announcement key={d.announcement?.updated_at || "new"} current={d.announcement} onChanged={changed} /></div>}
                    </div>
                )}
            </main>
        </div>
    );
}
