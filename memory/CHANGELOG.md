# VIen EMR — Changelog

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
