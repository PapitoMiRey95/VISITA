# VIen EMR — Changelog

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
