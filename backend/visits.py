"""Canonical clinical VISIT domain (UI name: Encounter). Phase 2A1: foundation only.

ONE collection `visits`. patient_ref is stable for life: "directory:<id>" when a directory
identity exists (directly or via patients.matched_directory_id), else "patient:<portal id>".
One IN_PROGRESS visit per (practice_id, patient_ref, physician_user_id) — DB-enforced.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

COLL = "visits"
IN_PROGRESS, STOPPED_UNSIGNED, SIGNED = "IN_PROGRESS", "STOPPED_UNSIGNED", "SIGNED"
READY_TO_SIGN = "READY_TO_SIGN"  # legacy alias (first Preview iteration) — treated exactly as STOPPED_UNSIGNED
UNSIGNED_STOPPED = (STOPPED_UNSIGNED, READY_TO_SIGN)
EDITABLE_STATUSES = (IN_PROGRESS, *UNSIGNED_STOPPED)  # documentation stays open until SIGNED
LOCKED_STATUSES = (SIGNED,)  # only signing locks the record server-side
RUNNING, PAUSED, STOPPED = "RUNNING", "PAUSED", "STOPPED"
SNAPSHOT_VERSION = 1
TIMER_FIELDS = ("timer_state", "elapsed_seconds", "running_since", "paused_at")
ENCOUNTER_TYPES = ("IN_CLINIC", "TELEPHONE", "VIDEO", "PROXY", "ADMIN", "PHYSICAL")
SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")
SNAPSHOT_FIELDS = ("last_name", "first_name", "date_of_birth", "health_card_display",
                   "health_card_version_code", "health_card_expiry_date")


class ActiveVisitExists(Exception):
    def __init__(self, visit):
        self.visit = visit


def _now():
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db):
    await db[COLL].create_index(
        [("practice_id", 1), ("patient_ref", 1), ("physician_user_id", 1)],
        unique=True, name="one_active_visit",
        partialFilterExpression={"status": IN_PROGRESS})
    await db[COLL].create_index([("practice_id", 1), ("patient_ref", 1), ("started_at", -1)])


def parse_ref(patient_ref: str):
    kind, _, ident = (patient_ref or "").partition(":")
    if kind not in ("directory", "patient") or not ident:
        return None, None
    return kind, ident


async def resolve_identity(db, patient_ref: Optional[str] = None, patient_id: Optional[str] = None,
                           directory_id: Optional[str] = None):
    """Returns {patient_ref, patient_id, directory_id, portal, directory} or None."""
    kind, ident = parse_ref(patient_ref) if patient_ref else (None, None)
    if kind == "directory":
        directory_id = directory_id or ident
    elif kind == "patient":
        patient_id = patient_id or ident
    portal = await db.patients.find_one({"id": patient_id}, {"_id": 0}) if patient_id else None
    if portal and portal.get("matched_directory_id"):
        directory_id = directory_id or portal["matched_directory_id"]
    if directory_id and not portal:
        portal = await db.patients.find_one({"matched_directory_id": directory_id}, {"_id": 0})
    directory = await db.patient_directory.find_one({"id": directory_id}, {"_id": 0}) if directory_id else None
    if directory_id and not directory:
        return None
    if not directory and not portal:
        return None
    return {
        "patient_ref": f"directory:{directory_id}" if directory_id else f"patient:{portal['id']}",
        "patient_id": portal["id"] if portal else None,
        "directory_id": directory_id,
        "portal": portal, "directory": directory,
    }


def all_refs(identity) -> list:
    refs = []
    if identity.get("directory_id"):
        refs.append(f"directory:{identity['directory_id']}")
    if identity.get("patient_id"):
        refs.append(f"patient:{identity['patient_id']}")
    return refs


async def find_active(db, practice_id, patient_ref, physician_user_id):
    return await db[COLL].find_one({"practice_id": practice_id, "patient_ref": patient_ref,
                                    "physician_user_id": physician_user_id, "status": IN_PROGRESS}, {"_id": 0})


async def create(db, *, practice_id, identity, snapshot, visita_patient_id, user, professional_id,
                 encounter_type, reason, appointment, source, ref_number):
    now = _now()
    actor = {"id": user["id"], "name": user.get("name")}
    doc = {
        "id": str(uuid.uuid4()), "ref_number": ref_number, "practice_id": practice_id,
        "patient_ref": identity["patient_ref"], "patient_id": identity["patient_id"],
        "directory_id": identity["directory_id"], "visita_patient_id": visita_patient_id,
        "patient_snapshot": {k: snapshot.get(k) for k in SNAPSHOT_FIELDS},
        "physician_user_id": user["id"], "physician_name": user.get("name"), "professional_id": professional_id,
        "appointment_id": (appointment or {}).get("id"), "appointment_ref": (appointment or {}).get("ref_number"),
        "source": source, "encounter_type": encounter_type, "reason": reason,
        "soap": {k: "" for k in SOAP_FIELDS},
        "vitals": dict(EMPTY_VITALS),
        "status": IN_PROGRESS,
        "timer_state": RUNNING, "elapsed_seconds": 0, "running_since": now, "paused_at": None,
        "started_at": now, "last_saved_at": None, "exited_at": None, "resumed_at": None,
        "created_at": now, "updated_at": now, "created_by": actor, "updated_by": actor, "save_count": 0,
    }
    try:
        await db[COLL].insert_one(doc)
    except DuplicateKeyError:
        existing = await find_active(db, practice_id, identity["patient_ref"], user["id"])
        raise ActiveVisitExists(existing)
    doc.pop("_id", None)
    return doc


async def save_soap(db, visit, patch: dict, user):
    """Apply changed S/O/A/P fields only. Returns (changed_fields, updated_doc)."""
    changed = {k: v for k, v in patch.items() if k in SOAP_FIELDS and v is not None and v != (visit.get("soap") or {}).get(k, "")}
    if not changed:
        return [], visit
    now = _now()
    sets = {f"soap.{k}": v for k, v in changed.items()}
    sets.update({"last_saved_at": now, "updated_at": now, "updated_by": {"id": user["id"], "name": user.get("name")}})
    res = await db[COLL].update_one({"id": visit["id"], "status": {"$in": list(EDITABLE_STATUSES)}}, {"$set": sets, "$inc": {"save_count": 1}})
    if not res.matched_count:
        return [], visit
    return sorted(changed), await db[COLL].find_one({"id": visit["id"]}, {"_id": 0})


VITAL_FIELDS = ("systolic_bp", "diastolic_bp", "heart_rate", "temperature_c", "weight_kg", "height_cm", "head_circumference_cm", "length_cm")
VITAL_RANGES = {"systolic_bp": (40, 300), "diastolic_bp": (20, 200), "heart_rate": (20, 300),
                "temperature_c": (25.0, 45.0), "weight_kg": (0.5, 500.0), "height_cm": (20.0, 272.0),
                "head_circumference_cm": (20.0, 70.0), "length_cm": (20.0, 130.0)}
EMPTY_VITALS = {**{k: None for k in VITAL_FIELDS}, "bmi": None, "weight_lb": None, "updated_at": None, "updated_by": None}


def validate_vitals(patch: dict) -> dict:
    """Return {field: value|None} for allowed fields only. Raises ValueError on bad input."""
    out = {}
    for k in VITAL_FIELDS:
        if k not in patch:
            continue
        v = patch[k]
        if v is None or v == "":
            out[k] = None
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{k} must be a number.")
        lo, hi = VITAL_RANGES[k]
        if not (lo <= float(v) <= hi):
            raise ValueError(f"{k} out of plausible range ({lo}-{hi}).")
        out[k] = round(float(v), 1) if isinstance(v, float) else int(v)
    return out


def compute_bmi(weight_kg, height_cm):
    if not weight_kg or not height_cm:
        return None
    return round(weight_kg / ((height_cm / 100) ** 2), 2)  # Access: BMI = WK / Hgt(m)^2


def compute_weight_lb(weight_kg):
    return round(weight_kg * 2.20462, 2) if weight_kg else None


async def save_vitals(db, visit, patch: dict, user):
    cur = {**EMPTY_VITALS, **(visit.get("vitals") or {})}
    changed = {k: v for k, v in validate_vitals(patch).items() if v != cur.get(k)}
    if not changed:
        return [], visit
    merged = {**cur, **changed}
    now = _now()
    merged.update({"bmi": compute_bmi(merged["weight_kg"], merged["height_cm"]), "weight_lb": compute_weight_lb(merged["weight_kg"]), "updated_at": now,
                   "updated_by": {"id": user["id"], "name": user.get("name")}})
    res = await db[COLL].update_one({"id": visit["id"], "status": {"$in": list(EDITABLE_STATUSES)}},
                                    {"$set": {"vitals": merged, "updated_at": now, "updated_by": merged["updated_by"]}})
    if not res.matched_count:
        return [], visit
    return sorted(changed), await db[COLL].find_one({"id": visit["id"]}, {"_id": 0})


def primary_dx(v: dict):
    src = v.get("signed_snapshot") if v.get("status") == SIGNED and v.get("signed_snapshot") else v
    d = (src.get("diagnoses") or [None])[0]
    return {"diagnosis_text": d.get("diagnosis_text"), "diagnosis_code": d.get("diagnosis_code")} if d else None


def history_row(v: dict) -> dict:
    return {"id": v["id"], "ref_number": v.get("ref_number"), "encounter_type": v.get("encounter_type"), "primary_dx": primary_dx(v),
            "status": v.get("status"), "started_at": v.get("started_at"), "last_saved_at": v.get("last_saved_at"),
            "exited_at": v.get("exited_at"), "stopped_at": v.get("stopped_at"), "signed_at": v.get("signed_at"), "physician_name": v.get("physician_name"),
            "appointment_ref": v.get("appointment_ref"), "reason": v.get("reason"), **timer_of(v),
            "has_vitals": any((v.get("vitals") or {}).get(k) is not None for k in VITAL_FIELDS)}


def timer_of(v: dict) -> dict:
    """Server-authoritative accumulated timer. Legacy visits (no timer fields) count as RUNNING since started_at."""
    if not v.get("timer_state"):
        return {"timer_state": RUNNING, "elapsed_seconds": 0, "running_since": v.get("started_at"), "paused_at": None}
    return {k: v.get(k) for k in TIMER_FIELDS}


def _secs_since(iso: str) -> int:
    return max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()))


async def timer_stop(db, visit, user):
    """RUNNING -> PAUSED: fold running span into elapsed_seconds. Idempotent when already PAUSED."""
    t = timer_of(visit)
    if t["timer_state"] == PAUSED:
        return t
    now = _now()
    t = {"timer_state": PAUSED, "elapsed_seconds": int(t["elapsed_seconds"] or 0) + _secs_since(t["running_since"] or now),
         "running_since": None, "paused_at": now}
    await db[COLL].update_one({"id": visit["id"]}, {"$set": {**t, "updated_at": now, "updated_by": {"id": user["id"], "name": user.get("name")}}})
    return t


async def timer_resume(db, visit, user):
    """PAUSED -> RUNNING on the SAME visit. Idempotent when already RUNNING."""
    t = timer_of(visit)
    now = _now()
    sets = {"resumed_at": now, "exited_at": None, "updated_at": now, "updated_by": {"id": user["id"], "name": user.get("name")}}
    if t["timer_state"] != RUNNING:
        t = {**t, "timer_state": RUNNING, "running_since": now, "paused_at": None}
    await db[COLL].update_one({"id": visit["id"]}, {"$set": {**t, **sets}})
    return t


# ---------------- Final lifecycle: IN_PROGRESS -> READY_TO_SIGN (stop, irreversible) -> SIGNED (immutable snapshot) ----------------
def lock_error(visit: dict):
    """Consistent 409 payload: VISIT_SIGNED (record locked) or VISIT_STOPPED (encounter timer ended; documentation still open)."""
    code = "VISIT_SIGNED" if visit.get("status") == SIGNED else "VISIT_STOPPED"
    return {"code": code, "status": visit.get("status"), "message": "This visit is signed. Corrections require an auditable addendum." if code == "VISIT_SIGNED"
            else "The encounter has ended; the timer cannot be changed. Documentation remains editable until signed."}


async def stop_final(db, visit, user):
    """Irreversible STOP of the ENCOUNTER: fold running time, freeze elapsed, status STOPPED_UNSIGNED. Timer can never resume;
    documentation stays editable (audited) until SIGN."""
    t = timer_of(visit)
    now = _now()
    elapsed = int(t["elapsed_seconds"] or 0) + (_secs_since(t["running_since"] or now) if t["timer_state"] == RUNNING else 0)
    sets = {"status": STOPPED_UNSIGNED, "stopped_at": now, "timer_state": STOPPED, "elapsed_seconds": elapsed, "running_since": None,
            "paused_at": None, "updated_at": now, "updated_by": {"id": user["id"], "name": user.get("name")}}
    res = await db[COLL].update_one({"id": visit["id"], "status": IN_PROGRESS}, {"$set": sets})
    return sets if res.modified_count else None


SNAPSHOT_KEYS = ("id", "ref_number", "practice_id", "patient_ref", "patient_id", "directory_id", "visita_patient_id", "patient_snapshot",
                 "encounter_type", "reason", "appointment_id", "appointment_ref", "started_at", "stopped_at", "elapsed_seconds",
                 "soap", "vitals", "diagnoses", "service", "physician_user_id", "professional_id", "physician_name")


def canonical_json(obj) -> str:
    """Deterministic representation: sorted keys, compact separators, ASCII-escaped — hashed with SHA-256."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def build_snapshot(visit: dict, signed_by: dict, signed_at: str) -> dict:
    snap = {k: visit.get(k) for k in SNAPSHOT_KEYS}
    snap["signed_at"], snap["signed_by"], snap["snapshot_version"] = signed_at, signed_by, SNAPSHOT_VERSION
    return snap


async def sign(db, visit, user, professional_id):
    """STOPPED_UNSIGNED -> SIGNED with immutable snapshot (exact reviewed state) + sha256 of canonical JSON. Authenticated identity only."""
    now = _now()
    signed_by = {"user_id": user["id"], "physician_user_id": visit.get("physician_user_id"), "professional_id": professional_id,
                 "physician_name": user.get("name"), "role": user.get("role")}
    snap = build_snapshot(visit, signed_by, now)
    digest = hashlib.sha256(canonical_json(snap).encode("utf-8")).hexdigest()
    sets = {"status": SIGNED, "signed_at": now, "signed_by": signed_by, "signed_snapshot": snap, "signed_snapshot_version": SNAPSHOT_VERSION,
            "signed_snapshot_hash": f"sha256:{digest}", "addenda": visit.get("addenda") or [],
            "updated_at": now, "updated_by": {"id": user["id"], "name": user.get("name")}}
    res = await db[COLL].update_one({"id": visit["id"], "status": {"$in": list(UNSIGNED_STOPPED)}}, {"$set": sets})
    return sets if res.modified_count else None


RECORD_KEYS = ("id", "ref_number", "encounter_type", "reason", "started_at", "stopped_at", "elapsed_seconds", "physician_name", "soap", "vitals", "diagnoses", "service", "patient_snapshot")


def read_only_record(v: dict) -> dict:
    """Visit Hx: SIGNED -> signed_snapshot is authoritative; otherwise the stored live fields. Never fabricates."""
    signed = v.get("status") == SIGNED and bool(v.get("signed_snapshot"))
    src = v["signed_snapshot"] if signed else v
    return {"source": "SIGNED_SNAPSHOT" if signed else "LIVE", "status": v.get("status"), "physician_user_id": v.get("physician_user_id"),
            "signed_at": v.get("signed_at"), "signed_by": v.get("signed_by"),
            "signed_snapshot_version": v.get("signed_snapshot_version"), "signed_snapshot_hash": v.get("signed_snapshot_hash"),
            "record": {k: src.get(k) for k in RECORD_KEYS}}
