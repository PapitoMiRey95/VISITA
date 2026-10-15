"""Read-only Production smoke test (admin only). Creates NOTHING except, when --create-synthetic is passed,
the two approved synthetic directory patients via the token-gated admin endpoint (idempotent).
Usage: PROD_URL=https://visitaemr.com ADMIN_EMAIL=... ADMIN_PASSWORD=... [MAINTENANCE_TOKEN=...] python ops/prod_smoke_test.py [--create-synthetic]
"""
import os
import sys
import requests

BASE = os.environ["PROD_URL"].rstrip("/")
H = {}
results = []


def check(name, ok, info=""):
    results.append((name, ok, info))
    print(("PASS" if ok else "FAIL"), name, info)


def get(path, **kw):
    return requests.get(f"{BASE}{path}", headers=H, timeout=30, **kw)


r = requests.get(f"{BASE}/api/practices", timeout=30)
check("app load /api/practices", r.status_code == 200, str(r.status_code))
r = requests.post(f"{BASE}/api/auth/login", json={"identifier": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]}, timeout=30)
check("admin login", r.status_code == 200, str(r.status_code))
H = {"Authorization": f"Bearer {r.json()['token']}"}
me = get("/api/auth/me").json().get("user", {})
check("auth/me admin", me.get("role") == "admin", f"encounter_enabled={me.get('encounter_enabled')}")

r = get("/api/internal/patient-lookup", params={"q": "a"})
check("patient search", r.status_code == 200 and isinstance(r.json(), list), f"{r.status_code} n={len(r.json()) if r.ok else '-'}")
r = get("/api/internal/directory", params={"q": "a"})
check("directory search", r.status_code == 200, str(r.status_code))
d_count = None
r = get("/api/internal/counters")
check("counters (work hub)", r.status_code == 200, str(r.status_code))
r = get("/api/internal/appointments", params={"status": "confirmed"})
check("appointments list", r.status_code == 200, f"{r.status_code} n={len(r.json()) if r.ok else '-'}")
r = get("/api/internal/appointments/reviews")
ok = r.status_code == 200 and "week_flags" in r.json()
check("duplicate-booking guard endpoint", ok, f"{r.status_code} week_flags={len(r.json().get('week_flags', [])) if ok else '-'} same_day_dupes={len(r.json().get('same_day_duplicates', [])) if ok else '-'}")
r = get("/api/internal/calendar", params={"days": 7})
check("calendar", r.status_code == 200, str(r.status_code))
r = get("/api/availability/slots", params={"days": 7})
check("availability slots", r.status_code == 200, str(r.status_code))
r = get("/api/internal/prescriptions")
check("Rx queue load", r.status_code == 200, f"{r.status_code} n={len(r.json()) if r.ok else '-'}")
r = get("/api/internal/send-rx")
check("send-rx recently sent (read)", r.status_code == 200, str(r.status_code))
r = get("/api/internal/pharmacies")
check("pharmacies list", r.status_code == 200, str(r.status_code))
r = get("/api/internal/audit", params={"limit": 5})
check("Audit & Compliance read", r.status_code in (200, 404), str(r.status_code))
r = get("/api/internal/identity-cleanup")
check("identity cleanup list (read-only)", r.status_code == 200, f"{r.status_code} n={len(r.json()) if r.ok and isinstance(r.json(), list) else '-'}")
r = get("/api/internal/verifications")
check("verifications queue", r.status_code == 200, str(r.status_code))

if "--create-synthetic" in sys.argv:
    r = requests.post(f"{BASE}/api/internal/admin/synthetic-test-patients", headers=H, json={"token": os.environ["MAINTENANCE_TOKEN"]}, timeout=30)
    check("create synthetic test patients", r.status_code == 200, r.text[:300])
    if r.ok:
        for p in r.json()["patients"]:
            rr = get("/api/internal/patient-lookup", params={"q": p["visita_patient_id"]})
            hit = [x for x in rr.json() if x.get("visita_patient_id") == p["visita_patient_id"]] if rr.ok else []
            check(f"synthetic {p['visita_patient_id']} searchable + flagged", bool(hit) and hit[0].get("is_synthetic") is True,
                  f"{hit[0].get('last_name') if hit else '-'}, {hit[0].get('first_name') if hit else '-'}")
            rr = get(f"/api/internal/patients/directory:{p['id']}/visits")
            check(f"visit hx read for {p['visita_patient_id']} (admin)", rr.status_code == 200, str(rr.status_code))

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)
