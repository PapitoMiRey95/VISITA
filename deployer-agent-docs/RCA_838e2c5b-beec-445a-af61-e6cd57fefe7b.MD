# RCA — Production migration execution request (visita-admin)

## Request
User explicitly authorized WRITE execution of three backend migration scripts against the PRODUCTION MongoDB, in order, each dry-run → apply → read-only verify:
1. `migrate_practice_backfill.py` (create default `dr-aguayo` practice; stamp `practice_id` where missing)
2. `migrate_internal_user_practices.py` (assign `practice_id=dr-aguayo` to clinic-role users)
3. `migrate_relationships_backfill.py` (backfill `patient_provider_relationships`)

## Outcome: NOT EXECUTED — hard capability constraint
The deployer agent has **no tool that can write to production Mongo**:
- `mongo_query` is read-only by construction (find/count/distinct/list_collections/list_indexes only). It cannot run a Python script or any write.
- The eph sandbox (`spawn_eph_pod`/`run_in_eph_pod`) boots source at `/app/scratch` but injects **no production secrets** — no production `MONGO_URL`, so the scripts cannot reach production Atlas from there.
- No other write path exists in the agent surface.

The user's authorization is genuine and sufficient as consent; the blocker is purely that no write mechanism is available to this agent. Also note the preview/source environment's `MONGO_URL` points at local preview Mongo, not production — so running the scripts in preview would NOT hit the production DB either.

## Read-only production baseline captured (DB: visita-admin-test_database, active run 838e2c5b)
Confirms the migration has NOT yet been applied:
- `practices` collection: does NOT exist → `dr-aguayo` active default practice NOT present.
- `patient_provider_relationships` collection: does NOT exist → migration 3 not run.
- patients with practice_id: **0 / 55**.
- Baseline denominators (match spec): patients 55, appointment_requests 96, patient_applications 6, users 59.
- Target collections PRESENT: patients, appointment_requests, patient_applications, prescription_requests, imaging_requests, bloodwork_requests, patient_referrals, referrals, internal_messages, patient_messages.
- Target collections ABSENT in prod today: patient_updates, private_requests, invoices (plus practices, patient_provider_relationships to be created). Scripts should create/skip as designed, but flag before apply.

No data was modified. No PINs, pharmacy/partner/provider/organization data touched or read-for-write. All operations were counts/finds.

## Required path forward
Production write migrations must be executed by an operator/environment that has production write access + the production `MONGO_URL` (e.g. an Emergent-run one-off job / support-executed migration). This is outside both this agent's toolset and E1's preview environment. The three scripts are additive/idempotent and not wired into startup, so they can be run out-of-band safely following the dry-run→review→apply→verify protocol the user specified, with the HARD STOP conditions enforced by whoever executes.
