"""Installation-level platform configuration (Platform Control Center).

Versioned: DRAFT -> PREVIEW (client renders the draft) -> PUBLISH (new PUBLISHED version,
previous becomes SUPERSEDED, audited with prev/new version) -> ROLLBACK (re-publish an older
version's config as a new version). Only developer_ops writes. Security/privacy/integrity
controls are NOT part of this model and cannot be toggled here.
"""
import copy
import time
import uuid

from db import db, now_iso

FEATURE_STATES = ("OFF", "PILOT", "ON")
# Feature registry: product modules only. PILOT = internal roles (admin/physician/staff/developer_ops) only.
FEATURES = {
    "emr": "EMR / Encounter", "pharmacy": "Pharmacy portal", "patient_portal": "Patient Portal", "caregiver": "Caregiver access",
    "registration": "Patient registration", "rx": "Prescriptions (Rx)", "calendar": "Calendar & appointments",
    "results": "Results (labs / imaging)", "referrals": "Referrals", "network": "Network", "jobs": "Jobs", "market": "Market",
}
AUDIENCES = ("public", "physician", "staff", "pharmacy", "patient", "network")
# API prefix -> feature. OFF fails at the backend too (403 FEATURE_OFF), not just in the UI.
API_FEATURE_PREFIXES = [
    ("/api/internal/visits", "emr"), ("/api/internal/soap-helpers", "emr"), ("/api/internal/diagnosis-catalog", "emr"),
    ("/api/internal/service-catalog", "emr"), ("/api/pharmacy/", "pharmacy"), ("/api/portal/", "patient_portal"),
    ("/api/caregiver", "caregiver"), ("/api/register", "registration"), ("/api/internal/prescriptions", "rx"),
    ("/api/internal/send-rx", "rx"), ("/api/internal/pharmacy-rx", "rx"), ("/api/internal/calendar", "calendar"),
    ("/api/internal/appointments", "calendar"), ("/api/availability", "calendar"), ("/api/internal/exams", "results"),
    ("/api/internal/referrals", "referrals"),
]
INTERNAL_ROLES = ("admin", "physician", "staff", "developer_ops")
# Operator-configurable public copy ONLY (legal/privacy/emergency language is intentionally excluded).
PUBLIC_SITE_FIELDS = ("headline", "subtitle", "search_placeholder", "cta_create_portal", "cta_apply_for_care",
                      "coming_soon_label", "footer_contact", "show_role_section")

DEFAULT_CONFIG = {
    "branding": {"app_name": "VIen", "short_name": "VIen"},
    "features": {k: ("OFF" if k in ("network", "jobs", "market") else "ON") for k in FEATURES},
    "navigation": {"hidden": {a: [] for a in AUDIENCES}},  # visibility only — never authorization
    "public_site": {"headline": "", "subtitle": "", "search_placeholder": "", "cta_create_portal": "", "cta_apply_for_care": "",
                    "coming_soon_label": "Coming soon", "footer_contact": "", "show_role_section": True},
    "operations": {}, "network": {}, "integrations": {},
}
SECTIONS = tuple(DEFAULT_CONFIG.keys())
_cache = {"at": 0.0, "live": None}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


async def published() -> dict:
    """Live (published) config, cached 5s. Falls back to defaults before first publish."""
    if _cache["live"] is not None and time.monotonic() - _cache["at"] < 5:
        return _cache["live"]
    doc = await db.platform_config_versions.find_one({"status": "PUBLISHED"}, {"_id": 0})
    live = {"version": (doc or {}).get("version", 0), "config": _merge(DEFAULT_CONFIG, (doc or {}).get("config"))}
    _cache.update(at=time.monotonic(), live=live)
    return live


async def draft() -> dict | None:
    return await db.platform_config_versions.find_one({"status": "DRAFT"}, {"_id": 0})


async def history(limit=20) -> list:
    items = await db.platform_config_versions.find({"status": {"$ne": "DRAFT"}}, {"_id": 0, "config": 0}).sort("version", -1).to_list(limit)
    live = await published()
    items.append({"version": 0, "status": "PUBLISHED" if live["version"] == 0 else "SUPERSEDED", "note": "Installation defaults",
                  "published_at": None, "published_by": {"name": "system"}})
    return items


def _validate(section: str, data: dict):
    if section not in SECTIONS:
        raise ValueError("Unknown section")
    if section == "features":
        bad = [k for k, v in data.items() if k not in FEATURES or v not in FEATURE_STATES]
        if bad:
            raise ValueError(f"Invalid feature entries: {bad}")
    if section == "navigation":
        for a, items in (data.get("hidden") or {}).items():
            if a not in AUDIENCES or any(i not in FEATURES for i in items):
                raise ValueError("Invalid navigation entry")
    if section == "public_site":
        bad = [k for k in data if k not in PUBLIC_SITE_FIELDS]
        if bad:
            raise ValueError(f"Not operator-configurable: {bad}")


async def save_draft(section: str, data: dict, user: dict) -> dict:
    _validate(section, data)
    base = (await draft()) or {"id": str(uuid.uuid4()), "status": "DRAFT", "config": copy.deepcopy((await published())["config"]),
                               "based_on_version": (await published())["version"], "created_at": now_iso()}
    base["config"][section] = _merge(base["config"].get(section, {}), data) if section != "navigation" else data
    base.update(updated_at=now_iso(), updated_by={"name": user.get("name"), "role": user.get("role")})
    await db.platform_config_versions.update_one({"id": base["id"]}, {"$set": base}, upsert=True)
    return base


async def discard_draft():
    await db.platform_config_versions.delete_many({"status": "DRAFT"})


async def _publish_config(config: dict, user: dict, note: str) -> tuple[int, int]:
    live = await published()
    new_version = live["version"] + 1
    await db.platform_config_versions.update_many({"status": "PUBLISHED"}, {"$set": {"status": "SUPERSEDED", "superseded_at": now_iso()}})
    await db.platform_config_versions.insert_one({"id": str(uuid.uuid4()), "version": new_version, "status": "PUBLISHED", "config": config,
                                                  "published_at": now_iso(), "published_by": {"name": user.get("name"), "role": user.get("role")},
                                                  "note": note, "created_at": now_iso()})
    _cache["live"] = None
    return live["version"], new_version


async def publish_draft(user: dict) -> tuple[int, int, list]:
    d = await draft()
    if not d:
        raise ValueError("No draft to publish")
    live = await published()
    changed = [s for s in SECTIONS if d["config"].get(s) != live["config"].get(s)]
    prev, new = await _publish_config(d["config"], user, f"Published draft (sections: {', '.join(changed) or 'none'})")
    await discard_draft()
    return prev, new, changed


async def rollback(version: int, user: dict) -> tuple[int, int]:
    if version == 0:
        return await _publish_config(copy.deepcopy(DEFAULT_CONFIG), user, "Rollback to v0 (installation defaults)")
    doc = await db.platform_config_versions.find_one({"version": version, "status": {"$in": ["SUPERSEDED", "PUBLISHED"]}}, {"_id": 0})
    if not doc:
        raise ValueError("Version not found")
    return await _publish_config(_merge(DEFAULT_CONFIG, doc["config"]), user, f"Rollback to v{version}")


def feature_state(config: dict, key: str) -> str:
    return (config.get("features") or {}).get(key, "ON")


def feature_for_path(path: str) -> str | None:
    for prefix, feat in API_FEATURE_PREFIXES:
        if path.startswith(prefix):
            return feat
    return None


def public_view(live: dict) -> dict:
    c = live["config"]
    return {"version": live["version"], "branding": c["branding"], "features": c["features"], "navigation": c["navigation"],
            "public_site": c["public_site"], "feature_labels": FEATURES}
