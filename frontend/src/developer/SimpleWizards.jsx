import { useState } from "react";
import { toast } from "sonner";
import { api, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";

/* Guided wizards for SIMPLE mode. Every wizard ends in the SAME audited endpoints as ADVANCED mode. */
export const KIND_LABEL = { CODE: "Software update", RESOURCE: "Server resources update", HOTFIX: "Small urgent fix", MAINTENANCE: "Temporarily offline (maintenance)", INCIDENT: "Problem reported" };

const Step = ({ n, title, children }) => (
    <div className="space-y-2"><div className="text-[11px] uppercase tracking-widest text-slate-500">Step {n}</div><div className="text-base font-bold text-slate-100">{title}</div>{children}</div>
);
const Choice = ({ active, onClick, title, hint, testid }) => (
    <button type="button" onClick={onClick} data-testid={testid} aria-pressed={active}
        className={`w-full text-left rounded-md border px-3 py-2.5 transition-colors ${active ? "border-emerald-400 bg-emerald-500/10" : "border-slate-700 hover:border-slate-500"}`}>
        <div className="text-sm font-semibold text-slate-100">{title}</div>{hint && <div className="text-xs text-slate-400 mt-0.5">{hint}</div>}
    </button>
);
export const Facts = ({ will, wont }) => (
    <div className="grid sm:grid-cols-2 gap-3 text-xs">
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3"><div className="font-bold text-emerald-300 mb-1">What WILL happen</div><ul className="space-y-1 text-slate-200">{will.map((w) => <li key={w}>✓ {w}</li>)}</ul></div>
        <div className="rounded-md border border-slate-700 p-3"><div className="font-bold text-slate-300 mb-1">What will NOT happen</div><ul className="space-y-1 text-slate-300">{wont.map((w) => <li key={w}>✕ {w}</li>)}</ul></div>
    </div>
);
function Shell({ open, onClose, title, desc, children, testid }) {
    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-lg bg-slate-900 border-slate-700 text-slate-100" data-testid={testid}>
                <DialogHeader><DialogTitle>{title}</DialogTitle>{desc && <DialogDescription className="text-slate-400">{desc}</DialogDescription>}</DialogHeader>
                {children}
            </DialogContent>
        </Dialog>
    );
}
const useRun = (onDone) => {
    const [busy, setBusy] = useState(false);
    const run = async (fn, ok) => { setBusy(true); try { const r = await fn(); toast.success(ok); onDone?.(r); return r; } catch (e) { toast.error(formatErr(e)); return null; } finally { setBusy(false); } };
    return [busy, run];
};

export function UpdateWizard({ open, onClose, onDone, presetKind }) {
    const [kind, setKind] = useState(presetKind || null);
    const [note, setNote] = useState("");
    const [step, setStep] = useState(presetKind ? 2 : 1);
    const [busy, run] = useRun(onDone);
    const begin = () => run(() => api.post("/developer/deployment/begin-update", { kind, note }), "Update started. VIen stays available and will check itself.").then((r) => r && onClose());
    return (
        <Shell open={open} onClose={onClose} title="Update VIen" desc="Install a new version while VIen remains available." testid="wiz-update">
            {step === 1 && (
                <Step n={1} title="What are you updating?">
                    <Choice active={kind === "CODE"} onClick={() => setKind("CODE")} title="New software version" hint="A new release of the VIen application." testid="wiz-update-kind-code" />
                    <Choice active={kind === "RESOURCE"} onClick={() => setKind("RESOURCE")} title="Server resources" hint="More memory or processing power. The software itself does not change." testid="wiz-update-kind-resource" />
                    <Choice active={kind === "HOTFIX"} onClick={() => setKind("HOTFIX")} title="Small urgent fix" hint="A quick correction to the current version." testid="wiz-update-kind-hotfix" />
                    <Choice active={false} onClick={() => { setKind("CODE"); setNote("Not sure of the update type — treated as a software update."); setStep(2); }} title="I’m not sure" hint="We’ll treat it as a software update, the safest default. VIen checks itself either way." testid="wiz-update-kind-unsure" />
                    <DialogFooter><Button variant="outline" onClick={onClose} className="border-slate-600 text-slate-200">Cancel</Button><Button disabled={!kind} onClick={() => setStep(2)} className="bg-emerald-500 text-slate-950" data-testid="wiz-update-next">Continue</Button></DialogFooter>
                </Step>
            )}
            {step === 2 && (
                <Step n={2} title={`Ready to start: ${KIND_LABEL[kind]}`}>
                    <Facts will={["VIen will remain available.", "Users will see a brief update notice.", "VIen will automatically check itself after the update."]}
                        wont={["Patient records will not be changed.", "No user will be logged out by this step.", "Nothing is undone or deleted."]} />
                    <label className="block text-xs text-slate-400">Optional note (what is being updated)<Input value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 bg-slate-950 border-slate-700 text-slate-100" data-testid="wiz-update-note" /></label>
                    <p className="text-xs text-slate-400">Next: start the update in the hosting panel. VIen clears the notice by itself once it has verified the new version three times in a row.</p>
                    <DialogFooter><Button variant="outline" onClick={() => setStep(1)} className="border-slate-600 text-slate-200">Back</Button><Button disabled={busy} onClick={begin} className="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold" data-testid="wiz-update-begin">Begin Update</Button></DialogFooter>
                </Step>
            )}
        </Shell>
    );
}

export function OfflineWizard({ open, onClose, onDone, on }) {
    const [confirm, setConfirm] = useState("");
    const [ack, setAck] = useState(false);
    const [busy, run] = useRun(onDone);
    const word = on ? "EXIT" : "ENTER";
    const go = () => run(() => api.post("/developer/maintenance-mode", { on: !on, confirm }), on ? "VIen is back online." : "VIen is temporarily offline for users.").then((r) => r && onClose());
    return (
        <Shell open={open} onClose={onClose} title={on ? "Bring VIen back online" : "Take VIen temporarily offline"} desc={on ? "Users will be able to use VIen again." : "For maintenance that should stop user changes."} testid="wiz-offline">
            {on ? <Facts will={["Users can sign in and use VIen again.", "The offline screen disappears automatically."]} wont={["No data is changed.", "No update is undone."]} />
                : <Facts will={["Patients, clinics and pharmacies see a calm “temporarily unavailable” screen.", "Saving and changes are blocked for all users until you bring VIen back.", "Operators keep access to this Control Center."]}
                    wont={["Patient records are NOT deleted or modified.", "No update is installed by this step.", "Nothing happens until you confirm below."]} />}
            {!on && <label className="flex items-start gap-2 text-xs text-slate-300"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="wiz-offline-ack" /> I understand users will not be able to use VIen until I bring it back online.</label>}
            <label className="block text-xs text-slate-400">Type <span className="font-mono font-bold text-slate-100">{word}</span> to confirm<Input value={confirm} onChange={(e) => setConfirm(e.target.value)} className="mt-1 bg-slate-950 border-slate-700 text-slate-100 font-mono" data-testid="wiz-offline-confirm" /></label>
            <DialogFooter><Button variant="outline" onClick={onClose} className="border-slate-600 text-slate-200">Cancel</Button>
                <Button disabled={busy || confirm !== word || (!on && !ack)} onClick={go} className={on ? "bg-emerald-500 text-slate-950 font-bold" : "bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold"} data-testid="wiz-offline-go">{on ? "Bring VIen back online" : "Take VIen offline"}</Button></DialogFooter>
        </Shell>
    );
}

export function MessageWizard({ open, onClose, onDone, current }) {
    const [message, setMessage] = useState(current?.active ? current.message : "");
    const [type, setType] = useState(current?.type || "INFO");
    const [busy, run] = useRun(onDone);
    const post = () => run(() => api.put("/developer/announcement", { message, type }), "Message is now visible to users.").then((r) => r && onClose());
    const remove = () => run(() => api.delete("/developer/announcement"), "Message removed.").then((r) => r && onClose());
    return (
        <Shell open={open} onClose={onClose} title="Post a message to users" desc="Show an informational notice across VIen. It does not block anyone." testid="wiz-message">
            <Textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Example: The clinic closes early this Friday at 3:00 PM." className="bg-slate-950 border-slate-700 text-slate-100" data-testid="wiz-message-text" />
            <div className="grid grid-cols-3 gap-2">
                {[["INFO", "Information", "Blue · general notices"], ["WARNING", "Heads-up", "Amber · something to plan for"], ["CRITICAL", "Important", "Red · only for urgent matters"]].map(([v, t, h]) => <Choice key={v} active={type === v} onClick={() => setType(v)} title={t} hint={h} testid={`wiz-message-type-${v.toLowerCase()}`} />)}
            </div>
            <div className="rounded-sm overflow-hidden border border-slate-700 text-[13px]"><div className={`px-3 py-1.5 text-center font-semibold ${type === "INFO" ? "bg-sky-700 text-white" : type === "WARNING" ? "bg-amber-500 text-slate-900" : "bg-red-700 text-white"}`} data-testid="wiz-message-preview">{message || "Your message preview"}</div></div>
            <DialogFooter>{current?.active && <Button variant="outline" disabled={busy} onClick={remove} className="border-slate-600 text-slate-200" data-testid="wiz-message-remove">Remove current message</Button>}
                <Button disabled={busy || !message.trim()} onClick={post} className="bg-emerald-500 text-slate-950 font-bold" data-testid="wiz-message-post">{current?.active ? "Update message" : "Post message"}</Button></DialogFooter>
        </Shell>
    );
}

export function CheckWizard({ open, onClose, onDone }) {
    const [result, setResult] = useState(null);
    const [busy, run] = useRun(onDone);
    const check = async () => { const r = await run(() => api.post("/developer/deployment/verify"), "Check complete"); if (r) setResult(r.data); };
    return (
        <Shell open={open} onClose={onClose} title="Check VIen" desc="Checks the website, database and storage. Safe to run at any time." testid="wiz-check">
            {!result && <p className="text-sm text-slate-300">This takes a few seconds and changes nothing.</p>}
            {result && (
                <div className={`rounded-md border p-3 text-sm ${result.ok ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" : "border-amber-500/40 bg-amber-500/10 text-amber-100"}`} data-testid="wiz-check-result">
                    {result.ok ? "All checks passed. VIen is healthy." : `A check did not pass (${result.reasons.map(humanReason).join("; ")}). If this continues, use “Recover from a problem”.`}
                    {result.state === "NORMAL" && result.result && <div className="mt-1 text-xs">VIen verified itself and returned to normal operation.</div>}
                </div>
            )}
            <DialogFooter><Button variant="outline" onClick={onClose} className="border-slate-600 text-slate-200">Close</Button><Button disabled={busy} onClick={check} className="bg-emerald-500 text-slate-950 font-bold" data-testid="wiz-check-run">{busy ? "Checking…" : result ? "Check again" : "Run check"}</Button></DialogFooter>
        </Shell>
    );
}
export const humanReason = (r) => r.startsWith("commit") ? "the new version is not running yet" : ({ api: "website", database: "database", storage: "file storage", readiness: "startup not finished" }[r] || r);

export function RecoverWizard({ open, onClose, onDone, state }) {
    const [choice, setChoice] = useState(null);
    const [confirm, setConfirm] = useState("");
    const [note, setNote] = useState("");
    const [busy, run] = useRun(onDone);
    const canResolve = state === "SERVICE_ISSUE" || state === "UPDATING";
    const act = async () => {
        let r = null;
        if (choice === "undo") r = await run(() => api.post("/developer/deployment/resolve", { confirm, note, rolled_back: true }), "Recorded: previous version restored. VIen is back to normal.");
        if (choice === "resolve") r = await run(() => api.post("/developer/deployment/resolve", { confirm, note, rolled_back: false }), "Problem marked as resolved. VIen is back to normal.");
        if (choice === "flag") r = await run(() => api.post("/developer/deployment/service-issue", { confirm, note }), "VIen is now marked as needing attention; users see a calm notice.");
        if (r) onClose();
    };
    const word = choice === "flag" ? "ISSUE" : "RESOLVE";
    return (
        <Shell open={open} onClose={onClose} title="Recover from a problem" desc="Undo or resolve a problematic update. Patient records are never affected by these actions." testid="wiz-recover">
            {!choice && (<>
                {canResolve && <Choice onClick={() => setChoice("undo")} title="Undo last update" hint="You restored the previous version in the hosting panel; record it and return VIen to normal." testid="wiz-recover-undo" />}
                {canResolve && <Choice onClick={() => setChoice("resolve")} title="The problem is fixed — mark as resolved" hint="Removes the attention notice and returns VIen to normal." testid="wiz-recover-resolve" />}
                {state === "UPDATING" && <Choice onClick={() => setChoice("flag")} title="Something is wrong — mark VIen as needing attention" hint="Switches the update notice to a calm “temporarily unavailable” notice while you investigate." testid="wiz-recover-flag" />}
                {!canResolve && <p className="text-sm text-slate-300" data-testid="wiz-recover-none">VIen is not reporting a problem right now. If a page shows an error, run “Check VIen” first.</p>}
            </>)}
            {choice && (<>
                {choice === "undo" && <Facts will={["VIen is recorded as returned to the previous application version.", "The attention notice is removed and VIen returns to normal."]} wont={["It does NOT roll back patient records or clinical data.", "It does NOT reinstall anything by itself — do the rollback in the hosting panel first."]} />}
                {choice === "resolve" && <Facts will={["The notice is removed.", "VIen returns to normal operation.", "The outcome is recorded with your name and time."]} wont={["Nothing is installed, undone or deleted.", "Patient records are not touched."]} />}
                {choice === "flag" && <Facts will={["Users see “VIen is temporarily unavailable…” instead of the update notice.", "VIen stays reachable; this is a status change only."]} wont={["Access is not blocked (use “Take VIen offline” for that).", "No data is changed."]} />}
                <label className="block text-xs text-slate-400">What happened? (optional)<Input value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 bg-slate-950 border-slate-700 text-slate-100" data-testid="wiz-recover-note" /></label>
                <label className="block text-xs text-slate-400">Type <span className="font-mono font-bold text-slate-100">{word}</span> to confirm<Input value={confirm} onChange={(e) => setConfirm(e.target.value)} className="mt-1 bg-slate-950 border-slate-700 text-slate-100 font-mono" data-testid="wiz-recover-confirm" /></label>
                <DialogFooter><Button variant="outline" onClick={() => { setChoice(null); setConfirm(""); }} className="border-slate-600 text-slate-200">Back</Button>
                    <Button disabled={busy || confirm !== word} onClick={act} className={choice === "flag" ? "bg-red-600 hover:bg-red-500 text-white font-bold" : "bg-emerald-500 text-slate-950 font-bold"} data-testid="wiz-recover-go">
                        {choice === "undo" ? "Record undo & return to normal" : choice === "resolve" ? "Mark as resolved" : "Mark as needing attention"}</Button></DialogFooter>
            </>)}
        </Shell>
    );
}

export function HelpWizard({ open, onClose, onPick }) {
    const OPTIONS = [
        ["install", "I want to install an update", "Use “Update VIen”. VIen stays available and checks itself afterwards.", "update"],
        ["slow", "VIen feels slow", "Run “Check VIen” first. If checks pass, slowness is usually temporary; a server-resources update may help.", "check"],
        ["login", "Users cannot log in", "Run “Check VIen”. If a check fails, use “Recover from a problem” and contact your developer.", "check"],
        ["error", "A page is showing an error", "Run “Check VIen”. A failing check points to the cause; otherwise note the page and time for your developer.", "check"],
        ["stop", "I need to temporarily stop access", "Use “Take VIen temporarily offline”. It blocks changes and shows a calm screen to users.", "offline"],
        ["message", "I only want to post a message", "Use “Post a message to users”. It never blocks anyone.", "message"],
    ];
    const [sel, setSel] = useState(null);
    const o = OPTIONS.find((x) => x[0] === sel);
    return (
        <Shell open={open} onClose={onClose} title="Help me choose" desc="What are you experiencing?" testid="wiz-help">
            <div className="space-y-2">{OPTIONS.map(([k, t]) => <Choice key={k} active={sel === k} onClick={() => setSel(k)} title={t} testid={`wiz-help-${k}`} />)}</div>
            {o && <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-100" data-testid="wiz-help-advice">{o[2]}</div>}
            <DialogFooter><Button variant="outline" onClick={onClose} className="border-slate-600 text-slate-200">Close</Button><Button disabled={!o} onClick={() => { onClose(); onPick(o[3]); }} className="bg-emerald-500 text-slate-950 font-bold" data-testid="wiz-help-go">Take me there</Button></DialogFooter>
        </Shell>
    );
}
