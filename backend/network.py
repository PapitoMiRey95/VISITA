"""VIen Network — Phase 1: People ↔ Connections ↔ Organizations ↔ Authorized workspace access.

Three separate concepts:
  NETWORK CONNECTION  (network_connections)  professional relationship — grants ZERO application access
  ORG MEMBERSHIP      (org_memberships)      person is affiliated with an organization (INVITED/ACTIVE/SUSPENDED/REMOVED)
  ACCESS GRANT        (membership.modules)   explicit, revocable workspace capabilities, enforced at the API
Organizations are the existing `practices`. Network profiles never carry PHI.
"""
import uuid
from datetime import datetime, timezone, timedelta

from db import db, now_iso

MODULES = {
    "patients": "Patients / basic patient information", "calendar": "Calendar / Appointments", "messages": "Messages / Intercom",
    "registration": "Registration / Verifications", "rx": "Rx workflow", "billing": "Billing / Private requests",
}
# Workspace API enforcement: module -> allowed /api prefixes. Anything else under /api/internal is denied for workspace sessions.
MODULE_API_PREFIXES = {
    "patients": ("/api/internal/patients", "/api/internal/patient-lookup", "/api/internal/directory", "/api/internal/identity-links", "/api/internal/registration-qr"),
    "calendar": ("/api/internal/calendar", "/api/internal/appointments", "/api/internal/appointment-search", "/api/availability", "/api/internal/slots", "/api/internal/breaks"),
    "messages": ("/api/internal/messages", "/api/internal/tasks", "/api/internal/work"),
    "registration": ("/api/internal/applications", "/api/internal/verifications", "/api/internal/portal-access-requests", "/api/internal/health-card-updates", "/api/internal/registration", "/api/internal/delegate-options"),
    "rx": ("/api/internal/prescriptions", "/api/internal/send-rx", "/api/internal/pharmacy-rx", "/api/internal/pharmacies"),
    "billing": ("/api/internal/invoices", "/api/internal/private-requests", "/api/internal/service-catalog"),
}
WORKSPACE_BASE_ALLOW = ("/api/auth/", "/api/me", "/api/system/", "/api/network/", "/api/internal/counters", "/api/internal/my-practice", "/api/health")
STATUSES = ("INVITED", "ACTIVE", "SUSPENDED", "REMOVED", "DECLINED")


def _person(u: dict) -> dict:
    return {"type": "person", "id": str(u["_id"]), "name": u.get("name"), "role": u.get("role")}


async def org_doc(org_id: str) -> dict | None:
    p = await db.practices.find_one({"id": org_id}, {"_id": 0})
    if not p:
        return None
    return {"type": "organization", "id": p["id"], "name": p.get("clinic_name") or p.get("physician_name") or p.get("slug"),
            "org_type": "Medical Clinic", "location": p.get("clinic_address") or "", "phone": p.get("clinic_phone"),
            "status": "VERIFIED" if p.get("active", True) else "INACTIVE", "owner_user_id": p.get("physician_user_id"),
            "owner_name": p.get("physician_name"), "slug": p.get("slug")}


async def is_org_owner(user: dict, org_id: str) -> bool:
    if user.get("role") == "admin" and user.get("practice_id") == org_id:
        return True
    p = await db.practices.find_one({"id": org_id}, {"physician_user_id": 1})
    return bool(p and p.get("physician_user_id") == str(user.get("id")))


async def profile_for(user_id: str) -> dict | None:
    from bson import ObjectId
    try:
        u = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        u = None
    if not u or u.get("role") in ("patient", "caregiver"):
        return None
    prof = await db.network_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {}
    mems = await db.org_memberships.find({"user_id": user_id, "status": {"$in": ["ACTIVE", "SUSPENDED"]}}, {"_id": 0}).to_list(20)
    owned = await db.practices.find({"physician_user_id": user_id}, {"_id": 0, "id": 1, "clinic_name": 1}).to_list(10)
    orgs = [{"id": m["org_id"], "name": m["org_name"], "role_title": m["role_title"], "status": m["status"]} for m in mems]
    orgs += [{"id": o["id"], "name": o.get("clinic_name"), "role_title": "Physician / Owner", "status": "ACTIVE"} for o in owned]
    headline = prof.get("headline") or ({"physician": "Physician", "staff": "Administrative professional", "admin": "Clinic administrator"}.get(u.get("role"), "VIen member"))
    conns = await connections_for("person", user_id)
    return {"id": user_id, "name": u.get("name"), "username": u.get("username"), "headline": headline, "summary": prof.get("summary", ""),
            "city": prof.get("city", ""), "languages": prof.get("languages", []), "availability": prof.get("availability", "NOT_LOOKING"),
            "avatar_url": prof.get("avatar_url"), "organizations": orgs, "connections": conns, "connection_count": len(conns)}


async def connections_for(kind: str, ident: str) -> list:
    rows = await db.network_connections.find({"status": "ACTIVE", "$or": [{"a.id": ident, "a.type": kind}, {"b.id": ident, "b.type": kind}]}, {"_id": 0}).to_list(100)
    out = []
    for r in rows:
        other = r["b"] if (r["a"]["id"] == ident and r["a"]["type"] == kind) else r["a"]
        out.append({**other, "since": r["since"], "relationship": r.get("relationship")})
    return out


async def _connect(a: dict, b: dict, relationship: str, membership_id: str):
    key = {"status": "ACTIVE", "a.id": a["id"], "b.id": b["id"]}
    if await db.network_connections.find_one(key):
        return
    await db.network_connections.insert_one({"id": str(uuid.uuid4()), "a": a, "b": b, "relationship": relationship,
                                             "via_membership_id": membership_id, "since": now_iso(), "status": "ACTIVE"})


async def invite(org: dict, invitee: dict, role_title: str, inviter: dict) -> dict:
    uid = str(invitee["_id"])
    existing = await db.org_memberships.find_one({"org_id": org["id"], "user_id": uid, "status": {"$in": ["INVITED", "ACTIVE", "SUSPENDED"]}})
    if existing:
        raise ValueError(f"{invitee.get('name')} already has a {existing['status'].lower()} membership at this organization.")
    m = {"id": str(uuid.uuid4()), "org_id": org["id"], "org_name": org["name"], "user_id": uid, "user_name": invitee.get("name"),
         "role_title": role_title, "status": "INVITED", "modules": [], "invited_by": {"id": str(inviter.get("id")), "name": inviter.get("name")},
         "invited_at": now_iso(), "updated_at": now_iso()}
    await db.org_memberships.insert_one(dict(m))
    return m


async def respond(m: dict, accept: bool, user: dict) -> dict:
    status = "ACTIVE" if accept else "DECLINED"
    upd = {"status": status, "updated_at": now_iso()}
    if accept:
        upd["accepted_at"] = now_iso()
    await db.org_memberships.update_one({"id": m["id"]}, {"$set": upd})
    if accept:
        org = await org_doc(m["org_id"])
        person = {"type": "person", "id": m["user_id"], "name": m["user_name"]}
        await _connect(person, {"type": "organization", "id": org["id"], "name": org["name"]}, m["role_title"], m["id"])
        if org.get("owner_user_id"):
            await _connect(person, {"type": "person", "id": org["owner_user_id"], "name": org.get("owner_name")}, f"{m['role_title']} at {org['name']}", m["id"])
    return {**m, **upd}


async def set_access(m: dict, modules: list) -> dict:
    mods = [x for x in modules if x in MODULES]
    await db.org_memberships.update_one({"id": m["id"]}, {"$set": {"modules": mods, "updated_at": now_iso()}})
    return mods


async def set_status(m: dict, status: str):
    await db.org_memberships.update_one({"id": m["id"]}, {"$set": {"status": status, "updated_at": now_iso()}})
    if status == "REMOVED":
        await db.network_connections.update_many({"via_membership_id": m["id"]}, {"$set": {"status": "ENDED", "ended_at": now_iso()}})


async def team(org_id: str) -> list:
    org = await org_doc(org_id)
    rows = [{"user_id": org["owner_user_id"], "name": org.get("owner_name"), "role_title": "Physician / Owner", "status": "ACTIVE", "owner": True, "modules": ["*"]}]
    for m in await db.org_memberships.find({"org_id": org_id, "status": {"$in": ["INVITED", "ACTIVE", "SUSPENDED"]}}, {"_id": 0}).sort("invited_at", 1).to_list(100):
        rows.append({"membership_id": m["id"], "user_id": m["user_id"], "name": m["user_name"], "role_title": m["role_title"], "status": m["status"],
                     "modules": m.get("modules", []), "connected": m["status"] in ("ACTIVE", "SUSPENDED"), "access_granted": bool(m.get("modules")) and m["status"] == "ACTIVE",
                     "invited_at": m.get("invited_at"), "accepted_at": m.get("accepted_at")})
    return rows


def workspace_allowed(path: str, modules: list) -> bool:
    if any(path.startswith(p) for p in WORKSPACE_BASE_ALLOW):
        return True
    for mod in modules:
        if any(path.startswith(p) for p in MODULE_API_PREFIXES.get(mod, ())):
            return True
    return not path.startswith("/api/internal")
