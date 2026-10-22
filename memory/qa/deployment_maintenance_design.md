# Deployment & Maintenance experience — design proposal (PREVIEW-only, awaiting GO)

Mockups (static, in Preview only): `/mockups/ops-deployment.html`, `/mockups/patient-states.html` (frontend/public; removed after implementation).

## Model — extend `system_state` (not a new system)
```
system_state.global.deployment = {
  state: NORMAL | UPDATING | MAINTENANCE | SERVICE_ISSUE,
  mode:  SOFT | FULL | null,                 # FULL == existing maintenance.on
  since, by (actor_label), note,
  verification: { required: 3, streak: 0, last_check_at, last_ok_at, deadline_at, checks: [..last 10] },
  build: { release_commit (RELEASE_INFO), bundle_hash (parsed from served index.html), tier (env RESOURCE_TIER or operator-set) },
}
deployment_history (new collection, append-only): { id, started_at, completed_at, kind, mode, operator, result: SUCCEEDED|RECOVERED|FAILED|ROLLED_BACK, build_from, build_to, verification_summary, note }
```
Existing `announcement` (Global message) and `maintenance` stay as-is. Derivation rules in `system_state.public_view`:
- UPDATING / SERVICE_ISSUE → a *managed* notice is emitted (`notice.kind = UPDATE|ISSUE`) that the client renders **above** any manual announcement; manual announcement is not deleted, just lower priority.
- MAINTENANCE ↔ `maintenance.on` (one source of truth; `set_maintenance` also sets `deployment.state`).

## State machine (backend `system_state.py`)
- `begin_update(user, note)`: NORMAL|SERVICE_ISSUE → UPDATING (mode SOFT), opens a `deployment_history` row, resets streak, deadline = now + 20 min.
- `verify()` (called by cron every 1 min in `.emergent/crons.yml` + on-demand button): runs the same probes as `/developer/status` (ping, bootstrap steps, storage) + compares `RELEASE_INFO.commit` to the one recorded at `begin_update` (new pod == new commit). ok → streak+1; 3 consecutive ok → NORMAL, history row SUCCEEDED (RECOVERED if it passed through SERVICE_ISSUE). fail → streak 0; past deadline or 3 consecutive failures → SERVICE_ISSUE (notice stays, copy switches to the outage text).
- `enter_full_maintenance(confirm "ENTER")` / `exit(confirm "EXIT")` — reuse existing endpoint; adds history row kind=FULL.
- `resolve_issue(user)`: SERVICE_ISSUE → NORMAL manual override (typed confirm), audited.
- All transitions audited (`deployment_state_changed`), developer_ops only; nothing reads/writes clinical collections.

## Endpoints
- `GET /api/system/banner` (public) — adds `notice {kind, message}` + `state`. Client already polls it every 30 s.
- `GET /api/developer/deployment` — state, verification, build, history(20).
- `POST /api/developer/deployment/begin-update`, `/verify`, `/resolve`, `POST /api/developer/deployment/build-info {tier}` (operator-entered tier; the platform does not expose tier/deploy status to the app — see limits).
- `POST /api/cron/deployment-verify` (platform cron, 1 min, token-guarded like refill-reminders).

## Frontend
- Control Center OPERATIONS tab → "Deployment & Maintenance" as mocked: state strip + actions, Production build card, Readiness card (verification streak), Global message + user-facing preview (managed notice vs manual), Recent deployments table. Existing MaintenanceMode + Announcement cards are folded into this layout (same components, moved).
- `SystemStatus.jsx`: `AnnouncementBar` renders the managed notice first (navy, calm, no icon noise); `MaintenanceScreen` restyled to the branded navy screen with Retry + auto-poll (already polls every 30 s) + emergency line from clinic profile.
- Friendly outage fallback: axios response interceptor flags 502/503/504/52x/network-error → `OutageCard` rendered by a small `<OutageBoundary>` inside Portal/Internal layouts (shell stays mounted, unsaved form state kept; Retry re-runs the failed queries; auto-retry 20 s). React `ErrorBoundary` also maps chunk-load failures to the same card.
- Copy (en/es/fr): UPDATE "VIen is being updated. Some services may be briefly unavailable. Please try again if something does not load." · ISSUE/FULL "VIen is temporarily unavailable. We're completing a brief system update. Please try again shortly." No "under development" language anywhere.

## Operator workflow (soft deploy)
1. Control Center → Begin Soft Update (note = what ships). Banner goes live within 30 s.
2. Trigger the platform deploy (Emergent panel / agent).
3. New pod comes up with new commit → cron verify passes 3× → NORMAL automatically, banner removed, history row SUCCEEDED with timings.
4. If the pod never becomes healthy within 20 min → SERVICE_ISSUE; banner switches to the outage copy; operator decides rollback (platform) → `resolve` when healthy.

## Honest limits
- Build hash, deploy start/finish and result are recorded by VIen itself (begin-update + verification), not read from the Emergent pipeline (no API exposed to the app). Resource tier is operator-entered/env, not auto-detected.
- Origin-down (pod fully gone) means the SPA itself may not load; the in-app card covers API failures and chunk failures. Replacing the raw Cloudflare/origin error page for a cold navigation requires a Cloudflare Custom Error Page / Worker on the domain (outside the app), or a service-worker cached fallback (`/offline.html` with the same copy) — proposed as Phase 3, optional.
- Full Maintenance keeps today's semantics: 503 for non-operator API calls via the existing middleware; reads are not selectively allowed (would need a write-only guard — can be added later).

## Phases
- Phase 1 (backend + Control Center UI + managed banner + branded maintenance screen + cron verify): ~1 session; testing_agent full-stack.
- Phase 2 (outage card/interceptor/error boundary, i18n): small.
- Phase 3 (SW offline fallback / Cloudflare page guidance): optional.
Production GO separate; Phase 1+2 ship together.
