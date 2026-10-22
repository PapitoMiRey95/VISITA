import { overdueDays } from "./workHubParts";

// Pure triage rules for active Work Hub lists. Read-only over existing fields; never stored.
const DAY = 86400000;
const SOON_DAYS = 7;

export const TRIAGE_GROUPS = [
    { key: "NOW", title: "Now", hint: "Overdue · due today · ASAP · needs attention", accent: "text-red-700 border-red-300", dot: "bg-red-500" },
    { key: "NEXT", title: "Next", hint: "Due soon · B1 / B2 · important", accent: "text-amber-800 border-amber-300", dot: "bg-amber-400" },
    { key: "ROUTINE", title: "Routine", hint: "No immediate urgency", accent: "text-slate-600 border-slate-300", dot: "bg-slate-300" },
];

export const effectiveDue = (item) => item.due_at || (item.status === "WAITING" ? item.waiting_until : null) || null;
export const isDueToday = (iso) => Boolean(iso) && new Date(iso).toDateString() === new Date().toDateString();
const daysUntil = (iso) => (iso ? Math.ceil((new Date(iso).getTime() - Date.now()) / DAY) : null);
const isOverdue = (item) => { const d = effectiveDue(item); return Boolean(d) && item.status !== "COMPLETED" && new Date(d).getTime() < Date.now(); };

// Lower = more urgent. Drives both the group and the order inside the group.
export function urgencyRank(item) {
    if (isOverdue(item)) return 0;
    if (isDueToday(effectiveDue(item))) return 1;
    if (item.priority === "ASAP") return 2;
    if (item.attention_level === "NEEDS_ATTENTION") return 3;
    if (item.signed && item.owner_role === "CLINIC") return 3;
    if (item.priority === "B1") return 4;
    const du = daysUntil(effectiveDue(item));
    if (du !== null && du <= SOON_DAYS) return 5;
    if (item.attention_level === "IMPORTANT") return 6;
    if (item.priority === "B2") return 7;
    return 9;
}
export const triageOf = (item) => { const r = urgencyRank(item); return r <= 3 ? "NOW" : r <= 7 ? "NEXT" : "ROUTINE"; };

// 1) urgency rank 2) earliest due/waiting time (none last) 3) oldest waiting item first.
export function triageSort(a, b) {
    const ra = urgencyRank(a), rb = urgencyRank(b);
    if (ra !== rb) return ra - rb;
    const da = effectiveDue(a), db = effectiveDue(b);
    if (da && db && da !== db) return da < db ? -1 : 1;
    if (!!da !== !!db) return da ? -1 : 1;
    return (a.created_at || "") < (b.created_at || "") ? -1 : 1;
}

export function groupByTriage(items) {
    const active = items.filter((i) => i.status !== "COMPLETED");
    return TRIAGE_GROUPS.map((g) => ({ ...g, items: active.filter((i) => triageOf(i) === g.key).sort(triageSort) })).filter((g) => g.items.length > 0);
}

export function triageCounts(items) {
    const c = { NOW: 0, NEXT: 0, ROUTINE: 0 };
    items.filter((i) => i.status !== "COMPLETED").forEach((i) => { c[triageOf(i)] += 1; });
    return c;
}

// Short task line: structured first, then free text.
export function taskLine(item) {
    const s = item.reason_label && item.reason_code !== item.referral_subtype ? item.reason_label : item.structured_summary;
    const extra = item.clinic_action_label && item.clinic_action_label !== s ? item.clinic_action_label : null;
    const base = s ? (extra ? `${s} — ${extra}` : s) : (item.message || "");
    if (!s && !item.message && item.clinic_action_label) return item.clinic_action_label;
    return base || "—";
}

// Visual clustering of identical actionable work (same category + same task). Records stay independent.
const MIN_CLUSTER = 3;
export function clusterItems(items) {
    const buckets = new Map();
    items.forEach((it) => {
        const k = `${it.category}|${taskLine(it).toLowerCase().replace(/\s+/g, " ").trim()}`;
        if (!buckets.has(k)) buckets.set(k, []);
        buckets.get(k).push(it);
    });
    const out = [];
    const used = new Set();
    items.forEach((it) => {
        if (used.has(it.id)) return;
        const k = `${it.category}|${taskLine(it).toLowerCase().replace(/\s+/g, " ").trim()}`;
        const b = buckets.get(k);
        if (b.length >= MIN_CLUSTER) {
            b.forEach((x) => used.add(x.id));
            out.push({ type: "cluster", key: k, category: it.category, task: taskLine(it), items: b });
        } else out.push({ type: "item", item: it });
    });
    return out;
}

// Concise single-state ownership label (preserves underlying owner_* fields).
export function shortName(name) {
    if (!name) return "";
    const parts = name.trim().split(/\s+/);
    if (/^dr\.?$/i.test(parts[0]) && parts.length > 1) return `Dr. ${parts[parts.length - 1]}`;
    return name;
}
export function ownerState(item, { userId, side } = {}) {
    if (item.status === "COMPLETED") return "Completed";
    const mineUser = item.owner_user_id && item.owner_user_id === userId;
    const mineQueue = !item.owner_user_id && item.owner_role === side;
    if (mineUser) return "You";
    if (item.awaiting_physician && item.created_by_role !== "physician") return `Waiting on ${shortName(item.owner_name) || "physician"}`;
    if (item.owner_user_id) return shortName(item.owner_name) || "Member";
    if (mineQueue) return item.owner_role === "CLINIC" ? "Clinic queue" : "Physician queue";
    return item.owner_role === "CLINIC" ? "Clinic" : "Any physician";
}

// Due / urgency text for the card footer (urgency only; no owner, no status words).
export function dueText(item) {
    const od = overdueDays(item);
    if (od !== null) return { text: od > 0 ? `Overdue · ${od} day${od === 1 ? "" : "s"}` : "Overdue", tone: "red" };
    const due = effectiveDue(item);
    if (isDueToday(due)) return { text: item.status === "WAITING" && !item.due_at ? "Resume today" : "Due today", tone: "red" };
    if (item.priority === "ASAP") return { text: "ASAP", tone: "red" };
    if (item.attention_level === "NEEDS_ATTENTION") return { text: "Needs attention", tone: "red" };
    if (item.signed && item.owner_role === "CLINIC") return { text: "Signed · action required", tone: "red" };
    const du = daysUntil(due);
    if (du !== null) {
        if (du === 1) return { text: item.status === "WAITING" && !item.due_at ? "Resume tomorrow" : "Due tomorrow", tone: du <= SOON_DAYS ? "amber" : "slate" };
        return { text: `${item.status === "WAITING" && !item.due_at ? "Resume" : "Due"} in ${du} days`, tone: du <= SOON_DAYS ? "amber" : "slate" };
    }
    if (item.priority === "B1") return { text: "B1 · ~1 week", tone: "amber" };
    if (item.attention_level === "IMPORTANT") return { text: "Important", tone: "amber" };
    if (item.priority === "B2") return { text: "B2 · 3–4 weeks", tone: "amber" };
    return { text: "", tone: "slate" };
}

// Unread = NEW and not yet opened by this user on this device.
const seenKey = (userId) => `vien.work.seen.${userId || "anon"}`;
export function loadSeen(userId) {
    try { return new Set(JSON.parse(localStorage.getItem(seenKey(userId)) || "[]")); } catch { return new Set(); }
}
export function markSeen(userId, id) {
    const s = loadSeen(userId); s.add(id);
    localStorage.setItem(seenKey(userId), JSON.stringify([...s].slice(-500)));
    return s;
}
export const isUnread = (item, seen) => item.status === "NEW" && !seen.has(item.id);
