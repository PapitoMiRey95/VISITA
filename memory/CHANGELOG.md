# VIen EMR — Changelog

## 2026-06 — Smart Medication Search for Prescription Requests (patient + caregiver) (PREVIEW ONLY, NOT DEPLOYED)
### Existing infra reused
- `medication_catalog` (generic `drug`, `catalog_key`) and `patient_medications` (physician-confirmed per patient); the shared `MedicationRefill` component (already delegate-aware via `on_behalf_of`); the existing `prescription_requests` queue/statuses (received → ...); `portal_access(RX_REQUESTS)` for caregiver authorization + audit.
### Backend (server.py)
- `GET /portal/medication-search?q=` (`portal_access(RX_REQUESTS)`): type-ahead from the first char. Ranking: (1) effective patient's physician-confirmed meds (prefix first, tagged source=patient), (2) catalog matches on generic/brand/aliases (prefix first). HARD max 5 enforced server-side. Patient-specific results come ONLY from the effective (own/managed) patient.
- `POST /portal/prescription-requests` (`portal_access(RX_REQUESTS)`): creates a normal `prescription_requests` doc (status `received`, source `patient_request`) with `medication_name` preserved EXACTLY, `medication_entry_source` = CATALOG|MANUAL, `requires_medication_review` = true for MANUAL. Stamps patient_id/practice_id of the effective patient + delegate audit (acted_by/on_behalf_of). NEVER writes patient_medications or medication_catalog; never auto-approves.
- Catalog seed `backend/seed_med_catalog.py` — idempotent/additive (upsert by `search:` key), ~64 common Family-Med meds with generic + brand + alias `search_terms`. Does not delete/overwrite existing rows.
### Frontend
- ONE shared `RequestDifferentMedication` inside `MedicationRefill.jsx` (used by both patient self and caregiver managed): debounced type-ahead (≤5 options, "YOUR MED" tag for the patient's own meds), "I can't find my medication" → exact free-text entry, submits to `/portal/prescription-requests` with the managed `on_behalf_of` param. Large mobile touch targets, no horizontal overflow.
- `internal/RxQueue.jsx`: physician/staff queue + detail now show a prominent "MANUAL ENTRY — REVIEW REQUIRED" badge when `medication_entry_source==="MANUAL"`.
### Verified in Preview (API + mobile UI)
- Search from 1st char; "A"/"Am"/"Aml" narrow correctly; never >5; generic ("Aml") + brand ("Tylenol", "ozempic") both match; Linda's confirmed Amlodipine ranked first (source=patient). Caregiver catalog request → patient_id=managed, practice_id set, source=patient_request, entry=CATALOG, review=false. Manual "Acetominofen 500" preserved verbatim, entry=MANUAL, review=true, appears in queue with manual badge, patient=Linda. No catalog/patient_medications side-effects. Security: cross-patient → 404, caregiver without RX_REQUESTS → 403 (search + request). Patient self search returns ≤5. Existing refill/photo/pharmacy/physician Rx flows untouched. Mobile layout verified.


## 2026-06 — Caregiver portal reuses the real Patient Portal (effectivePatient) + Health Card pending-review (PREVIEW ONLY, NOT DEPLOYED)
### Architecture — reuse, not duplicate
- Managed-patient mode is now the REAL Patient Portal scoped to the managed patient via an `X-On-Behalf-Of` header (module-level `setOnBehalfOf` in `lib/api.js` + request interceptor) that the backend `portal_access` dependency already enforces (active grant + permission + practice + verification).
- `PortalLayout.jsx` is managed-aware (URL `/portal/manage/:patientId`): sets the header synchronously, scopes the overview query, shows the persistent banner "You are managing {name}'s account · {relationship}" + "Return to my account", and renders permission-gated bottom nav (Home/Appts/Rx/Results/Requests/Health Card). `managed` is URL-driven (not data-driven) so the caregiver guard never redirects mid-load.
- Routes: `/portal/manage/:patientId` now nests the SAME pages — `PortalHome` (managed branch), `PortalAppointments`, `PortalPrescriptions` (+ `MedicationRefill`), `PortalDocuments`, `PortalMyRequests`, and new `PortalHealthCard`. Pages thread a `base` path from `usePortal()` for internal navigation.
- REMOVED the duplicate simplified caregiver UI: `portal/ManagedPortal.jsx` (and its inline simplified ApptForm). `ManagedPeople` now opens the real managed portal.
### Backend (server.py)
- `/portal/overview` → `portal_access()`; adds a `delegate` block `{is_delegate, patient_name, relationship, permissions}` and gates every section by permission (APPOINTMENTS/RX_REQUESTS/DOCUMENTS/REQUEST_STATUS). Messages & billing always hidden for delegates. Self patients unchanged (full data).
- Appointment `select`/`cancel`/`reschedule` → `portal_access("APPOINTMENTS")` with delegate audit (acted_by/on_behalf_of). Appointment CREATE practice_id fix remains intact.
- Health Card: new `HEALTH_CARD_UPDATE` delegate permission (delegates.py). `POST /portal/profile/health-card` is now delegate-aware — SELF = instant authoritative write (unchanged); DELEGATE = writes `pending_health_card` only (NO authoritative overwrite) + audit. New staff endpoints `GET /internal/health-card-updates` (practice-scoped pending list) and `POST /internal/patients/{id}/health-card/{approve|reject}` (approve updates record + identity_history; reject leaves it unchanged; both audit patient_id/practice/acted_by=caregiver/on_behalf_of=patient/old+submitted/reviewed_by/decision).
### Frontend (new)
- `portal/PortalHealthCard.jsx` — reuses `HealthCardNumberInput` + same fields/validation; submits to pending-review; shows current + pending state. EN/ES/FR i18n added (`portal:managed.*`, `nav.documents`, `nav.healthCard`).
- `internal/HealthCardUpdates.jsx` + nav entry — staff review queue (current vs submitted, Approve/Decline).
- `FamilyAccess.jsx` offers the new HEALTH_CARD_UPDATE permission.
### Verified in Preview (API + mobile UI)
- Caregiver lands on People → opens managed portal: banner + managed Home + gated nav render. Appointments shows the SAME patient flow (reason/date/time/type/note/submit); created request carries managed patient_id + practice_id + delegate audit and appears in Staff/Admin queue. Rx shows managed meds/refill. Overview permission-gated (messages/billing hidden). Health Card submit → pending (authoritative record unchanged) → staff list shows it → Approve updates record, Decline leaves unchanged; audit records caregiver+patient+reviewer. Security: cross-patient/practice → 404; missing permission → 403. Normal patient portal unchanged (self overview full, delegate.is_delegate=false). No fabricated patient/PIN/chart.


## 2026-06 — Rx intake not appearing in queue — RCA + fix (PREVIEW ONLY, NOT DEPLOYED)
- SYMPTOM: a new Rx request submitted from Admin/Staff -> Rx -> Request Intake did not appear in the Prescription Requests queue (admin or physician), while older requests did.
- ROOT CAUSE (reproduced): the staff intake endpoint `POST /api/internal/pharmacy-rx` (`create_pharmacy_rx`) and the pharmacy-portal endpoint `POST /api/pharmacy/rx` (`pharmacy_create_rx`) inserted `prescription_requests` docs WITHOUT a `practice_id`. The internal queue `GET /api/internal/prescriptions` and `/api/internal/counters` both filter by `pscope(user)` = `{"practice_id": user.practice_id}`, so a `practice_id: None` record is silently excluded. Patient-origin inserts (`patient_refill`, `patient_photo`) already stamp `practice_id`, which is why those (and seeded demo records) appeared. Confirmed by creating a staff intake: `practice_id=None`, status `waiting_physician`, NOT present in the queue.
- FIX (smallest safe, reuses existing practice scoping): stamp `practice_id` on the two inserts. Staff intake uses `user.get("practice_id")`. Pharmacy portal (pharmacies are global, no practice) resolves the patient's practice via new helper `_practice_for_directory(d)` = directory.practice_id -> linked patient.practice_id -> active `patient_practice_relationships` -> single-practice fallback. No schema change, no new Rx system, no historical data touched.
- VERIFIED in Preview: (1) staff intake now stamps practice_id and appears in admin queue; (2) appears in physician queue and `counters.rx` matches; (3) physician can PATCH/process it; (4) pharmacy-origin request resolves practice_id and appears in admin queue; (5) patient-origin unchanged; (6) exactly one record per submit (no duplicate). All test records cleaned up afterward (rx baseline restored).


## 2026-06 — Caregiver mobile blank-login RCA + fix & patient self-reg name fields (PREVIEW ONLY, NOT DEPLOYED)
### A) Caregiver first-login blank page — ROOT CAUSE + FIX
- ROOT CAUSE (reproduced on mobile AND desktop): the `caregiver` role was not handled in post-login routing. `homePath()` in `components/RoleRoute.jsx`, plus `SignIn.jsx` and `ChangePassword.jsx`, all fell through to `/internal` for caregivers. `/internal` is gated to staff/physician/admin, so `RoleRoute` bounced the caregiver to `homePath("caregiver")` which also returned `/internal` → a redirect-to-self that renders nothing = blank screen. NOT caused by missing patient_id/PIN/chart; `/portal/overview` returns 403 for caregivers and is handled safely by react-query.
- FIX (smallest safe): centralized `homePath()` and added `caregiver → /portal/people`; `SignIn.jsx` and `ChangePassword.jsx` now reuse `homePath(role)`. `PortalHome.jsx` redirects `role==="caregiver"` to `/portal/people` so the Home tab never drops a caregiver into an own-patient overview. No fabricated patient/PIN/chart; delegate permissions and practice isolation untouched.
- Caregiver-only lands on "People I help manage"; caregiver-who-is-also-patient (role=patient) still lands on `/portal`. All own-patient portal pages already use `overview.data?.patient` optional chaining + empty-array defaults, so caregiver-only sees empty states, never a crash. Verified on mobile viewport (390x844) with robert.helper.qa@demo.com: lands on People I help manage (Linda Nguyen, 4 perms), no blank.
### B) Patient self-registration name fields (stored separately)
- The patient self-reg + new-patient forms already collected First / Second name / First last / Second last but JOINED them into first_name/last_name on submit. Now sent and stored SEPARATELY: `first_name`, `middle_name`, `last_name`, `second_last_name` (middle/second-last optional). Caregiver "person you are helping" section unchanged (identity there relies on OHIP+version+DOB).
- Matching stability: backend (`server.py`) combines first+middle and last+second-last ONLY for `directory_mod.match_registration`, so matching behavior is identical to before. Core stored first_name/last_name are the base values; `users.name` stores the full combined display name.
- Models `RegisterBody` + `NewPatientRequestBody` gained optional `middle_name`/`second_last_name`; stored on patient doc, new-patient application doc, and preserved on the unclaimed-record claim path. `_portal_patient_snapshot` now returns the two fields; `_portal_search_ors` searches them; frontend `lib/name.js formatPatientName` appends them when present (legacy records unaffected). FR labels added to `locales/fr/auth.json` (EN/ES already present).
- Verified in Preview: new OHIP registration stores all four fields separately (first=TestGiven, middle=MiddleX, last=SurOne, second_last=SurTwo), users.name="TestGiven MiddleX SurOne SurTwo"; internal search finds the patient by "MiddleX" and by "SurTwo". Mobile form layout clean. Test account cleaned up afterward.


## 2026-06 — Caregiver access bridge for directory-only ACTIVE patients (PREVIEW ONLY, NOT DEPLOYED)
- Problem: staff could not approve caregiver (portal access) requests for a valid ACTIVE clinic patient that had no portal account (e.g. Carlos Chazi / PIN 152). Old behavior returned 409 and the Approve button was disabled.
- Backend (`server.py`): new helper `_ensure_portal_patient_for_directory(d, req, user)`. On APPROVE for a directory-only ACTIVE patient it (1) reuses an existing linked portal patient, else (2) creates a MINIMAL UNCLAIMED portal patient anchored to the canonical directory identity: preserves existing VISITA PIN, canonical demographics, `matched_directory_id`/`canonical_directory_id`, practice-scoped, `verification_status=verified`, `portal_status=UNCLAIMED`, `is_unclaimed=true`, `has_login=false`, email=None, NO users doc, NO password, no fabricated data. Sets `patient_directory.linked_patient_id`, claims the PIN in `visita_pins`, anchors the Stage-C relationship, audits `unclaimed_portal_patient_created`. Then creates/activates the `patient_portal_delegates` grant as before. Removed the 409 for valid ACTIVE directory-only patients.
- Registration claim: `POST /api/auth/register` now detects an UNCLAIMED bridge record linked to the matched ACTIVE directory record and CLAIMS it (attaches the new patient login to the SAME patient_id, preserving PIN/history/active delegate grants) instead of blocking with 409 or creating a duplicate.
- Frontend (`PortalAccessRequests.jsx`): Approve enabled for directory-only picks (`disabled={!picked || busy}`); amber "needs portal record" blocker replaced with an informational note explaining a no-login portal record will be created.
- Still enforced: explicit staff patient selection, MatchComparison review, explicit Approve & grant, practice scoping, audit trail.
- Verified end-to-end via API in Preview (Carlos Chazi / PIN 152): approve created the unclaimed record + grant (no user account), later self-registration claimed the same record (no duplicate, PIN + grant preserved). All test artifacts cleaned from Preview DB afterward.


## 2026-06 — Verifications: auto-expand single candidate (PREVIEW ONLY, NOT DEPLOYED)
- Frontend-only (Verifications.jsx). On the Pending tab, when a verification has EXACTLY ONE suggested VISITA candidate, the shared MatchComparison widget auto-expands on load (read-only), still collapsible via Hide/Compare toggle. Multiple candidates keep the existing manual per-candidate Compare behavior.
- `cmp` single-state refactored to a `cmps` map keyed by `patientId:candidateId`; `useEffect` + `autoLoaded` ref auto-loads single-candidate compares once. Reuses existing MatchComparison component and `GET /api/internal/verifications/{patient_id}/compare` endpoint. NO backend changes, NO auto-approve, NO auto-link, NO change to matching/ranking/linking logic.
- Verified via frontend testing agent (iteration_72): auto-expand, Hide/re-Compare toggle, and no auto-approve/link all pass. Awaiting user review before any PRODUCTION GO.


## 2026-10-02 — Reuse patient match comparison in Verifications (PREVIEW ONLY, NOT DEPLOYED)
- Backend: extracted shared `_match_fields_payload(submitted, canonical)` helper (Name/DOB/OHIP/Version/Issue/Expiry; OHIP compared on digits, returned masked). Portal Access compare now calls it; NEW `GET /api/internal/verifications/{patient_id}/compare?candidate_id=` reuses it (candidate resolved from patient_directory or patients). Practice-scoped, no auto-verify/link.
- Frontend: extracted shared `internal/MatchComparison.jsx` (green/red highlight, N/6 score, masked OHIP) now imported by BOTH PortalAccessRequests and Verifications. Verifications pending items gain a per-candidate "Compare" toggle. No duplicate matching logic/component.
- Verified: endpoint returns correct structure/match booleans with masked OHIP; widget already visually confirmed in Portal Access; compile clean; Verifications renders cleanly.


## 2026-10-02 — Portal Access review: patient match comparison (PREVIEW ONLY, NOT DEPLOYED)
Self-verified (curl + DB + UI). No auto-approve/auto-link; staff must pick a patient + click Approve (unchanged).
- NEW backend GET /api/internal/portal-access-requests/{req_id}/compare?patient_id= returns a field-by-field match (Name, DOB, OHIP number, Version code, Issue date, Expiry date) between the caregiver-submitted patient info and a candidate canonical patient. OHIP compared server-side on normalized digits; both sides returned MASKED (•••• ••• NNN) — the full canonical number is never sent to the client. Practice-scoped.
- Frontend (PortalAccessRequests.jsx ApproveDialog): when staff pick a candidate, a compact side-by-side "Patient match check" table renders (LEFT submitted / RIGHT canonical) with green=match (✓) and red=differ (✗), plus an X/N score. Caregiver/password/approval architecture unchanged.


## 2026-10-02 — Caregiver signup form refinement (PREVIEW ONLY, NOT DEPLOYED)
Self-verified E2E (curl + DB + UI). Approval architecture unchanged (PENDING portal_access_requests → staff approve → patient_portal_delegates).
- Person being helped: OHIP now REQUIRED, reusing the normal patient-registration components/validation (HealthCardNumberInput + Version Code + IssueDatePicker + ExpiryPicker). Backend PortalAccessRequestBody now requires patient_health_card_number and carries version/issue/expiry; stored on the request for staff matching.
- Heading "Your information" → "Caregiver Information" (EN/ES/FR).
- Caregiver now sets THEIR OWN password at signup (Password + Confirm, eye show/hide, live match feedback, Submit disabled until valid+matching, min 6). Backend hashes it (bcrypt via authlib) and stores ONLY the hash on the pending request (never plaintext; excluded from the staff list projection); on approval the caregiver user is created with that hash (active, must_change_password=false, email_verified=false) and the stored hash is $unset. Decline also clears it. If the email is an existing VIen user, no password is stored (reused). Verified: caregiver logs in with their chosen password; no temp password issued.
- Submit button label → "Submit Access Request".
- Integration_expert consulted before auth changes (bcrypt hash-at-submit, apply-at-approval pattern confirmed).


## 2026-10-02 — Centralized Exams & Results module (PREVIEW ONLY, NOT DEPLOYED)
Tested testing_agent iteration_71: 100% pass (all 33 verification points), no bugs, security confirmed, test data cleaned.
REMOVED/DEPRECATED:
- Patient-facing exam request pages: /portal/imaging & /portal/bloodwork now redirect to /portal/appointments; Home imaging/bloodwork tiles removed; Help/Messages imaging routing removed (patients request CARE, not tests).
- Internal Imaging & Bloodwork sidebar silos removed; /internal/imaging & /internal/bloodwork redirect to /internal/exams. Old ImagingQueue/BloodworkQueue + PortalImaging/PortalBloodwork files remain unrouted (no destructive deletion). Old /api/internal/imaging & /bloodwork endpoints kept for back-compat.
CENTRALIZED WORKFLOW (ONE module 'Exams & Results'):
- Tabs: Requests, Results Received, Ready for Physician, Reviewed, Needs Patient Match. Filters: All/Laboratory/Imaging/Cardiac/Pulmonary-Sleep/Pathology-Cytology/Screening/Other.
- Requests tab AGGREGATES existing imaging_requests + bloodwork_requests, auto-classified (X-Ray→Diagnostic Imaging/X-Ray; bloodwork→Laboratory/Bloodwork). No migration; history preserved.
- Add Result (staff/admin): find patient → category/subtype → upload PDF → RECEIVED (or NEEDS_PATIENT_MATCH if no patient) → Match → Send to Physician → READY_FOR_PHYSICIAN.
- Physician Review: View PDF (closing does nothing) + Sign & Complete with SEPARATE notify (default ON) + release (default OFF) flags → REVIEWED. Release-later + Keep-Internal on Reviewed tab.
- Patient: reviewed-unreleased results show in Results & Reports as 'Reviewed results (not yet released)' with 'Request access to report' (flag only — never creates a new exam/imaging/bloodwork request). Released PDFs show with type/date/reviewed-by + View/Download.
COLLECTIONS/ENDPOINTS:
- NEW collection exam_results {status: RECEIVED→READY_FOR_PHYSICIAN→REVIEWED (+NEEDS_PATIENT_MATCH); patient_notified, shared_with_patient separate flags; reviewed_by/at, signed_at, access_requested}.
- NEW endpoints under /api/internal/exams/* (requests, results CRUD, match, send-to-physician, pdf, review, release, keep-internal) + POST /api/portal/results/{id}/request-access.
- REUSED: attachments/object storage (entity_type 'exam_result'), result taxonomy, secure patient download gate (shared+ownership), patient_updates, generic no-PHI notification.
- counters: staff 'exams' (NEEDS_PATIENT_MATCH+RECEIVED); physician 'results_review' (READY_FOR_PHYSICIAN) + 'result_access'. Practice-scoped.
COMPATIBILITY: no destructive migration; old data intact; old routes redirect; old endpoints retained.


## 2026-10-02 — Results & Reports (push-based release) redesign (PREVIEW ONLY, NOT DEPLOYED)
Tested by testing_agent iteration_70: 5/5 backend + all UI scenarios PASS. No issues. Security gate confirmed (cross-patient 404). Test data cleaned up.
- REMOVED old patient "Results / Document Request" UI (copy_result/copy_imaging/copy_other) from PortalMessages.jsx. Backend POST /api/portal/document-requests kept (unreferenced, legacy).
- NEW patient "Results & Reports" (PortalDocuments.jsx, route /portal/documents): shows only physician-reviewed + released results. Each row: type (subtype→category), date, "Reviewed by {physician}", View, Download. Empty → "No results or reports are currently available to view." Bottom "Have questions about a result?" → Request an Appointment. Home tile relabeled "Results & Reports".
- Reused existing Review & Release workflow (attachments). Extended:
  - backend/attachments.py mark_shared() now stores result_category, result_subtype, reviewed_by, reviewed_at; list_shared_for_patient() returns these + type_label; serve_shared_for_patient() already gates on shared_with_patient + patient_id (SERVER-SIDE security, not UI-only).
  - backend/server.py ShareAttachmentBody + POST /api/internal/attachments/{id}/share accept result_category/result_subtype/reviewed_by/notify; patient_update + notification use a GENERIC "Your results have been reviewed by your physician…" message (never normal/abnormal).
- NEW internal "Review & Release" dialog (Attachments.jsx) with taxonomy (frontend/src/lib/resultTaxonomy.js: Laboratory, Diagnostic Imaging, Cardiac Tests, Pulmonary/Sleep, Pathology/Cytology, Screening, Other Reports + subtypes), reviewing physician field, and notify toggle. No second document system — reuses attachments + patient_updates + object storage.
- i18n EN/ES updated (FR falls back to EN).


## 2026-10-01 — Phase B: Staff Portal Account Mgmt + Physician Medical Record + Medication Mgmt (PREVIEW ONLY, NOT DEPLOYED)
Tested by testing_agent iteration_69: 18/18 backend PASS; UI panels render + actions verified. No blocking issues.
- **Staff/Admin Portal Account panel** (`PortalAccountPanel.jsx`, roles admin+staff) in Patients detail. Shows status, login email, email_verified, access enabled/disabled, must_change_password, last_login_at, temp-password expiry. Actions (all audited, practice-scoped, current password never shown):
  - `GET /api/internal/patients/{id}/portal-account`
  - `POST .../portal-account/send-reset` (emails 6-digit reset code)
  - `POST .../portal-account/resend-verification` (re-issues 72h activation link; only when pending_activation)
  - `POST .../portal-account/temp-password` (one-time temp pw, 72h expiry, must_change_password=true, shown once)
  - `POST .../portal-account/force-password-change`
  - `POST .../portal-account/email` (duplicate→409; sets email_verified=false; no merge)
  - `POST .../portal-account/disable` + `/enable` (login-only block; patient/PIN/history preserved)
- **Login** now records `last_login_at` and rejects an expired one-time temp password (403).
- **Portal Access nav badge**: `GET /api/internal/counters` now returns `portal_access` = PENDING portal_access_requests (practice-scoped); sidebar badge wired.
- **Physician Medical Record** (`MedicalRecord.jsx`, roles admin+physician): `GET /api/internal/patients/{id}/medical-record` → summary, encounters (appointment_requests), medications {active, discontinued}, documents. Shows only existing VIen data (no fabrication). Cross-practice → 404.
- **Medication Management** (physician/admin): `POST /api/internal/patients/{id}/medications` (Add) and `PATCH .../medications/{med_id}` with action_type continue|edit|discontinue. Reuses `patient_medications` + `_regimen_key` + `medication_catalog` + `physician_rx_memory`. Discontinue sets active=false (never deletes); edit stores previous+new in a `history[]`. Patient Portal "Your Medicines" (`GET /api/portal/medications`) reflects state live.


## 2026-06 — Patients stale-data RCA fix + Copy patient info (PREVIEW)
- **RCA**: Internal Patients search (`_search_patients_merged`) returned the `patient_directory` snapshot for VERIFIED portal patients linked to a directory record (matched_directory_id), so canonical edits (portal profile/email/address/health-card) didn't show — the screen read a stale directory copy. Canonical `patients` data was correct all along (write path fine; read source wrong).
- **Smallest safe fix (read-path only, no data change)**: for verified portal patients, return the CANONICAL `_portal_patient_snapshot(p)`, backfilling only PIN + pharmacy from the linked directory. Verified: canonical edit (city) now reflects immediately in the Patients screen; PIN preserved. Fix is in code — deploying it resolves Production; no prod data migration needed.
- **Copy patient info** button added to the Patients detail (clean text: name, DOB, VIen PIN, phone, email, address, OHIP+version+expiry, pharmacy).
- STILL PENDING (next phase, not built): Phase B staff Patient-Portal Account panel + actions, Physician Medical Record view, physician medication management (Continue/Change/Stop/Add → patient_medications w/ portal sync), Portal Access nav pending-counter badge.


## 2026-06 — Portal account: sex at signup + self email-change (code) + request PIN (PREVIEW ONLY)
Self-tested (curl + screenshots). NOT deployed.
- **Sex at signup**: added Sex (Male/Female/X) to Create Patient Portal account form; stored on the patient at registration (RegisterBody.sex). Post-signup edit already existed.
- **Patient self email change (code-verified)**: `POST /api/portal/account/email/request` (requires current password; 409 if another user owns the new email) sends a 6-digit code to the NEW address; `POST /api/portal/account/email/verify` swaps user.email + patient.email only after the code matches — same patient_id/PIN/clinical record preserved, audited old→new. Stored in `email_changes` (hashed code, 15-min, 5-try, single-use). Operates on the logged-in user's own account, so a delegate can't change a managed patient's email. UI in PortalAccount (Change email → code).
- **Request my PIN**: `POST /api/portal/account/request-pin` creates a `pin_requests` record (practice-scoped) + patient confirmation + audit; button next to the VISITA PIN. (Staff-side PIN-request queue UI is a follow-up.)
- i18n EN/ES/FR added. Phase B staff portal-account management still pending.


## 2026-06 — Caregiver public signup + clinic review + password UX (Phase A, PREVIEW ONLY)
Verified: testing_agent iteration_68 (backend 11/12, frontend 100%; both minor items fixed) + curl + screenshots. NOT deployed.
- **Part 1 whoFor** — Create Patient Portal now asks "Who are you creating this account for?" → Myself (existing flow unchanged) / Someone I help care for.
- **Part 1 caregiver intake** — new public `POST /api/portal-access-requests` stores an intake record in NEW collection `portal_access_requests` (status PENDING). It NEVER creates a delegate grant and NEVER auto-links a patient. Collects person-being-helped (name/DOB/optional HC), requester (name/email/phone), relationship, authorization basis, note. Notes an existing VIen user by email without creating anything.
- **Part 2 clinic review** — staff page /internal/portal-access-requests ("Portal Access" nav): list pending/reviewed; Approve (staff picks the matching patient — no name auto-link) creates/activates the existing `patient_portal_delegates` grant with the four v1 perms, reusing an existing VIen user by email or creating a caregiver-only user (temp password, must_change_password, no chart/PIN; shown once); Decline leaves no access. assert_practice blocks cross-practice approval.
- **Part 3 password UX** — account creation now has Password + Confirm password, each with a show/hide eye, inline match/mismatch feedback, and Create Account disabled until they match (min 6).
- Caregiver v1 permissions + audit (acted_by delegate / on_behalf_of patient) unchanged. i18n EN/ES/FR added.
- Phase B (patient self email-change + staff portal-account management + reset/temp surfaces) NOT started yet.


## 2026-06 — Landing search emphasis (Google-style) (PREVIEW ONLY, visual)
- Landing search is now the dominant control: standalone centered pill (w-full max-w-[760px], h-14 mobile / h-16 desktop), left search icon, Search button integrated on the right, readable placeholder. Removed the uppercase "FIND YOUR CLINIC…" label. Sign in + Create Patient Portal + Apply for care moved into a compact card below; emergency notice below that. Pure Landing.jsx CSS/structure change — search backend, routing, auth, role filter, portal/apply, QR, i18n all unchanged. Verified desktop (search 760×64, results render) + no horizontal overflow; testids unchanged (iteration_67 flows preserved). Not deployed.


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

## PRODUCTION DEPLOY — Landing CTA Visual Refinement (2026-10-02)
- Deployed to https://visitaemr.com: Sign in (Space Grotesk, uppercase, 0.18em tracking, cyan glow, hover arrow), Create Patient Portal + Apply for care (black 900 text on cyan-700). Also included earlier Preview-verified Verifications auto-expand single candidate.
- LIVE verified: computed styles correct, hover arrow works, Apply->/register?new=1, Portal->/register, Sign in->/login role panel; desktop/mobile OK, no regressions.

## HOTFIX PROD — Portal Access blank page (2026-10-02)
- Root cause: commit 9df6527 (MatchComparison extraction) removed `Check, X` from the lucide-react import in PortalAccessRequests.jsx while RequestCard still rendered them on PENDING cards → ReferenceError "Check is not defined" → blank page whenever ≥1 PENDING request exists (Prod had 1).
- Fix: restored import; added "—"/Unknown fallbacks for optional request fields and null-safe match/submitted/canonical in MatchComparison. Frontend only. Deployed (bundle main.d0097762.js) and LIVE verified.

## PREVIEW ONLY — Portal Access approval patient search fix (2026-10-02, NOT deployed)
- Root cause: ApproveDialog used GET /internal/patients (portal `patients` collection only, single-field regex). Directory-only patients (e.g. Carlos Jorge CHAZI, PIN 152, ACTIVE, no portal account) never appeared; full-name queries also failed.
- Fix: new GET /api/internal/portal-access-requests/candidates?q= (merged search = practice-scoped verified portal accounts + active directory records; exact PIN first for digit queries; first/last/full/last+first via token clause). Compare endpoint now accepts directory candidates. Approve on a directory-only candidate returns 409 with clear message; UI disables Approve + shows hint. Dialog prefills full submitted name (falls back to last name), shows "LAST, First / DOB: YYYY Mon - DD / PIN: n" + "No portal account" badge.
- OPEN DECISION: directory-only patients (Carlos Chazi) cannot be approved until a portal record exists — needs product decision (create portal record on approve vs. separate flow).

## 2026-10-22 — Production resource upgrade (Starter → Launch 0.5 vCPU / 2 GB), resource-only republish
- User GO received. Dispatched to deployer with strict no-build / no code-DB-secrets-domain-config change brief. Deploy job 7e7c2f10.
- Before/after read-only latency bench (5 runs, GET only): `memory/qa/prod_bench.sh`, results in `memory/qa/prod_bench_{before,after}.txt`. Public endpoint timings unchanged within noise (edge/ingress-dominated ~170–650 ms); post-switch /api/health shows fresh pod bootstrap attempts=1 with ALL index steps ok (audit_indexes ok). Benefit is OOM/cold-start elimination, not raw latency of cheap endpoints.
- Authenticated endpoint benchmark (/internal/appointments, /prescriptions, /calendar, /work) requires Prod credentials not held in repo — owner to supply or run.

## 2026-10-22 — Enter Encounter perf optimization (PREVIEW ONLY, NOT deployed)
- Frontend: `encounter/readyCache.js` single-slot same-patient prefetch of `/internal/visits/ready` from `StartEncounterButton` (mount + click); `EncounterPage` consumes it (consume-once, 60s max age, 1.5s StrictMode grace) else fetches; active-visit redirect preserved. `/internal/visits/active` call from the button removed (ready.active now includes started_at). Service catalog cached via react-query (30 min); SOAP helper list cached per [search, patient_ref, visit_id] (10 min); initial empty SOAP-helper / Issue-Plan searches fire immediately (typing still debounced).
- Backend: `_visit_context` only loads medications_active (recent_appointments/documents → null, no consumer); `visit_ready` gathers find_active + context; `visit_get` gathers context + audit; idempotent `patient_directory.id` index in `_ensure_core_indexes`.
- Measured Preview (in-cluster browser, 3 runs): click→shell 150–214 ms → **62–86 ms**; click→SOAP editable 205–251 → 62–86 ms; all panels ~230–290 → ~190–275 ms; `/visits/ready` Mongo round-trips 6→4 (incl. auth), 0 critical-path requests after click. testing_agent iteration_89 all pass. Pre-existing unrelated pytest failures (stale SIGNED fixtures, BMI rounding, leftover IN_PROGRESS VIS-000095 on Sarai Lopez Iglesias from 2026-10-15).

## 2026-10-22 — DEPLOYED to Production: Enter Encounter perf delta + Password Requirements (user GO for both)
- Bundle main.399ba12f.js → main.38b194bd.js. /api/health ready, bootstrap attempts=1, all steps ok (core_indexes incl. new patient_directory.id, audit_indexes). New bundle references /internal/visits/ready prefetch and no longer calls /internal/visits/active. Register page loads with no console errors. Authenticated Prod smoke (Enter Encounter, Start/Exit/Re-enter, Stop/Sign, Visit Hx) to be run by owner with own physician account.

## 2026-10-22 — Deployment & Maintenance experience, Phase 1+2 (PREVIEW ONLY, NOT deployed)
- Backend `deployment.py`: state machine NORMAL|UPDATING|MAINTENANCE|SERVICE_ISSUE in `system_state.global.deployment` + append-only `deployment_history`; kind-aware verification (CODE/HOTFIX compare expected commit when supplied; RESOURCE readiness-only); 3 consecutive OK → NORMAL; failed checks keep UPDATING; 20-min deadline → SERVICE_ISSUE; manual ISSUE/RESOLVE (typed confirms, rolled-back flag); Full Maintenance synced (history mode FULL); targeted $set writes (no lost-update race); all transitions audited `deployment_state_changed`. Endpoints `/api/developer/deployment[/begin-update|/verify|/service-issue|/resolve|/build-info]`, `/api/cron/deployment-verify` (crons.yml every minute). `/api/system/banner` adds `state` + managed `notice`.
- Frontend: `developer/DeploymentOps.jsx` (OPERATIONS tab: state strip/actions, build/tier, readiness+checks, user-facing preview, history; existing Maintenance + Global message cards kept below); `SystemStatus.jsx` ManagedNotice (above manual announcement; on portal/internal/login/register/public auth pages via App `PublicNotice`), branded MaintenanceScreen (Retry, auto-poll, 911 line); `OutageBoundary.jsx` + `api.js` interceptor (502/504/52x/network/non-maintenance 503 → in-page card, Retry + 20 s auto-retry, page stays mounted; render-error boundary); i18n en/es/fr `common.system.*`.
- Tests: `tests/test_deployment_state.py` (7) + testing-agent `tests/test_deployment_state_extra.py` (12) → 19/19 after fixes; testing_agent iteration_90 frontend 100%. Phase 3 (Cloudflare/SW offline fallback for fully unreachable origin) NOT implemented — documented in `memory/qa/deployment_maintenance_design.md`.

## 2026-10-22 — Control Center SIMPLE | ADVANCED mode (PREVIEW ONLY, NOT deployed)
- `developer/SimpleOps.jsx` + `developer/SimpleWizards.jsx`: SIMPLE (default, localStorage vien_cc_mode) guided home — status hero (Is VIen working?), attention + Recommended action (Does anything need my attention?), 6 task cards (Update VIen / Take offline↔Bring back online / Post a message / Check VIen / Recover from a problem / Help me choose), humanized history with "View technical details". Wizards translate plain choices → CODE/RESOURCE/HOTFIX, show WILL/WILL-NOT facts, require checkbox + typed ENTER/EXIT/ISSUE/RESOLVE for risky actions, and call the SAME audited endpoints. ADVANCED = unchanged technical tabs. `DeveloperPortal.jsx` header toggle.
- testing_agent iteration_91: all flows pass; permission (physician redirected/403) and audit rows verified. Post-report tweaks: resolved headline, 1-hour window for "healthy again", recommend "Mark as resolved" when checks pass.

## 2026-10-22 — operations_operator role + Update wizard clarity + SERVICE_ISSUE guidance (PREVIEW ONLY, NOT deployed)
- Backend: `OPERATOR_ROLES=(developer_ops, operations_operator)` for status/deployment GET, begin-update (403 for operator while SERVICE_ISSUE), verify, announcement PUT/DELETE; everything else stays `OPS_ROLES` (developer_ops): maintenance-mode, service-issue, resolve, build-info, platform-config, data-ops. `/platform/auth/login` accepts both platform roles and is in maintenance ALLOW_PREFIXES; maintenance gate bypass = OPERATOR_ROLES. Preview-only seed `OPERATIONS_OPERATOR_EMAIL/PASSWORD` (operator@visita.demo). Excluded from delegate/user pickers.
- Frontend: operator forced to SIMPLE (no toggle/tabs, limited badge/note; no offline/recover cards; recommended actions needing developer → "Contact developer"). Update wizard 4 steps: Choose → Prepare VIen (explicit "does not install or publish anything") → Publish (hosting-panel instructions; no fake link) → Verification. SERVICE_ISSUE guided flow: Run Check VIen → "The problem is still present." [Recover (developer_ops)] [Contact developer] [Check again] / "Checks are passing now" → Mark as resolved (developer_ops).
- Tests: testing_agent iteration_92 (all UI flows pass; 2 backend findings fixed: operator begin-update escape, platform login 503 during maintenance; dead recommended buttons for operator fixed). pytest 66/66 (test_deployment_state*, test_cc_operator_role, test_cc_simple_mode_api).

## 2026-10-22 — DEPLOYED to Production: Deployment & Maintenance Phase 1+2, SIMPLE|ADVANCED Control Center, operations_operator capability (no account seeded)
- Bundle main.38b194bd.js → main.8c149d97.js. /api/health ready, bootstrap attempts=1, all steps ok. /api/system/banner: state NORMAL, notice null, announcement null, maintenance.on=false (preserved). Bundle contains operations_operator / simple-ops / wizard / outage-card markers. Unauth probes OK (/login, /signin 200; /api/developer/deployment 401; cron 401 without secret). Authenticated Prod smoke (devops login, SIMPLE/ADVANCED, Check VIen, Global message, audit) left to owner; deployer debug query dispatched for secrets/users/system_state/cron confirmation.
