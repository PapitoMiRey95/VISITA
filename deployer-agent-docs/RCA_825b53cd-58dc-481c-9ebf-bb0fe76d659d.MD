# Pre-Deploy Secret/Env Inspection — visita-admin

Scope: READ-ONLY pre-deploy check. No deploy, no secret writes performed.
Active (live) run inspected: `825b53cd-58dc-481c-9ebf-bb0fe76d659d` (redeploy, succeeded 2026-10-09 15:14:58Z).
Frontend: cloudflare. Tier: tier_0. URL: https://visita-admin.emergent.host (domains: visitaemr.com, www.visitaemr.com — both verified).

## CRITICAL FINDING
Both flags that must NOT be true in Production are currently TRUE in Production:
- ALLOW_DEMO_SEEDING  → present, value == "true"  (matches_expected:true)
- ALLOW_DATA_MIGRATIONS → present, value == "true" (matches_expected:true)

These are NOT false/absent. On next pod boot they would seed demo data / run data migrations.
Must be set to false (or removed) in Deployment Panel -> Secrets BEFORE deploying.

Also noted: PORTAL_AUTO_CONFIRM == "true" (truthy) — flagged in case unintended.

## Requested keys — presence / flag check (values never read)
- ALLOW_DEMO_SEEDING: PRESENT, = true  [SHOULD BE false/absent]
- ALLOW_DATA_MIGRATIONS: PRESENT, = true  [SHOULD BE false/absent]
- RUN_DISABLE_DEMO_ACCOUNTS_V1: ABSENT
- MAINTENANCE_TOKEN: PRESENT (non-empty)
- APP_BASE_URL: PRESENT (non-empty)
- ENCOUNTER_PILOT_USERS: ABSENT
- CORS_ORIGINS: PRESENT (non-empty)
- PORTAL_AUTO_CONFIRM: PRESENT, = true
- RESEND_API_KEY: PRESENT (non-empty)
- JWT_SECRET: PRESENT (non-empty)
- MONGO_URL: PRESENT (system key)
- DB_NAME: PRESENT (system key)
- ADMIN_EMAIL: PRESENT (non-empty)
- PHYSICIAN_USERNAME: PRESENT (non-empty)
- PHARMACY_USERNAME: PRESENT (non-empty)
- WEBHOOK_CRON_SECRET: PRESENT (non-empty)

## Full list of configured Production secret/env NAMES (35)
ADMIN_EMAIL, ADMIN_PASSWORD, ALLOW_DATA_MIGRATIONS, ALLOW_DEMO_SEEDING, APP_BASE_URL,
CORS_ORIGINS, DB_NAME, EMAIL_FROM_NAME, EMAIL_REPLY_TO, EMERGENT_EMAIL_KEY, EMERGENT_LLM_KEY,
ENABLE_HEALTH_CHECK, INTEGRATION_PROXY_URL, JWT_SECRET, MAINTENANCE_TOKEN, MIGRATION_RUN_TOKEN,
MONGO_URL, PHARMACY_ID, PHARMACY_NAME, PHARMACY_PASSWORD, PHARMACY_USERNAME,
PHYSICIAN_TEMP_PASSWORD, PHYSICIAN_USERNAME, PORTAL_AUTO_CONFIRM, REACT_APP_BACKEND_URL,
RESEND_API_KEY, TEST_ADMIN_PASSWORD, TEST_PATIENT_PASSWORD, TEST_PHYSICIAN_PASSWORD,
TEST_STAFF_PASSWORD, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER,
WDS_SOCKET_PORT, WEBHOOK_CRON_SECRET

## Release identifier & rollback
- Current deployed release = image tag / run id `825b53cd-58dc-481c-9ebf-bb0fe76d659d`. No git commit hash exposed via tooling.
- Rollback available: YES. Prior successful release image retained: `0dfd1a93-a804-48f0-85d8-c7e74acc3ac6` (2026-10-08 21:01:07Z); older: `073c419e...`, `b60be223...`.
- CAVEAT: rollback reuses the old IMAGE but env/secrets are re-composed from CURRENT Production secret rows at deploy time. A rollback will NOT flip ALLOW_DEMO_SEEDING / ALLOW_DATA_MIGRATIONS to false — those must be corrected in the Secrets tab regardless.

## Does the pipeline copy Preview .env into Production for keys MISSING in Production?
YES — for CUSTOM keys, additively:
- First deploy: custom secrets seeded from Preview pod .env.
- Subsequent deploys: custom secrets carried forward from previous PRODUCTION run. Preview .env ONLY ADDS keys not already present in Production; it NEVER overwrites a key already set in Production.
- SYSTEM keys (MONGO_URL, DB_NAME, REACT_APP_BACKEND_URL, INTEGRATION_PROXY_URL, STRIPE_*, EMERGENT_PUSH_KEY) are always regenerated and overwrite.

Implications:
- ALLOW_DEMO_SEEDING / ALLOW_DATA_MIGRATIONS already EXIST in Production (=true), so Preview .env will NOT overwrite them. They stay true across redeploys until changed manually in Secrets. Preview .env values are not the cause; the Production rows are independently true.
- RUN_DISABLE_DEMO_ACCOUNTS_V1 and ENCOUNTER_PILOT_USERS are ABSENT in Production. If present in Preview .env, they WILL be added to Production from Preview on the next deploy. Decide intended Production values first.

## Required user actions before deploy
1. In Deployment Panel -> Secrets, set ALLOW_DEMO_SEEDING=false and ALLOW_DATA_MIGRATIONS=false (or delete them). Verify PORTAL_AUTO_CONFIRM is intentionally true.
2. Decide intended Production values for RUN_DISABLE_DEMO_ACCOUNTS_V1 and ENCOUNTER_PILOT_USERS before deploying, since missing keys get pulled from Preview .env.
