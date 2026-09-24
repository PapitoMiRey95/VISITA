"""Healthcare Organization (Partner) model helpers.

Organizations are external, partner-submitted healthcare entities (clinics,
hospitals, pharmacies, labs, etc.). They are a SEPARATE entity from providers/
doctors — an organization may have many providers and locations, and a provider
may later be affiliated with multiple organizations. Partner accounts can manage
ONLY their own organization profile and never touch patient PHI or clinic data.
"""
import uuid

# Stable organization-type taxonomy (stored verbatim; used for later filtering).
# NOTE: a Doctor/Provider is NOT an organization type — providers are separate.
ORG_TYPES = [
    "Family / Primary Care Clinic",
    "Specialist Clinic",
    "Hospital / Hospital Department",
    "Solo Physician Practice",
    "Pharmacy",
    "Diagnostic Imaging",
    "Laboratory",
    "Allied Health",
    "Other Healthcare Organization",
]

VERIFICATION_STATUSES = ("UNVERIFIED", "VERIFIED", "FLAGGED", "SUSPENDED")


def ensure_ids(items, prefix):
    """Assign a stable internal id to each dict item that lacks one."""
    out = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        d = dict(it)
        if not d.get("id"):
            d["id"] = f"{prefix}_{uuid.uuid4().hex[:8]}"
        out.append(d)
    return out


def norm_name(name: str) -> str:
    return "".join((name or "").lower().split())


def compute_completeness(o: dict) -> int:
    """Rough 0-100 profile-completeness score for the internal Organizations view."""
    checks = [
        o.get("address") or o.get("locations"),
        o.get("website") or o.get("fax"),
        o.get("description"),
        o.get("specialties"),
        o.get("services"),
        o.get("languages"),
        o.get("business_hours") or o.get("locations"),
        o.get("referral_instructions"),
        bool(o.get("providers")),
        bool(o.get("photos")),
    ]
    filled = sum(1 for c in checks if c)
    return round(filled / len(checks) * 100)


def build_provider_view(provider: dict, orgs: list) -> dict:
    """Resolve a global provider record into an internal read-only view showing
    every organization it is affiliated with and the locations linked at each.
    `orgs` is the full list of organization docs (already loaded once by caller)."""
    pid = provider.get("id")
    affiliations = []
    created_by_name = None
    for o in (orgs or []):
        if o.get("id") == provider.get("created_by_org_id"):
            created_by_name = o.get("organization_name")
        loc_by_id = {l.get("id"): l for l in (o.get("locations") or []) if isinstance(l, dict)}
        for aff in (o.get("providers") or []):
            if not isinstance(aff, dict):
                continue
            if (aff.get("provider_id") or aff.get("id")) != pid:
                continue
            locs = []
            for lid in (aff.get("location_ids") or []):
                loc = loc_by_id.get(lid)
                if loc:
                    label = (loc.get("label") or loc.get("address") or "").strip() or "Location"
                    where = ", ".join([s for s in [loc.get("city"), loc.get("province")] if s])
                    locs.append({"id": lid, "label": label, "where": where})
            affiliations.append({
                "organization_id": o.get("id"),
                "organization_name": o.get("organization_name"),
                "organization_type": o.get("organization_type"),
                "locations": locs,
            })
    return {
        "id": pid,
        "name": provider.get("name"),
        "specialties": provider.get("specialties") or "",
        "created_by_org_id": provider.get("created_by_org_id"),
        "created_by_org_name": created_by_name,
        "affiliations": affiliations,
    }


def serialize_org(o: dict) -> dict:
    """Return a JSON-safe org dict (drops Mongo _id, adds completeness)."""
    d = {k: v for k, v in o.items() if k != "_id"}
    d["profile_completeness"] = compute_completeness(o)
    return d
