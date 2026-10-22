"""Installation-level system state: global announcement + maintenance mode.

Stored in `system_state` (single doc id="global") and cached in memory (short TTL) so the
maintenance-mode middleware never adds a DB round-trip per request. Only `developer_ops`
(installation operator) may change it; organization roles never inherit these controls.
"""
import time

from db import db, now_iso

ANNOUNCEMENT_TYPES = ("INFO", "WARNING", "CRITICAL")
DEFAULT_MAINTENANCE_MSG = "VIen is temporarily unavailable for scheduled maintenance. Please try again shortly."
_cache = {"at": 0.0, "state": None}
CACHE_TTL = 5.0

# Paths that must keep working during maintenance (infra probes, banner, login, developer portal).
ALLOW_PREFIXES = ("/api/health", "/api/system/", "/api/me/theme", "/api/auth/login", "/api/auth/me", "/api/auth/logout",
                  "/api/developer/", "/health", "/api/practices", "/api/settings/public", "/api/cron/")


def _default():
    return {"id": "global",
            "announcement": {"active": False, "type": "INFO", "message": "", "updated_at": None, "by": None},
            "maintenance": {"on": False, "message": DEFAULT_MAINTENANCE_MSG, "since": None, "by": None}}


async def get_state(fresh: bool = False) -> dict:
    now = time.monotonic()
    if not fresh and _cache["state"] is not None and now - _cache["at"] < CACHE_TTL:
        return _cache["state"]
    doc = await db.system_state.find_one({"id": "global"}, {"_id": 0})
    state = {**_default(), **(doc or {})}
    _cache.update(at=now, state=state)
    return state


async def _save(state: dict, *fields: str):
    """Targeted write of the given top-level fields only (default: announcement + maintenance) — never the whole doc."""
    fields = fields or ("announcement", "maintenance")
    await db.system_state.update_one({"id": "global"}, {"$set": {f: state[f] for f in fields}}, upsert=True)
    _cache.update(at=0.0, state=None)


def actor_label(user: dict) -> dict:
    return {"id": str(user.get("_id") or user.get("id")), "name": user.get("name"), "role": user.get("role")}


async def set_announcement(message: str, type_: str, user: dict) -> dict:
    s = await get_state(fresh=True)
    s["announcement"] = {"active": True, "type": type_, "message": message.strip(), "updated_at": now_iso(), "by": actor_label(user)}
    await _save(s, "announcement")
    return s["announcement"]


async def clear_announcement(user: dict) -> dict:
    s = await get_state(fresh=True)
    s["announcement"] = {**s["announcement"], "active": False, "updated_at": now_iso(), "by": actor_label(user)}
    await _save(s, "announcement")
    return s["announcement"]


async def set_maintenance(on: bool, message: str, user: dict) -> dict:
    s = await get_state(fresh=True)
    s["maintenance"] = {"on": on, "message": (message or "").strip() or DEFAULT_MAINTENANCE_MSG,
                        "since": now_iso() if on else None, "by": actor_label(user)}
    await _save(s, "maintenance")
    return s["maintenance"]


def public_view(state: dict) -> dict:
    a, m = state["announcement"], state["maintenance"]
    import deployment as dep_mod
    dep = dep_mod._dep(state)
    return {"announcement": {"active": a["active"], "type": a["type"], "message": a["message"], "updated_at": a["updated_at"]} if a["active"] else None,
            "maintenance": {"on": m["on"], "message": m["message"], "since": m["since"]},
            "state": "MAINTENANCE" if m["on"] else dep["state"],
            "notice": dep_mod.notice_for(dep, m["on"])}


def path_allowed(path: str) -> bool:
    return any(path.startswith(p) for p in ALLOW_PREFIXES)
