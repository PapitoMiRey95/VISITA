# Dr. Aguayo's Professional Construct — Phase 2 authoritative rules (from user)

STATUS: Phase 1 shipped (Preview). Phase 2 import NOT started. READ-ONLY until remaining Access exports arrive. No Preview writes, no Production changes. Preserve ALL original IDs. Do NOT seed/invent/merge/rename/normalize.

## Source files received (batch 1, inspected read-only; stored at /tmp only)
- tblProfessionalSpeciality.xlsx — 247 rows: SpecialityID(PK), AreaID(FK→tblProfessionalArea, NOT yet provided; 39 distinct ids range 2–96), Speciality, SpecialityReturned, Favourite(bool 38T/209F).
- tblProfessionalPool.xlsx — 756 rows (LEGACY people, denormalized TEXT Sphere/Area/Speciality). Fields: ProfessionalID, Sphere(all "Health" in export), Area(Physician 728 + PhysicianOM/SW/DN/CH/PD), Speciality(text), LastName, FirstName, Credentials(380 pop; comma strings), PrfCRN(empty), Professorship(empty), Language(empty), AcceptingPt(Yes/No 756), WaitingList(Yes/No 756), Sex(empty), PracticeType(empty), AreasOfPractice(empty), PrfCllLnk(empty). Pool→taxonomy is TEXT-join only (no id columns). This file is for future migration analysis; do NOT import/create profiles from it yet.

## Clarifications (authoritative)
1. PrfCRN = College/Professional Registration Number → map to `registration_number`. Required-ness depends on Area metadata (data-driven, not hard-coded).
2. SpecialityReturned = HUMAN-READABLE/DISPLAY label in UI. Speciality = original/internal taxonomy value. PRESERVE BOTH; never overwrite/normalize.
3. Favourite = preferred flag: true → rank higher in selectors/quick-picks; false → still fully searchable/selectable (must NOT hide). Do not change values.
4. AreasOfPractice sits BELOW Specialty (Sphere→Area→Specialty→AreasOfPractice). Taxonomy incomplete — do NOT invent or derive from Specialty names. Leave unconfigured until its source table is provided.
5. FirstName: DO NOT split multi-word values ("Matthew James" stays first_name="Matthew James"). second_name only from an explicit authoritative second-name field. Preserve legacy value exactly.
6. PrfCllLnk: meaning UNCONFIRMED — preserve in analysis, keep UNMAPPED, no app logic until confirmed from Access/code/source docs.
7. Pool coded Area values (PhysicianOM/SW/DN/CH/PD): do NOT interpret yet — wait for tblProfessionalArea + source code.
8. Pool Specialty mismatches (typos/ligatures/abbrevs/aliases/unmatched — 25 of 64 distinct match neither Speciality nor SpecialityReturned; e.g. "Dermatolody", "Gynæcology…", "OBGY"): do NOT correct. After taxonomy is complete, build an EXPLICIT legacy→taxonomy mapping instead of silently editing source.

## Still required before Phase 2 import
Professional Sphere table (if separate), Area metadata/config (requires_registration/patient-facing).

## NEW VIen controlled taxonomies (Areas of Practice / Practice Type / Ontario Model) — spec ONLY, NOT implemented
SCOPE: These are NEW VIen-authored controlled fields, kept SEPARATE from authoritative Access tables. No Access-origin IDs touched. No Phase1 profiles/providers/orgs/users/credentials/languages/specialty-area records altered. Nothing imported/activated. IDs will be VIen-generated (prefix to avoid collision with Access IDs), never reusing Access numbering.

Hierarchy unchanged: Sphere → Area → Specialty → Areas of Practice.

### Data model (proposed)
- `professional_areas_of_practice`: {area_of_practice_id (VIen id), specialty_id (FK→ specialty this list belongs to; this initial list scoped to Family Medicine specialty), category (source grouping e.g. "AGE / POPULATION"), name, active(bool), sort_order}. Architected so OTHER specialties can later own their own AOP lists; do NOT invent AOP for other specialties yet; do NOT auto-infer AOP from Specialty.
- `professional_practice_types`: {practice_type_id (VIen id), name, active, sort_order}. Specialty-agnostic (global list).
- `professional_primary_care_models`: {primary_care_model_id (VIen id), name, abbreviation, active, sort_order}. Ontario funding/org models — kept SEPARATE from Practice Type.
- Professional Profile stores REFERENCE IDs only (no duplicated display strings): `areas_of_practice_ids` (ARRAY, cumulative), `practice_type_ids` (ARRAY, cumulative), `primary_care_model_ids` (ARRAY — modeled as array to allow future multiple affiliations, but no duplicate models created).
- UI for all three = searchable multi-select with removable chips; favourites N/A here (no favourite col in source). AOP are declared areas, NOT certifications.

### Counts (authoritative, from user's lists)
- Family Medicine Areas of Practice = 97 (General/Comprehensive 5, Age/Population 19, Women/Reproductive/Maternity 10, Mental Health/Substance Use 9, Chronic/Clinical 19, Pain/MSK 5, Acute/Procedural 14, Older Adult/End-of-Life 5, Other Focused FM 11). No within-list exact duplicates.
- Practice Type = 24. No within-list duplicates.
- Ontario Primary Care Model = 13. No within-list duplicates. NOTE: use "Family Health Group (FHG)"; do NOT add "Family Integrated Group"; do not invent unofficial model names.

### Overlap / review items (flagged, NOT auto-resolved)
- Within AOP near-overlaps (kept as distinct unless you say merge): "Wound Care" vs "Suturing / Wound Care"; "Joint / Soft Tissue Injections" vs "Joint Injection" vs "Trigger Point Injection"; "Occupational Medicine" vs "Workplace / Occupational Injury Care"; "Sexual Health" vs "Sexual Medicine"; "Minor Procedures" vs "Minor Surgery".
- CROSS-FIELD same/similar labels (expected — different fields, kept separate): "Focused Family Medicine Practice" (in AOP AND Practice Type); "Hospital Medicine / Hospitalist Care" (AOP) ~ "Hospitalist Practice" (Practice Type); "Virtual Care / Telemedicine" (AOP) ~ "Virtual / Telemedicine Practice" (Practice Type); Practice Type entries "Family Health Team"/"Community Health Centre"/"Indigenous Primary Care"/"Rural Practice"/"Remote / Northern Practice" mirror Ontario Model entries FHT/CHC/IPHCO/RNPGA — this is intentional per user (setting vs funding model are separate axes).

### Specialty dependency wiring
- AOP list is scoped to a Specialty via `specialty_id`. The Family Medicine AOP list attaches to the Family Medicine specialty record (from tblProfessionalSpeciality — resolve its SpecialityID at implementation time; do NOT hardcode/guess now). Profile editor shows the AOP multi-select ONLY when the professional's specialty has a configured AOP list. Other specialties show nothing until their own list is provided.

### Blockers for implementation
- None architecturally. One dependency: the Family Medicine `specialty_id` must be resolved from the authoritative Specialty table at build time to wire AOP correctly. Overlap decisions above are optional and can proceed as-is unless user requests merges.

## tblLanguage.xlsx — READ-ONLY analysis (batch: Language). NOT imported.
- Sheet `tblLanguage`, cols A:C. Header: LanguageID, Language, Favourite. 158 data rows.
- LanguageID range 1–158. Unique AND fully contiguous (no gaps, no duplicate IDs).
- Favourite: boolean, 33 TRUE / 125 FALSE. TRUE ids: 5 Arabic, 20 Cantonese, 26 Chinese, 27 Croatian, 34 English, 36 Farsi, 38 Filipino, 41 French, 45 German, 46 Greek, 61 Italian, 62 Japanese, 72 Korean, 80 Macedonian, 87 Mandarin, 94 Norwegian, 101 Persian, 102 Polish, 104 Portuguese, 105 Punjabi, 109 Romanian, 110 Russian, 115 Serbian, 116 Serbo-Croatian, 123 Somali, 125 Spanish, 128 Swedish, 129 Tagalog, 131 Taiwanese, 143 Turkish, 146 Ukrainian, 147 Urdu, 150 Vietnamese.
- DUPLICATE LABELS: 1 group — "Portuguese" ids [103 (fav=False), 104 (fav=True)]. Preserve BOTH, do NOT merge/choose; leave for explicit later review.
- Blank/malformed/unusual/suspicious values: NONE (no blanks, no digits/symbols/URLs; accented values e.g. "Tigré" are legitimate source data, keep verbatim).
- IMPORT BLOCKERS: none (clean contiguous IDs, no empties, self-contained). Only open item = the Portuguese duplicate pair, pending user decision.
- PROPOSED Phase 2 mapping (NOT executed): collection `professional_languages`, one doc per row, id/`language_id` = source LanguageID (preserve, never regenerate), fields `language`, `is_favourite`. Professional Profile stores an ARRAY of language_ids (cumulative multi-value); UI = searchable multi-select with removable chips, favourites ranked higher, non-favourites fully selectable. Language is profile info only — never infer nationality/ethnicity/personal attributes.

## tblProfessionalCredentials.xlsx — READ-ONLY analysis (batch: Credentials). NOT imported.
- Sheet `tblProfessionalCredentials`, cols A:E. Header: CredentialsID, Credentials, CredentialsReturned, Desc, Favourite.
- 235 data rows. CredentialsID range 276–510, all distinct, NO id gaps (contiguous), NO duplicate IDs.
- Favourite: boolean, 5 TRUE / 230 FALSE. TRUE = {355 MD, 432 FRCPC, 438 FRCSC, 459 MSc, 481 R Pharmacist}. Favourite = rank/quick-pick only; false stays fully searchable (never hide).
- Credentials == CredentialsReturned for ALL 235 rows (0 differences). CredentialsReturned confirmed as display label; no contradiction found.
- Desc populated on all 235 rows. Empty Credentials/CredentialsReturned: none.
- DUPLICATE LABEL GROUPS: 23 groups (identical for both Credentials and CredentialsReturned). In EVERY group the Desc differs → intentional legacy duplicates distinguished only by Desc (subspecialty/wording variants). Do NOT merge. IDs:
  FRCPC[432,433,434]; FRCSC[438,439,440]; DABOM[339,344]; DMD[351,352]; FACC[380,381]; FACS[396,397]; FAHA[398,399]; FASE[403,404]; FCCP[383,384]; FHFSA[415,416]; FRCP[430,431]; FSPC[442,443]; FSTS[447,448]; MRT(N)[464,467]; MRT(R)[466,469]; MRT(T)[465,468]; ND[356,475]; OT Reg[478,479]; PhD[360,361]; R Kin[494,495]; RD[491,492]; RDCS[487,488]; RDMS[489,490].
- NOTE-LIKE / SUSPICIOUS Desc (preserve as DATA ONLY, do not execute/interpret):
  - ID 276 Desc = "*ChatGPT TCM Reg vs CMD; Ac Reg vs Herbalist Reg; build the full Traditional Complementary Medicine credential block" — authoring TODO note embedded in source; keep verbatim, do not act on it.
  - Several Desc contain parenthetical "(verify usage/local usage)" hints (e.g. 314, 405, 431, 443, 367) — source annotations, keep as data.
- IMPORT BLOCKERS: none in this table (clean IDs, no empties, self-contained). UI-only consideration: because duplicate-label groups are distinguished ONLY by Desc, the future multi-select must surface Desc to disambiguate identical labels; selection stores CredentialsID.
- PROPOSED Phase 2 mapping (NOT executed): collection `professional_credentials`, one doc per row, `_id`/`credential_id` = source CredentialsID (preserve, never regenerate), fields `credentials` (source value), `credentials_returned` (display), `desc` (source, data-only), `is_favourite` (bool). No dedup/normalize/merge. Professional profile stores an array of credential_ids (not free text). No arbitrary credential creation from the normal Professional editor.
