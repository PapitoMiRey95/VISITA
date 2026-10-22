import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Rocket, Wrench, Megaphone, HeartPulse, Undo2, HelpCircle, ChevronDown, ChevronUp, CheckCircle2, AlertTriangle, Clock } from "lucide-react";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { formatDateTime } from "../lib/date";
import { UpdateWizard, OfflineWizard, MessageWizard, CheckWizard, RecoverWizard, HelpWizard, KIND_LABEL, humanReason } from "./SimpleWizards";

const STATUS = {
    NORMAL: { title: "Everything is working normally.", sub: "No action is needed.", cls: "bg-emerald-500/10 border-emerald-500/40 text-emerald-200", Icon: CheckCircle2 },
    UPDATING: { title: "VIen is being updated.", sub: "VIen stays available. It checks itself and clears the notice automatically.", cls: "bg-sky-500/10 border-sky-500/40 text-sky-100", Icon: Clock },
    MAINTENANCE: { title: "VIen is temporarily offline.", sub: "Users see a calm maintenance screen. Bring VIen back online when finished.", cls: "bg-amber-500/10 border-amber-500/40 text-amber-100", Icon: Wrench },
    SERVICE_ISSUE: { title: "VIen needs attention.", sub: "Users see a short “temporarily unavailable” notice.", cls: "bg-red-500/10 border-red-500/40 text-red-100", Icon: AlertTriangle },
};

function attention(d, announcement) {
    const dep = d.deployment; const st = dep.state; const p = d.probe || {};
    const failing = ["api", "database", "storage", "readiness"].filter((k) => !["ONLINE", "CONNECTED", "READY"].includes(p[k]));
    const last = dep.verification?.checks?.[0];
    if (st === "SERVICE_ISSUE") return { level: "high", text: failing.length ? `${failing.length} system check${failing.length > 1 ? "s are" : " is"} failing (${failing.map(humanReason).join(", ")}).` : last && !last.ok ? `The last check did not pass: ${last.reasons.map(humanReason).join(", ")}.` : (d.history?.[0]?.result === "MANUAL_ISSUE" ? "An operator marked VIen as needing attention. Current checks are passing." : "The last update did not complete in time, but current checks are passing."), rec: dep.verification.streak >= dep.verification.required ? "resolve" : "check" };
    if (st === "MAINTENANCE") return { level: "mid", text: `VIen has been offline since ${formatDateTime(dep.since)}.`, rec: "online" };
    if (st === "UPDATING") return { level: "low", text: last && !last.ok ? `Waiting for the new version (${last.reasons.map(humanReason).join(", ")}). Verified ${dep.verification.streak} of ${dep.verification.required} times.` : `Verified ${dep.verification.streak} of ${dep.verification.required} times so far.`, rec: "check" };
    if (failing.length) return { level: "mid", text: `${failing.length} system check${failing.length > 1 ? "s are" : " is"} failing (${failing.map(humanReason).join(", ")}).`, rec: "check" };
    if (announcement?.active) return { level: "none", text: `A message to users is currently shown: “${announcement.message}”.`, rec: "message" };
    return null;
}
const REC = { check: ["Check VIen", "Run recommended check"], resolve: ["Recover from a problem", "Mark as resolved"], online: ["Bring VIen back online", "Bring VIen back online"], message: ["Post a message to users", "Review message"] };

function TaskCard({ Icon, title, hint, onClick, testid, disabled, tone = "" }) {
    return (
        <button type="button" onClick={onClick} disabled={disabled} data-testid={testid}
            className={`text-left rounded-lg border border-slate-800 bg-slate-900/70 p-4 hover:border-emerald-500/50 hover:bg-slate-900 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${tone}`}>
            <Icon className="w-5 h-5 text-emerald-400" /><div className="mt-2 font-bold text-slate-100">{title}</div><div className="text-xs text-slate-400 mt-1 leading-snug">{hint}</div>
        </button>
    );
}

function HistoryItem({ h }) {
    const [open, setOpen] = useState(false);
    const done = h.status === "COMPLETED";
    const okResult = ["SUCCEEDED", "RESOLVED", "RECOVERED"].includes(h.result);
    const headline = h.kind === "MAINTENANCE" ? (done ? "VIen was temporarily offline and is back" : "VIen is temporarily offline")
        : h.result === "ROLLED_BACK" ? `${KIND_LABEL[h.kind] || h.kind} undone — previous version restored`
        : h.result === "SUPERSEDED" ? `${KIND_LABEL[h.kind] || h.kind} replaced by a newer action`
        : h.status === "SERVICE_ISSUE" ? `${KIND_LABEL[h.kind] || h.kind} needs attention`
        : h.kind === "INCIDENT" ? (done ? "Problem reported — resolved" : "Problem reported")
        : done ? `${KIND_LABEL[h.kind] || h.kind} ${okResult ? "completed successfully" : "finished"}` : `${KIND_LABEL[h.kind] || h.kind} in progress`;
    const verified = h.verified_at ? "VIen verified itself after the update" : h.result === "RESOLVED" ? "Marked resolved by the operator" : h.result === "ROLLED_BACK" ? "Previous version restored by the operator" : h.result === "TIMEOUT" ? "Did not verify in time" : null;
    return (
        <li className="rounded-md border border-slate-800 bg-slate-900/60 p-3" data-testid={`simple-history-${h.id}`}>
            <div className="flex items-start justify-between gap-3">
                <div>
                    <div className={`font-semibold ${h.status === "SERVICE_ISSUE" || h.result === "TIMEOUT" ? "text-red-200" : "text-slate-100"}`} data-testid="simple-history-title">{headline}</div>
                    <div className="text-xs text-slate-400 mt-0.5">{formatDateTime(h.started_at)} · Performed by {h.operator?.name || "operator"}{h.note ? ` · ${h.note}` : ""}</div>
                    {verified && <div className={`text-xs mt-1 ${okResult || h.result === "ROLLED_BACK" ? "text-emerald-300" : "text-amber-300"}`}>{okResult || h.result === "ROLLED_BACK" ? "✓" : "!"} {verified}</div>}
                </div>
                <button type="button" onClick={() => setOpen(!open)} className="text-[11px] text-slate-400 hover:text-slate-200 flex items-center gap-1 shrink-0" data-testid="simple-history-details">{open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />} View technical details</button>
            </div>
            {open && <pre className="mt-2 text-[10px] font-mono text-slate-400 bg-slate-950 rounded-sm p-2 overflow-x-auto" data-testid="simple-history-raw">{JSON.stringify(h, null, 2)}</pre>}
        </li>
    );
}

export function SimpleOps({ status, onChanged }) {
    const q = useQuery({ queryKey: ["developer-deployment"], queryFn: async () => (await api.get("/developer/deployment")).data, refetchInterval: 15000 });
    const [wiz, setWiz] = useState(null); // update | offline | message | check | recover | help | online
    const d = q.data;
    if (q.error) return <div className="text-sm text-red-400">{formatErr(q.error)}</div>;
    if (!d) return <div className="text-sm text-slate-500" data-testid="simple-loading">Loading…</div>;
    const st = d.deployment.state; const S = STATUS[st] || STATUS.NORMAL;
    const att = attention(d, status?.announcement);
    const changed = () => { q.refetch(); onChanged(); };
    const close = () => setWiz(null);
    const maintenanceOn = st === "MAINTENANCE";
    return (
        <div className="space-y-6" data-testid="simple-ops">
            <section className={`rounded-lg border p-5 ${S.cls}`} data-testid="simple-status" data-state={st}>
                <div className="flex items-start gap-3"><S.Icon className="w-7 h-7 shrink-0" /><div><div className="text-[11px] uppercase tracking-widest opacity-70">Is VIen working?</div><h2 className="text-xl font-extrabold" data-testid="simple-status-title">{S.title}</h2><p className="text-sm opacity-80 mt-0.5">{S.sub}</p></div></div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-5" data-testid="simple-attention">
                <div className="text-[11px] uppercase tracking-widest text-slate-500">Does anything need my attention?</div>
                {att ? (
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
                        <div><div className="text-sm text-slate-100" data-testid="simple-attention-text">{att.text}</div><div className="text-xs text-slate-400 mt-1">Recommended: <span className="text-emerald-300 font-semibold" data-testid="simple-recommended">{REC[att.rec][0]}</span></div></div>
                        <Button onClick={() => setWiz(att.rec === "online" ? "offline" : att.rec === "resolve" ? "recover" : att.rec)} className="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold" data-testid="simple-recommended-run">{REC[att.rec][1]}</Button>
                    </div>
                ) : <div className="mt-2 text-sm text-slate-200" data-testid="simple-attention-none">{d.history?.[0]?.result && d.history[0].result !== "SUCCEEDED" ? "Everything is healthy again. No further action is needed." : "No. All system checks are passing."}</div>}
            </section>

            <section>
                <div className="text-[11px] uppercase tracking-widest text-slate-500 mb-2">What can I safely do?</div>
                <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="simple-tasks">
                    <TaskCard Icon={Rocket} title="Update VIen" hint="Install a new version while VIen remains available." onClick={() => setWiz("update")} testid="task-update" disabled={maintenanceOn || st === "UPDATING"} />
                    <TaskCard Icon={Wrench} title={maintenanceOn ? "Bring VIen back online" : "Take VIen temporarily offline"} hint={maintenanceOn ? "Users can use VIen again." : "For maintenance that should stop user changes."} onClick={() => setWiz("offline")} testid="task-offline" />
                    <TaskCard Icon={Megaphone} title="Post a message to users" hint="Show an informational notice across VIen." onClick={() => setWiz("message")} testid="task-message" />
                    <TaskCard Icon={HeartPulse} title="Check VIen" hint="Check the website, database and storage." onClick={() => setWiz("check")} testid="task-check" />
                    <TaskCard Icon={Undo2} title="Recover from a problem" hint="Undo or resolve a problematic update." onClick={() => setWiz("recover")} testid="task-recover" />
                    <TaskCard Icon={HelpCircle} title="I’m not sure / Help me choose" hint="Answer one question and we’ll point you to the safest action." onClick={() => setWiz("help")} testid="task-help" tone="border-dashed" />
                </div>
            </section>

            <section data-testid="simple-history">
                <div className="text-[11px] uppercase tracking-widest text-slate-500 mb-2">Recent activity</div>
                <ul className="space-y-2">{(d.history || []).slice(0, 8).map((h) => <HistoryItem key={h.id} h={h} />)}{!d.history?.length && <li className="text-sm text-slate-500 italic">Nothing recorded yet.</li>}</ul>
            </section>

            <UpdateWizard key={`u${wiz === "update"}`} open={wiz === "update"} onClose={close} onDone={changed} />
            <OfflineWizard key={`o${wiz === "offline"}${maintenanceOn}`} open={wiz === "offline"} onClose={close} onDone={changed} on={maintenanceOn} />
            <MessageWizard key={`m${wiz === "message"}`} open={wiz === "message"} onClose={close} onDone={changed} current={status?.announcement} />
            <CheckWizard key={`c${wiz === "check"}`} open={wiz === "check"} onClose={close} onDone={changed} />
            <RecoverWizard key={`r${wiz === "recover"}`} open={wiz === "recover"} onClose={close} onDone={changed} state={st} />
            <HelpWizard key={`h${wiz === "help"}`} open={wiz === "help"} onClose={close} onPick={setWiz} />
        </div>
    );
}
