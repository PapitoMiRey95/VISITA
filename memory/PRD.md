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

## Twilio/SMS FULLY REMOVED (2026-06, iteration_15) — verified backend testing agent 13/13
- **Per explicit user instruction**, Twilio/SMS was completely removed. VIen EMR now uses **EMAIL (Resend) + IN-PORTAL notifications only** for all appointment lifecycle events (confirm, physician direct-book, 24h reminder, reschedule, cancel). NO SMS.
- Removed from `notifications.py`: `_send_sms`, `SMS_SENDER`, `TWILIO_ENABLED`, and all `_send_sms(...)` calls. `schedule_reminders` now inserts **only** `reminder_type='email'`. `send_due_reminders` cancels any legacy `reminder_type='sms'` row **without sending** and without contacting Twilio.
- `backend/.env`: `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER` removed. `twilio` package uninstalled and dropped from requirements.txt.
- `.emergent/crons.yml` description updated (email reminders only); endpoint unchanged.
- **Historical `outbound_notifications` channel='sms' rows preserved as read-only** — never deleted. No new sms rows are created.
- Sections 95-102 above (Twilio LIVE) are now HISTORICAL/superseded.



## Patient-portal calendar booking (2026-06, iteration_13) — self-verified end-to-end (screenshot)
- Replaced the 3× "Preferred Option" dropdowns in Patient Portal → Request an Appointment with a visual monthly calendar flow: **Select Date → Select Available Time → Reason → Optional Note → Review → Submit**.
- `PortalAppointments.jsx` now uses shadcn `Calendar` (react-day-picker). Fetches `/api/availability/slots?days=60`, groups slots by date. Calendar `disabled` matcher = any date NOT in the available-dates set, so Fri/Sat/Sun, past dates, closures, vacations, blocked dates, and fully-booked/no-availability dates are all greyed/unclickable automatically (Mon–Thu 11:30–16:30 America/Toronto default). `fromDate`/`toDate` bound navigation to the availability window.
- After a date is picked, time buttons show only that day's remaining slots (office hours − confirmed − blocked − lunch − vacations/closures, via `generate_slots` busy subtraction — verified: an already-booked 4:00 PM slot was absent). Selecting a time reveals Reason + optional Note + a Review card ("YYYY Mon - DD at H:MM AM/PM"). Submit posts `options:[chosenSlot]` to the UNCHANGED `POST /api/portal/appointments` → still creates a REQUEST needing clinic approval.
- No backend change. Staff/Admin native calendar unchanged. Global date format `YYYY Mon - DD` preserved. New data-testids: appt-calendar, appt-time-<HH:MM>, appt-reason, appt-note, appt-review-when, appt-submit.

## Google Calendar appointment import + Link Patient (2026-06, iteration_14) — self-verified (curl + admin screenshot)
- **Office hours updated**: mon–thu end `16:30 → 17:00` (11:30 AM–5:00 PM) so 30-min slots run 11:30 AM…4:30 PM (last start 4:30), matching the clinic's real Google Calendar. Fri/Sat/Sun stay disabled. Reproduces the calendar's slot pattern exactly (verified against Thu 24 open-slot count).
- **One-time production import** `POST /api/internal/appointments/import` (admin): body `{appointments:[{date,time,patient_name,label?,reason?}], breaks:[{date,start,end,reason?}], dry_run?}`. Imported the Sep 21–24 + Sep 28 patient appointments as STATUS=confirmed (`imported:true`, `import_source:"google_calendar"`, `booked_from.source_type:"import"`). Skipped "Open x1" (available) and Friday "No citar". Breaks (3:00–3:30 each day) + Wed 23 "Recycling Day" 10:00–11:30 added to `availability.blocked_periods`.
- **41 created, 38 auto-linked, 3 flagged PATIENT LINK REQUIRED** (CHIRRILLO Joseph, VALERO UZCATEGUI Heidy Nailed, GUTIERREZ NUNEZ Darwin Steven — no single directory match). **Idempotent**: re-running skips existing (matched on imported + date + confirmed_slot_time); NOT seed data, persists across restarts/deploys.
- **No duplicate notifications**: import sends NO confirmation SMS/email (verified 0 outbound for imported appts). Linked appts still >24h away get normal 24h reminders scheduled (verified 76 pending = 38×email+sms); unlinked appts (patient_id null) get none.
- **Availability now reflects imports** (verified): Sep 21 & 22 → 0 open (fully booked, dates auto-disable in patient portal); Sep 24 → 9 open (4:30 booked + 3:00 break removed); Sep 28 → 1 open (12:30); Sep 29 → 10 open.
- **Matching helper** `_match_directory_by_name`: links only on EXACTLY ONE directory match (first+last, else last-only); never guesses → otherwise flags `patient_link_required:true`, stores `original_imported_name`.
- **Link Patient (staff/admin)**: `POST /api/internal/appointments/{id}/link-patient {directory_id}` — sets patient_id (linked_patient_id or directory id), visita_patient_id, patient_name from directory, clears the flag, preserves `original_imported_name`, records `linked_by`/`linked_at`, and schedules reminders if >24h out. Does NOT modify patient_directory. Reuses `GET /api/internal/directory?q=`. UI: AppointmentQueue detail shows a "PATIENT LINK REQUIRED" badge + inline directory search (name / VISITA ID / HCN) with per-result Link button (data-testids: patient-link-required, link-patient-open, link-patient-search, link-to-appointment-&lt;id&gt;).
- Imported appointments behave like native ones in the Admin calendar/queue (reschedule, cancel, complete, no-show, fee controls) and are NOT labeled demo data.


## Simplified Admin Calendar Block Day (2026-06, iteration_15) — self-verified (curl + screenshot)
- Replaced the Block time-range modal (start/end/reason) with one-click **Block Day**: confirm "Block all remaining available appointment slots for <YYYY Mon - DD>?" -> [Cancel]/[Block Day].
- `POST /api/internal/calendar/block-day {date}`: blocks every REMAINING open slot (one blocked_period per slot, tagged `block_day:true`). Existing appointments are NOT modified. Blocked slots vanish from Patient Portal availability; if none remain the date auto-disables.
- `POST /api/internal/calendar/unblock-day {date}`: removes ONLY `block_day:true` blocks for that date (appointments untouched).
- `GET /api/internal/calendar` day rows now include `day_blocked`; Calendar.jsx shows a red "DAY BLOCKED" banner + "Unblock Day" toggle. Verified on 2026-09-24: block -> patient open 9->0, appt kept; unblock -> 0->9, appt kept.

## Settings: grouped Blocked Days display (2026-06, iteration_16) — self-verified (screenshot)
- Settings > Physician Availability reorganized into labeled sections: WEEKLY AVAILABILITY (mon-thu hours + duration), BLOCKED DAYS, PARTIAL BLOCKS, VACATIONS, CLOSURES.
- BLOCKED DAYS: full-day blocks (blocked_periods with `block_day:true`) are grouped to ONE row per date (VIen format `YYYY Mon - DD`) with a single [Unblock] button (POST /internal/calendar/unblock-day -> restores slots, keeps appointments). Individual per-slot block records stay in scheduling logic but are hidden from the UI. Verified: 32 slot-blocks across 3 dates -> 3 rows.
- PARTIAL BLOCKS: non-block_day entries render one editable row each (date, start-end, reason) e.g. daily 3:00-3:30 Break, 09/23 Recycling Day 10:00-11:30. Editing writes back into the full blocked_periods array (block_day entries preserved on Save).

## Recurring Daily Break + de-cluttered availability (2026-06, iteration_17) — self-verified
- Daily break is now a RECURRING availability rule: availability doc `break_start:"15:00"`, `break_end:"15:30"` (in DEFAULT_AVAILABILITY too). `_slots_for_day` subtracts it on every working day, so 3:00 PM is NEVER offered to patients (verified 10-05 -> 10 slots, no 3:00 PM). Confirmed appointments unchanged.
- Purged the 7 old dated per-day "Break" (15:00-15:30) and the "Recycling Day" (10:00-11:30) records from blocked_periods (kept block_day entries). Recycling Day was a personal reminder, not scheduling.
- Settings UI: removed the "Partial Blocks" section; added a read-only DAILY BREAK row ("Mon-Thu | 3:00 PM-3:30 PM"). Final sections: Weekly Availability, Daily Break, Blocked Days, Vacations, Closures. Availability = weekly hours - recurring break - confirmed appts - blocked days - vacations - closures.

## PENDING: Production import of real schedule (awaiting deploy-live)
- Script (persistent, idempotent, stdlib-only): `/app/scripts/prod_import.py <LIVE_URL> <ADMIN_ID> <ADMIN_PW>`.
- Runs entirely via the LIVE site admin API (production DB is separate from preview). Validated against preview: login OK, sets Mon-Thu 11:30-17:00 + recurring break 15:00-15:30, imports 41 appts (idempotent: skips existing by imported+date+time), blocks 2026-09-29/09-30/10-01.
- On fresh production it will: create 41, link ~38, flag 3 PATIENT LINK REQUIRED (CHIRRILLO, VALERO UZCATEGUI, GUTIERREZ NUNEZ); NO confirmation SMS/email; schedule 24h reminders for linked appts still >24h out.
- Admin creds (same as seed): kevinrodriguez9528@gmail.com / VisitaAdmin2026!. RUN THIS ONCE the deployment is live, then verify admin calendar + patient-portal availability. Do NOT copy preview test bookings.

## Security/code-quality focused cleanup (2026-06, iteration_13-regression) — verified by testing_agent (no regressions)
- P1 hardcoded secret: tests/test_password_reset.py demo password now env-driven (DEMO_PATIENT_PASSWORD). NOTE: admin (VisitaAdmin2026!) + physician (Newman2013_!) passwords are hardcoded across several other test files and committed to git -> RECOMMENDED ROTATION (flagged to user; not yet actioned).
- P2 undefined vars: FALSE POSITIVE (pyflakes + pylint E0601/E0602 clean across backend).
- P3 auth token in sessionStorage -> HttpOnly cookie: DEFERRED (larger migration; needs logout endpoint, get_current_user cookie read, withCredentials, CORS origin change from *; forces re-login). Impact explained to user, awaiting go-ahead.
- P4 hook deps: FALSE POSITIVES (stable module imports + stable setState setters + local vars). Documented intentional empty-deps with comments in AuthContext.jsx, Settings.jsx, PortalAppointments.jsx. use-toast.js left (shadcn lib).
- P5 craco.config.js console: FALSE POSITIVE (build-time only, no sensitive data in shipped bundle).
- Also fixed array-index React keys -> stable keys in PortalAppointments.jsx & AppointmentQueue.jsx.
- Large refactors (seed.py/directory.py/AppointmentQueue/etc complexity) intentionally NOT done per user; remain backlog.

## Patient calendar real-availability + mobile + cache safety (2026-06, iteration_14) — verified by testing_agent (6/6 pass)
- CONFIRMED not a frontend bug in preview: patient calendar already uses backend /availability/slots as single source of truth (availableDates derived from backend; no hardcoded Mon-Thu). Verified Sep 21/22/23 DISABLED (0 slots), Sep 24 (9) / Sep 28 (1) ENABLED at 375/390/430px, no horizontal scroll, flow not clipped.
- Root cause of user seeing Sep21/22 selectable = the DEPLOYED PRODUCTION app (separate DB, no imports yet). Fix for prod = run /app/scripts/prod_import.py once live.
- Added cache-safety to PortalAppointments.jsx: slots query staleTime:0 + refetchOnMount:always + refetchOnWindowFocus; refetch on month change (onMonthChange) and on date pick; pre-submit re-check that re-fetches and shows \"This appointment time is no longer available. Please select another time.\" if the slot was taken. Both mobile+desktop use REACT_APP_BACKEND_URL (same origin).


## Pharmacy Portal + new "pharmacy" role (2026-06, iteration_16) — verified testing_agent 9/9 + curl
- NEW authenticated role `pharmacy`, locked to ONE pharmacy per account ("1670 Dufferin Drug Mart"). Reuses existing JWT/bcrypt auth (username login via same /signin), existing Rx pipeline (prescription_requests, source="pharmacy") and existing Messages pipeline (patient_messages, source="pharmacy").
- Pharmacy portal at /pharmacy (RoleRoute roles=["pharmacy"]). Nav ONLY: Rx | Messages | Account/Logout. Cannot reach /internal or /portal (redirect + backend 403).
- Rx: search patient (identity/contact only — name, PIN, DOB, home/cell, full address, HCN+version; NO clinical data) -> medication form (name*, strength, duration, pharmacy note, message to physician) -> attach JPG/PNG/PDF (camera or upload, 15MB) -> submit. Flows into clinic RxQueue with PHARMACY badge + downloadable attachment.
- Messages: pharmacy compose/reply with optional patient link, Rx ref, attachment. Folds into clinic MessageQueue with PHARMACY badge + pharmacy name; clinic replies via existing PATCH /internal/messages/{id} (patient_reply). notify_patient guarded to skip when source=="pharmacy" or no patient_id.
- Files: backend server.py (PHARMACY PORTAL section, ~L1909), seed.py (env-gated create-if-missing pharmacy account), frontend/src/pharmacy/{PharmacyLayout,PharmacyRx,PharmacyMessages,PharmacyAccount,shared}.jsx, App.js, RoleRoute.jsx, SignIn.jsx, internal/RxQueue.jsx, internal/MessageQueue.jsx, lib/api.js (openAttachment).
- Object storage (storage.py) reused for attachments; served ONLY via authenticated endpoints (no public URLs).
- PREVIEW pharmacy account seeded: 1670dufferin / Dufferin2026! (backend/.env PHARMACY_USERNAME/PASSWORD/NAME/ID). Attachments: pharmacy/rx & pharmacy/messages.
- PRODUCTION: real account is NOT created until PHARMACY_* prod secrets are set (deliberate, after user approval). Seed is strictly create-if-missing (never overwrites existing users/passwords). No production data touched by this feature.
- STATUS: Built & tested in Preview. AWAITING USER REVIEW before deploying to Production.

## Internal PATIENTS lookup (2026-06, agentic edit) — read-only, Preview-verified
- New internal sidebar section "Patients" (icon UserSearch) for admin/staff/physician ONLY (added to both role lists in InternalLayout). NOT in Pharmacy Portal.
- Backend: GET /api/internal/patient-lookup?q= (CLINIC_ROLES) searches patient_directory by name / VISITA PIN / health card (norm_hcn) / phone (flexible digit regex r"\D*".join(digits)). Returns _directory_snapshot: full_name, visita_patient_id, date_of_birth, age, home_phone, cell_phone, address_full, health_card_number + version_code, patient_status, current_pharmacy. Read-only; no writes.
- Frontend: frontend/src/internal/Patients.jsx (search + results + read-only snapshot panel), route /internal/patients, dates via formatDate (YYYY Mon - DD).
- Reuses existing directory_mod.norm_hcn + _age_from_dob. No clinical chart (meds/labs/imaging/referrals) exposed — placeholder note for future VISITA info.
- STATUS: built & verified in Preview (search by name/PIN/phone all work; snapshot matches spec). NOT yet deployed to production.

## Patients Lookup DEPLOYED to Production (2026-06) — verified
- Deploy 1: Patients lookup feature (GET /api/internal/patient-lookup + /internal/patients page). Verified live: name/PIN/HCN/phone search, snapshot fields, admin+physician access, unauthenticated 401, regressions OK, data unchanged (15 Rx; avail 11:30-17:00, break 15:00-15:30, 60 blocks).
- Deploy 2 (frontend-only): Patients UX fix — results collapse after selection, snapshot stays full-width, "Change Patient" reopens search, click-outside closes results; "—" fallback for empty rows. testing_agent iteration_17 PASSED all 4 UX behaviors + role access + no regressions. Verified live on production (bundle main.4984b7c3.js).
- Pharmacy note: production pharmacy 1670dufferin already completed its forced first-login password change (owns a private password). Not disturbed by deploys (create-if-missing seed).

## Rx Void / Archive soft-delete (2026-06, iteration_18) — testing_agent 4/4 backend + frontend PASS
- Staff/Admin can Void/Archive a prescription request (RxQueue detail -> "Void / Archive request", reason select [Duplicate / Entered by mistake / No longer needed / Other] -> Void Request). Physician -> 403.
- Backend server.py `_update_request`: `action=='void'` sets internal_status='voided', voided_by, voided_at, void_reason, completed_at; NO patient notification. Active queue (GET /api/internal/prescriptions) excludes voided via `$nin:['voided']`; `?status=voided` returns archived items. Soft-delete only — no hard delete.
- READ-ONLY hardening: any non-'void' action on an already-voided record returns 409; Queue.jsx hides forward-action buttons, internal-note input, and Book Appointment on voided items (shows read-only note + VOIDED/ARCHIVED banner with reason/by/at). RxQueue.jsx adds "Voided / Archived" filter + banner.
- Verified on Preview (curl + screenshot + testing_agent): active count 3 (no voided), voided filter 3 with banners, 409 on non-void action, data intact. Code-only deploy to Production triggered (2026-06); production data untouched (no reseed/reset/migration/imports).

## Patient Portal request simplifications + Patients dropdown (2026-06) — Preview-verified, code-only deploy triggered
- **Imaging** (PortalImaging.jsx): kept X-Ray/Ultrasound selector, optional Patient note, and disclaimer "This does not authorize imaging. Your request will be reviewed by the clinic and physician." Body part / region -> REQUIRED dropdown (Head/Skull, Neck, Chest, Abdomen, Pelvis, Cervical/Thoracic/Lumbar Spine, Shoulder, Arm/Elbow, Wrist/Hand, Hip, Leg/Knee, Ankle/Foot, Other). Reason -> REQUIRED dropdown (New symptoms / pain / injury; Follow-up / Repeat imaging; Other). No study/view choice, no appointment question. Backend /portal/imaging unchanged. data-testid img-reason, img-bodypart.
- **Bloodwork** (PortalBloodwork.jsx): free-text reason -> single REQUIRED dropdown (Routine / Annual bloodwork; Follow-up / Repeat bloodwork; New symptoms or health concern; Other) + optional note; kept "Dr. Aguayo decides…" note. Backend /portal/bloodwork unchanged. data-testid bld-reason.
- **Internal Patients** (Patients.jsx): search-results dropdown max-height now calc(100vh-13rem) (taller, more matches visible) — cosmetic.
- Frontend-only; no backend/schema changes, no hard deletes. Code-only Production deploy triggered together (user-approved); no production data modified.

## Patient email confirmations via Resend (2026-06) — Preview-verified (curl + DB), NOT deployed
- **Account verified email** (NEW): when Staff/Admin sets a patient's verification to "verified" AND it was not already verified, sends Resend email — subject "Your VIen EMR account has been verified" + in-portal "Account verified" note. Dedup: guarded by `was_verified` check so re-approving / unrelated edits do NOT resend (verified: 2nd approve created 0 extra emails). No clinical data in email. New: email_service.account_verified_html(name, portal_url); notifications.account_verified(db, patient); server.py verify_patient wired with was_verified guard. Logged to outbound_notifications (channel=email).
- **Appointment confirmed email** (already existed, satisfies request): notifications.appointment_confirmed fires on staff approve / physician book / calendar book → subject "Appointment Confirmed — Dr. Aguayo", body has date (YYYY Mon - DD) + time + Dr. Aguayo, portal link; no medical reason. Logged to outbound_notifications.
- Emails to fake @demo.com log status 'failed' gracefully (template passes the _assert_safe_email G2/G3 gate); real addresses send. Preview demo patient restored to pending after test.

## Appointment Type (In-Clinic / Telephone) (2026-06) — Preview-verified (curl+DB+screenshot), NOT deployed
- Patient booking (PortalAppointments.jsx): required Appointment type step (two selectable cards In-Clinic / Telephone with descriptions) shown before Reason; submit blocked until chosen. Review card shows "Type: In-Clinic/Telephone Appointment" + patient-facing note "Your appointment type and time are not confirmed until the clinic approves your request. You will be notified once it is confirmed." Sends appointment_type in POST /portal/appointments.
- Backend: AppointmentBody.appointment_type (IN_CLINIC|TELEPHONE, else None); create_appointment validates+stores on NEW requests only (no backfill). Serialized in portal overview appt_view, internal /internal/appointments (raw docs), and /internal/calendar day appointments. Preserved through approve/confirm (stored on the request doc).
- Confirmation: notifications.appointment_confirmed includes type label — in-portal "Your Telephone Appointment/In-Clinic Appointment…" + email (email_service.appointment_confirmed_html gains type_label row). _type_label -> 'Telephone Appointment' | 'In-Clinic Appointment' | 'Not specified'.
- Badges: reusable components/ApptTypeBadge.jsx (Hospital/Phone/HelpCircle lucide icons; IN-CLINIC green, PHONE sky, NOT SPECIFIED grey). Shown in patient request cards, internal AppointmentQueue new "Type" column + detail dialog, and Admin Calendar appointment cards (only when set). Existing appts without a type show "NOT SPECIFIED".
- DATA SAFETY: only new requests get a type; no modification/backfill of existing appointments; availability/scheduling rules unchanged. data-testids: appt-type-select, appt-type-IN_CLINIC, appt-type-TELEPHONE, appt-review-type, appt-not-confirmed-note, appt-type-badge-*, appt-detail-type.
- Default: patient booking pre-selects IN_CLINIC (still switchable; validation intact).
- Internal type EDIT (2026-06, Preview-verified curl+DB+screenshot, NOT deployed): PATCH /api/internal/appointments/{id}/type {appointment_type} — staff/physician/admin (CLINIC_ROLES). Updates appointment_type only (date/time/status/patient preserved), pushes history entry, audits set_type. Notifies patient (in-portal 'Appointment type updated' + Resend email 'Appointment Update — Dr. Aguayo', no clinical detail) ONLY when a CONFIRMED/rescheduled appt switches between two real types (IN_CLINIC<->TELEPHONE); NOT_SPECIFIED->type fill-in does NOT notify; no backfill. Reusable components/ApptTypeEditor.jsx (clickable badge + pencil -> dialog; confirm step before notifying on confirmed switch) wired into AppointmentQueue detail + Calendar cards; badge refreshes immediately via react-query invalidate/refetch. New: notifications.appointment_type_changed, email_service.appointment_type_changed_html. data-testids: appt-type-edit-<id>, appt-type-editor-dialog, appt-type-set-IN_CLINIC/TELEPHONE, appt-type-confirm-save/cancel.

## Clinic Calendar Month view (2026-06) — Preview-verified (screenshot), NOT deployed
- Calendar.jsx: added Day | Week | Month toggle; MONTH is now the DEFAULT view. New MonthGrid: Google-style 7-col grid (Sun-Sat), 6 rows (42 cells), full month + spillover days dimmed; prev/next by month, Today button, today highlighted (green pill). Each cell: date number, appt count, first 3 appts (time + surname via patient_name.split(',')[0]), "+ X more"; non-working days (backend `closed` = Fri/Sat/Sun) grayed; `day_blocked` shows small red BLOCKED badge with existing confirmed appts still visible. Clicking a date opens that date in the Day view. Reuses GET /internal/calendar (same source of truth); no scheduling/availability/block changes, no drag/resize.
- Backend server.py internal_calendar: `days` cap raised 14 -> 42 (read-only widening so Month can fetch 42 days from the grid's Sunday start). Day(1)/Week(7) unchanged. No data mutation.
- Day + Week views unchanged (verified: Week 7 cards/30 appts, Day 1 card with type editor + reschedule/complete/no-show/cancel + block). data-testids: cal-view-month, cal-month-grid, cal-month-cell, cal-month-today, cal-month-blocked, cal-month-appt, cal-month-more.
- Week/Day card COMPACTING (2026-06): tighter padding/margins, type editor + actions moved inline on one row, reason kept truncated — ~9 appts/column without scrolling. UI only.

## BUGFIX: Completing/past slots no longer bookable (2026-06) — testing_agent iteration_22 14/14 PASS, NOT deployed
- Root cause: get_busy_slots only counted confirmed/rescheduled, so COMPLETE/NO_SHOW freed the slot; and slot generation never filtered past times.
- Fix (source): server.py get_busy_slots now includes ['confirmed','rescheduled','completed','no_show'] (completed/no_show keep their slot). availability.py: new _now_cutoff (America/Toronto via zoneinfo) + is_past_slot; _slots_for_day/generate_slots/calendar_range skip past dates entirely and past times on today. Endpoint guards (is_past_slot) added to create_appointment (400), select_slot (409), patient reschedule (400), calendar_book (400), internal reschedule action (400). 'approve' action intentionally has NO past guard (confirms a requested time, not an availability pick).
- Also: internal_calendar days cap raised 14->42 (for Month view).
- Verified: complete/no_show keep slot occupied; today excludes past times; past-date open_slots []; patient+admin blocked from booking/rescheduling past (400/409); availability doc byte-identical; break/blocked rules intact. Preview only.





