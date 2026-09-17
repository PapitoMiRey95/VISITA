# VISITA Web Portal — PRD

## Original Problem
Web application for Dr. Aguayo's family practice acting as a communication / request-management / appointment-approval / referral-fax-preparation / internal-task workflow layer AROUND the existing Microsoft Access VISITA EMR. It does NOT replace the EMR. Three experiences: Patient Portal (mobile-first), Clinic Staff Hub (desktop-dense, VISITA green-on-light-blue identity), Physician Hub (minimal). Plus Admin.

## Architecture
- Backend: FastAPI + MongoDB (motor). JWT email/password auth (Bearer token, localStorage). Object storage (Emergent) for referral PDFs. All routes under `/api`.
  - Files: `server.py` (routes), `auth.py` (hash/jwt), `storage.py` (object storage), `db.py` (helpers, status maps, HCN masking), `seed.py` (demo data).
- Frontend: React + Tailwind + shadcn/ui + react-query. `IBM Plex Sans` (internal dense) + `Nunito` (patient portal). Routes `/portal/*` (patient) and `/internal/*` (staff/physician/admin).

## Roles
patient, staff, physician, admin. Patients see only their own data. Referral upload = physician/admin. Mark-as-faxed = staff/admin. Settings = admin.

## Implemented (2026-06 / build 1) — Core Version 1, all verified by testing agent (23/23 backend, all frontend flows)
- JWT auth + role-based access; owner/admin = kevinrodriguez9528@gmail.com.
- Patient registration flow ("Are you a patient?" → type → form) with ACCOUNT VERIFICATION PENDING; staff/admin manual verification (HCN masked); pending patients blocked from submitting requests.
- Patient Portal: Home tiles, Request Appointment, Prescription Request, Referral Status (+ New Referral → request appointment), Imaging (X-Ray/Ultrasound), Message the Clinic (smart routing), My Requests, Account (+ notifications). Non-emergency disclaimer everywhere.
- Clinic Staff Hub: live actionable counters as navigation (Rx 3, Referrals 2, Imaging 1, Messages 4, Appointments 5, Doctor Tasks 2, Verifications). Dense queues with search + status filters + row actions + internal notes.
- Referral Ready-to-Fax: physician uploads completed PDF (drop-off) → Ready-to-Fax, counter +1; staff Open/Download PDF → Mark as Faxed → counter −1, moves to Faxed History. Counter counts ONLY ready_to_fax && !faxed. (verified 2→3→2).
- Prescription / Appointment / Imaging / Message workflows with staff actions (review, send-to-physician, complete, appointment-required; appointment approve/suggest/more-info/decline). Patient-facing statuses only (internal wording never leaks).
- Physician Hub: reduced counters (Rx/Imaging/Messages) + Referral Drop-Off + Intercom.
- Internal Intercom / Tasks: physician→staff tasks (Doctor Tasks counter), staff→doctor messages, complete/escalate.
- Admin: configurable Clinic Settings + editable Message Templates (defaults from brief). AuditLog written for key actions. In-app Notifications (minimal medical info).
- Human-readable ref numbers (RX-, APT-, IMG-, MSG-, REF-, TSK-). Patient model prepared for future VISITA import (visita_patient_id, demographics only). Demo data (verified + pending patients, pharmacies).

## Data Models (collections)
users, patients, appointment_requests, prescription_requests, referrals (ready-to-fax + fax history), patient_referrals (patient-facing status), imaging_requests, patient_messages, internal_messages (tasks/intercom), pharmacies, notifications, audit_logs, settings, templates, counters, app_meta.

## Not in V1 (by design)
Referral PDF generation (done in Access EMR), full clinical chart, automatic Bell fax, direct Access DB connection, MFA/lockout (architecture prepared), full patient CSV import UI (models/fields prepared), advanced analytics/reporting.

## Backlog / Next
- P1: Admin Patient Import tool UI (CSV upload → preview → map → dedupe → confirm) with ImportBatch model + portal-account matching suggestions.
- P1: Physician "Create Task for staff from a queue item" shortcut; assign-to-staff dropdown in queues.
- P2: MFA, account lockout/rate limiting, session inactivity expiry, admin disable-account.
- P2: Data export (demographics / request history / fax history CSV).
- P2: Email/SMS/WhatsApp notification channels (in-app is source of truth in V1).

## Test Credentials
See /app/memory/test_credentials.md.
