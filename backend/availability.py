"""Physician availability + native slot generation.

Availability is fully configurable (stored in the `settings` collection under
id="availability"). VIen EMR is the source of truth: slot generation subtracts
`busy` times (confirmed appointments), blocked periods, closures and vacations.
No external calendar dependency.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULT_AVAILABILITY = {
    "id": "availability",
    "timezone": "America/Toronto",
    "appointment_duration": 30,
    "days": {
        "mon": {"enabled": True, "start": "11:30", "end": "16:30"},
        "tue": {"enabled": True, "start": "11:30", "end": "16:30"},
        "wed": {"enabled": True, "start": "11:30", "end": "16:30"},
        "thu": {"enabled": True, "start": "11:30", "end": "16:30"},
        "fri": {"enabled": False, "start": "11:30", "end": "16:30"},
        "sat": {"enabled": False, "start": "11:30", "end": "16:30"},
        "sun": {"enabled": False, "start": "11:30", "end": "16:30"},
    },
    "vacations": [],        # [{"start": "2026-07-01", "end": "2026-07-14", "reason": ""}]
    "closures": [],         # [{"date": "2026-06-25", "reason": ""}]
    "blocked_periods": [],  # [{"date": "2026-06-23", "start": "13:00", "end": "14:00", "reason": ""}]
    "exceptions": [],       # [{"date": "2026-06-27", "start": "10:00", "end": "13:00"}] override hours
    "break_start": "15:00",  # recurring daily break (applies to every working day)
    "break_end": "15:30",
}


def _to_min(hhmm: str) -> int:
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def _label(mins: int) -> str:
    h, m = divmod(mins, 60)
    ampm = "AM" if h < 12 else "PM"
    hh = h % 12 or 12
    return f"{hh}:{m:02d} {ampm}"


def _norm_time(t: str) -> str:
    """Accept 'HH:MM' or a label like '1:30 PM' and return 'HH:MM' 24h."""
    t = (t or "").strip()
    if not t:
        return ""
    up = t.upper()
    if "AM" in up or "PM" in up:
        pm = "PM" in up
        core = up.replace("AM", "").replace("PM", "").strip()
        h, m = (core.split(":") + ["0"])[:2]
        h = int(h) % 12 + (12 if pm else 0)
        return f"{h:02d}:{int(m):02d}"
    h, m = (t.split(":") + ["0"])[:2]
    return f"{int(h):02d}:{int(m):02d}"


def _now_cutoff(avail):
    """(today_iso, minutes_since_midnight) in the clinic timezone (America/Toronto)."""
    tz = ZoneInfo((avail or {}).get("timezone") or "America/Toronto")
    now = datetime.now(tz)
    return now.date().isoformat(), now.hour * 60 + now.minute


def is_past_slot(avail, ds: str, time_str: str) -> bool:
    """True if the given date/time is earlier than 'now' in the clinic timezone."""
    if not ds:
        return False
    today_iso, now_min = _now_cutoff(avail)
    if ds < today_iso:
        return True
    if ds == today_iso and _to_min(_norm_time(time_str)) < now_min:
        return True
    return False


def _slots_for_day(avail, d, dur, busy, cutoff=None):
    """Available slots for a single date `d`. Returns (closed, reason, slots).

    `cutoff` = (today_iso, now_minutes) in clinic tz; slots at or before now are omitted."""
    ds = d.isoformat()
    closures = {c.get("date"): c.get("reason") for c in avail.get("closures", [])}
    if ds in closures:
        return True, (closures[ds] or "Office closed"), []
    for v in avail.get("vacations", []):
        if v.get("start", "") <= ds <= v.get("end", ""):
            return True, (v.get("reason") or "Vacation"), []
    exceptions = {e.get("date"): e for e in avail.get("exceptions", [])}
    if ds in exceptions:
        start, end = _to_min(exceptions[ds]["start"]), _to_min(exceptions[ds]["end"])
    else:
        cfg = avail.get("days", {}).get(WEEKDAY_KEYS[d.weekday()], {})
        if not cfg.get("enabled"):
            return True, "Not a working day", []
        start, end = _to_min(cfg["start"]), _to_min(cfg["end"])
    day_blocks = [(_to_min(b["start"]), _to_min(b["end"])) for b in avail.get("blocked_periods", []) if b.get("date") == ds]
    # Recurring daily break (applies to every working day) — never offered to patients.
    if avail.get("break_start") and avail.get("break_end"):
        day_blocks.append((_to_min(avail["break_start"]), _to_min(avail["break_end"])))
    # Past-time cutoff: whole past days, or earlier times on today (clinic tz).
    past_before = None
    if cutoff:
        today_iso, now_min = cutoff
        if ds < today_iso:
            return False, None, []
        if ds == today_iso:
            past_before = now_min
    slots, t = [], start
    while t + dur <= end:
        occupied = any(bs <= t < be for bs, be in day_blocks) or f"{ds} {t // 60:02d}:{t % 60:02d}" in busy
        if past_before is not None and t < past_before:
            occupied = True
        if not occupied:
            slots.append({
                "date": ds, "weekday": d.strftime("%A"),
                "time": f"{t // 60:02d}:{t % 60:02d}", "label": _label(t),
                "display": f"{d.strftime('%Y %b - %d')} ({d.strftime('%a')}) · {_label(t)}",
            })
        t += dur
    return False, None, slots


def generate_slots(avail: dict, days: int = 28, busy=None):
    """Return available appointment slots for the next `days` days.

    `busy` is a set of "YYYY-MM-DD HH:MM" strings for times already occupied by
    VIen EMR appointments (confirmed/rescheduled/completed/no_show)."""
    busy = busy or set()
    avail = avail or DEFAULT_AVAILABILITY
    dur = int(avail.get("appointment_duration") or 30) or 30
    cutoff = _now_cutoff(avail)
    today = date.today()
    out = []
    for i in range(1, days + 1):
        _, _, slots = _slots_for_day(avail, today + timedelta(days=i), dur, busy, cutoff)
        out.extend(slots)
    return out


def calendar_range(avail: dict, start: str, days: int, busy=None):
    """Per-day open slots for a date range starting at `start` (inclusive)."""
    busy = busy or set()
    avail = avail or DEFAULT_AVAILABILITY
    dur = int(avail.get("appointment_duration") or 30) or 30
    cutoff = _now_cutoff(avail)
    d0 = date.fromisoformat(start)
    out = []
    for i in range(days):
        d = d0 + timedelta(days=i)
        closed, reason, slots = _slots_for_day(avail, d, dur, busy, cutoff)
        out.append({"date": d.isoformat(), "weekday": d.strftime("%A"),
                    "closed": closed, "reason": reason, "open_slots": slots})
    return out


def is_within(avail: dict, ds: str, time_str: str) -> bool:
    avail = avail or DEFAULT_AVAILABILITY
    if not ds:
        return False
    try:
        d = date.fromisoformat(ds)
    except Exception:
        return False
    if ds in {c.get("date") for c in avail.get("closures", [])}:
        return False
    if any(v.get("start", "") <= ds <= v.get("end", "") for v in avail.get("vacations", [])):
        return False
    exceptions = {e.get("date"): e for e in avail.get("exceptions", [])}
    if ds in exceptions:
        start, end = _to_min(exceptions[ds]["start"]), _to_min(exceptions[ds]["end"])
    else:
        cfg = avail.get("days", {}).get(WEEKDAY_KEYS[d.weekday()], {})
        if not cfg.get("enabled"):
            return False
        start, end = _to_min(cfg["start"]), _to_min(cfg["end"])
    t = _to_min(_norm_time(time_str))
    return start <= t < end
