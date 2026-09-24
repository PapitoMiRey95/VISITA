"""Healthcare Organization (Partner) model helpers.

Organizations are external, partner-submitted healthcare entities (clinics,
hospitals, pharmacies, labs, etc.). They are a SEPARATE entity from providers/
doctors — an organization may have many providers and locations, and a provider
may later be affiliated with multiple organizations. Partner accounts can manage
ONLY their own organization profile and never touch patient PHI or clinic data.
"""

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


def norm_name(name: str) -> str:
    return "".join((name or "").lower().split())


def compute_completeness(o: dict) -> int:
    """Rough 0-100 profile-completeness score for the internal Organizations view."""
    checks = [
        o.get("address"),
        o.get("website") or o.get("fax"),
        o.get("description"),
        o.get("specialties"),
        o.get("services"),
        o.get("languages"),
        o.get("business_hours"),
        o.get("referral_instructions"),
        bool(o.get("providers")),
    ]
    filled = sum(1 for c in checks if c)
    return round(filled / len(checks) * 100)


def serialize_org(o: dict) -> dict:
    """Return a JSON-safe org dict (drops Mongo _id, adds completeness)."""
    d = {k: v for k, v in o.items() if k != "_id"}
    d["profile_completeness"] = compute_completeness(o)
    return d
