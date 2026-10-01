# Production Rollout Plan — Multi-Practice Registration / Relationships / Isolation + QR
STATUS: PREVIEW-ONLY PLAN — NOT YET APPROVED, NOT DEPLOYED. For user approval.

Scope of this package: Stage A (practice context + context-aware registration), Stage B
(server-side practice_id isolation), Stage C (patient_provider_relationships), and the
per-practice Registration QR. FORMER_CLOSED data cleanup is explicitly OUT OF SCOPE here.

## 1. Exact idempotent migrations required (run in PRODUCTION runtime, in order)
All three are standalone CLI scripts, additive, idempotent, support `--dry-run`, and are
NOT wired into startup. They connect via MONGO_URL/DB_NAME of the environment they run in,
so they MUST be executed inside the Production runtime (deployer/ops exec), never from preview.

1. `backend/migrate_practice_backfill.py`
   - Creates the default practice `{slug: dr-aguayo, registration_code: AGUAYO, is_default:true, active:true}` IF MISSING (physician_name/clinic_* pulled from settings/physician user).
   - Stamps `practice_id` (+ `practice_backfilled_at`) on records MISSING it across the workflow collections.
2. `backend/migrate_internal_user_practices.py`
   - Assigns `practice_id = dr-aguayo` to staff/physician/admin users MISSING it. Aborts with a clear message if the default practice doesn't exist (run step 1 first).
3. `backend/migrate_relationships_backfill.py`
   - Derives one `patient_provider_relationships` row per active portal patient and per OPEN application (see §4).

Each supports: `python <script>.py --dry-run` (report only) then `python <script>.py` (apply).

## 2. Exact collections affected
- CREATED/UPSERTED: `practices` (1 default doc if missing), `patient_provider_relationships` (new).
- FIELD ADDED (`practice_id`, additive, only where missing) in: patients, patient_applications,
  appointment_requests, prescription_requests, imaging_requests, bloodwork_requests,
  patient_referrals, referrals, patient_updates, patient_messages, internal_messages,
  private_requests, invoices.
- FIELD ADDED (`practice_id`) on: users (staff/physician/admin only; patients/pharmacy/partner untouched).
- NO collection is dropped, cleared, or re-keyed. NO documents deleted. NO existing `practice_id` overwritten.

## 3. Expected backfill behavior
- practice backfill: creates 1 practice (if absent); stamps every workflow record lacking practice_id → dr-aguayo. Re-run = 0 changes.
- internal-user backfill: stamps internal users lacking practice_id → dr-aguayo. Re-run = 0 changes.
- relationships backfill: for each active patient → status `active` if verified/portal-active, `inactive` if rejected, else `applicant`; anchored to matched_directory_id (if any) + patient_id + PIN. For each OPEN application (REQUEST_RECEIVED/WAITING_LIST/UNDER_REVIEW/SENT_TO_PHYSICIAN) → `applicant` keyed by application_id. De-dupes to ONE row per (practice, canonical identity). Re-run = stable count.
- Preview reference run: 61 relationships (23 active / 38 applicant), all dr-aguayo; re-run stable.

## 4. Confirmation — nothing runs automatically at startup
- `@app.on_event("startup")` does ONLY: create indexes, init storage, call `seed_all`.
- `seed_all`: real-PHI directory import + appt_v2 are gated behind `_migrations_enabled()` (env `ALLOW_DATA_MIGRATIONS`) AND `app_meta` one-time markers (directory_v1 / appt_v2). Demo seeding is gated by its own flag + `seeded_v1` marker.
- The THREE Stage A/B/C migration scripts are NOT referenced anywhere in startup/seed (verified by grep). They only run when invoked manually.

## 5. Order of operations
0. Snapshot/backup the Production MongoDB. Confirm backup restorable.
1. Pre-check (read-only against prod): does `practices` exist? any patients missing practice_id? count relationships (should be 0).
2. Deploy the code build (backend + frontend) for Stages A–C + QR.
   - IMPORTANT: new registrations resolve the practice by slug/default; if `practices` is empty, registration returns 400. So run step 3 immediately at/with deploy.
3. Run `migrate_practice_backfill.py --dry-run` → review → apply.
4. Run `migrate_internal_user_practices.py --dry-run` → review → apply.
5. Run `migrate_relationships_backfill.py --dry-run` → review → apply.
6. Set/confirm prod env `APP_BASE_URL=https://visitaemr.com` (activation email links).
7. Run the smoke-test checklist (§8). If any fail → rollback (§6).

## 6. Rollback / safety considerations
- All migrations additive & idempotent → re-running is safe; partial runs resume cleanly.
- Code rollback = redeploy previous build. The added field (`practice_id`), the `practices`
  collection, the `patient_provider_relationships` collection, and the `/internal/my-practice`
  route are INERT to older code (old code ignores them) → no data corruption on downgrade.
- No destructive operation exists in this package, so "data rollback" is normally unnecessary;
  the DB snapshot from step 0 is the ultimate fallback.
- If the practice doc is created with wrong display fields, it can be edited in place (Settings/DB)
  without touching scoping (scoping keys off the stable practice id).

## 7. Protected records / special cases
- Patient Aracely Izao (VISITA PIN 3040): protected. This package performs NO deletion, so 3040
  is inherently untouched. (FORMER_CLOSED cleanup — which would delete — is NOT part of this rollout.)
- Real owner `kevinrodriguez9528@gmail.com` + real staff/physician: only receive an additive practice_id.
- Production pharmacy account (1670dufferin) and partner/organization/provider data: untouched.
- Existing `visita_pins` / canonical PINs: never changed or retired by these migrations.
- FORMER_CLOSED directory rows: left as reference-only; not reactivated, not deleted, no relationship created from the register path.

## 8. Smoke-test checklist (read-mostly on Production, post-migration)
QR registration:
- [ ] `GET /api/internal/my-practice` (staff token) → slug=dr-aguayo, correct names, NO internal id/code. Patient token → 403.
- [ ] Visiting `/register/dr-aguayo` shows "You're registering with Dr. Pablo Aguayo" + Yes/No, no code entry.
- [ ] Internal "Registration QR" page renders QR + link `https://visitaemr.com/register/dr-aguayo` + Copy/Download/Print.

Practice isolation:
- [ ] `GET /api/internal/counters` and each queue (rx/imaging/bloodwork/messages/appointments/referrals/verifications/applications/tasks) return ONLY dr-aguayo-scoped data.
- [ ] Cross-practice single-record fetch/patch returns 404 (anti-enumeration) — structurally verified; prod has one practice.

Patient-provider relationships:
- [ ] A verified patient has a `patient_provider_relationships` row status=active (anchored to directory_id + PIN).
- [ ] An OPEN application has an applicant row; accepting it (physician) transitions SAME row applicant→active with history, creating exactly ONE canonical directory record.

Identity Link:
- [ ] Identity Link Review queue loads (practice-scoped), linking preserves canonical PIN, 409 if the directory record is already linked elsewhere, and creates NO second canonical identity.

Former / re-establish disabled:
- [ ] `/auth/register` with a FORMER_CLOSED directory match returns `{application_required:true}` (no account, no re-establish route, no relationship row). (Requires prod patient_directory loaded.)

No clinical record merging:
- [ ] Linking/verifying never copies clinical data between records; only identity anchors + PIN are set.

No cross-practice data leakage:
- [ ] `GET /api/internal/canonical/{directory_id}/relationships` → `others[]` exposes practice_name + status ONLY (no patient_id/name/dob/phone/email/PIN/HCN).

## 9. Known dependency / flag
- Production `patient_directory` population (real PHI directory import) is a SEPARATE, still-blocked item (Issue 1). ACTIVE_MATCH on registration and the FORMER_CLOSED smoke check depend on it. The Stage A/B/C migrations themselves do NOT require the directory to be present (they key off patients/applications/users).
