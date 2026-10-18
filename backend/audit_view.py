"""Settings → Audit & Compliance: READ-ONLY viewer over the EXISTING `audit_logs` collection.
No mutation endpoints exist for audit records. Practice scoping is derived (older records carry no practice_id):
  a record is visible iff practice_id == user's practice, OR meta.practice_id matches, OR its entity is a visit /
  directory patient / portal patient of the practice. Physicians additionally only see their own visits' events."""
import re
from datetime import datetime, timedelta, timezone

from names import full_display_name

MODULE = {"visit": "Visit", "patient_directory": "Patient", "patient": "Patient", "appointment_request": "Appointment", "appointment": "Appointment",
          "prescription_request": "Prescription", "referral": "Referral", "invoice": "Billing", "settings": "Settings", "user": "User"}
PAGE_MAX = 200


async def ensure_indexes(db):
    """NON-CRITICAL performance indexes (see index_bootstrap.AUDIT_INDEXES). Never gates readiness."""
    import index_bootstrap as ib
    return await ib.ensure_audit_indexes_background(db)


async def _scope(db, user):
    """Returns ($or scope filter, visit map) for the caller's practice. Never crosses practices."""
    pid = user.get("practice_id")
    vq = {"practice_id": pid}
    if user["role"] == "physician":
        vq["physician_user_id"] = user["id"]
    visits = {v["id"]: v async for v in db.visits.find(vq, {"_id": 0, "id": 1, "ref_number": 1, "patient_ref": 1, "status": 1, "patient_snapshot": 1,
                                                                 "visita_patient_id": 1, "signed_at": 1, "signed_by": 1, "signed_snapshot_version": 1, "signed_snapshot_hash": 1})}
    dir_ids = [d["id"] async for d in db.patient_directory.find({"practice_id": pid}, {"_id": 0, "id": 1})]
    pt_ids = [p["id"] async for p in db.patients.find({"practice_id": pid}, {"_id": 0, "id": 1})]
    ors = [{"practice_id": pid}, {"meta.practice_id": pid}, {"entity_type": "visit", "entity_id": {"$in": list(visits)}},
           {"entity_type": "patient_directory", "entity_id": {"$in": dir_ids}}, {"entity_type": "patient", "entity_id": {"$in": pt_ids}}]
    if user["role"] == "physician":  # physicians: only their own visits + events they performed
        ors = [{"entity_type": "visit", "entity_id": {"$in": list(visits)}}, {"actor_id": user["id"], "$or": ors}]
    return {"$or": ors}, visits


def _iso_day(s, end=False):
    d = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return ((d + timedelta(days=1)) if end else d).isoformat()


async def _patient_labels(db, rows, visits):
    refs = {r.get("meta", {}).get("patient_ref") for r in rows if r.get("meta", {}).get("patient_ref")}
    refs |= {visits[r["entity_id"]]["patient_ref"] for r in rows if r.get("entity_type") == "visit" and r["entity_id"] in visits}
    labels = {}
    dids = [x.split(":", 1)[1] for x in refs if x.startswith("directory:")]
    pids = [x.split(":", 1)[1] for x in refs if x.startswith("patient:")]
    async for d in db.patient_directory.find({"id": {"$in": dids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "visita_patient_id": 1}):
        labels[f"directory:{d['id']}"] = {"name": full_display_name(d), "pin": d.get("visita_patient_id")}
    async for p in db.patients.find({"id": {"$in": pids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "middle_name": 1, "second_last_name": 1, "visita_patient_id": 1}):
        labels[f"patient:{p['id']}"] = {"name": full_display_name(p), "pin": p.get("visita_patient_id")}
    return labels


def _row(r, visits, labels):
    v = visits.get(r["entity_id"]) if r.get("entity_type") == "visit" else None
    pref = r.get("meta", {}).get("patient_ref") or (v or {}).get("patient_ref")
    lab = labels.get(pref) or {}
    return {"id": r["id"], "created_at": r["created_at"], "action": r["action"], "entity_type": r.get("entity_type"), "entity_id": r.get("entity_id"),
            "module": MODULE.get(r.get("entity_type"), r.get("entity_type")), "actor_id": r.get("actor_id"), "actor_name": r.get("actor_name"), "actor_role": r.get("actor_role"),
            "old_status": r.get("old_status"), "new_status": r.get("new_status") or r.get("meta", {}).get("resulting_status"),
            "patient_ref": pref, "patient_name": lab.get("name"), "patient_pin": lab.get("pin"),
            "visit_ref": (v or {}).get("ref_number") or r.get("meta", {}).get("ref_number"), "visit_status": (v or {}).get("status"),
            "meta": r.get("meta") or {}, "practice_id": r.get("practice_id") or r.get("meta", {}).get("practice_id")}


async def list_events(db, user, *, date_from=None, date_to=None, patient_ref=None, visit_ref=None, actor=None, action=None, module=None,
                      visit_status=None, page=1, page_size=50):
    scope, visits = await _scope(db, user)
    f = dict(scope)
    ands = []
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = _iso_day(date_from)
        if date_to:
            rng["$lt"] = _iso_day(date_to, end=True)
        ands.append({"created_at": rng})
    if visit_ref:
        ids = [vid for vid, v in visits.items() if (v.get("ref_number") or "").upper() == visit_ref.strip().upper()]
        ands.append({"$or": [{"entity_type": "visit", "entity_id": {"$in": ids}}, {"meta.ref_number": visit_ref.strip().upper()}]})
    if patient_ref:
        ids = [vid for vid, v in visits.items() if v.get("patient_ref") == patient_ref]
        ands.append({"$or": [{"meta.patient_ref": patient_ref}, {"entity_type": "visit", "entity_id": {"$in": ids}}, {"entity_id": patient_ref.split(":", 1)[-1]}]})
    if actor:
        ands.append({"$or": [{"actor_id": actor}, {"actor_name": {"$regex": re.escape(actor), "$options": "i"}}]})
    if action:
        ands.append({"action": {"$regex": re.escape(action), "$options": "i"}})
    if module:
        ands.append({"entity_type": {"$in": [k for k, m in MODULE.items() if m.lower() == module.lower()] or [module]}})
    if visit_status:
        ands.append({"entity_type": "visit", "entity_id": {"$in": [vid for vid, v in visits.items() if v.get("status") == visit_status]}})
    if ands:
        f = {"$and": [scope, *ands]}
    page_size = max(1, min(int(page_size), PAGE_MAX))
    total = await db.audit_logs.count_documents(f)
    rows = await db.audit_logs.find(f, {"_id": 0}).sort("created_at", -1).skip((max(1, int(page)) - 1) * page_size).to_list(page_size)
    labels = await _patient_labels(db, rows, visits)
    return {"items": [_row(r, visits, labels) for r in rows], "total": total, "page": int(page), "page_size": page_size}


async def get_event(db, user, audit_id):
    scope, visits = await _scope(db, user)
    r = await db.audit_logs.find_one({"$and": [{"id": audit_id}, scope]}, {"_id": 0})
    if not r:
        return None
    labels = await _patient_labels(db, [r], visits)
    out = _row(r, visits, labels)
    v = visits.get(r["entity_id"]) if r.get("entity_type") == "visit" else None
    if v and v.get("status") == "SIGNED":
        out["signed"] = {"signed_at": v.get("signed_at"), "signed_by": v.get("signed_by"), "version": v.get("signed_snapshot_version"), "hash": v.get("signed_snapshot_hash")}
    return out


async def visit_timeline(db, user, visit_id):
    scope, visits = await _scope(db, user)
    v = visits.get(visit_id)
    rows = await db.audit_logs.find({"$and": [{"entity_type": "visit", "entity_id": visit_id}, scope]}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    if not v and not rows:
        return None
    labels = await _patient_labels(db, rows, visits)
    stopped = next((r["created_at"] for r in rows if r["action"] == "visit_stopped"), None)
    items = [{**_row(r, visits, labels), "after_stop": bool(stopped and r["created_at"] > stopped and r["action"] not in ("visit_stopped", "visit_read", "visit_signed", "visit_exited"))} for r in rows]
    sig = next((r["meta"] for r in reversed(rows) if r["action"] == "visit_signed"), None)
    if v and v.get("status") == "SIGNED":
        signed = {"signed_at": v.get("signed_at"), "signed_by": v.get("signed_by"), "version": v.get("signed_snapshot_version"), "hash": v.get("signed_snapshot_hash")}
    elif sig:  # visit document no longer present — integrity reference from the stored signing event only
        signed = {"signed_at": sig.get("signed_at"), "signed_by": sig.get("signed_by"), "version": sig.get("signed_snapshot_version"), "hash": sig.get("signed_snapshot_hash"), "from_audit_only": True}
    else:
        signed = None
    last = rows[-1] if rows else {}
    status = v.get("status") if v else (last.get("new_status") or last.get("meta", {}).get("resulting_status"))
    pref = v.get("patient_ref") if v else last.get("meta", {}).get("patient_ref")
    return {"visit": {"id": visit_id, "ref_number": (v or {}).get("ref_number") or last.get("meta", {}).get("ref_number"), "status": status, "patient_ref": pref,
                      "patient": labels.get(pref), "document_present": bool(v)}, "signed": signed, "items": items}
