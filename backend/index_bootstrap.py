"""Index bootstrap helpers: listIndexes-first, create only what is missing.

`ensure_missing(db, coll, specs)` compares each approved spec's key pattern against the
collection's existing indexes and creates ONLY the missing ones. Existing indexes are never
dropped, rebuilt, renamed or altered.
"""
import asyncio
import logging

logger = logging.getLogger("visita")

# Approved audit_logs PERFORMANCE indexes (non-unique; speed up the Audit & Compliance viewer).
# They never gate readiness and are the ONLY indexes the maintenance endpoint may build.
AUDIT_INDEXES = [
    {"keys": [("created_at", -1)]},
    {"keys": [("practice_id", 1), ("created_at", -1)]},
    {"keys": [("entity_id", 1), ("created_at", -1)]},
    {"keys": [("actor_id", 1), ("created_at", -1)]},
    {"keys": [("action", 1), ("created_at", -1)]},
    {"keys": [("meta.patient_ref", 1), ("created_at", -1)]},
]


def index_name(keys) -> str:
    return "_".join(f"{k}_{v}" for k, v in keys)


async def existing_key_patterns(db, coll) -> dict:
    """{name: [(field, dir), ...]} for every index on the collection (empty if collection absent)."""
    try:
        infos = await db[coll].index_information()
    except Exception:
        return {}
    return {name: [(k, int(v) if isinstance(v, (int, float)) else v) for k, v in info["key"]] for name, info in infos.items()}


def _present(keys, existing: dict) -> bool:
    return any(list(keys) == list(pattern) for pattern in existing.values())


async def ensure_missing(db, coll, specs, timeout=None) -> list:
    """Create only the approved specs that are missing. Returns per-index results:
    {name, status: EXISTS|CREATED|FAILED, error?}. Never raises."""
    existing = await existing_key_patterns(db, coll)
    out = []
    for spec in specs:
        keys, name = spec["keys"], index_name(spec["keys"])
        if _present(keys, existing):
            out.append({"name": name, "status": "EXISTS"})
            continue
        opts = {k: v for k, v in spec.items() if k != "keys"}
        try:
            coro = db[coll].create_index(keys, **opts)
            await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)
            out.append({"name": name, "status": "CREATED"})
        except Exception as e:
            logger.warning(f"[indexes] {coll}.{name} not created: {type(e).__name__}: {e}")
            out.append({"name": name, "status": "FAILED", "error": f"{type(e).__name__}: {e}"[:200]})
    return out


async def plan(db, coll, specs) -> list:
    """Dry-run: EXISTS / MISSING per approved spec. Read-only."""
    existing = await existing_key_patterns(db, coll)
    return [{"name": index_name(s["keys"]), "status": "EXISTS" if _present(s["keys"], existing) else "MISSING"} for s in specs]


async def ensure_audit_indexes_background(db, timeout=20) -> list:
    """Non-critical: best-effort build of missing audit_logs indexes with a short deadline each."""
    results = await ensure_missing(db, "audit_logs", AUDIT_INDEXES, timeout=timeout)
    failed = [r["name"] for r in results if r["status"] == "FAILED"]
    if failed:
        logger.warning(f"[indexes] audit_logs performance indexes deferred (readiness unaffected): {failed}. "
                       "Build them via POST /api/internal/admin/maintenance/audit-indexes.")
    return results
