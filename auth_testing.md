# VIsita EMR — Auth & Storage testing notes

## Google Sign-In (Emergent-managed) — PATIENTS ONLY
This app does NOT use the Emergent session_token/cookie model. Google is only an
alternative way to obtain the app's existing JWT.

Flow:
1. Patient Sign-In page (/signin, patient variant only) → "Continue with Google"
   redirects to https://auth.emergentagent.com/?redirect=<origin>/signin
2. Returns to /signin#session_id=... ; frontend posts { session_id } to
   POST /api/auth/google
3. Backend GETs Emergent session-data (X-Session-ID), extracts {id(sub), email},
   matches an EXISTING patient user by exact normalized email (role=patient),
   links google_sub on first login, then issues the normal app JWT.

Rules verified:
- No account auto-creation (unmatched email → 404 with the exact copy).
- Non-patient roles rejected (patient-only).
- Inactive/disabled accounts still blocked (same as password login).
- google_sub mismatch on a later login → 403.
- Audit: google_login_no_account / google_account_linked / google_login_success.

Because a real Google account is required for a true browser E2E, backend logic is
covered by: `python -m tests.test_google_auth_manual` (from /app/backend) which
mocks the Emergent session-data call and exercises all branches against the real
app + Mongo. Frontend: button appears only on patient /signin and launches OAuth.

## Internal Attachments (Phase 1) — staff/physician/admin only
- Upload: POST /api/internal/{entity_type}/{entity_id}/attachments (multipart "file")
  entity_type ∈ {imaging, bloodwork, message}. PDF/JPG/PNG only, 15 MB max.
- List:   GET  /api/internal/{entity_type}/{entity_id}/attachments
- Download: GET /api/internal/attachments/{att_id}/download  (also ?auth=<jwt> for img)
- Remove (soft): DELETE /api/internal/attachments/{att_id}
- Patients/pharmacy/partner have NO access (403). No public URLs. Metadata in Mongo
  `attachments` collection (soft-delete via is_deleted). Referral PDFs unchanged.
