# Production Release Safety Check — MANDATORY before EVERY Production deploy
(Established by user, 2026-06. Applies to all future deploys including cleanup/removal deploys.)

Before any Production deploy, verify ALL:
1. Every new feature's Production dependencies exist.
2. Required migrations/backfills are identified in advance.
3. No feature goes live before its required migration/config exists.
4. No critical migration is silently expected to happen later.
5. No secrets/config required by the feature are missing.
6. Existing core workflows still pass PREVIEW smoke tests: login, patients, applications,
   verifications, appointments, Rx, imaging, bloodwork, referrals, counters.
7. New feature has a SAFE FALLBACK if a dependency is missing: clear unavailable/error
   state, NEVER infinite loading.
8. Run read-only PRODUCTION pre-checks before deploy.
9. Deploy code + required additive migrations as ONE coordinated rollout.
10. Run immediate PRODUCTION smoke test after deploy.

RULES:
- If any dependency is missing: STOP the deployment rather than ship a partially functional feature.
- Do NOT add new functionality during a Production rollout.

## Known gap surfaced by this policy (to fix)
- Registration QR page (`RegistrationQR.jsx`): when `GET /api/internal/my-practice` fails
  (e.g., practice context missing), the page sat on "Loading your practice…" indefinitely —
  violates rule 7 (no infinite loading). FIX: show a clear "practice context unavailable"
  state + retry, and disable retries hang. Bundle into the next follow-up deploy.

## Lesson learned (QR incident, 2026-06)
Code shipped before its required migrations ran in prod (migrations have no auto/startup
path). Result: empty `practices` + no `practice_id` → my-practice 404 → QR stuck loading.
Mitigation now in place: migrations are run via the one-time admin endpoint as part of the
SAME rollout window (rule 9), and features must fail safe (rule 7).
