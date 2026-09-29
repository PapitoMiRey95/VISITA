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
tblProfessionalArea (id→name + metadata e.g. requires_registration/patient-facing), Professional Sphere table (if separate), tblProfessionalCredentials, Professional Language, Practice Type, Area metadata/config, Areas of Practice (if exists).
