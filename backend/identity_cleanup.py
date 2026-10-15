"""Identity Cleanup — controlled, staff-driven historical reconciliation of portal accounts
vs canonical patient_directory records. Read-only queue/case builders + narrowly scoped,
audited mutations (link via the hardened helper, half-link repair, per-field demographic
apply). Never touches clinical collections, PINs or deletes anything."""
import re

import directory as dmod
from db import audit, mask_hcn, now_iso
from names import family_names, full_display_name, given_names

# classes
SAFE_LINK = "SAFE_LINK_CANDIDATE"
POSSIBLE = "POSSIBLE_MATCH_REVIEW"
CONFLICT = "IDENTITY_CONFLICT"
HALF_LINK = "HALF_LINK"
DIR_LINKED = "DIRECTORY_ALREADY_LINKED"
MULTI_PORTAL = "MULTIPLE_PORTAL_ACCOUNTS"
CLINICAL = "CLINICAL_HISTORY_REVIEW_REQUIRED"
NO_MATCH = "NO_MATCH"
LINKED_RECONCILE = "LINKED_RECONCILE_DEMOGRAPHICS"

IDENTITY_CRITICAL = {"name", "date_of_birth", "health_card_number"}

# canonical directory field -> portal field
FIELDS = [
    ("name", None), ("date_of_birth", "date_of_birth"), ("sex", "sex"),
    ("health_card_number", "health_card_number"), ("health_card_version_code", "health_card_version"),
    ("health_card_issue_date", "health_card_issue_date"), ("health_card_expiry_date", "health_card_expiry_date"),
    ("email", "email"), ("cell_phone", "phone"), ("home_phone", "home_phone"),
    ("address", "address"), ("unit", "unit"), ("city", "city"), ("province", "province"),
    ("postal_code", "postal_code"), ("country", "country"),
]
LABELS = {"name": "Full name", "date_of_birth": "Date of birth", "sex": "Sex", "health_card_number": "Health card number",
          "health_card_version_code": "Version code", "health_card_issue_date": "HC issue date", "health_card_expiry_date": "HC expiry date",
          "email": "Email", "cell_phone": "Cell phone", "home_phone": "Home phone", "address": "Street address", "unit": "Unit",
          "city": "City", "province": "Province", "postal_code": "Postal code", "country": "Country"}


def _norm(field, v):
    if v in (None, ""):
        return ""
    s = str(v).strip()
    if field in ("health_card_number",):
        return dmod.norm_hcn(s)
    if field in ("cell_phone", "home_phone"):
        return re.sub(r"\D", "", s)
    if field == "postal_code":
        return re.sub(r"\s+", "", s).upper()
    if field in ("email",):
        return s.lower()
    if field == "date_of_birth":
        return dmod.norm_dob(s)
    return re.sub(r"\s+", " ", s).upper()


def _dir_val(d, field):
    if field == "name":
        return full_display_name(d)
    if field == "date_of_birth":
        return d.get("norm_dob") or dmod.norm_dob(d.get("date_of_birth"))
    return d.get(field)


def _portal_val(p, field, pfield):
    if field == "name":
        return full_display_name(p)
    return p.get(pfield)


def compare_fields(d, p):
    rows = []
    for field, pfield in FIELDS:
        cv, pv = _dir_val(d, field), _portal_val(p, field, pfield)
        nc, npv = _norm(field, cv), _norm(field, pv)
        if nc and npv:
            state = "MATCH" if nc == npv else "CONFLICT"
        elif nc:
            state = "CANONICAL_ONLY"
        elif npv:
            state = "PORTAL_ONLY"
        else:
            state = "EMPTY"
        rec = "KEEP_CANONICAL"
        if state == "PORTAL_ONLY":
            rec = "ADD_TO_CANONICAL"
        elif state == "CONFLICT":
            rec = "KEEP_CANONICAL" if field == "name" else "REVIEW"
        rows.append({"field": field, "label": LABELS[field], "canonical": cv, "portal": pv, "state": state,
                     "identity_critical": field in IDENTITY_CRITICAL, "recommendation": rec})
    return rows


def evidence(d, p):
    ev = []
    dh, ph = dmod.norm_hcn(d.get("health_card_number")) or d.get("norm_hcn") or "", dmod.norm_hcn(p.get("health_card_number"))
    if dh and ph:
        ev.append("EXACT_HCN" if dh == ph else "DIFFERENT_HCN")
    dd, pd = _dir_val(d, "date_of_birth"), dmod.norm_dob(p.get("date_of_birth"))
    if dd and pd:
        ev.append("EXACT_DOB" if dd == pd else "DIFFERENT_DOB")
    df, dl = set(_tok(d.get("first_name"))), set(_tok(d.get("last_name")))
    pf = _tok(" ".join(x for x in [p.get("first_name"), p.get("middle_name")] if x))
    pl = _tok(" ".join(x for x in [p.get("last_name"), p.get("second_last_name")] if x))
    if df == set(pf) and dl == set(pl):
        ev.append("EXACT_NAME")
    elif pf and pl and all(t in df for t in pf) and all(t in dl for t in pl):
        ev.append("SHORTENED_NAME")
    else:
        ev.append("NAME_INCOMPATIBLE")
    if p.get("matched_directory_id") == d["id"] and d.get("linked_patient_id") != p["id"]:
        ev.append("HALF_LINK_PORTAL_SIDE")
    if d.get("linked_patient_id") == p["id"] and p.get("matched_directory_id") != d["id"]:
        ev.append("HALF_LINK_DIRECTORY_SIDE")
    if d.get("linked_patient_id") and d["linked_patient_id"] != p["id"]:
        ev.append("EXISTING_DIRECTORY_LINK")
    return ev


def _tok(s):
    return [t for t in dmod.norm_name(s).split(" ") if t]


async def dependencies(db, portal_id=None, directory_id=None):
    """Clinical/operational references attached to ONE identity side."""
    refs = []
    if portal_id:
        refs.append(f"patient:{portal_id}")
    if directory_id:
        refs.append(f"directory:{directory_id}")
    pid_q = {"patient_id": portal_id} if portal_id else None
    out = {}
    out["visits"] = await db.visits.count_documents({"$or": [{"patient_ref": {"$in": refs}}] + ([{"patient_id": portal_id}] if portal_id else []) + ([{"directory_id": directory_id}] if directory_id else [])}) if refs else 0
    for key, coll in [("prescriptions", "prescription_requests"), ("imaging", "imaging_requests"), ("bloodwork", "bloodwork_requests"),
                      ("results", "exam_results"), ("referrals", "referrals"), ("medications", "patient_medications"), ("appointments", "appointment_requests")]:
        out[key] = await db[coll].count_documents(pid_q) if pid_q else 0
    hx_q = {"$or": ([{"patient_ref": {"$in": refs}}] if refs else []) + ([{"patient_id": portal_id}] if portal_id else []) + ([{"directory_id": directory_id}] if directory_id else [])}
    for key, coll in [("conditions", "patient_conditions"), ("surgeries", "patient_surgeries"), ("allergies", "patient_allergies")]:
        out[key] = await db[coll].count_documents(hx_q) if hx_q["$or"] else 0
    rx_q = {"$or": ([{"patient_id": portal_id}] if portal_id else []) + ([{"patient_directory_id": directory_id}] if directory_id else [])}
    out["rx_transmissions"] = await db.rx_transmissions.count_documents(rx_q) if rx_q["$or"] else 0
    clinical_keys = ["visits", "prescriptions", "imaging", "bloodwork", "results", "referrals", "medications", "conditions", "surgeries", "allergies", "rx_transmissions"]
    out["has_clinical"] = any(out[k] for k in clinical_keys)
    return out


async def _other_portal_for_dir(db, did, pid):
    return await db.patients.find_one({"id": {"$ne": pid}, "matched_directory_id": did, "active_status": True},
                                      {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "middle_name": 1, "second_last_name": 1,
                                       "visita_patient_id": 1, "verification_status": 1})


def _portal_brief(p):
    return {"id": p["id"], "full_name": full_display_name(p), "visita_patient_id": p.get("visita_patient_id"),
            "verification_status": p.get("verification_status"), "date_of_birth": p.get("date_of_birth"),
            "health_card_masked": mask_hcn(p.get("health_card_number")), "portal_status": p.get("portal_status"),
            "matched_directory_id": p.get("matched_directory_id"), "identity_cleanup": p.get("identity_cleanup"),
            "historical_visita_patient_id": p.get("historical_visita_patient_id")}


def _dir_brief(d):
    return {"id": d["id"], "full_name": full_display_name(d), "visita_patient_id": d.get("visita_patient_id"),
            "date_of_birth": _dir_val(d, "date_of_birth"), "health_card_masked": mask_hcn(d.get("health_card_number")),
            "patient_status": d.get("patient_status"), "linked_patient_id": d.get("linked_patient_id")}


async def _duplicate_portal(db, p):
    """Another ACTIVE portal account sharing strong identity evidence: exact HCN, or exact DOB + exact full name."""
    q = {"id": {"$ne": p["id"]}, "active_status": True}
    proj = {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "middle_name": 1, "second_last_name": 1, "visita_patient_id": 1, "verification_status": 1, "health_card_number": 1, "date_of_birth": 1}
    h = dmod.norm_hcn(p.get("health_card_number"))
    if h:
        async for o in db.patients.find(q, proj):
            if dmod.norm_hcn(o.get("health_card_number")) == h:
                return _portal_brief(o), "HCN"
    if p.get("date_of_birth"):
        async for o in db.patients.find({**q, "date_of_birth": p["date_of_birth"]}, proj):
            if full_display_name(o).upper() == full_display_name(p).upper():
                return _portal_brief(o), "NAME_DOB"
    return None


async def classify(db, p):
    """Returns (class, directory_doc_or_None, evidence, strength, other_portal)."""
    pid = p["id"]
    mdir = p.get("matched_directory_id")
    d = await db.patient_directory.find_one({"id": mdir}) if mdir else await db.patient_directory.find_one({"linked_patient_id": pid})
    strength = None
    if d:
        both = d.get("linked_patient_id") == pid and mdir == d["id"]
        if both:
            cs = (p.get("identity_cleanup") or {}).get("status")
            if cs == "linked":
                return LINKED_RECONCILE, d, evidence(d, p), "linked", None
            return None, d, [], None, None
        if d.get("linked_patient_id") and d["linked_patient_id"] != pid:
            return DIR_LINKED, d, evidence(d, p), "linked_elsewhere", await _other_portal_for_dir(db, d["id"], pid)
        return HALF_LINK, d, evidence(d, p), "half", None
    strength, cands = await dmod.live_candidates(db, p)
    if not cands:
        dup = await _duplicate_portal(db, p)
        if dup:
            return MULTI_PORTAL, None, ["DUPLICATE_PORTAL_" + dup[1]], "portal_duplicate", dup[0]
        return NO_MATCH, None, [], "none", None
    d = await db.patient_directory.find_one({"id": cands[0]["id"]})
    ev = evidence(d, p)
    other = await _other_portal_for_dir(db, d["id"], pid)
    if (d.get("linked_patient_id") and d["linked_patient_id"] != pid) or other:
        return MULTI_PORTAL, d, ev, strength, other or {"id": d.get("linked_patient_id")}
    if "DIFFERENT_HCN" in ev or "DIFFERENT_DOB" in ev or "NAME_INCOMPATIBLE" in ev:
        return CONFLICT, d, ev, strength, None
    dep = await dependencies(db, portal_id=pid)
    if dep["has_clinical"]:
        return CLINICAL, d, ev, strength, None
    return (SAFE_LINK if strength == "strong" else POSSIBLE), d, ev, strength, None


async def queue(db, practice_id):
    rows = []
    cur = db.patients.find({"practice_id": practice_id, "active_status": True,
                            "verification_status": {"$in": ["verified", "pending"]},
                            "$or": [{"identity_linked": {"$ne": True}}, {"identity_cleanup.status": "linked"}]}).sort("created_at", -1)
    async for p in cur:
        cls, d, ev, strength, other = await classify(db, p)
        if not cls:
            continue
        if cls == NO_MATCH and p.get("verification_status") != "verified":
            continue
        rows.append({"class": cls, "strength": strength, "evidence": ev, "portal": _portal_brief(p),
                     "canonical": _dir_brief(d) if d else None, "other_portal": other})
    order = {HALF_LINK: 0, SAFE_LINK: 1, LINKED_RECONCILE: 2, POSSIBLE: 3, CONFLICT: 4, CLINICAL: 5, MULTI_PORTAL: 6, DIR_LINKED: 7, NO_MATCH: 8}
    rows.sort(key=lambda r: order.get(r["class"], 9))
    return rows


async def case(db, p, directory_id=None):
    cls, d, ev, strength, other = await classify(db, p)
    if directory_id and (not d or d["id"] != directory_id):
        d = await db.patient_directory.find_one({"id": directory_id})
        if d:
            ev = evidence(d, p)
            cls = cls if cls in (HALF_LINK, DIR_LINKED, LINKED_RECONCILE) else (CONFLICT if any(x in ev for x in ("DIFFERENT_HCN", "DIFFERENT_DOB", "NAME_INCOMPATIBLE")) else POSSIBLE)
    dep_portal = await dependencies(db, portal_id=p["id"])
    dep_dir = await dependencies(db, directory_id=d["id"]) if d else None
    linked_both = bool(d and d.get("linked_patient_id") == p["id"] and p.get("matched_directory_id") == d["id"])
    can_link = cls in (SAFE_LINK, POSSIBLE) and not dep_portal["has_clinical"] and not linked_both
    return {
        "class": cls, "strength": strength, "evidence": ev, "other_portal": other,
        "portal": {**_portal_brief(p), **{k: p.get(k) for k in ["first_name", "middle_name", "last_name", "second_last_name", "sex", "email", "phone", "home_phone",
                                                                 "address", "unit", "city", "province", "postal_code", "country", "health_card_version",
                                                                 "health_card_issue_date", "health_card_expiry_date", "identity_outcome", "verified_at"]},
                   "health_card_number": p.get("health_card_number")},
        "canonical": ({**_dir_brief(d), **{k: d.get(k) for k in ["first_name", "last_name", "sex", "email", "cell_phone", "home_phone", "address", "unit", "city",
                                                                  "province", "postal_code", "country", "health_card_version_code", "health_card_issue_date",
                                                                  "health_card_expiry_date"]}, "health_card_number": d.get("health_card_number")} if d else None),
        "dependencies": {"portal": dep_portal, "canonical": dep_dir},
        "fields": compare_fields(d, p) if d else [],
        "link_state": "LINKED" if linked_both else ("HALF_LINK" if cls in (HALF_LINK,) else "UNLINKED"),
        "can_link": can_link,
        "can_repair": cls == HALF_LINK,
        "blocked_reason": (CLINICAL if dep_portal["has_clinical"] and cls in (SAFE_LINK, POSSIBLE, CLINICAL) else
                           cls if cls in (CONFLICT, MULTI_PORTAL, DIR_LINKED) else None),
    }


async def repair_half_link(db, p, d, user):
    pid, did = p["id"], d["id"]
    pside, dside = p.get("matched_directory_id") == did, d.get("linked_patient_id") == pid
    if pside and dside:
        return {"ok": True, "already_consistent": True}
    if not (pside or dside):
        raise ValueError("Not a half-link between these two records.")
    if d.get("linked_patient_id") and d["linked_patient_id"] != pid:
        raise ValueError("Directory record is linked to another portal account.")
    if p.get("matched_directory_id") and p["matched_directory_id"] != did:
        raise ValueError("Portal account is linked to another directory record.")
    other = await _other_portal_for_dir(db, did, pid)
    if other:
        raise ValueError("Another active portal account already points at this directory record.")
    ts = now_iso()
    pin = d.get("visita_patient_id")
    upd = {"matched_directory_id": did, "canonical_directory_id": did, "identity_linked": True,
           "identity_linked_by": user["name"], "identity_linked_at": ts, "updated_at": ts,
           "identity_cleanup": {"status": "linked", "linked_at": ts, "by": user["name"], "via": "half_link_repair"}}
    if pin:
        upd["visita_patient_id"] = pin
    await db.patient_directory.update_one({"id": did}, {"$set": {"linked_patient_id": pid, "updated_at": ts}})
    await db.patients.update_one({"id": pid}, {"$set": upd})
    await audit("identity_cleanup_half_link_repaired", "patient", pid, user,
                meta={"directory_id": did, "visita_patient_id": pin, "repaired_side": "directory" if pside else "portal",
                      "resulting_identity_state": "LINKED_EXISTING"})
    return {"ok": True, "visita_patient_id": pin}


def _apply_value(field, p, pfield):
    return _portal_val(p, field, pfield)


async def apply_fields(db, p, d, selections, confirm_identity_critical, user):
    """selections: [{field, action: USE_PORTAL|KEEP_CANONICAL}] — only USE_PORTAL mutates (directory only)."""
    pmap = dict(FIELDS)
    rows = {r["field"]: r for r in compare_fields(d, p)}
    applied, skipped = [], []
    sets = {}
    for sel in selections:
        f, act = sel.get("field"), sel.get("action")
        if f not in rows or act != "USE_PORTAL":
            skipped.append({"field": f, "reason": "no_change"})
            continue
        row = rows[f]
        if row["state"] in ("MATCH", "CANONICAL_ONLY", "EMPTY"):
            skipped.append({"field": f, "reason": row["state"]})
            continue
        if f in IDENTITY_CRITICAL and not confirm_identity_critical:
            skipped.append({"field": f, "reason": "IDENTITY_CRITICAL_CONFIRMATION_REQUIRED"})
            continue
        old = row["canonical"]
        if f == "name":
            new_first = given_names(p)
            new_last = family_names(p)
            sets.update({"first_name": new_first, "last_name": new_last,
                         "norm_first": dmod.norm_name(new_first), "norm_last": dmod.norm_name(new_last)})
            new = full_display_name(p)
        elif f == "date_of_birth":
            new = dmod.norm_dob(p.get("date_of_birth"))
            sets.update({"date_of_birth": new, "norm_dob": new})
        elif f == "health_card_number":
            new = p.get("health_card_number")
            sets.update({"health_card_number": new, "norm_hcn": dmod.norm_hcn(new)})
        else:
            new = _apply_value(f, p, pmap[f])
            sets[f] = new
        applied.append({"field": f, "old": old, "new": new})
    if sets:
        sets["updated_at"] = now_iso()
        await db.patient_directory.update_one({"id": d["id"]}, {"$set": sets})
        for a in applied:
            await audit("demographic_reconciled", "patient_directory", d["id"], user,
                        meta={"directory_id": d["id"], "portal_patient_id": p["id"], "field": a["field"],
                              "old_value": a["old"], "new_value": a["new"], "source": "PORTAL_REGISTRATION",
                              "identity_critical": a["field"] in IDENTITY_CRITICAL})
    return {"applied": applied, "skipped": skipped}
