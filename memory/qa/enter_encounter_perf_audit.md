# Enter Encounter — read-only performance audit (2026-10-22)

Flow measured: Patients detail → "Enter Encounter" → `/internal/encounter?patient_ref=…` → `GET /api/internal/visits/ready` → Workspace.
Only ONE entry point exists in code (`StartEncounterButton` is used solely in `internal/Patients.jsx`); Work Hub / appointment queue has no Enter Encounter button. The `/internal/encounter/:visitId` route (unsigned-visits banner, Visit Hx) uses `GET /internal/visits/{id}` which has the same shape plus an audit insert.

## Preview (browser in-cluster, 3 runs, test physician PAGUAYO, patient Maria Lopez)
click→"Loading encounter…" 30–44 ms · click→shell rendered 150–214 ms · click→SOAP editable 205–251 ms · network idle 209–269 ms.
Waterfall: 0–22 ms route change · 22→131 ms `/visits/ready` (108 ms, 3.5 KB) · 150 ms shell paints · 110/111→170–230 ms 8 parallel satellite calls (recent-vitals, metrics-summary, annual-exam-month, service-catalog, conditions, surgeries, allergies, visits) · 336→382 ms issue-plan-history + soap-helpers (debounced).
Backend compute for `/visits/ready` on localhost: ~6 ms; Mongo ops: users, patients, visits, patient_medications, appointment_requests, attachments = 6 sequential round-trips (7 when the patient is directory-linked). Each satellite = 3 sequential round-trips (users, patients, own query).
Dev-only artefact: every call appears twice in Preview = React 18 StrictMode double-effect (not present in the Production build).

## Production (unauthenticated only — authenticated gap)
`/api/internal/visits/ready` 401 (0 DB): min 157 / p50 232 / p75 367 ms. 1-DB-query public endpoint: min 214 / p50 235 ms → inferred ~40–55 ms per Mongo round-trip (remote cluster) vs <1 ms in Preview. SPA = single 1.87 MB `main.js`, no code-splitting; Encounter is in the same bundle so NO chunk is fetched on click.
Estimated Prod `/visits/ready` server time = floor ~160 ms + 6–7 × ~45 ms ≈ 430–500 ms; plus browser RTT to edge, plus satellites (floor + 3 × 45 ≈ 300 ms) that start only after the shell → ~750–900 ms to "panels filled"; ≈1 s with the old 0.05 vCPU throttling.

## Slowest 3
1. `/visits/ready` — 6–7 sequential Mongo round-trips, 2 of them (appointment_requests, attachments + N parent lookups) build `context.recent_appointments` / `context.documents` that the UI never reads.
2. Second wave: 8 satellite requests each re-doing auth + identity resolution (24 Mongo ops) and gated behind the shell.
3. Mongo RTT in Prod (remote cluster) multiplied by the sequential chain; no `id` index on `patient_directory` (COLLSCAN 842 docs) and none on patient_medications/appointment_requests/attachments (small today).

## Cause of visible "Loading encounter…"
The whole Workspace is gated on `shell` (`/visits/ready`); nothing renders until that single sequential-chain request returns. In Prod that is ~450 ms+ of server time plus the user's RTT, during which the placeholder shows.
