# prod_unstamped_18 — appointment_requests (practice_id null/missing, status in [requested,confirmed,rescheduled])

Source: READ-ONLY mongo_query against deployed DB `visita-admin-test_database`, run 825b53cd-58dc-481c-9ebf-bb0fe76d659d.
count = 18, find returned 18 (not truncated). `ref` = stored `ref_number`. No `rescheduled` rows present (all are requested/confirmed).

NOTE: the requested target filename was /app/deployer-agent-docs/prod_unstamped_18.json. The deployer agent can only write to this fixed RCA path, so the array is persisted here instead.

```json
[
  {"ref": "APT-000097", "id": "6a72ddf6-0ebe-41ab-b972-39730611fa7a", "status": "confirmed"},
  {"ref": "APT-000099", "id": "6f52a19b-2e05-4202-8c7a-b680a1079686", "status": "requested"},
  {"ref": "APT-000100", "id": "ff339408-03ae-40d3-bb7e-af0406b03f6a", "status": "requested"},
  {"ref": "APT-000101", "id": "142bbafb-8039-42cb-ab4e-ed789d2d9191", "status": "confirmed"},
  {"ref": "APT-000102", "id": "a89278b8-dd06-423d-aba6-817fb8ebcba6", "status": "confirmed"},
  {"ref": "APT-000103", "id": "0df748b8-9ed2-4607-af8c-2e36fd5563b0", "status": "requested"},
  {"ref": "APT-000105", "id": "ee91da8a-a946-41f9-b5dd-0b2a3f8395be", "status": "requested"},
  {"ref": "APT-000107", "id": "d6c5fdc4-8357-4b83-bbb8-62747526fb62", "status": "requested"},
  {"ref": "APT-000109", "id": "ef442088-32c8-4e5f-a83d-21b7869185ab", "status": "confirmed"},
  {"ref": "APT-000110", "id": "71c04074-f3cd-4bbf-94fe-ee30543a2035", "status": "confirmed"},
  {"ref": "APT-000111", "id": "1bfd8c83-3445-4b40-bc7a-18fc172cec21", "status": "confirmed"},
  {"ref": "APT-000114", "id": "31da1ae7-0241-494a-b114-905c180fdb1e", "status": "confirmed"},
  {"ref": "APT-000115", "id": "89015cf1-b168-465b-886c-e295919aad4d", "status": "confirmed"},
  {"ref": "APT-000117", "id": "0fe0c1ec-4102-4493-abc5-2f0dccd6b301", "status": "confirmed"},
  {"ref": "APT-000119", "id": "f46c3989-10ae-4550-8439-6eb7c81234ed", "status": "confirmed"},
  {"ref": "APT-000121", "id": "b4c44287-9de3-4571-8220-df98adfeed10", "status": "confirmed"},
  {"ref": "APT-000123", "id": "9db6ce8e-eed1-4723-8d6b-b8d5bda006a2", "status": "confirmed"},
  {"ref": "APT-000124", "id": "9c559379-cfe9-4df0-8700-94c8689ffcb5", "status": "confirmed"}
]
```
