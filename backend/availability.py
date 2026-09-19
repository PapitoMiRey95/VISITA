"""Physician availability + slot generation.

Availability is fully configurable (stored in the `settings` collection under
id="availability"). Slot generation is designed so a future Google Calendar
integration can pass in `busy` times to subtract occupied slots without any
changes to callers.
"""
from datetime import date, timedelta

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


def generate_slots(avail: dict, days: int = 28, busy=None):
    """Return available appointment slots for the next `days` days.

    `busy` is an optional set of "YYYY-MM-DD HH:MM" strings representing times
    already occupied (future Google Calendar integration passes these in)."""
    busy = busy or set()
    avail = avail or DEFAULT_AVAILABILITY
    dur = int(avail.get("appointment_duration") or 30) or 30
    vacations = avail.get("vacations", [])
    closures = {c.get("date") for c in avail.get("closures", [])}
    exceptions = {e.get("date"): e for e in avail.get("exceptions", [])}
    blocks = avail.get("blocked_periods", [])
    today = date.today()
    out = []
    for i in range(1, days + 1):
        d = today + timedelta(days=i)
        ds = d.isoformat()
        if ds in closures:
            continue
        if any(v.get("start", "") <= ds <= v.get("end", "") for v in vacations):
            continue
        if ds in exceptions:
            ex = exceptions[ds]
            start, end = _to_min(ex["start"]), _to_min(ex["end"])
        else:
            cfg = avail.get("days", {}).get(WEEKDAY_KEYS[d.weekday()], {})
            if not cfg.get("enabled"):
                continue
            start, end = _to_min(cfg["start"]), _to_min(cfg["end"])
        day_blocks = [(_to_min(b["start"]), _to_min(b["end"])) for b in blocks if b.get("date") == ds]
        t = start
        while t + dur <= end:
            occupied = any(bs <= t < be for bs, be in day_blocks) or f"{ds} {t // 60:02d}:{t % 60:02d}" in busy
            if not occupied:
                out.append({
                    "date": ds,
                    "weekday": d.strftime("%A"),
                    "time": f"{t // 60:02d}:{t % 60:02d}",
                    "label": _label(t),
                    "display": f"{d.strftime('%Y %b - %d')} ({d.strftime('%a')}) · {_label(t)}",
                })
            t += dur
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
