"""Preview scenario: verified portal registration refreshes the canonical directory record on link. Self-cleaning."""
import os
import sys
import uuid

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
r = requests.post(f"{API}/auth/login", json={"identifier": "kevinrodriguez9528@gmail.com", "password": "VisitaAdmin2026!"})
TOK = r.json()["token"]; H = {"Authorization": f"Bearer {TOK}"}
PRACTICE = db.practices.find_one({}, {"id": 1})["id"]
out, ok, made = [], True, {"patients": [], "dirs": []}


def chk(n, c, e=""):
    global ok
    ok &= bool(c)
    out.append(f"{'PASS' if c else 'FAIL'}  {n} {e}")


def mk_dir(**kw):
    d = {"id": str(uuid.uuid4()), "first_name": "Qa", "last_name": "Mergecase", "date_of_birth": "1980-03-04", "patient_status": "ACTIVE",
         "practice_id": PRACTICE, "health_card_number": "9999000111", "import_source": "qa", "norm_first": "qa", "norm_last": "mergecase", "norm_dob": "1980-03-04", **kw}
    db.patient_directory.insert_one(d); made["dirs"].append(d["id"]); return d


def mk_portal(**kw):
    p = {"id": str(uuid.uuid4()), "first_name": "Qa", "last_name": "Mergecase", "date_of_birth": "1980-03-04", "email": f"qa.merge.{uuid.uuid4().hex[:6]}@example.test",
         "verification_status": "pending", "portal_status": "PENDING", "active_status": True, "practice_id": PRACTICE, "patient_type": "ohip",
         "health_card_number": "9999000111", "created_at": "2026-10-19T00:00:00+00:00", **kw}
    db.patients.insert_one(p); made["patients"].append(p["id"]); return p


def link(p, d):
    return requests.post(f"{API}/internal/verifications/{p['id']}", headers=H, json={"decision": "verified", "matched_patient_id": d["id"]})


def dir_now(d):
    return db.patient_directory.find_one({"id": d["id"]}, {"_id": 0})


def card(d):
    res = requests.get(f"{API}/internal/patient-lookup", headers=H, params={"q": "9999000111"}).json()
    return [x for x in res if x.get("directory_id") == d["id"] or x.get("id") == d["id"]]


# CASE 1 — canonical missing sex/issue/expiry (+ version) ; CASE 7 completeness
d1 = mk_dir(sex_code=None, health_card_version_code=None)
p1 = mk_portal(sex="Male", health_card_version="AB", health_card_issue_date="2025-05-01", health_card_expiry_date="2030-05-01", phone="(416) 555-0101",
               address="12 Test Street", city="Toronto", province="ON", postal_code="M1M 1M1")
r = link(p1, d1); chk("C1 link ok", r.status_code == 200, r.text[:100])
n = dir_now(d1)
chk("C1 canonical filled sex/version/issue/expiry", n.get("sex") == "Male" and n.get("sex_code") == "M" and n.get("health_card_version_code") == "AB" and n.get("health_card_issue_date") == "2025-05-01" and n.get("health_card_expiry_date") == "2030-05-01")
chk("C1 contact/address filled", n.get("cell_phone") == "(416) 555-0101" and n.get("address") == "12 Test Street" and n.get("postal_code") == "M1M 1M1" and n.get("email") == p1["email"])
c = card(d1); chk("C6 lookup → ONE canonical result, portal linked", len(c) == 1 and c[0]["source"] == "directory" and c[0]["patient_id"] == p1["id"], len(c))
chk("C7 card shows values + HC status VALID (not INCOMPLETE)", c and c[0]["sex"] == "Male" and c[0]["health_card_issue_date"] == "2025-05-01" and c[0]["health_card_status"] == "VALID", c and c[0]["health_card_status"])
a = db.audit_logs.find_one({"action": "canonical_refreshed_from_registration", "entity_id": d1["id"]})
chk("C1 audit: source + changes with from/to", a and a["meta"]["source"] == "VERIFIED_PORTAL_REGISTRATION" and a["meta"]["changes"]["health_card_issue_date"] == {"from": None, "to": "2025-05-01"} and a["meta"]["conflicts"] == {})
chk("C1 no conflicts", a and not a["meta"]["conflicts"])
chk("C6 no duplicate patient created", db.patients.count_documents({"health_card_number": "9999000111"}) == 1 and db.patient_directory.count_documents({"health_card_number": "9999000111"}) == 1)

# CASE 2 + 3 — stale version / older contact → updated
d2 = mk_dir(health_card_version_code="ZZ", email="old@example.test", cell_phone="(416) 555-0000", address="1 Old Rd", city="Ottawa", province="ON", postal_code="K1K 1K1", sex_code="F")
p2 = mk_portal(sex="Female", health_card_version="KL", email="new@example.test", phone="(647) 555-9999", address="99 New Ave", city="Toronto", province="ON", postal_code="M5V 2T6")
r = link(p2, d2); chk("C2/3 link ok", r.status_code == 200, r.text[:100]); n = dir_now(d2)
chk("C2 version code updated ZZ→KL", n.get("health_card_version_code") == "KL")
chk("C3 contact + address refreshed", n.get("email") == "new@example.test" and n.get("cell_phone") == "(647) 555-9999" and n.get("address") == "99 New Ave" and n.get("city") == "Toronto" and n.get("postal_code") == "M5V 2T6")
a = db.audit_logs.find_one({"action": "canonical_refreshed_from_registration", "entity_id": d2["id"]})
chk("C2/3 audit from/to", a and a["meta"]["changes"]["health_card_version_code"] == {"from": "ZZ", "to": "KL"} and a["meta"]["changes"]["email"]["from"] == "old@example.test")
chk("same-value sex (F/Female) → no change, no conflict", "sex" not in a["meta"]["changes"] and "sex" not in a["meta"]["conflicts"])

# CASE 4 — strong conflicts (DOB, HCN, sex) are NOT overwritten
d4 = mk_dir(date_of_birth="1979-01-01", health_card_number="9999000222", sex_code="M", health_card_version_code="AA", norm_dob="1979-01-01")
p4 = mk_portal(date_of_birth="1980-03-04", health_card_number="9999000333", sex="Female", health_card_version="BB")
r = link(p4, d4); chk("C4 link ok", r.status_code == 200, r.text[:100]); n = dir_now(d4)
chk("C4 DOB/HCN/sex NOT overwritten", n["date_of_birth"] == "1979-01-01" and n["health_card_number"] == "9999000222" and n["sex_code"] == "M" and not n.get("sex"))
chk("C4 non-identity current field still refreshed (version AA→BB)", n.get("health_card_version_code") == "BB")
a = db.audit_logs.find_one({"action": "canonical_refreshed_from_registration", "entity_id": d4["id"]})
chk("C4 conflicts recorded for review", a and set(a["meta"]["conflicts"]) == {"date_of_birth", "health_card_number", "sex"})
la = db.audit_logs.find_one({"action": "identity_linked", "entity_id": p4["id"]})
chk("C4 identity_linked audit lists conflicts", la and "date_of_birth" in la["meta"]["identity_conflicts"])

# CASE 5 — registration blank does not erase canonical
d5 = mk_dir(email="keep@example.test", cell_phone="(905) 555-1111", health_card_version_code="QQ", health_card_issue_date="2020-01-01", health_card_expiry_date="2027-01-01", address="5 Keep St", city="Hamilton", province="ON", postal_code="L8L 1A1", sex_code="M")
p5 = mk_portal(email=None, phone="", health_card_version=None, address=None, city=None, sex=None)
r = link(p5, d5); chk("C5 link ok", r.status_code == 200, r.text[:100]); n = dir_now(d5)
chk("C5 nothing erased", n["email"] == "keep@example.test" and n["cell_phone"] == "(905) 555-1111" and n["health_card_version_code"] == "QQ" and n["address"] == "5 Keep St" and n["sex_code"] == "M")
chk("C5 no refresh audit written (no changes/conflicts)", db.audit_logs.count_documents({"action": "canonical_refreshed_from_registration", "entity_id": d5["id"]}) == 0)

# practice scope: directory from another practice must not be touched
d6 = mk_dir(practice_id="other-practice-zzz", sex_code=None)
p6 = mk_portal(sex="Male")
r = link(p6, d6)
chk("C10 cross-practice link rejected or canonical untouched", r.status_code != 200 or not dir_now(d6).get("sex"), r.status_code)

print("\n".join(out))
db.patients.delete_many({"id": {"$in": made["patients"]}}); db.patient_directory.delete_many({"id": {"$in": made["dirs"]}})
db.practice_relationships.delete_many({"directory_id": {"$in": made["dirs"]}}) if "practice_relationships" in db.list_collection_names() else None
db.patient_practice_relationships.delete_many({"directory_id": {"$in": made["dirs"]}}) if "patient_practice_relationships" in db.list_collection_names() else None
print("cleanup:", db.patients.count_documents({"id": {"$in": made["patients"]}}), db.patient_directory.count_documents({"id": {"$in": made["dirs"]}}))
print("PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
