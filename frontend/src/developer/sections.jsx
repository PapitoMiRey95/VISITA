import { useState } from "react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { formatErr } from "../lib/api";
import { Card, PublishBar, saveDraft } from "./platformConfig";

const effective = (cfg) => (cfg?.draft || cfg?.published)?.config || {};

export function FeaturesSection({ cfg, onChanged }) {
    const conf = effective(cfg);
    const reg = cfg?.registry || {};
    const [busy, setBusy] = useState(false);
    const setFeature = async (key, state) => {
        setBusy(true);
        try { await saveDraft("features", { ...conf.features, [key]: state }); onChanged(); } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    const toggleNav = async (audience, key) => {
        const hidden = { ...(conf.navigation?.hidden || {}) };
        const list = new Set(hidden[audience] || []);
        list.has(key) ? list.delete(key) : list.add(key);
        hidden[audience] = [...list];
        setBusy(true);
        try { await saveDraft("navigation", { hidden }); onChanged(); } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <div className="space-y-5">
            <Card title="Feature registry" testid="pc-features">
                <p className="text-xs text-slate-400 mb-3">OFF fails closed at the API and hides navigation. PILOT = internal roles only (admin / physician / staff). Security, privacy, audit and signed-visit integrity are safeguards and are not listed here.</p>
                <table className="w-full text-sm">
                    <tbody>
                        {Object.entries(reg.features || {}).map(([key, label]) => (
                            <tr key={key} className="border-b border-slate-800" data-testid={`feature-row-${key}`}>
                                <td className="py-2 text-slate-200">{label} <span className="text-[10px] text-slate-500 font-mono">{key}</span></td>
                                <td className="py-2 text-right">
                                    {(reg.states || []).map((st) => (
                                        <button key={st} type="button" disabled={busy} onClick={() => setFeature(key, st)} data-testid={`feature-${key}-${st.toLowerCase()}`}
                                            className={`ml-1 px-2 py-0.5 rounded-sm text-xs font-bold border ${conf.features?.[key] === st ? (st === "OFF" ? "bg-slate-500 text-slate-950 border-slate-500" : st === "PILOT" ? "bg-amber-400 text-slate-900 border-amber-400" : "bg-emerald-500 text-slate-900 border-emerald-500") : "border-slate-700 text-slate-400"}`}>{st}</button>
                                    ))}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </Card>
            <Card title="Navigation visibility (not authorization)" testid="pc-navigation">
                <p className="text-xs text-slate-400 mb-3">Tick to hide a module from an audience's navigation. Backend permissions are unchanged by this setting.</p>
                <div className="overflow-x-auto"><table className="text-xs">
                    <thead><tr><th className="text-left text-slate-500 pr-3">Module</th>{(reg.audiences || []).map((a) => <th key={a} className="px-2 text-slate-500 uppercase">{a}</th>)}</tr></thead>
                    <tbody>{Object.entries(reg.features || {}).map(([key, label]) => (
                        <tr key={key} className="border-b border-slate-800"><td className="py-1 pr-3 text-slate-300">{label}</td>
                            {(reg.audiences || []).map((a) => <td key={a} className="text-center"><input type="checkbox" disabled={busy} checked={(conf.navigation?.hidden?.[a] || []).includes(key)} onChange={() => toggleNav(a, key)} data-testid={`nav-hide-${a}-${key}`} /></td>)}
                        </tr>
                    ))}</tbody>
                </table></div>
            </Card>
            <PublishBar cfg={cfg} onChanged={onChanged} />
        </div>
    );
}

const FIELDS = [
    ["headline", "Main headline", "input"], ["subtitle", "Subtitle", "input"], ["search_placeholder", "Search placeholder", "input"],
    ["cta_create_portal", "CTA: Create Patient Portal", "input"], ["cta_apply_for_care", "CTA: Apply for care", "input"],
    ["coming_soon_label", "Coming Soon label", "input"], ["footer_contact", "Footer / contact information", "textarea"],
];

export function PublicSiteSection({ cfg, onChanged }) {
    const conf = effective(cfg);
    const [form, setForm] = useState(conf.public_site || {});
    const [busy, setBusy] = useState(false);
    const save = async () => {
        setBusy(true);
        try { await saveDraft("public_site", { ...form, show_role_section: form.show_role_section !== false }); toast.success("Draft saved — preview updated"); onChanged(); }
        catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
    };
    return (
        <div className="space-y-5">
            <div className="grid md:grid-cols-2 gap-5">
                <Card title="Public site copy (draft)" testid="pc-public-site">
                    <p className="text-xs text-slate-400 mb-3">Operator-configurable copy only. Legal, privacy, security and emergency language is not editable here.</p>
                    <div className="space-y-2">
                        {FIELDS.map(([k, label, kind]) => (
                            <label key={k} className="block text-xs text-slate-400">{label}
                                {kind === "textarea"
                                    ? <Textarea rows={2} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} className="mt-1 bg-slate-950 border-slate-700 text-slate-100" data-testid={`ps-${k}`} />
                                    : <Input value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} className="mt-1 bg-slate-950 border-slate-700 text-slate-100" data-testid={`ps-${k}`} />}
                            </label>
                        ))}
                        <label className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={form.show_role_section !== false} onChange={(e) => setForm({ ...form, show_role_section: e.target.checked })} data-testid="ps-show_role_section" /> Show “How do you use VIen?” role section</label>
                        <Button size="sm" disabled={busy} onClick={save} className="bg-sky-500 hover:bg-sky-400 text-slate-900" data-testid="ps-save-draft">Save draft</Button>
                    </div>
                </Card>
                <Card title="Preview (draft)" testid="pc-public-preview">
                    <div className="rounded-md bg-[#081423] p-5 text-center border border-slate-800">
                        <div className="text-2xl font-bold text-white" data-testid="ps-preview-headline">{form.headline || <span className="text-slate-600 text-sm">(no headline — default landing)</span>}</div>
                        <div className="text-slate-300 text-sm mt-1">{form.subtitle}</div>
                        <div className="mt-4 h-11 rounded-full bg-[#0f1e30] border border-white/10 text-slate-500 text-sm flex items-center px-5">{form.search_placeholder || "Search clinic, physician, pharmacy or service…"}</div>
                        <div className="mt-4 flex justify-center gap-2 text-xs">
                            <span className="px-3 py-1.5 rounded-md bg-cyan-500 text-slate-900 font-bold">{form.cta_create_portal || "Create Patient Portal"}</span>
                            <span className="px-3 py-1.5 rounded-md border border-slate-600 text-slate-200">{form.cta_apply_for_care || "Apply for care"}</span>
                        </div>
                        {form.footer_contact && <div className="mt-4 text-[11px] text-slate-400 whitespace-pre-wrap">{form.footer_contact}</div>}
                    </div>
                    <div className="text-[11px] text-slate-500 mt-2">Live site shows v{cfg?.published?.version ?? 0}. Publish to apply the draft.</div>
                </Card>
            </div>
            <PublishBar cfg={cfg} onChanged={onChanged} />
        </div>
    );
}
