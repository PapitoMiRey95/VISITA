# VIen Address Legacy Import Manifest

## Source files

- `tblAddress.xlsx` — legacy street-name pool (`AddressID`, `Address`, `ProvID`, `Favourite`, `Favourite2`); 1,474 data rows.
- `tblAddressType.xlsx` — street type/suffix pool (`AddressTypeID`, `AddressType`, `Favourite`); 117 data rows. Examples: Avenue, Boulevard, Road, Street.
- `tblAddressSubType.xlsx` — directional suffix pool (`AddressSubTypeID`, `AddressSubType`); 4 data rows: East, North, South, West.
- `tblPostalCode.xlsx` — postal-code pool (`PostalCodeID`, `PostalCode`, `CityID`, `ProvID`, `Favourite`); 13,230 data rows. Postal code maps to CityID + ProvID.
- `tblCity.xlsx` — city/locality pool (`CityID`, `City`, `ProvID`, `Favourite`, `Favourite2`); 288 data rows, including 267 Ontario rows.
- `tblProv.xlsx` — province/territory pool (`ProvID`, `Prov`, `FullProv`); 13 data rows. Ontario = ProvID 9 / ON.

## Important semantic correction

Legacy names are misleading if read literally:

- `Address` = street-name pool, not necessarily a complete civic address.
- `Address Type` = street suffix/type (Avenue, Boulevard, Road, Street, etc.), NOT location/entity type.
- `Address Subtype` = street directional suffix (East, North, South, West), NOT a clinic/hospital subtype.

Location context such as Practice / Clinic / Hospital / Department must remain a separate VIen concept.

## Toronto display convention requested by Dr. Aguayo

Canonical display labels for current VIen UI:

- Toronto
- Toronto York
- Toronto North York
- Toronto East York
- Toronto Etobicoke
- Toronto Scarborough

Legacy source aliases that must remain matchable/importable:

- `Toronto York North` -> canonical display `Toronto North York`
- `Toronto York East` -> canonical display `Toronto East York`

Do not rewrite the source XLSX files. Preserve source IDs/labels as import aliases where useful.

## Postal-code behavior

- Normalize postal code for lookup (uppercase, Canadian `A1A 1A1` display format).
- If postal code exists in the pool, use its `CityID` and `ProvID` to suggest/populate City + Province.
- Do not overwrite a City/Province value the user has deliberately edited/confirmed.
- Ontario (`ON`) may be the default for current Ontario workflows, but the province model must remain Canada-capable because `tblProv` contains all provinces/territories.
- Unknown postal codes must never block address entry.
- Internal staff/physician forms may offer `+ Add postal code` to add a reviewed new Postal Code + City + Province to the shared pool.
- Patient-facing registration/profile may accept an unknown postal code and manual City/Province, but should NOT silently teach the global shared postal-code pool from unreviewed patient input. Store/queue it as a candidate for review if desired.

## Address-entry behavior

Where VIen captures an address, preserve any existing civic-number/unit fields already present in the current schema. Do not drop them merely because they are absent from these pool files.

Use the legacy pools as standardization/autocomplete assistance:

1. civic/street number (existing VIen field, if present)
2. Address / street name
3. Address Type / street suffix
4. Address Subtype / directional suffix (optional)
5. unit/suite (existing VIen field, if present)
6. Postal Code
7. City
8. Province (default ON where appropriate)

Assemble a human-readable display address, e.g. `1214 Lansdowne Avenue`, while retaining the structured components.

Do not require a street name to already exist in `tblAddress`; allow `+ Add` / manual entry so the pool can evolve.

## Data-integrity rule

The pool should assist standardization, not become a hard blocker. Preserve original user-entered text and stable source IDs/aliases where useful. Never silently normalize a confirmed address into a different address.
