"""Developer Data Operations — purpose-built TEST-data cleanup for the installation operator.

Every destructive action fails closed unless the published platform config says
operations.data_mode == "PRELAUNCH_TEST". Switching to LIVE_CLINICAL is one-way.
No generic query surface: callers can only search, preview and remove ONE identified test record.
"""
import re

from db import db, now_iso

DATA_MODES = ("PRELAUNCH_TEST", "LIVE_CLINICAL")
DEFAULT_DATA_MODE = "PRELAUNCH_TEST"
RESET_CONFIRM = "RESET TEST PATIENT"
DELETE_USER_CONFIRM = "DELETE TEST USER"
PURGE_CONFIRM = "PURGE ALL TEST DATA"
# Never touched by per-record cleanup (system / catalog / config / audit collections).
SKIP_COLLECTIONS = {
    "users", "patients", "patient_directory", "audit_logs", "platform_config_versions", "system_state", "app_meta",
    "practices", "providers", "pharmacies", "soap_helpers", "diagnosis_catalog", "service_catalog", "medication_catalog",
    "settings", "templates", "visita_pins", "dev_announcements", "waitlist", "jobs", "job_applications",
}
PROTECTED_ROLES = ("developer_ops",)


def data_mode(config: dict) -> str:
    return ((config.get("operations") or {}).get("data_mode")) or DEFAULT_DATA_MODE


def _rx(q: str) -> dict:
    return {"$regex": re.escape(q), "$options": "i"}


async def search(q: str) -> list:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    out = []
    pats = await db.patients.find({"$or": [
        {"id": q}, {"visita_patient_id": q}, {"email": _rx(q)}, {"first_name": _rx(q)}, {"last_name": _rx(q)},
    ]}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "visita_patient_id": 1, "email": 1, "portal_status": 1,
         "record_status": 1, "is_demo": 1, "created_at": 1}).limit(15).to_list(15)
    for p in pats:
        logins = await db.users.find({"patient_id": p["id"]}, {"email": 1, "role": 1, "active": 1}).to_list(5)
        out.append({"type": "patient", "id": p["id"], "name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                    "pin": p.get("visita_patient_id"), "email": p.get("email"), "portal_status": p.get("portal_status"),
                    "record_status": p.get("record_status"), "is_demo": p.get("is_demo"), "created_at": p.get("created_at"),
                    "logins": [{"id": str(u["_id"]), "email": u.get("email"), "role": u.get("role"), "active": u.get("active", True)} for u in logins]})
    pids = {p["id"] for p in pats}
    users = await db.users.find({"$or": [{"email": _rx(q)}, {"name": _rx(q)}, {"username": _rx(q)}]},
                                {"email": 1, "name": 1, "role": 1, "active": 1, "patient_id": 1, "username": 1, "created_at": 1}).limit(15).to_list(15)
    for u in users:
        if u.get("patient_id") in pids:
            continue
        out.append({"type": "user", "id": str(u["_id"]), "name": u.get("name"), "email": u.get("email"), "username": u.get("username"),
                    "role": u.get("role"), "active": u.get("active", True), "patient_id": u.get("patient_id"), "created_at": u.get("created_at"),
                    "protected": u.get("role") in PROTECTED_ROLES})
    dirs = await db.patient_directory.find({"$or": [{"id": q}, {"visita_patient_id": q}, {"first_name": _rx(q)}, {"last_name": _rx(q)}]},
                                           {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "visita_patient_id": 1, "linked_patient_id": 1, "patient_status": 1}).limit(10).to_list(10)
    for d in dirs:
        if d.get("linked_patient_id") in pids:
            continue
        out.append({"type": "directory", "id": d["id"], "name": f"{d.get('first_name', '')} {d.get('last_name', '')}".strip(),
                    "pin": d.get("visita_patient_id"), "linked_patient_id": d.get("linked_patient_id"), "patient_status": d.get("patient_status")})
    return out


def _ref_filter(pid: str, dir_ids: list) -> dict:
    refs = [f"patient:{pid}"] + [f"directory:{d}" for d in dir_ids]
    ors = [{"patient_id": pid}, {"patient_ref": {"$in": refs}}]
    if dir_ids:
        ors.append({"directory_id": {"$in": dir_ids}})
    return {"$or": ors}


async def patient_preview(pid: str) -> dict | None:
    p = await db.patients.find_one({"id": pid}, {"_id": 0})
    if not p:
        return None
    dirs = await db.patient_directory.find({"$or": [{"linked_patient_id": pid}, {"id": p.get("matched_directory_id") or "__none__"}]},
                                           {"_id": 0, "id": 1, "visita_patient_id": 1, "first_name": 1, "last_name": 1, "patient_status": 1, "linked_patient_id": 1}).to_list(5)
    dir_ids = [d["id"] for d in dirs]
    logins = await db.users.find({"patient_id": pid}, {"email": 1, "role": 1, "active": 1, "name": 1}).to_list(10)
    flt = _ref_filter(pid, dir_ids)
    deps = {}
    for coll in sorted(await db.list_collection_names()):
        if coll in SKIP_COLLECTIONS or coll.startswith("system."):
            continue
        n = await db[coll].count_documents(flt)
        if n:
            deps[coll] = n
    uids = [str(u["_id"]) for u in logins]
    grants_as_delegate = await db.patient_portal_delegates.count_documents({"delegate_user_id": {"$in": uids}}) if uids else 0
    return {
        "patient": {"id": p["id"], "name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(), "pin": p.get("visita_patient_id"),
                    "email": p.get("email"), "dob": p.get("date_of_birth"), "portal_status": p.get("portal_status"),
                    "record_status": p.get("record_status"), "is_demo": p.get("is_demo"), "created_at": p.get("created_at"), "practice_id": p.get("practice_id")},
        "logins": [{"id": str(u["_id"]), "email": u.get("email"), "role": u.get("role"), "active": u.get("active", True), "name": u.get("name")} for u in logins],
        "directory": dirs, "dependencies": deps, "grants_as_delegate": grants_as_delegate,
        "total_dependency_docs": sum(deps.values()),
    }


async def reset_patient(pid: str, include_directory: bool) -> dict:
    """Hard-delete the test patient, its login identities and every dependent document. Returns counts."""
    pv = await patient_preview(pid)
    if not pv:
        return {}
    dir_ids = [d["id"] for d in pv["directory"]]
    flt = _ref_filter(pid, dir_ids)
    deleted = {}
    for coll in pv["dependencies"]:
        deleted[coll] = (await db[coll].delete_many(flt)).deleted_count
    uids = [u["id"] for u in pv["logins"]]
    if uids:
        deleted["patient_portal_delegates(as_delegate)"] = (await db.patient_portal_delegates.delete_many({"delegate_user_id": {"$in": uids}})).deleted_count
        deleted["password_resets"] = (await db.password_resets.delete_many({"user_id": {"$in": uids}})).deleted_count
        deleted["account_activations"] = (await db.account_activations.delete_many({"user_id": {"$in": uids}})).deleted_count
    deleted["users"] = (await db.users.delete_many({"patient_id": pid})).deleted_count
    if include_directory and dir_ids:
        deleted["patient_directory"] = (await db.patient_directory.delete_many({"id": {"$in": dir_ids}})).deleted_count
        pins = [d.get("visita_patient_id") for d in pv["directory"] if d.get("visita_patient_id")]
        if pv["patient"].get("pin"):
            pins.append(pv["patient"]["pin"])
        if pins:
            deleted["visita_pins"] = (await db.visita_pins.delete_many({"_id": {"$in": pins + [str(x) for x in pins]}})).deleted_count
    elif dir_ids:
        r = await db.patient_directory.update_many({"id": {"$in": dir_ids}}, {"$set": {"linked_patient_id": None, "updated_at": now_iso()}})
        deleted["patient_directory(unlinked)"] = r.modified_count
    deleted["patients"] = (await db.patients.delete_many({"id": pid})).deleted_count
    return {"deleted": deleted, "total": sum(deleted.values()), "preview": pv}


async def user_preview(uid: str) -> dict | None:
    from bson import ObjectId
    try:
        u = await db.users.find_one({"_id": ObjectId(uid)})
    except Exception:
        u = await db.users.find_one({"_id": uid})
    if not u:
        return None
    return {"id": str(u["_id"]), "email": u.get("email"), "name": u.get("name"), "role": u.get("role"), "username": u.get("username"),
            "active": u.get("active", True), "patient_id": u.get("patient_id"), "created_at": u.get("created_at"),
            "protected": u.get("role") in PROTECTED_ROLES,
            "grants_as_delegate": await db.patient_portal_delegates.count_documents({"delegate_user_id": str(u["_id"])}),
            "_raw_id": u["_id"]}


async def delete_user(uid: str) -> dict:
    pv = await user_preview(uid)
    if not pv:
        return {}
    raw = pv.pop("_raw_id")
    deleted = {
        "patient_portal_delegates(as_delegate)": (await db.patient_portal_delegates.delete_many({"delegate_user_id": pv["id"]})).deleted_count,
        "password_resets": (await db.password_resets.delete_many({"user_id": pv["id"]})).deleted_count,
        "account_activations": (await db.account_activations.delete_many({"user_id": pv["id"]})).deleted_count,
        "users": (await db.users.delete_one({"_id": raw})).deleted_count,
    }
    return {"deleted": deleted, "total": sum(deleted.values()), "preview": pv}


async def purge_preview() -> dict:
    """Counts only — architecture for PURGE ALL TEST DATA. The purge itself is intentionally NOT wired."""
    counts = {}
    for coll in sorted(await db.list_collection_names()):
        if coll in SKIP_COLLECTIONS - {"users", "patients", "patient_directory"} or coll.startswith("system."):
            continue
        n = await db[coll].estimated_document_count()
        if n:
            counts[coll] = n
    counts["users(non-operator)"] = await db.users.count_documents({"role": {"$nin": list(PROTECTED_ROLES)}})
    return {"counts": counts, "confirm_phrase": PURGE_CONFIRM, "wired": False}
