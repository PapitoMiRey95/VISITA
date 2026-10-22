"""Deployment & Maintenance state machine (Platform Control Center → Operations).

Extends `system_state.global` with a `deployment` sub-document; append-only `deployment_history`.
NORMAL → UPDATING (Soft Update, app stays up, managed notice) → verification → NORMAL.
While UPDATING failed checks only reset the streak; after TIMEOUT_MIN without 3 consecutive OK
checks → SERVICE_ISSUE (operator may enter it sooner). SERVICE_ISSUE is left by explicit resolve.
MAINTENANCE mirrors the existing maintenance.on flag. Nothing here touches clinical collections.
"""
import uuid
from datetime import datetime, timedelta, timezone

from db import db, now_iso, audit
import system_state as sys_mod

STATES = ("NORMAL", "UPDATING", "MAINTENANCE", "SERVICE_ISSUE")
KINDS = ("CODE", "RESOURCE", "HOTFIX")
REQUIRED_OK = 3
TIMEOUT_MIN = 20
MAX_CHECKS = 12
NOTICE = {
    "UPDATE": "VIen is being updated. Some services may be briefly unavailable. Please try again if something does not load.",
    "ISSUE": "VIen is temporarily unavailable. We\u2019re completing a brief system update. Please try again shortly.",
    "MAINTENANCE": "VIen is temporarily unavailable. We\u2019re completing a brief system update. Please try again shortly.",
}


def default() -> dict:
    return {"state": "NORMAL", "mode": None, "kind": None, "since": None, "by": None, "note": None, "expected_commit": None,
            "deployment_id": None, "issue_seen": False,
            "verification": {"required": REQUIRED_OK, "streak": 0, "last_check_at": None, "last_ok_at": None, "deadline_at": None, "checks": []},
            "build": {"tier": None, "tier_updated_at": None}}


def _dep(state: dict) -> dict:
    d = {**default(), **(state.get("deployment") or {})}
    d["verification"] = {**default()["verification"], **(d.get("verification") or {})}
    d["build"] = {**default()["build"], **(d.get("build") or {})}
    return d


async def get() -> dict:
    return _dep(await sys_mod.get_state(fresh=True))


async def _save(dep: dict):
    # Targeted write: never read-modify-write the whole system_state doc (cron verify vs operator edits).
    await db.system_state.update_one({"id": "global"}, {"$set": {"deployment": dep}}, upsert=True)
    sys_mod._cache.update(state=None, at=0.0)


def _reset_run(dep: dict):
    dep.update(mode=None, kind=None, note=None, expected_commit=None, deployment_id=None, issue_seen=False)
    dep["verification"]["deadline_at"] = None


def notice_for(dep: dict, maintenance_on: bool) -> dict | None:
    st = dep.get("state")
    if maintenance_on or st == "MAINTENANCE":
        return {"kind": "MAINTENANCE", "message": NOTICE["MAINTENANCE"]}
    if st == "UPDATING":
        return {"kind": "UPDATE", "message": NOTICE["UPDATE"]}
    if st == "SERVICE_ISSUE":
        return {"kind": "ISSUE", "message": NOTICE["ISSUE"]}
    return None


async def history(limit: int = 20) -> list:
    return await db.deployment_history.find({}, {"_id": 0}).sort("started_at", -1).to_list(limit)


async def _hist_update(dep_id: str | None, **fields):
    if dep_id:
        await db.deployment_history.update_one({"id": dep_id}, {"$set": fields})


async def _transition(dep: dict, new_state: str, user: dict | None, reason: str, **meta):
    old = dep["state"]
    dep["state"] = new_state
    dep["since"] = now_iso()
    dep["by"] = sys_mod.actor_label(user) if user else {"id": None, "name": "system", "role": "system"}
    await _save(dep)
    await audit("deployment_state_changed", "system_state", "global", user or {"id": None, "name": "system", "role": "system"},
                old_status=old, new_status=new_state, meta={"reason": reason, "deployment_id": dep.get("deployment_id"), **meta})


async def begin_update(user: dict, kind: str, note: str, expected_commit: str | None, current_commit: str | None) -> dict:
    if kind not in KINDS:
        raise ValueError("kind must be CODE, RESOURCE or HOTFIX")
    dep = await get()
    if dep["state"] == "MAINTENANCE":
        raise ValueError("Exit Full Maintenance before starting a Soft Update.")
    now = datetime.now(timezone.utc)
    if dep.get("deployment_id") and dep["state"] in ("UPDATING", "SERVICE_ISSUE"):
        await _hist_update(dep["deployment_id"], status="COMPLETED", result="SUPERSEDED", completed_at=now_iso())
    dep_id = str(uuid.uuid4())
    await db.deployment_history.insert_one({
        "id": dep_id, "kind": kind, "mode": "SOFT", "note": (note or "").strip() or None, "status": "IN_PROGRESS", "result": None,
        "started_at": now_iso(), "completed_at": None, "operator": sys_mod.actor_label(user),
        "build_from": current_commit, "expected_commit": (expected_commit or "").strip() or None, "build_to": None,
        "verification": {"ok": 0, "failed": 0}, "rollback_target": current_commit, "transitions": [{"to": "UPDATING", "at": now_iso()}],
    })
    dep.update(mode="SOFT", kind=kind, note=(note or "").strip() or None, expected_commit=(expected_commit or "").strip() or None,
               deployment_id=dep_id, issue_seen=False,
               verification={**default()["verification"], "deadline_at": (now + timedelta(minutes=TIMEOUT_MIN)).isoformat()})
    await _transition(dep, "UPDATING", user, "begin_update", kind=kind, expected_commit=dep["expected_commit"])
    return dep


def evaluate(dep: dict, probe: dict) -> tuple[bool, list]:
    """probe = {api, database, storage, readiness, commit}. Returns (ok, reasons)."""
    reasons = []
    if probe.get("api") != "ONLINE": reasons.append("api")
    if probe.get("database") != "CONNECTED": reasons.append("database")
    if probe.get("storage") != "CONNECTED": reasons.append("storage")
    if probe.get("readiness") != "READY": reasons.append("readiness")
    exp = dep.get("expected_commit")
    if exp and dep.get("kind") in ("CODE", "HOTFIX"):
        cur = probe.get("commit") or ""
        if not (cur.startswith(exp) or exp.startswith(cur) if cur else False):
            reasons.append(f"commit {cur or 'n/a'} != expected {exp}")
    return (not reasons), reasons


async def verify(probe: dict, source: str = "cron") -> dict:
    dep = await get()
    ok, reasons = evaluate(dep, probe)
    v = dep["verification"]
    now = datetime.now(timezone.utc)
    check = {"at": now_iso(), "ok": ok, "reasons": reasons, "source": source, "commit": probe.get("commit")}
    v["checks"] = ([check] + (v.get("checks") or []))[:MAX_CHECKS]
    v["last_check_at"] = check["at"]
    if ok:
        v["last_ok_at"] = check["at"]
    if dep["state"] not in ("UPDATING", "SERVICE_ISSUE"):
        await _save(dep)
        return {"state": dep["state"], "ok": ok, "reasons": reasons, "streak": v.get("streak", 0)}
    v["streak"] = (v.get("streak", 0) + 1) if ok else 0
    await db.deployment_history.update_one({"id": dep.get("deployment_id")}, {"$inc": {"verification.ok" if ok else "verification.failed": 1}})
    if dep["state"] == "UPDATING":
        if v["streak"] >= v.get("required", REQUIRED_OK):
            result = "RECOVERED" if dep.get("issue_seen") else "SUCCEEDED"
            await _hist_update(dep.get("deployment_id"), status="COMPLETED", result=result, completed_at=now_iso(), build_to=probe.get("commit"),
                               verified_at=now_iso())
            dep_id = dep.get("deployment_id")
            _reset_run(dep)
            await _transition(dep, "NORMAL", None, "verification_passed", streak=v["streak"], result=result, deployment_id=dep_id)
            return {"state": "NORMAL", "ok": True, "reasons": [], "streak": v["streak"], "result": result}
        deadline = v.get("deadline_at")
        if deadline and now > datetime.fromisoformat(deadline):
            dep["issue_seen"] = True
            await _hist_update(dep.get("deployment_id"), status="SERVICE_ISSUE", result="TIMEOUT")
            await _transition(dep, "SERVICE_ISSUE", None, "verification_timeout", minutes=TIMEOUT_MIN, last_reasons=reasons)
            return {"state": "SERVICE_ISSUE", "ok": ok, "reasons": reasons, "streak": v["streak"]}
    await _save(dep)
    return {"state": dep["state"], "ok": ok, "reasons": reasons, "streak": v["streak"]}


async def enter_service_issue(user: dict, note: str) -> dict:
    dep = await get()
    if dep["state"] == "MAINTENANCE":
        raise ValueError("Exit Full Maintenance first.")
    dep["issue_seen"] = True
    if not dep.get("deployment_id"):
        dep_id = str(uuid.uuid4())
        await db.deployment_history.insert_one({"id": dep_id, "kind": "INCIDENT", "mode": "SOFT", "note": (note or "").strip() or None, "status": "SERVICE_ISSUE",
                                                "result": None, "started_at": now_iso(), "completed_at": None, "operator": sys_mod.actor_label(user),
                                                "build_from": None, "expected_commit": None, "build_to": None, "verification": {"ok": 0, "failed": 0}, "rollback_target": None})
        dep["deployment_id"] = dep_id
    else:
        await _hist_update(dep["deployment_id"], status="SERVICE_ISSUE", result="MANUAL_ISSUE")
    await _transition(dep, "SERVICE_ISSUE", user, "manual_service_issue", note=(note or "").strip() or None)
    return dep


async def resolve(user: dict, note: str, rolled_back: bool, current_commit: str | None) -> dict:
    dep = await get()
    if dep["state"] not in ("SERVICE_ISSUE", "UPDATING"):
        raise ValueError("Nothing to resolve — system is not in SERVICE_ISSUE or UPDATING.")
    result = "ROLLED_BACK" if rolled_back else "RESOLVED"
    await _hist_update(dep.get("deployment_id"), status="COMPLETED", result=result, completed_at=now_iso(), build_to=current_commit,
                       resolution_note=(note or "").strip() or None)
    dep_id = dep.get("deployment_id")
    _reset_run(dep)
    await _transition(dep, "NORMAL", user, "manual_resolve", result=result, note=(note or "").strip() or None, deployment_id=dep_id)
    return dep


async def sync_maintenance(on: bool, user: dict, message: str | None):
    """Keep deployment.state in step with the existing Full Maintenance flag + history row."""
    dep = await get()
    if on:
        if dep["state"] == "MAINTENANCE":
            return  # already in Full Maintenance — no duplicate row
        if dep.get("deployment_id") and dep["state"] in ("UPDATING", "SERVICE_ISSUE"):
            await _hist_update(dep["deployment_id"], status="COMPLETED", result="SUPERSEDED", completed_at=now_iso(),
                               resolution_note="Superseded by Full Maintenance")
        dep_id = str(uuid.uuid4())
        await db.deployment_history.insert_one({"id": dep_id, "kind": "MAINTENANCE", "mode": "FULL", "note": (message or "").strip() or None, "status": "IN_PROGRESS",
                                                "result": None, "started_at": now_iso(), "completed_at": None, "operator": sys_mod.actor_label(user),
                                                "build_from": None, "expected_commit": None, "build_to": None, "verification": {"ok": 0, "failed": 0}, "rollback_target": None})
        dep.update(mode="FULL", kind="MAINTENANCE", deployment_id=dep_id, note=(message or "").strip() or None)
        await _transition(dep, "MAINTENANCE", user, "full_maintenance_entered")
    else:
        if dep["state"] != "MAINTENANCE":
            return  # EXIT while not in Full Maintenance never touches UPDATING / SERVICE_ISSUE
        await _hist_update(dep.get("deployment_id"), status="COMPLETED", result="SUCCEEDED", completed_at=now_iso())
        _reset_run(dep)
        await _transition(dep, "NORMAL", user, "full_maintenance_exited")


async def set_build_info(user: dict, tier: str | None) -> dict:
    dep = await get()
    dep["build"] = {"tier": (tier or "").strip() or None, "tier_updated_at": now_iso()}
    await _save(dep)
    await audit("deployment_build_info_updated", "system_state", "global", user, meta={"tier": dep["build"]["tier"]})
    return dep["build"]
