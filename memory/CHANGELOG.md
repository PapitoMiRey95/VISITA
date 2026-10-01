# VIen EMR — Changelog

## 2026-06 — Landing + patient login UX simplification (PREVIEW ONLY)
One universal entry point. Verified: testing_agent iteration_66 (15/15, 100% backend+frontend, zero issues) + curl + screenshots. NOT deployed to Production.

- **Landing (Landing.jsx rewritten)** — replaced the multiple large role cards with a single panel: prominent SEARCH ("Search clinic, physician, pharmacy or service…", uses existing GET /practices), a "Sign in" button, "Current patient? → Create Patient Portal" (/register), and "Looking for a family doctor? → Apply for care" (/register?new=1). Existing background/branding kept. Search result → /register/{slug}.
- **Sign-in role filter** — "Sign in" opens an inline "How do you use VIen?" step → Patient (/signin), Clinic/Staff (/signin?internal=1), Professional·Pharmacy·Health Partner (/signin?partner=1). No internal role names exposed; no cards on first screen.
- **Patient login wording (SignIn.jsx + i18n)** — title "Sign in as a patient", subtitle "For current patients"; bottom prompt "Current patient without a portal? → Create Patient Portal"; added subtle "Looking for a family doctor? → Apply for care". Google sign-in unchanged. Auth architecture untouched.
- **Apply for care — status in Canada (Register.jsx + backend)** — when OHIP = No, show "What is your current status in Canada?" with 8 options (Canadian citizen / Permanent resident / Work permit / Study permit / Visitor / Refugee or protected person / Other / Unsure or Prefer not to say). NOT labeled "migration status"; administrative-only, NEVER auto-blocks; OHIP coverage and status remain separate. Backend: one additive optional field `NewPatientRequestBody.status_in_canada`, stored on the application (coverage still derived independently). Create-Patient-Portal YES/NO routing (already-patient → portal vs Apply) unchanged.
- Generic /register remains search-only (no registration-code field); direct /register/{slug} + QR unchanged. i18n EN/ES/FR updated (landing2.*, signin.*, register.newPatient.status*).



## 2026-06 — Patient Portal: Smart Medication List + simplified refill (PREVIEW ONLY)
Separates the OFFICIAL, physician-controlled medication list from refill-request history. Verified: testing_agent iteration_65 (11/11 backend, frontend 100%, zero issues) + main-agent curl + screenshot.

- **"Your Medicines" (read-only)** — `GET /api/portal/medications` returns `{pharmacy_label, medications[]}` from the authoritative `patient_medications` (active, physician-confirmed only; populated solely by `_remember_patient_medications` when a physician SENDS a prescription). Patients can never add/edit/delete here. Delegate-aware (`portal_access(RX_REQUESTS)`).
- **Refill from the list** — `POST /api/portal/refill-requests` {medication_ids[], supply_type(standard|longer), requested_months, requested_supply_text, travel_note, patient_note}. Creates ONE `prescription_request` per selected med sharing one `batch_id` (keeps physician Rx queue single-med rendering 100% intact); authoritative drug/strength/directions are copied from `patient_medications` (never patient free-text). source=`patient_refill`.
- **Longer supply / travel** — 4/5/6/Other months + optional travel note + disclaimer. Remains `internal_status=received` (physician review; NEVER auto-approved).
- **Fixed v1 pharmacy** — destination = "1670 Dufferin Drug Mart" via `_refill_pharmacy_label` (reads `practices.default_pharmacy_name`, else the default constant). NO pharmacy picker / preferred-pharmacy field anywhere.
- **"I don't see my medicine" (photo review)** — `POST /api/portal/prescriptions/photo` (multipart file + optional name/note). source=`patient_photo`, review_required=true, image stored in object storage (reuses `_store_pharmacy_upload`), viewable by staff/physician at `/api/internal/prescriptions/{id}/attachment`. NEVER mutates `patient_medications` — only a physician-sent prescription can.
- **Status/notify** — send-rx link-back now advances ANY source request to `prescription_sent` and, for patient-origin requests, emits a no-PHI patient_update + in-portal notification + generic email ("Prescription sent to your pharmacy").
- **Delegate compatibility** — all three endpoints use `portal_access(RX_REQUESTS)`; `on_behalf_of` is server-verified and audited (acted_by=delegate, on_behalf_of=patient). Delegates get no medication-editing rights.
- **Frontend** — new shared `portal/MedicationRefill.jsx` (used by `PortalPrescriptions.jsx` self + `ManagedPortal.jsx` delegate), `PortalHome` "Your Medicines" card, i18n en/es/fr. Created requests carry `practice_id` so they appear in the scoped internal queue.
- NOT deployed to Production (awaiting approval). Seeded test meds: Maria (3), Linda (2, delegated to Maria w/ RX_REQUESTS).



## 2026-06 — Caregiver v1 final check + public link-preview branding (PREVIEW ONLY)
- **Non-patient caregiver (already supported, re-verified end-to-end)**: staff "Add access -> New caregiver" (name+email) creates a role=caregiver user with NO patient_id, NO patient record, NO PIN, must_change_password=true, one-time temp password; existing email is reused (no duplicate). Confirmed: caregiver logs in, sees only delegated patients (has_own_patient=false), managed summary honours only granted permissions, self-portal /portal/overview -> 403, action without permission -> 403. Existing-VIen-user path unchanged. No code changes were needed for Part 1.
- **Public link-preview branding**: `frontend/public/index.html` — replaced `<meta name="description" content="A product of emergent.sh">` with "Patient portal for appointments, prescription requests, and clinic communication."; title "VIen EMR" -> "Visita EMR Network"; added og:site_name/title/description/type/url (https://visitaemr.com/) + twitter:card/title/description. Verified rendered preview HTML contains new metadata and 0 occurrences of "A product of emergent.sh". Platform emergent-main.js script left untouched. No manifest.json exists. No routes/workflows/registration/isolation touched. (Production previews update only after the next deploy; WhatsApp/social caches may show old preview for a while.)


## 2026-06 — Family / Caregiver delegated portal access (v1) (PREVIEW ONLY)
A delegate uses their OWN login to act on behalf of a granted patient — no duplicate identities, no shared passwords, no impersonation. Verified: testing_agent iteration_64 (17/17 backend, frontend 100%, zero issues) + main-agent curl.

- **New collection `patient_portal_delegates`** + `backend/delegates.py` {id, patient_id, delegate_user_id, practice_id, relationship(+other), permissions[], active, granted_at/by, consent_type/note, revoked_at/by, created/updated}. Permissions: APPOINTMENTS, RX_REQUESTS, DOCUMENTS, REQUEST_STATUS.
- **`PortalCtx` + `portal_access(permission)` dependency**: no `on_behalf_of` ⇒ self (verified patient); with `on_behalf_of` (header X-On-Behalf-Of or query param) ⇒ enforce active grant + required permission + patient practice + verification, all server-side. Unauthorized/cross-practice ⇒ 404 (no existence leak); missing permission ⇒ 403.
- **Delegate-aware endpoints**: POST /portal/appointments (APPOINTMENTS), POST /portal/prescriptions (RX_REQUESTS), GET /portal/documents + download (DOCUMENTS). Reads: GET /portal/my-delegations, GET /portal/managed/{id}/summary (permission-filtered, patient-facing statuses only, released docs only).
- **Audit**: every delegated action records actor=delegate (id/name/role) + meta.on_behalf_of_patient_id + acted_by_user_id + delegate_relationship. Never attributed solely to the patient.
- **Staff/admin**: GET/POST /internal/patients/{id}/delegates, PATCH, POST .../{grant_id}/revoke (soft: active=false + revoked_at/by, history preserved, immediate access loss), GET /internal/user-search, POST /internal/caregivers (role=caregiver, no chart/PIN, temp password + must_change_password, reuses existing email), GET /internal/delegate-options.
- **Frontend**: internal `FamilyAccess.jsx` on the Patients record (list/add existing-or-new-caregiver/revoke); portal `ManagedPeople.jsx` (/portal/people), `ManagedPortal.jsx` (/portal/manage/:id with 'You are managing X's account' banner + Return to my account + permission-gated sections + fail-safe error), PortalHome 'People I help manage' card. /portal now allows roles patient + caregiver.
- Reused existing bcrypt/JWT auth (no new auth mechanism). NOT deployed to Production (awaiting approval).


## 2026-06 — Cleanup deploy: QR fail-safe + remove temporary migration endpoint
Bundled, cleanup-only (no new features, no schema, no migrations, no data cleanup). Preview rule-6 smoke passed (all logins + all internal queues 200).

- **QR fail-safe (rule 7)**: `RegistrationQR.jsx` no longer shows infinite "Loading…". `useQuery` retry:1/800ms; on error renders a clear "Practice context unavailable" card (`qr-error`) with a Retry button (`qr-retry`); `isLoading` spinner is bounded and ends on settle. Happy path unchanged (QR + copy/download/print).
- **Removed** `POST /api/internal/admin/run-stage-migrations` + MigrationRunBody + hmac import + the three migrate_* module imports from server.py (endpoint now 404 in preview). The migrate_*.py scripts remain in the repo as the canonical CLI migrations.
- Removed `MIGRATION_RUN_TOKEN` from preview backend/.env. Production secret to be removed/rotated by the user after live verification.
- Established `/app/memory/RELEASE_SAFETY_CHECKLIST.md` (mandatory pre-deploy checklist).


## 2026-06 — One-time maintenance endpoint to run Stage A/B/C migrations in Production
Root cause of the stuck QR ("Loading your practice…"): the three manual prod migrations never ran (deployer has no prod write path; preview MONGO_URL ≠ prod). Fix = a TEMPORARY, admin-only, token-gated endpoint that runs the exact three approved backfills using the app's own (production) DB connection.

- **`POST /api/internal/admin/run-stage-migrations`** (admin role + `MIGRATION_RUN_TOKEN`, `hmac.compare_digest`). Body `{token, dry_run}`. Runs ONLY practice_backfill → internal_user_practices → relationships_backfill, IN ORDER, stopping if any step's `ok` is false. NOT generic: no arbitrary scripts/collections/queries/shell. Returns safe summary counts only (no PHI/raw docs). Token never logged or echoed; 403 on missing/bad token.
- Refactored the three `migrate_*` scripts to expose importable `run(db, dry_run)` returning structured summaries (CLI `__main__` still works). relationships_backfill adds a duplicate-(practice,directory) detector → aborts (`ok:false`) if any duplicate canonical-identity rows exist.
- Safety preserved: additive, idempotent, never overwrites existing non-null practice_id, no deletes, no PIN changes, no FORMER_CLOSED cleanup, no pharmacy/partner/provider touch.
- Preview verified: staff→403, admin+bad token→403, dry-run 0 writes, apply idempotent (practice 0 / users 0 / relationships stable / dups 0).
- `MIGRATION_RUN_TOKEN` added to preview backend/.env (preview-only test value). Production value must be set in Production secrets. Endpoint + token to be REMOVED in a follow-up deploy after prod verification.


## 2026-06 — Professional Profile SIMPLIFICATION (PREVIEW ONLY)
Lightweight descriptive layer; core VIen (users→practices→patients→relationships→workflows) stays fully independent. Frontend-only + one backend doc comment. No schema change, no patient-care/RBAC/isolation change. Self-verified (UI screenshots + curl).

- **`ProfessionalEditor.jsx` split into Basics + collapsible "Optional professional details"**: Basics (always visible) = First name, Surname, Primary Specialty (single select over all specialties — "Family Medicine" selectable directly, no Sphere/Area needed), Credentials, Professional phone/fax/email, clinic/practice address. Optional (collapsed by default, `prof-optional-toggle`) = Second name, Sphere→Area, Registration #, Areas of Practice (97), Languages, Practice Type, Ontario model, Sex, Professorship, Accepting-patients. No fields deleted; progressive disclosure only.
- **Registration # hard block REMOVED**: previously forced when a taxonomy Area had `required:true`. Now always optional; shows a soft amber hint "Registration number recommended for this professional area." No backend requirement added.
- **Prefill on NEW profile only** (`buildPrefill` in `Professionals.jsx` via existing `GET /internal/my-practice`): suggests first/surname (from user name, honorific stripped) + professional phone + clinic address from the assigned practice. EDITABLE; never synced back; an EXISTING profile is never overwritten (prefill passed only when `selfProfile` is null).
- **Physician Hub dismissible reminder** (`Hub.jsx` `ProfileReminder`): neutral slate styling, shown only to physician/admin with no profile, "Complete your professional profile (optional)" + Set-it-up / dismiss (dismissal stored per-user in localStorage). No modal, no gate, no completion %.
- **Backend doc comment** (server.py PROFESSIONALS section): records the architecture boundary — core VIen independent of profiles, `vien_professional_*` = optional metadata, legacy Access tables = reference/future Referral Directory ONLY, no Access-ID reconciliation. Only `surname` required to save (unchanged).
- Preserved: `/professionals/me`, self/admin editing, editor grants, linked_user_id, audit history, organization affiliations, public contact fields, directory list/view, all taxonomy collections, existing saved profiles. Verified: physician with NO profile uses all patient-care workflows. NOT deployed.


## 2026-06 — Quick win: per-practice Registration QR (PREVIEW ONLY)
Effortless onboarding — each active practice gets a QR pointing at its own `/register/{slug}`. Reuses the Stage A slug/context model; NO new registration system. Self-verified (backend curl + UI screenshots, all 6 checkpoints).

- **Backend**: `GET /api/internal/my-practice` (CLINIC_ROLES) returns the caller's practice slug + display names + `register_path` ONLY — no internal ids, no registration_code. Patients/pharmacy/partner → 403.
- **Frontend**: new `internal/RegistrationQR.jsx` (route `/internal/registration-qr`, nav "Registration QR" for staff/physician/admin). Builds `${window.location.origin}/register/{slug}` (preview vs prod auto), renders a QRCodeCanvas, and offers Copy link / Download PNG / Print. Added `qrcode.react` (yarn). Print CSS in index.css isolates the QR card.
- **Scan flow (unchanged Stage A)**: QR → `/register/{slug}` auto-resolves practice → "You're registering with Dr. [Name]" → "Are you already a patient at this clinic?" Yes/No. No code, no physician search, no clinic selection.
- **Isolation**: each practice's QR encodes only its own slug; registration resolves+stamps strictly by slug, so a practice's QR can never register into another practice. Existing registration logic untouched. NOT deployed to Production.


## 2026-06 — Multi-physician Registration STAGE C: patient↔practice relationships (PREVIEW ONLY)
ONE global canonical patient identity (patient_directory + canonical PIN); per-practice relationship state lives separately in the NEW `patient_provider_relationships` collection. A patient can be active at one practice and applicant/former/inactive at another WITHOUT duplicate identities and with NO clinical-record merging. Verified: testing_agent iteration_63 (13/13 backend, frontend OK, zero product bugs) + my own curl/UI smoke.

- **New collection `patient_provider_relationships`** `{id(rel_*), practice_id, directory_id?, patient_id?, application_id?, visita_patient_id?, status, source, created_by, created_at, updated_at, history[]}`. Statuses: active | applicant | former | inactive. At most ONE row per (practice_id, canonical identity).
- **New module `backend/relationships.py`**: `upsert_relationship(...)` de-dupes by (practice_id, directory_id > patient_id > application_id), attaches newly-known anchors without clobbering, appends `history` ONLY on status change. `relationships_for_directory`, `relationship_for_patient`, `serialize`.
- **Wired into every flow** (server.py): register → active (ACTIVE_MATCH) else applicant; `/applications/new-patient` → applicant (by application_id); physician accept of new-patient application → applicant→active anchored to the single freshly-created canonical directory+PIN (history preserved); former_return accept → active; verify → active, reject → inactive; Identity Link `link-directory` → re-anchors relationship to canonical directory_id, preserves PIN, never creates a 2nd identity, 409 on cross-account.
- **New read endpoints**: `GET /api/internal/patients/{id}/relationship` (caller-practice, 404 cross-practice); `GET /api/internal/canonical/{directory_id}/relationships` → `{own: full, others: [{practice_name,status,label} ONLY — no PHI]}`. `/internal/verifications` + `/internal/identity-links` payloads now carry `relationship:{own,others}`; `/internal/identity-links` is now practice-scoped (pscope).
- **Frontend**: `Verifications.jsx` `RelationshipBadges` (testids relationship-badges/relationship-own/relationship-other) render "This practice: <status>" + other-practice status chips on Pending + Identity Link Review items.
- **Idempotent backfill** `backend/migrate_relationships_backfill.py` (dry-run supported) — ran in preview: 61 relationships (23 active, 38 applicant), all dr-aguayo; re-run = stable.
- **No re-establish regression**: FORMER_CLOSED register still returns `application_required` with NO account and NO relationship row (reference-only). NOT deployed to Production.


## 2026-06 — Stage B verification pass + isolation leak fixes (PREVIEW ONLY)
Independent verification (testing_agent iteration_62, 42/44) found cross-practice leaks that were NOT covered when pscope() was retrofitted. Fixed + re-verified (regression test_practice_isolation.py now 44/44).

- **HIGH — `GET /api/internal/counters`**: every `count_documents()` (physician + staff/admin branches) now merges `pscope(user)` so counters reflect ONLY the caller's practice (previously counted across all practices). Verified: seeding a foreign-practice rx no longer bumps the admin rx counter.
- **`GET /api/internal/referrals/history`** and **`GET /api/internal/verifications/history`**: added `pscope(user)` — faxed-referral and verified/rejected-patient history are now practice-scoped.
- **`internal_messages` (tasks/intercom) now carries `practice_id`**: stamped at all 4 insert points (create_task, private-request notify, private-request patient reply, invoice payment notify) and the `/internal/tasks` list + tasks/doctor_tasks counters now scope by it. Backfilled 56 existing internal_messages to the default `dr-aguayo` practice. Added `internal_messages` to `migrate_practice_backfill.py` WORKFLOW_COLLECTIONS (idempotent for other envs).
- **`GET /api/internal/directory`** intentionally LEFT unscoped — it is the canonical global patient directory; per-practice relationship state is Stage C's job (patient_provider_relationships).
- Regression test `backend/tests/test_practice_isolation.py` (seeds a synthetic Practice B, asserts list/counter/single-record 404 isolation, cleans up) corrected to mirror server `db.RX_ACTIVE`. Result: 44/44 pass. No Production changes.


## 2026-10-01 — Stage A tweak: New Patient Application fields (PREVIEW ONLY)
Applies to the New Patient Application (apply) form only; existing-patient registration unchanged. Verified via curl (fields stored, coverage derived) + UI render.

- **Full home address** added to the application: street, unit (optional), city, province, postal code, country (required except unit).
- **Coverage**: single "Do you have OHIP?" Yes/No → stored as `coverage` = `OHIP` / `PRIVATE_UNINSURED` (No). No Tourist/Visitor/Private choice shown to the patient.
- **Previous family doctor**: "Have you had a family doctor before?" Yes/No (`had_family_doctor`). If Yes → "Why are you looking for a new family doctor?" dropdown (retired / moved-relocated / moved area / clinic closed / no longer a patient / relationship ended / closer to home / Other); Other → optional free-text (`reason_other`).
- Backend `NewPatientRequestBody` + `/applications/new-patient` store the new fields; `_serialize_application` exposes them to internal staff. New-flow `YesNo` toggle component added. EN/ES i18n added.

Files: `backend/server.py`; `frontend/src/pages/Register.jsx`, `locales/{en,es}/auth.json`. Not deployed.

## 2026-10-01 — Stage A correction: removed former-patient / re-establish-care routing (PREVIEW ONLY)
Registration now keys off the CURRENT relationship with the resolved practice only. Verified via curl (FORMER→application, ACTIVE→verification, UNMATCHED→manual verification) + UI smoke.

- **`/auth/register` FORMER branch replaced**: a FORMER_CLOSED directory match no longer returns `former_detected`/re-establish. It now returns `{application_required: true, message_code: "APPLICATION_REQUIRED", prefill}` and creates NO account — the person is routed to the normal New Patient Application like any prospective patient.
- **ACTIVE** → unchanged (portal account + verification queue, `practice_id` stamped). **UNMATCHED self-declared** → unchanged (account + `UNMATCHED_CURRENT_PATIENT` manual verification). Coverage (OHIP/No-OHIP) unaffected.
- **`POST /applications/return-request`** marked **LEGACY/DORMANT** (docstring) — unreferenced by any UI, retained only so historical `former_return` applications stay processable. No new `former_return` records can be created from the patient journey.
- **Frontend `Register.jsx`**: removed the `former` notice step, the `reestablish` form, `submitReestablish`, and `former` state. `application_required` now routes to the apply form (step 99) with a neutral toast. No "Former Patient" / "Re-establish Care" patient-facing UI remains.
- **AuthContext**: `former_detected` → `application_required`.
- Legacy-but-dormant retained (document only, not reachable from new flow): `return-request` endpoint; internal Applications queue still renders historical `former_return` records + their acceptance path; seed templates `former_patient_detected` / `reestablish_care_confirmation` (unused); `directory.FORMER_MATCH` still used for *detection* (to route to application). No historical data deleted.

Production MONGO_URL note: Emergent support has **rotated** the exposed Production Mongo credential — rotation is **complete**, no longer a pending blocker.

## 2026-10-01 — Multi-physician Registration Stage A (PREVIEW ONLY, not deployed)
Care-ownership context model + simplified registration UX. Verified via curl (practice endpoints, context stamping, 404/400, idempotent migration, generic default) and UI smoke (slug route banner, Yes/No → OHIP, No → application, generic Find-your-clinic).

- **New `practices` collection** = care-ownership context: `{id, slug, registration_code, physician_user_id, physician_name, clinic_name, clinic_phone, clinic_address, active, is_default}`. Distinct from the referral `organizations`/`providers` registry (NOT reused for care ownership).
- **`practice_id` scope field** added to new patients/applications; `RegisterBody`/`ReturnRequestBody`/`NewPatientRequestBody` accept optional `practice_slug`/`practice_code`/`practice_id`.
- **Public resolution endpoints**: `GET /api/practices/{slug}`, `GET /api/practices/by-code/{code}`, `GET /api/practices?q=` (no secrets; registration_code never returned). `resolve_practice_for_registration` rejects an explicit-but-unknown context (400) and falls back to the single active practice when none supplied (existing `/register` behavior unchanged).
- **Explicit idempotent migration** `backend/migrate_practice_backfill.py` (`--dry-run` supported, NOT run at startup): created default `dr-aguayo` practice and stamped `practice_id` on 251 existing records across 12 workflow collections. Re-run = 0 changes.
- **Registration UX** (`Register.jsx`, route `/register/:practiceSlug`): link/QR auto-resolves practice → banner "You're registering with Dr. X" → "Are you already a patient at this clinic?" Yes/No → (Yes) "Do you have OHIP?" Yes/No → verify form; (No) → application. Generic `/register` → "Find your clinic" (code or search) fallback. Coverage (OHIP/No-OHIP→private) decoupled from status; tourist removed as a top-level path.

Files: `backend/server.py`, `backend/migrate_practice_backfill.py`; `frontend/src/pages/Register.jsx`, `frontend/src/App.js`, `locales/{en,es}/auth.json`. Stage B (server-side queue isolation) and Stage C (patient_provider_relationships) NOT yet built.

## 2026-10-01 — Patient Identity Linking + Secure Document Delivery (PREVIEW ONLY, not deployed)
Verified end-to-end: backend via curl (all 16 checkpoints), frontend via testing_agent iteration_61 (11/11, 100%, no bugs).

**PART 1 — Identity Link Review (internal, staff/admin)**
- `GET /api/internal/identity-links`: review queue of portal accounts that have directory candidates and are not yet linked (`identity_linked != true`).
- `POST /api/internal/patients/{id}/link-directory {directory_id}` (staff/admin): links a portal account to a canonical `patient_directory` record — preserves canonical PIN, sets `matched_directory_id`/`canonical_directory_id`/`identity_linked`, back-links `linked_patient_id`, audits `identity_linked`. 409 if the directory record is already linked to another account. No clinical merge, no demographic overwrite. Ambiguous = manual (explicit directory_id).
- UI: new "Identity Link Review" tab in `Verifications.jsx` with side-by-side compare, candidate quick-link, and a directory search to link any canonical record.

**PART 2 — Secure document delivery (generic event model, first via Imaging)**
- Attachments gain `shared_with_patient`/`shared_at`/`shared_by` + denormalized `patient_id`; internal uploads stay INTERNAL (badge) and invisible to patients.
- `POST /api/internal/attachments/{id}/share {complete}` (staff/physician/admin): releases ONE doc, creates a reusable `patient_updates` event, in-portal notification, GENERIC no-PHI Resend email (`document_available_html`), and completes the imaging request.
- Patient: `GET /api/portal/documents`, `GET /api/portal/documents/{id}/download` (server-side ownership → 404 for others), `POST /api/portal/updates/{id}/read`; overview now returns `updates` (unread) + `documents`.
- UI: "New update" card above Upcoming Appointment (`PortalHome.jsx`), persistent "Documents & Results" page (`PortalDocuments.jsx`, route `/portal/documents`, Home tile), view/download; doc persists after update read.
- Structured "Results / Document Request" action on Requests & Help (`PortalMessages.jsx`) via `POST /api/portal/document-requests` (fixed purposes, no free text) → flows into staff Message queue.

Files: `backend/server.py`, `backend/attachments.py`, `backend/email_service.py`; `frontend/src/internal/{Attachments,Verifications}.jsx`, `frontend/src/portal/{PortalHome,PortalMessages,PortalDocuments}.jsx`, `frontend/src/lib/api.js`, `frontend/src/App.js`, `locales/{en,es}/{portal,requests}.json`. NOT deployed to Production.

## 2026-10-01 — Patient Portal UX refinement (PREVIEW ONLY, not deployed)
Patient-facing UI/i18n only. No backend, appointment logic, or data changes.

- **Upcoming Appointment card** on Portal Home (top, below greeting): shows nearest future
  confirmed/rescheduled appointment (date, time, reason, status) with "View appointment";
  "View all appointments" when >1 future appt. No-appointment state shows "Request an appointment" CTA.
  Reuses `/portal/overview` appointments data (collection `appointment_requests`).
- **Removed general patient messaging**: `PortalMessages.jsx` refactored to structured actions only
  (Appointment, Prescription, New Referral, Referral Status, X-Ray/Ultrasound). Removed "Message for
  Doctor", "Other", and the free-text form/submit. Removed the "send a longer message" nudge from the
  appointment form (bypass pathway). Historical messages remain shown read-only. Backend
  `POST /portal/messages` endpoint untouched (not called from patient UI anymore).
- **Page renamed** "Message the Clinic" → "Requests & Help" (title + Home tile). Bottom-nav label
  "Messages" → "Help" (route `/portal/messages` unchanged, testid `nav-messages` kept).
- **Results & Follow-up** informational card added to Home with "Request an appointment" CTA.
- **Emergency warning** moved from top to bottom of Home (kept, less dominant).
- Home order: Greeting → Upcoming Appointment → service tiles → Results & Follow-up → Emergency warning.
- i18n: EN + ES updated (`portal.json`, `requests.json`). FR falls back to EN (no FR keys).

Files: `frontend/src/portal/PortalHome.jsx`, `PortalMessages.jsx`, `PortalLayout.jsx`,
`PortalAppointments.jsx`; `locales/{en,es}/portal.json`, `locales/{en,es}/requests.json`.

Verified in Preview (manual, mobile 430px): populated card = linda.nguyen@demo.com (nearest Oct 13 of 5),
no-appt state = maria.lopez@demo.com. All 15 user verification points pass. NOT deployed to Production.
