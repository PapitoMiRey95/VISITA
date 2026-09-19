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

## Appointment Workflow v2 (2026-06 update) — verified (16/16 new tests + frontend)
- Configurable **Physician Availability** (settings id="availability"): per-day enable + start/end, appointment duration, closures, vacations, blocked periods; timezone America/Toronto. Default Mon–Thu 11:30–16:30, 30-min. Admin-editable in Settings (`/api/admin/availability`).
- **Slot generation** (`availability.py`): `generate_slots` (accepts future `busy` set for Google Calendar) + `is_within` validation. Endpoint `GET /api/availability/slots`.
- **Patient request**: chooses up to 3 ranked preferred slots (no free-text times); each validated within availability.
- **Staff modal**: Approve (validates within availability), **Offer Available Times** (slot selector, up to 3 → status `alternatives_offered`, notifies patient) — replaced "Suggest Another Time"; Request More Info; Decline.
- **Patient self-selection**: `POST /portal/appointments/{id}/select` → auto CONFIRMED, no re-approval; notifies patient + staff (audit).
- Statuses: requested, alternatives_offered, confirmed, more_info_required, declined, cancelled, completed. Counter still counts only `requested`.
- **Notification integration layer** (`notifications.py`): in-portal active; SMS/email queued to `outbound_notifications` as `prepared` (disabled) — ready to wire the clinic's existing Google Apps Script + Twilio + Email system. `sync_calendar` is a stub (no assumptions about Apps Script). Medical reasons kept out of external payloads.
- Future Google Calendar availability (office hours − existing events − blocks) architected via the `busy` parameter; not implemented until the clinic's Calendar/Apps Script code is provided.

## Patient Status / Former-Patient Workflow (2026-06 update) — verified (12/12 backend + frontend, iteration_8)
- **`patient_directory` collection** (single, `patient_status` field, extensible): imported once at startup from two bundled workbooks in `/app/backend/data/` — 828 ACTIVE + 2156 FORMER_CLOSED (guard `app_meta.directory_v1`). Normalized match keys (norm_first/last/dob/hcn). `directory.py` holds import + `match_registration`.
- **Registration matching** (`POST /api/auth/register`): 3 outcomes for current-patient types. ACTIVE_MATCH → account created (PENDING_VERIFICATION) + suggested directory record shown in Verifications; FORMER_PATIENT_REVIEW → NO account created, returns `{former_detected:true, message, prefill}`, patient routed to neutral Re-establish-Care flow; UNMATCHED_CURRENT_PATIENT → account created, flagged for staff review. Two-level match: strong=OHIP, possible=name+DOB; multiple = AMBIGUOUS. Duplicate-account guard when an ACTIVE record is already linked.
- **Public application endpoints**: `POST /api/applications/return-request` (former return), `POST /api/applications/new-patient` (new patient) → `patient_applications` (ref APP-xxxxxx), status REQUEST_RECEIVED + waiting-list confirmation (editable templates: former_patient_detected, reestablish_care_confirmation, new_patient_request_confirmation, application_not_accepted). `preferred_language` stored (default en) for multilingual-readiness.
- **Internal Patient Applications queue** (`/internal/applications`, page Applications.jsx): filter NEW/FORMER, statuses REQUEST_RECEIVED/WAITING_LIST/UNDER_REVIEW/SENT_TO_PHYSICIAN/ACCEPTED/NOT_ACCEPTING/CLOSED. Patient-facing map (Request Received/On Waiting List/Under Review/Accepted/Request Closed). Counter `applications` (staff+physician) counts active statuses only.
- **Physician-only final decision**: `PATCH /api/internal/applications/{id}` action=accept|not_accepting are physician-only (staff→403). Accepting a former_return flips the matched directory record FORMER_CLOSED→ACTIVE (records reactivated_by/at, previous_status, application id) — audited. Staff can review/waitlist/send_to_physician/close + notes.
- **Verifications enhanced**: shows review_queue badge + suggested directory candidates (side-by-side). Verify+link writes `linked_patient_id`/`visita_patient_id` onto the directory record (stable VISITA-id link). `GET /api/internal/directory?q=` staff manual search.
- Separation of concerns kept: patient_status (directory) vs portal_status (account). Former reactivation still requires portal verification afterwards.

## Backlog / Next (updated)
- P1: Side-by-side diff highlighting on Verifications for changed demographics (phone/address/HCN version) + "mark for VISITA update".
- P1: Ambiguous-match staff picker to select the correct directory record when >1 candidate.
- P2: Full multilingual (es/fr) template selection using preferred_language.
- P2: Active→Former transition handling of an existing portal account (disable new requests, keep history).
- P2 (still open): Admin CSV import UI, MFA, account lockout/rate limiting, strict file-upload hardening, soft-delete.

## Bloodwork Request + Book-Appointment-from-request (2026-06 update) — verified (13/13 backend + frontend, iteration_9)
- **Bloodwork Request** (mirrors Imaging): patient submits Reason (required) + optional note (NO test selection — physician decides tests). Collection `bloodwork_requests` (ref BLD-*). Portal: Home tile `tile-bloodwork` + `/portal/bloodwork` + shows in My Requests/overview. Internal: `/internal/bloodwork` queue in Staff + Physician sidebar/Hub with live `bloodwork` counter. Physician actions: Approve/Process (complete), Appointment Required, Request More Info (more_info_required), Decline (declined). Generic `_update_request` now also supports `more_info` and `decline` actions.
- **Book Appointment from a request** (`POST /api/internal/book-appointment`, staff+physician): available on Prescription, Imaging, Bloodwork, Patient Message dialogs (`act-book-appointment` -> `BookAppointmentModal`). Creates an immediately CONFIRMED appointment (APT-*) linked via `booked_from{source_type,source_id,source_ref}`, records confirmed_date/time/confirmed_slot_time, approved_by/booked_by; flips source request to `appointment_booked` + `linked_appointment_id`; notifies patient. Reason pre-filled from request type. NOT added to Referrals (drop-off only) by design.
- **Double-booking prevention**: `_slot_taken` blocks a second confirmed appt at the same date+time (409) on book + approve + reschedule (self excluded). Out-of-window times rejected (400) via `avail_mod.is_within` (Mon–Thu 11:30–16:30 America/Toronto).
- **Reschedule / Cancel** on confirmed appointments (Appointment queue, Confirmed filter -> `appt-confirmed-block`): `appt-reschedule` opens BookAppointmentModal in reschedule mode (PATCH action=reschedule, re-validates + notifies); `appt-cancel` (action=cancel -> status 'cancelled', notifies). No deletion; history preserved. New patient-facing status "Appointment Booked" added to RX/IMG/BLD/MSG maps.

## Notes / tech debt (not actioned per user's "keep simple" directive)
- server.py ~1420 lines — candidate to split into routers/ later.
- Minor Radix DialogContent aria-describedby a11y warning across internal dialogs (pre-existing).
- book_appointment insert+source-update not transactional (low risk orphan appt if update fails).

## Pharmacy Rx Intake + global date format + VIen EMR rebrand (2026-06) — verified (iteration_10, 15/15 backend + frontend)
- **Rebrand**: App is now "VIen EMR". Reusable `<Logo>` (`components/Logo.jsx`) = Ontario healthcare-network icon (`public/vien-logo.png`, transparent) + wordmark; used on Landing, SignIn, Register, Portal & Internal headers (dark/light variants). Tab title updated. Legacy Microsoft Access system still referred to as "VISITA" (source of truth) intentionally.
- **Global date display**: `lib/date.js` `formatDate` -> "YYYY Mon - DD" (month always 3-letter English), `formatDateTime` adds "· h:mm AM/PM". Applied to DOB, request timestamps, referral/fax history, appointment confirmations. Availability slot `display` (backend) + server confirmed_display fallbacks use same format. Storage stays ISO.
- **Pharmacy Rx Intake** (staff): `/internal/rx` has a "Pharmacy Refill" button + Source column (PHARMACY/PATIENT badges). `/internal/pharmacy-intake` = 3-panel screen (LEFT active meds [model-ready, empty until VISITA sync], CENTER refill request form: pharmacy, meds, duration/qty, received_via fax|phone|other, pharmacy/internal notes, SEND TO PHYSICIAN, RIGHT patient snapshot). Endpoints: `GET /internal/directory?q=`, `GET /internal/patient-snapshot/{directory_id}` (name/PIN/DOB/age/phone + model-ready medications/last_visit_date/last_visit_plan/current_pharmacy), `POST /internal/pharmacy-rx` (source='pharmacy', internal_status='waiting_physician'). prescription_requests now has a `source` field ('patient' default | 'pharmacy').
- **Physician Rx actions**: Approve (-> 'approved_process_visita', does NOT auto-prescribe), Modify (approved+physician_note), Appointment Required, Request More Info, Decline, + Book Appointment. Approve/Modify gated to prescription entity only. Staff then Mark Completed. RX_ACTIVE now includes approved_process_visita + more_info_required so the single Rx counter covers both sources.
- Future VISITA read-only sync: patient_directory/patient-snapshot fields (medications, last_visit_date, last_visit_plan, current_pharmacy) are placeholders; no Access DB connection.

## Native scheduling + Google removal (2026-06, iteration_11) — verified 6/6 + cron send
- **Google-independent**: removed all Google Calendar/Sheets/Apps Script stubs. notifications.py is fully native. VIen EMR is the scheduling source of truth.
- **Availability = configured hours − confirmed appointments − blocks/closures/vacations**: `get_busy_slots()` feeds `generate_slots`/`calendar_range`; booked slots truly disappear. Availability config already supports days/hours/duration/blocked_periods/lunch/vacations/closures/exceptions (admin editable via /admin/availability).
- **Native calendar**: `GET /api/internal/calendar?start&days` (per-day closed/reason/open_slots/appointments). Frontend `/internal/calendar` = Day/Week views (staff+physician nav) with book (open slot → directory patient search → `POST /internal/calendar/book`, confirmed), reschedule, cancel, complete, no-show, and block-time (`POST /internal/calendar/block`).
- **Statuses**: REQUESTED/CONFIRMED/RESCHEDULED/CANCELLED/COMPLETED/NO SHOW. appt_update actions complete + no_show added; history never deleted.
- **Direct email confirmations** via Resend (`appointment_confirmed_html`: first name, date 'YYYY Mon - DD', time, clinic, portal link; no medical info) + in-portal notification, on staff approve / physician book / calendar book. Emails to real addresses send; fake @demo.com show status 'failed' gracefully.
- **24h reminder engine**: on confirm, `schedule_reminders` creates email+sms `appointment_reminders` at confirmed_time−24h (America/Toronto). Cancel/complete/no-show cancels pending; reschedule re-schedules. `GET`? → `POST /api/cron/appointment-reminders` (Bearer WEBHOOK_CRON_SECRET) queues `send_due_reminders`. Platform cron `.emergent/crons.yml` (appt-reminders, */15). Email sent now; SMS via Twilio when TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER env set (else recorded 'prepared', skipped). NOTE: enabling Twilio later requires `pip install twilio`.


## Twilio SMS + late-cancellation policy (2026-06, iteration_12) — verified (curl backend + frontend testing agent)
- **Twilio LIVE**: `twilio` installed (in requirements.txt). Secrets in backend/.env: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` (single source of truth; `TWILIO_FROM_NUMBER` fully removed). Never logged/exposed to frontend/UI.
- **5 SMS events** via `notifications.py` `_send_sms`, all prefixed `"Dr. Aguayo's Office:"`, America/Toronto, NO clinical details: confirmation (`appointment_confirmed`, also covers physician direct-book/calendar book), reschedule (`appointment_rescheduled`), cancellation (`appointment_cancelled`), 24h reminder (`send_due_reminders`), + alternatives-offered. Time formatted as `YYYY Mon - DD at H:MM AM/PM` via `_fmt_when`.
- **Tracking**: every SMS logged to `outbound_notifications`: appointment_id, patient_id, to, message_type, body, delivery_status (sent/failed/prepared/no_phone/duplicate), twilio_sid, error, dedup_key, sent_at, created_at. Twilio failure NEVER interrupts workflow (email + in-portal still proceed).
- **Dedup**: `dedup_key = <appt_id>:<type>:<date> <time24>`; a second identical send returns "duplicate" (verified: 2 approves → 1 SMS). A later change to a new time produces a new key → new SMS.
- **Patient self-service 24h policy** (America/Toronto): `POST /api/portal/appointments/{id}/cancel` and `/reschedule`. >24h away → allowed. <24h → 403 with the exact $40 late-fee lock message; portal shows amber `within-24h-notice` + Contact Clinic instead of buttons. Overview `appt_view` exposes `hours_until`, `can_self_modify`, `late_fee`; patient `has_outstanding_fee`.
- **$40 late fee (staff/admin only)**: appt_update actions `record_fee` / `mark_fee_paid` / `waive_fee` (`late_fee.status` outstanding→paid/waived, amount=40). AppointmentQueue detail shows `late-fee-controls`. Outstanding fee blocks patient self-book (`create_appointment`) and self-reschedule → 403 OUTSTANDING_FEE_MSG. 24h restriction applies to patients only; staff can always cancel/reschedule.
- **crons.yml** unchanged (SMS now actually sends on the 24h reminder job since Twilio is live).


## Patient-portal calendar booking (2026-06, iteration_13) — self-verified end-to-end (screenshot)
- Replaced the 3× "Preferred Option" dropdowns in Patient Portal → Request an Appointment with a visual monthly calendar flow: **Select Date → Select Available Time → Reason → Optional Note → Review → Submit**.
- `PortalAppointments.jsx` now uses shadcn `Calendar` (react-day-picker). Fetches `/api/availability/slots?days=60`, groups slots by date. Calendar `disabled` matcher = any date NOT in the available-dates set, so Fri/Sat/Sun, past dates, closures, vacations, blocked dates, and fully-booked/no-availability dates are all greyed/unclickable automatically (Mon–Thu 11:30–16:30 America/Toronto default). `fromDate`/`toDate` bound navigation to the availability window.
- After a date is picked, time buttons show only that day's remaining slots (office hours − confirmed − blocked − lunch − vacations/closures, via `generate_slots` busy subtraction — verified: an already-booked 4:00 PM slot was absent). Selecting a time reveals Reason + optional Note + a Review card ("YYYY Mon - DD at H:MM AM/PM"). Submit posts `options:[chosenSlot]` to the UNCHANGED `POST /api/portal/appointments` → still creates a REQUEST needing clinic approval.
- No backend change. Staff/Admin native calendar unchanged. Global date format `YYYY Mon - DD` preserved. New data-testids: appt-calendar, appt-time-<HH:MM>, appt-reason, appt-note, appt-review-when, appt-submit.
