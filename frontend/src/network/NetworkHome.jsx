import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Building2, Users, UserCircle2, Link2, ShieldCheck, LogOut, ArrowRight, Search, Check, X, Ban, Trash2, RotateCcw, ChevronLeft } from "lucide-react";
import { toast } from "sonner";
import { api, formatErr, setToken } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Logo } from "../components/Logo";
import { formatDate } from "../lib/date";

const Pill = ({ children, tone = "slate", testid }) => {
    const t = { green: "bg-emerald-500/15 text-emerald-700 border-emerald-300", amber: "bg-amber-500/15 text-amber-800 border-amber-300", red: "bg-red-500/15 text-red-700 border-red-300", blue: "bg-sky-500/15 text-sky-800 border-sky-300", slate: "bg-slate-100 text-slate-700 border-slate-200" }[tone];
    return <span data-testid={testid} className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full border ${t}`}>{children}</span>;
};
const statusTone = (s) => ({ ACTIVE: "green", INVITED: "amber", SUSPENDED: "red" }[s] || "slate");
const Avatar = ({ name, size = "w-12 h-12 text-base" }) => <div className={`${size} rounded-full bg-gradient-to-br from-[#1e50a0] to-[#12bfa0] text-white font-bold flex items-center justify-center flex-shrink-0`}>{(name || "?").split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase()}</div>;

export function NetworkShell({ title, children, back }) {
    const { user, logout } = useAuth();
    const nav = useNavigate();
    return (
        <div className="min-h-screen bg-visita-bg text-slate-900" data-testid="network-shell">
            <header className="bg-visita-ribbon text-white px-6 py-3 flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <Logo variant="dark" iconClass="h-7 w-7" textClass="text-lg" />
                    <span className="text-xs uppercase tracking-[0.2em] text-white/80 border-l border-white/20 pl-4">Network</span>
                </div>
                <nav className="flex items-center gap-1 text-sm">
                    {[["/network", "Home"], [`/network/people/${user?.id}`, "My Profile"], ["/network#connections", "My Connections"], ["/network#organizations", "My Organizations"]].map(([to, l]) => (
                        <Link key={l} to={to} className="px-3 py-1.5 rounded-sm text-white/90 hover:text-white font-medium" data-testid={`network-nav-${l.toLowerCase().replace(/ /g, "-")}`}>{l}</Link>
                    ))}
                    {["physician", "admin", "staff"].includes(user?.role) && <Button size="sm" variant="ghost" className="text-white" onClick={() => nav("/internal")} data-testid="network-back-internal">Clinic app</Button>}
                    <Button size="sm" variant="ghost" className="text-white" onClick={logout} data-testid="network-logout"><LogOut className="w-4 h-4" /></Button>
                </nav>
            </header>
            <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">
                {back && <button type="button" onClick={() => nav(-1)} className="text-xs text-slate-600 inline-flex items-center gap-1" data-testid="network-back"><ChevronLeft className="w-3.5 h-3.5" /> Back</button>}
                {title && <h1 className="text-2xl font-bold tracking-tight">{title}</h1>}
                {children}
            </main>
        </div>
    );
}

const Card = ({ title, icon: Icon, children, testid, right }) => (
    <section className="bg-white border border-slate-200 rounded-md p-5" data-testid={testid}>
        <div className="flex items-center justify-between mb-3"><h2 className="text-sm font-bold flex items-center gap-2">{Icon && <Icon className="w-4 h-4 text-visita-green" />} {title}</h2>{right}</div>
        {children}
    </section>
);

function ConnectionRow({ c }) {
    const to = c.type === "organization" ? `/network/orgs/${c.id}` : `/network/people/${c.id}`;
    return (
        <Link to={to} className="flex items-center gap-3 py-2 border-b border-slate-100 last:border-0" data-testid="network-connection-row">
            {c.type === "organization" ? <div className="w-10 h-10 rounded-md bg-sky-100 text-sky-800 flex items-center justify-center"><Building2 className="w-5 h-5" /></div> : <Avatar name={c.name} size="w-10 h-10 text-sm" />}
            <div className="min-w-0 flex-1"><div className="font-semibold truncate">{c.name}</div><div className="text-xs text-slate-600 truncate">{c.relationship} · connected {formatDate(c.since)}</div></div>
            <Link2 className="w-4 h-4 text-visita-green" />
        </Link>
    );
}

export default function NetworkHome() {
    const nav = useNavigate();
    const q = useQuery({ queryKey: ["network-home"], queryFn: async () => (await api.get("/network/home")).data });
    const [busy, setBusy] = useState(false);
    const d = q.data;
    const respond = async (id, action) => {
        setBusy(true);
        try { await api.post(`/network/invitations/${id}/${action}`); toast.success(action === "accept" ? "You joined the organization" : "Invitation declined"); q.refetch(); }
        catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const open = async (m) => {
        try {
            const { data } = await api.post(`/network/workspace/${m.id}/enter`);
            setToken(data.token); toast.success(`Workspace: ${data.workspace.org_name}`); window.location.assign("/internal");
        } catch (e) { toast.error(formatErr(e)); }
    };
    if (q.error) return <NetworkShell title="VIen Network"><div className="text-sm text-red-700" data-testid="network-error">{formatErr(q.error)}</div></NetworkShell>;
    if (!d) return <NetworkShell title="VIen Network"><div className="text-sm text-slate-600">Loading…</div></NetworkShell>;
    const me = d.me;
    return (
        <NetworkShell title="VIen Network">
            <p className="text-sm text-slate-600 -mt-4">People and organizations connected through VIen. Connections never grant clinical access; organizations authorize workspace tools explicitly.</p>
            {d.invitations.length > 0 && (
                <Card title="Invitations" icon={ShieldCheck} testid="network-invitations">
                    {d.invitations.map((i) => (
                        <div key={i.id} className="flex items-center justify-between gap-3 py-2 border-b border-slate-100 last:border-0" data-testid="network-invitation">
                            <div className="text-sm"><span className="font-semibold">{i.org_name}</span> invited you to join as <span className="font-semibold">{i.role_title}</span><div className="text-xs text-slate-600">Invited by {i.invited_by?.name} · {formatDate(i.invited_at)}</div></div>
                            <div className="flex gap-2">
                                <Button size="sm" disabled={busy} onClick={() => respond(i.id, "accept")} className="bg-visita-green hover:bg-visita-greenDark text-white" data-testid="invitation-accept"><Check className="w-3.5 h-3.5 mr-1" /> Accept</Button>
                                <Button size="sm" variant="outline" disabled={busy} onClick={() => respond(i.id, "decline")} data-testid="invitation-decline"><X className="w-3.5 h-3.5 mr-1" /> Decline</Button>
                            </div>
                        </div>
                    ))}
                </Card>
            )}
            <div className="grid md:grid-cols-3 gap-5">
                <Card title="My Profile" icon={UserCircle2} testid="network-my-profile">
                    <Link to={`/network/people/${me.id}`} className="flex items-center gap-3">
                        <Avatar name={me.name} />
                        <div className="min-w-0"><div className="font-bold truncate" data-testid="network-me-name">{me.name}</div><div className="text-xs text-slate-600 truncate">{me.headline}</div>{me.organizations[0] && <div className="text-xs text-slate-600 truncate">{me.organizations[0].name}</div>}</div>
                    </Link>
                    <div className="mt-3 text-xs text-slate-600">{me.connection_count} connection(s) · {me.organizations.length} organization(s)</div>
                </Card>
                <Card title="My Connections" icon={Link2} testid="network-my-connections">
                    <div id="connections">{me.connections.length ? me.connections.map((c) => <ConnectionRow key={c.type + c.id} c={c} />) : <div className="text-xs text-slate-600">No connections yet.</div>}</div>
                </Card>
                <Card title="My Organizations" icon={Building2} testid="network-my-organizations">
                    <div id="organizations" className="space-y-3">
                        {d.owned_organizations.map((o) => (
                            <div key={o.id} className="border border-slate-200 rounded-md p-3" data-testid="network-owned-org">
                                <div className="font-semibold">{o.name}</div><div className="text-xs text-slate-600 mb-2">Physician / Owner</div>
                                <Button size="sm" variant="outline" onClick={() => nav(`/network/orgs/${o.id}`)} data-testid="network-open-org">Team & connections <ArrowRight className="w-3.5 h-3.5 ml-1" /></Button>
                            </div>
                        ))}
                        {d.memberships.map((m) => (
                            <div key={m.id} className="border border-slate-200 rounded-md p-3" data-testid="network-membership">
                                <div className="font-semibold">{m.org_name}</div>
                                <div className="flex items-center gap-2 mt-1 text-xs text-slate-600">{m.role_title} <Pill tone={statusTone(m.status)} testid="membership-status">{m.status}</Pill>{m.modules?.length ? <Pill tone="blue">access granted</Pill> : <Pill>no access yet</Pill>}</div>
                                <Button size="sm" className="mt-2 bg-visita-ribbon hover:bg-[#162c49] text-white" disabled={m.status !== "ACTIVE" || !m.modules?.length} onClick={() => open(m)} data-testid="open-workspace">Open Workspace <ArrowRight className="w-3.5 h-3.5 ml-1" /></Button>
                            </div>
                        ))}
                        {!d.owned_organizations.length && !d.memberships.length && <div className="text-xs text-slate-600">No organizations yet.</div>}
                    </div>
                </Card>
            </div>
        </NetworkShell>
    );
}

export function PersonProfile() {
    const { id } = useParams();
    const q = useQuery({ queryKey: ["network-person", id], queryFn: async () => (await api.get(`/network/people/${id}`)).data });
    const p = q.data;
    if (!p) return <NetworkShell back>{q.error ? <div className="text-sm text-red-700">{formatErr(q.error)}</div> : "Loading…"}</NetworkShell>;
    return (
        <NetworkShell back>
            <section className="bg-white border border-slate-200 rounded-md p-6 flex items-start gap-5" data-testid="person-profile">
                <Avatar name={p.name} size="w-20 h-20 text-2xl" />
                <div className="flex-1 min-w-0">
                    <h1 className="text-2xl font-bold" data-testid="person-name">{p.name}</h1>
                    <div className="text-sm font-medium text-slate-700" data-testid="person-headline">{p.headline}</div>
                    {p.organizations.map((o) => <div key={o.id} className="text-sm text-slate-700"><Link to={`/network/orgs/${o.id}`} className="underline-offset-2 hover:underline">{o.name}</Link> · {o.role_title} <Pill tone={statusTone(o.status)}>{o.status}</Pill></div>)}
                    <div className="text-xs text-slate-600 mt-2">{[p.city, p.languages?.join(", ")].filter(Boolean).join(" · ")}{p.availability === "AVAILABLE" ? " · Available for work" : ""}</div>
                    {p.summary && <p className="text-sm mt-3">{p.summary}</p>}
                    <div className="text-xs text-slate-600 mt-3">{p.connection_count} connection(s) · {p.organizations.length} organization(s)</div>
                </div>
            </section>
            <Card title="Connections" icon={Link2} testid="person-connections">{p.connections.length ? p.connections.map((c) => <ConnectionRow key={c.type + c.id} c={c} />) : <div className="text-xs text-slate-600">No connections yet.</div>}</Card>
        </NetworkShell>
    );
}

function InviteDialog({ org, onDone }) {
    const [open, setOpen] = useState(false);
    const [q, setQ] = useState("");
    const [results, setResults] = useState([]);
    const [pick, setPick] = useState(null);
    const [role, setRole] = useState("Secretary");
    const search = async (v) => { setQ(v); if (v.trim().length < 2) return setResults([]); const { data } = await api.get("/network/search", { params: { q: v } }); setResults(data.results); };
    const send = async () => {
        try { await api.post(`/network/orgs/${org.id}/invite`, { user_id: pick.id, role_title: role }); toast.success(`Invitation sent to ${pick.name}`); setOpen(false); setPick(null); setQ(""); onDone(); }
        catch (e) { toast.error(formatErr(e)); }
    };
    return (
        <>
            <Button size="sm" onClick={() => setOpen(true)} className="bg-visita-green hover:bg-visita-greenDark text-white" data-testid="invite-person-btn"><Users className="w-3.5 h-3.5 mr-1" /> Invite person</Button>
            <Dialog open={open} onOpenChange={setOpen}>
                <DialogContent data-testid="invite-dialog">
                    <DialogHeader><DialogTitle>Invite to {org.name}</DialogTitle><DialogDescription>Search an existing VIen identity by name, email or username. Invitation creates a membership request only — workspace access is granted separately.</DialogDescription></DialogHeader>
                    <div className="relative"><Search className="w-4 h-4 absolute left-2.5 top-2.5 text-slate-400" /><Input value={q} onChange={(e) => search(e.target.value)} placeholder="Kevin Rodriguez, kevin@…, KRODRIGUEZ" className="pl-8" data-testid="invite-search" /></div>
                    {results.length > 0 && !pick && <ul className="border border-slate-200 rounded-md divide-y max-h-48 overflow-auto">{results.map((r) => <li key={r.id}><button type="button" onClick={() => setPick(r)} className="w-full text-left px-3 py-2 text-sm flex items-center gap-2" data-testid="invite-result"><Avatar name={r.name} size="w-7 h-7 text-xs" /><span className="font-semibold">{r.name}</span><span className="text-xs text-slate-600">{r.email}{r.username ? ` · @${r.username}` : ""}</span></button></li>)}</ul>}
                    {pick && <div className="flex items-center gap-3 border border-emerald-300 bg-emerald-50 rounded-md p-3 text-sm" data-testid="invite-picked"><Avatar name={pick.name} size="w-8 h-8 text-xs" /><div className="flex-1"><div className="font-semibold">{pick.name}</div><div className="text-xs text-slate-600">{pick.email}</div></div><button type="button" onClick={() => setPick(null)} className="text-xs underline">change</button></div>}
                    <div><label className="text-xs text-slate-600">Role at the organization</label>
                        <div className="flex flex-wrap gap-2 mt-1">{["Secretary", "Receptionist", "Medical Office Assistant", "Nurse", "Administrator"].map((r) => <button key={r} type="button" onClick={() => setRole(r)} className={`px-2.5 py-1 rounded-full text-xs font-semibold border ${role === r ? "bg-visita-ribbon text-white border-visita-ribbon" : "border-slate-300"}`} data-testid={`invite-role-${r.toLowerCase().replace(/ /g, "-")}`}>{r}</button>)}</div></div>
                    <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={!pick} onClick={send} className="bg-visita-green hover:bg-visita-greenDark text-white" data-testid="invite-send">Send invitation</Button></DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
}

function AccessPanel({ org, member, onDone }) {
    const [mods, setMods] = useState(member.modules || []);
    const [busy, setBusy] = useState(false);
    const act = async (fn, msg) => { setBusy(true); try { await fn(); toast.success(msg); onDone(); } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); } };
    return (
        <div className="mt-3 border border-slate-200 rounded-md p-4 bg-slate-50" data-testid="access-panel">
            <div className="text-sm font-bold mb-2">Clinic Access — {member.name}</div>
            <div className="grid sm:grid-cols-2 gap-2">
                {Object.entries(org.modules).map(([k, label]) => (
                    <label key={k} className="flex items-center gap-2 text-sm" data-testid={`access-module-${k}`}><input type="checkbox" checked={mods.includes(k)} onChange={(e) => setMods(e.target.checked ? [...mods, k] : mods.filter((x) => x !== k))} /> {label}</label>
                ))}
            </div>
            <p className="text-[11px] text-slate-600 mt-2">Encounter, prescribing and physician-only actions stay protected by their own permissions regardless of this list. Every change is audited.</p>
            <div className="flex flex-wrap gap-2 mt-3">
                <Button size="sm" disabled={busy} onClick={() => act(() => api.put(`/network/orgs/${org.id}/members/${member.membership_id}/access`, { modules: mods }), "Access saved")} className="bg-visita-ribbon hover:bg-[#162c49] text-white" data-testid="access-save">Save access</Button>
                {member.status === "ACTIVE" ? <Button size="sm" variant="outline" disabled={busy} onClick={() => act(() => api.post(`/network/orgs/${org.id}/members/${member.membership_id}/suspend`), "Access suspended")} data-testid="access-suspend"><Ban className="w-3.5 h-3.5 mr-1" /> Suspend access</Button>
                    : <Button size="sm" variant="outline" disabled={busy} onClick={() => act(() => api.post(`/network/orgs/${org.id}/members/${member.membership_id}/reactivate`), "Access reactivated")} data-testid="access-reactivate"><RotateCcw className="w-3.5 h-3.5 mr-1" /> Reactivate</Button>}
                <Button size="sm" variant="outline" disabled={busy} className="border-red-300 text-red-700" onClick={() => window.confirm(`Remove ${member.name} from ${org.name}?`) && act(() => api.post(`/network/orgs/${org.id}/members/${member.membership_id}/remove`), "Removed from organization")} data-testid="access-remove"><Trash2 className="w-3.5 h-3.5 mr-1" /> Remove from organization</Button>
            </div>
        </div>
    );
}

export function OrgProfile() {
    const { id } = useParams();
    const [openAccess, setOpenAccess] = useState(null);
    const q = useQuery({ queryKey: ["network-org", id], queryFn: async () => (await api.get(`/network/orgs/${id}`)).data });
    const o = q.data;
    if (!o) return <NetworkShell back>{q.error ? <div className="text-sm text-red-700">{formatErr(q.error)}</div> : "Loading…"}</NetworkShell>;
    return (
        <NetworkShell back>
            <section className="bg-white border border-slate-200 rounded-md p-6 flex items-start gap-5" data-testid="org-profile">
                <div className="w-20 h-20 rounded-md bg-sky-100 text-sky-800 flex items-center justify-center"><Building2 className="w-10 h-10" /></div>
                <div className="flex-1">
                    <h1 className="text-2xl font-bold" data-testid="org-name">{o.name}</h1>
                    <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700 mt-1">{o.org_type} <Pill tone={o.status === "VERIFIED" ? "green" : "slate"} testid="org-status">{o.status}</Pill></div>
                    {o.location && <div className="text-sm text-slate-700 mt-1">{o.location}</div>}
                    <div className="text-sm text-slate-700 mt-1">Physician / Owner: <Link to={`/network/people/${o.owner_user_id}`} className="font-semibold hover:underline" data-testid="org-owner">{o.owner_name}</Link></div>
                </div>
            </section>
            <Card title="Team / People" icon={Users} testid="org-team" right={o.can_manage && <InviteDialog org={o} onDone={() => q.refetch()} />}>
                {o.team.map((t) => (
                    <div key={t.user_id + (t.membership_id || "")} className="py-3 border-b border-slate-100 last:border-0" data-testid="team-member">
                        <div className="flex items-center gap-3">
                            <Avatar name={t.name} size="w-10 h-10 text-sm" />
                            <div className="flex-1 min-w-0"><Link to={`/network/people/${t.user_id}`} className="font-semibold hover:underline">{t.name}</Link><div className="text-xs text-slate-600">{t.role_title}</div></div>
                            <div className="flex flex-wrap gap-1.5 justify-end">
                                {t.owner ? <Pill tone="blue">Owner</Pill> : <>
                                    <Pill tone={t.connected ? "green" : "slate"} testid="member-connected">{t.connected ? "Connected" : "Invited"}</Pill>
                                    <Pill tone={statusTone(t.status)} testid="member-status">Membership {t.status}</Pill>
                                    <Pill tone={t.access_granted ? "blue" : "slate"} testid="member-access">{t.access_granted ? `Access granted (${t.modules.length})` : "No access"}</Pill>
                                </>}
                            </div>
                            {o.can_manage && !t.owner && t.status !== "INVITED" && <Button size="sm" variant="outline" onClick={() => setOpenAccess(openAccess === t.membership_id ? null : t.membership_id)} data-testid="manage-access-btn"><ShieldCheck className="w-3.5 h-3.5 mr-1" /> Access</Button>}
                        </div>
                        {openAccess === t.membership_id && <AccessPanel org={o} member={t} onDone={() => q.refetch()} />}
                    </div>
                ))}
            </Card>
            <Card title="Connections" icon={Link2} testid="org-connections">{o.connections.length ? o.connections.map((c) => <ConnectionRow key={c.type + c.id} c={c} />) : <div className="text-xs text-slate-600">No connections yet.</div>}</Card>
        </NetworkShell>
    );
}
