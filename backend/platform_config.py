"""Installation-level platform configuration (Platform Control Center).

Versioned: DRAFT -> PREVIEW (client renders the draft) -> PUBLISH (new PUBLISHED version,
previous becomes SUPERSEDED, audited with prev/new version) -> ROLLBACK (re-publish an older
version's config as a new version). Only developer_ops writes. Security/privacy/integrity
controls are NOT part of this model and cannot be toggled here.
"""
import copy
import re
import time
import uuid

from db import db, now_iso

FEATURE_STATES = ("OFF", "PILOT", "ON")
# Feature registry: product modules only. PILOT = internal roles (admin/physician/staff/developer_ops) only.
FEATURES = {
    "emr": "EMR / Encounter", "pharmacy": "Pharmacy portal", "patient_portal": "Patient Portal", "caregiver": "Caregiver access",
    "registration": "Patient registration", "rx": "Prescriptions (Rx)", "calendar": "Calendar & appointments",
    "results": "Results (labs / imaging)", "referrals": "Referrals", "network": "Network", "jobs": "Jobs", "market": "Market",
    "profile_completion": "Patient profile completion (missing health-card info prompt + Rx gate)",
}
AUDIENCES = ("public", "physician", "staff", "pharmacy", "patient", "network")
# API prefix -> feature. OFF fails at the backend too (403 FEATURE_OFF), not just in the UI.
API_FEATURE_PREFIXES = [
    ("/api/internal/visits", "emr"), ("/api/internal/soap-helpers", "emr"), ("/api/internal/diagnosis-catalog", "emr"),
    ("/api/internal/service-catalog", "emr"), ("/api/pharmacy/", "pharmacy"), ("/api/portal/", "patient_portal"),
    ("/api/caregiver", "caregiver"), ("/api/register", "registration"), ("/api/internal/prescriptions", "rx"),
    ("/api/internal/send-rx", "rx"), ("/api/internal/pharmacy-rx", "rx"), ("/api/internal/calendar", "calendar"),
    ("/api/internal/appointments", "calendar"), ("/api/availability", "calendar"), ("/api/internal/exams", "results"),
    ("/api/internal/referrals", "referrals"), ("/api/network/", "network"),
]
INTERNAL_ROLES = ("admin", "physician", "staff", "developer_ops", "network")
# Operator-configurable public copy ONLY (legal/privacy/emergency language is intentionally excluded).
PUBLIC_SITE_FIELDS = ("headline", "subtitle", "search_placeholder", "cta_create_portal", "cta_apply_for_care",
                      "coming_soon_label", "footer_contact", "show_role_section")

DEFAULT_CONFIG = {
    "branding": {"app_name": "VIen", "short_name": "VIen", "operator_name": "OAKMONT Developers", "operator_title": "CEO"},
    "features": {k: ("OFF" if k in ("network", "jobs", "market", "profile_completion") else "ON") for k in FEATURES},
    "navigation": {"hidden": {a: [] for a in AUDIENCES}},  # visibility only — never authorization
    "public_site": {"headline": "", "subtitle": "", "search_placeholder": "", "cta_create_portal": "", "cta_apply_for_care": "",
                    "coming_soon_label": "Coming soon", "footer_contact": "", "show_role_section": True},
    "operations": {"data_mode": "PRELAUNCH_TEST"}, "network": {}, "integrations": {},
}
SECTIONS = tuple(DEFAULT_CONFIG.keys())
DATA_MODES = ("PRELAUNCH_TEST", "LIVE_CLINICAL")
_cache = {"at": 0.0, "live": None}


def operator_brand(config: dict) -> str:
    return (config.get("branding") or {}).get("operator_name") or "OAKMONT Developers"


def operator_actor(config: dict, user: dict) -> dict:
    """Attribution stored on config versions: brand for display, real individual kept for audit integrity."""
    return {"name": operator_brand(config), "role": user.get("role"), "actor_name": user.get("name"),
            "actor_id": str(user.get("id") or ""), "actor_username": user.get("username")}


def operator_profile(config: dict, user: dict) -> dict:
    b = config.get("branding") or {}
    individual = re.sub(r"\s*[\u2013\u2014-]\s*Developer\s*$", "", user.get("name") or "")  # presentation only; account name unchanged
    return {"brand": operator_brand(config), "title": b.get("operator_title") or "", "individual": individual,
            "username": user.get("username"), "email": user.get("email"), "role": user.get("role")}


def live_data_mode(config: dict) -> str:
    return ((config.get("operations") or {}).get("data_mode")) or "PRELAUNCH_TEST"


def _enforce_one_way(config: dict, live_config: dict) -> dict:
    """LIVE_CLINICAL is permanent: no draft/publish/rollback may return to PRELAUNCH_TEST."""
    if live_data_mode(live_config) == "LIVE_CLINICAL":
        config.setdefault("operations", {})["data_mode"] = "LIVE_CLINICAL"
    return config


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
    if section == "operations":
        bad = [k for k in data if k != "data_mode"]
        if bad or ("data_mode" in data and data["data_mode"] not in DATA_MODES):
            raise ValueError("operations accepts only data_mode = PRELAUNCH_TEST | LIVE_CLINICAL")


async def save_draft(section: str, data: dict, user: dict) -> dict:
    _validate(section, data)
    live_cfg = (await published())["config"]
    if section == "operations" and live_data_mode(live_cfg) == "LIVE_CLINICAL" and data.get("data_mode") == "PRELAUNCH_TEST":
        raise ValueError("Data mode is LIVE_CLINICAL — this switch is one-way and cannot return to PRELAUNCH_TEST.")
    base = (await draft()) or {"id": str(uuid.uuid4()), "status": "DRAFT", "config": copy.deepcopy((await published())["config"]),
                               "based_on_version": (await published())["version"], "created_at": now_iso()}
    base["config"][section] = _merge(base["config"].get(section, {}), data) if section != "navigation" else data
    base.update(updated_at=now_iso(), updated_by=operator_actor(live_cfg, user))
    await db.platform_config_versions.update_one({"id": base["id"]}, {"$set": base}, upsert=True)
    return base


async def discard_draft():
    await db.platform_config_versions.delete_many({"status": "DRAFT"})


async def _publish_config(config: dict, user: dict, note: str) -> tuple[int, int]:
    live = await published()
    config = _enforce_one_way(config, live["config"])
    new_version = live["version"] + 1
    await db.platform_config_versions.update_many({"status": "PUBLISHED"}, {"$set": {"status": "SUPERSEDED", "superseded_at": now_iso()}})
    await db.platform_config_versions.insert_one({"id": str(uuid.uuid4()), "version": new_version, "status": "PUBLISHED", "config": config,
                                                  "published_at": now_iso(), "published_by": operator_actor(live["config"], user),
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
