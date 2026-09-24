"""STAGED Production admin action — disable demo/test accounts (SECURITY REMEDIATION).

SAFETY CONTRACT (do not weaken):
- Sets `active=false` ONLY. Never hard-deletes, never edits passwords, never edits any
  other user field or any related/workflow/audit record.
- Operates ONLY on the explicit ALLOWLIST below (exact emails). Never pattern-wide.
- Skips anything in KEEP_SET, skips already-inactive users, skips non staff/patient roles.
- DRY-RUN by default. Executes only when env CONFIRM_DISABLE == "GO-DISABLE-APPROVED".
- Records disabled_by / disabled_at / disabled_reason and writes one audit_logs entry.

Run (deployer, Production, after explicit human GO):
    CONFIRM_DISABLE=GO-DISABLE-APPROVED python -m ops.disable_demo_accounts
Dry-run (default, safe preview of intended changes):
    python -m ops.disable_demo_accounts
"""
import os
import asyncio
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from motor.motor_asyncio import AsyncIOMotorClient

# Exact, explicitly-approved demo/test accounts (staff + patients). No wildcards.
ALLOWLIST = [
    "staff@visita.demo",
    "maria.lopez@demo.com",
    "john.smith@demo.com",
    "carlos.perez@demo.com",
    "linda.nguyen@demo.com",
    "ahmed.khan@demo.com",
    "sofia.martinez@demo.com",
    "robert.chen@demo.com",
    "test_p2_222d90dd@demo.com",
    "test_p2_27c02446@demo.com",
    "test_p2_1d758b99@demo.com",
    "test_p2_a1e3492b@demo.com",
    "test_reg_51cdbed7@demo.com",
]

# Never touch these regardless of ALLOWLIST (real / pending-clarification accounts).
KEEP_SET = {
    "kevinrodriguez9528@gmail.com",   # real owner/admin
    "jorgemessi6426@gmail.com",       # UNKNOWN — pending clarification
    "waglucio50@gmail.com",           # real patient, pending activation
}

ALLOWED_ROLES = {"staff", "patient"}
REASON = "security-remediation: demo/test account deactivation (source-known credentials)"
CONFIRM_TOKEN = "GO-DISABLE-APPROVED"


async def main():
    confirmed = os.environ.get("CONFIRM_DISABLE", "").strip() == CONFIRM_TOKEN
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    planned, skipped = [], []
    try:
        for email in ALLOWLIST:
            e = email.lower()
            if e in KEEP_SET:
                skipped.append((e, "in KEEP_SET")); continue
            u = await db.users.find_one({"email": e}, {"_id": 1, "role": 1, "active": 1, "name": 1})
            if not u:
                skipped.append((e, "not found")); continue
            if u.get("role") not in ALLOWED_ROLES:
                skipped.append((e, f"role={u.get('role')} not allowed")); continue
            if u.get("active") is False:
                skipped.append((e, "already inactive")); continue
            planned.append((e, u["_id"], u.get("role")))

        print(f"[{'EXECUTE' if confirmed else 'DRY-RUN'}] targets={len(planned)} skipped={len(skipped)}")
        for e, _id, role in planned:
            print(f"  DISABLE  {e}  (role={role})")
        for e, why in skipped:
            print(f"  SKIP     {e}  ({why})")

        if not confirmed:
            print("DRY-RUN only. Re-run with CONFIRM_DISABLE=GO-DISABLE-APPROVED to apply.")
            return

        for e, _id, role in planned:
            await db.users.update_one({"_id": _id, "active": {"$ne": False}}, {"$set": {
                "active": False,
                "disabled_by": "security-remediation",
                "disabled_at": now,
                "disabled_reason": REASON,
            }})
            await db.audit_logs.insert_one({
                "action": "account_disabled", "entity": "user", "entity_id": str(_id),
                "actor": {"id": None, "name": "security-remediation", "role": "system"},
                "meta": {"email": e, "role": role, "reason": REASON}, "at": now,
            })
            print(f"  DISABLED {e}")
        print(f"Done. Disabled {len(planned)} account(s). No passwords/records deleted.")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
