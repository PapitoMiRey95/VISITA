"""Stage C — patient ↔ practice relationships.

ONE global canonical patient identity (patient_directory) may hold a DIFFERENT
relationship state per practice. This module owns the `patient_provider_relationships`
collection and the upsert/query helpers. It NEVER merges clinical records and never
creates a second canonical identity — it only records per-practice state.

Relationship status:
  - active     : currently an active patient at that practice
  - applicant  : applied / registered, awaiting the clinic's decision or verification
  - former     : previously active, no longer active at that practice
  - inactive   : relationship closed/disabled (generic)

A relationship is keyed to a practice and anchors to whatever is known:
  - directory_id   : canonical identity (preferred; set once known)
  - patient_id     : the portal account for that practice
  - application_id : originating application (for applicants with no directory record yet)
"""
from datetime import datetime, timezone
import uuid

ACTIVE = "active"
APPLICANT = "applicant"
FORMER = "former"
INACTIVE = "inactive"
STATUSES = {ACTIVE, APPLICANT, FORMER, INACTIVE}

COLL = "patient_provider_relationships"


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _find_existing(db, practice_id, directory_id=None, patient_id=None, application_id=None):
    """Find the single relationship for this practice anchored to any known id.
    Priority: directory_id > patient_id > application_id. This enforces one
    relationship per (practice, canonical identity)."""
    if directory_id:
        r = await db[COLL].find_one({"practice_id": practice_id, "directory_id": directory_id})
        if r:
            return r
    if patient_id:
        r = await db[COLL].find_one({"practice_id": practice_id, "patient_id": patient_id})
        if r:
            return r
    if application_id:
        r = await db[COLL].find_one({"practice_id": practice_id, "application_id": application_id})
        if r:
            return r
    return None


async def upsert_relationship(db, *, practice_id, status, directory_id=None, patient_id=None,
                              application_id=None, visita_patient_id=None, by="system",
                              source="system", note=None):
    """Create or update the (practice, canonical patient) relationship.

    - De-dupes to a single relationship per practice+identity; attaches newly-known
      anchors (directory_id/patient_id/application_id/PIN) without clobbering set values.
    - Appends a history entry only when the status actually changes (or on creation).
    Returns the stored relationship dict (no _id).
    """
    if status not in STATUSES:
        raise ValueError(f"Invalid relationship status: {status}")
    if not practice_id:
        raise ValueError("practice_id is required for a relationship")

    existing = await _find_existing(db, practice_id, directory_id, patient_id, application_id)
    now = _now()

    if existing:
        set_fields = {"updated_at": now}
        # Attach newly-known anchors without overwriting an existing non-null value.
        for k, v in (("directory_id", directory_id), ("patient_id", patient_id),
                     ("application_id", application_id), ("visita_patient_id", visita_patient_id)):
            if v and not existing.get(k):
                set_fields[k] = v
        status_changed = existing.get("status") != status
        if status_changed:
            set_fields["status"] = status
        update = {"$set": set_fields}
        if status_changed:
            update["$push"] = {"history": {"status": status, "at": now, "by": by,
                                           "source": source, "note": note,
                                           "from_status": existing.get("status")}}
        await db[COLL].update_one({"id": existing["id"]}, update)
        return await db[COLL].find_one({"id": existing["id"]}, {"_id": 0})

    doc = {
        "id": "rel_" + uuid.uuid4().hex,
        "practice_id": practice_id,
        "directory_id": directory_id,
        "patient_id": patient_id,
        "application_id": application_id,
        "visita_patient_id": visita_patient_id,
        "status": status,
        "source": source,
        "created_by": by,
        "created_at": now,
        "updated_at": now,
        "history": [{"status": status, "at": now, "by": by, "source": source,
                     "note": note, "from_status": None}],
    }
    await db[COLL].insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def relationships_for_directory(db, directory_id):
    """All per-practice relationships for one canonical identity (across practices)."""
    if not directory_id:
        return []
    return await db[COLL].find({"directory_id": directory_id}, {"_id": 0}).to_list(100)


async def relationship_for_patient(db, practice_id, patient_id=None, directory_id=None):
    return await _find_existing(db, practice_id, directory_id=directory_id, patient_id=patient_id)


def serialize(r):
    if not r:
        return None
    return {k: v for k, v in r.items() if k != "_id"}
