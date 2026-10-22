import json, requests
API = [l.split("=", 1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL")][0] + "/api"
tok = requests.post(f"{API}/auth/login", json={"email": "kevinrodriguez9528@gmail.com", "password": "VisitaAdmin2026!"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}
g = lambda path, **p: requests.get(f"{API}{path}", params=p, headers=H).json()
def post(path, body, expect=200, auth=True):
    x = requests.post(f"{API}{path}", json=body, headers=H if auth else {}); assert x.status_code == expect, (path, body, x.status_code, x.text); return x.json()
# A/B/C postal + Toronto canonical
a = g("/internal/address/postal-lookup", postal="m6e4h1"); print("A", a); assert a["city"] == "Toronto York" and a["province"] == "ON" and a["city_id"] == 244
from pymongo import MongoClient
env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l and not l.startswith("#"))
db = MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
ny = db.ref_postal_codes.find_one({"city_id": 157}); ey = db.ref_postal_codes.find_one({"city_id": 67})
b = g("/internal/address/postal-lookup", postal=ny["_id"]); print("B", ny["_id"], b["city"]); assert b["city"] == "Toronto North York"
c = g("/internal/address/postal-lookup", postal=ey["_id"]); print("C", ey["_id"], c["city"]); assert c["city"] == "Toronto East York"
print("B-alias search:", [x["name"] for x in g("/internal/address/cities", q="York North")])  # legacy alias still matches
# D unknown does not block (location with manual city/province)
d = g("/internal/address/postal-lookup", postal="K9Z 9Z9"); assert d["found"] is False; print("D", d)
# E internal add postal → future lookup succeeds
e = post("/internal/address/postal-codes", {"postal_code": "K9Z9Z9", "city": "Peterborough", "province": "ON"}); print("E", e, g("/internal/address/postal-lookup", postal="K9Z 9Z9")["found"])
post("/internal/address/postal-codes", {"postal_code": "M6E4H1", "city": "X", "province": "ON"}, 409)  # cannot override legacy mapping
# F patient unknown → candidate only, pool untouched
f = post("/public/address/postal-candidate", {"postal_code": "L9Z 9Z9", "city": "Barrie", "province": "ON"}, auth=False); print("F", f, "pool has it:", bool(db.ref_postal_codes.find_one({"_id": "L9Z9Z9"})), "candidate:", bool(db.ref_postal_candidates.find_one({"postal_norm": "L9Z9Z9"})))
print("F public lookup:", requests.get(f"{API}/public/address/postal-lookup", params={"postal": "M6E 4H1"}).json())
# G/H/I/J/K locations
pr = post("/professionals", {"surname": "QATEMPSMITH", "first_name": "Jane", "title": "Dr."}); pid = pr.get("id") or pr["profile"]["id"]
l1 = post("/internal/locations", {"entity_type": "professional", "entity_id": pid, "label": "Lansdowne office", "location_type": "PRACTICE", "location_subtype": "SPECIALIST_OFFICE", "street_number": "1214", "street_name": "Lansdowne", "street_type": "Avenue", "postal_code": "M6E 4H1", "city": "Toronto York", "province": "ON", "fax": "416-555-0101"})
print("G", l1["address"], "|", l1["display_line"]); assert l1["address"] == "1214 Lansdowne Avenue"
l2 = post("/internal/locations", {"entity_type": "professional", "entity_id": pid, "label": "Main St office", "location_type": "PRACTICE", "location_subtype": "MAIN_OFFICE", "street_number": "123", "street_name": "Main", "street_type": "Street", "street_direction": "West", "unit": "Suite 410A", "postal_code": "M5G 1X5", "city": "Toronto", "province": "ON", "fax": "416-555-0202"})
print("H/I", l2["address"]); assert l2["address"] == "123 Main Street West, Suite 410A" and l2["unit"] == "Suite 410A"
rows = g("/internal/locations", entity_type="professional", entity_id=pid); print("J", len(rows), [(r["label"], r["fax"]) for r in rows]); assert len(rows) == 2
k = post("/internal/locations", {"entity_type": "destination", "label": "QATEMP Mount Sinai — Cardiology Referral Service", "specialty": "Cardiology", "location_type": "HOSPITAL", "location_subtype": "REFERRAL_INTAKE", "street_number": "700", "street_name": "University", "street_type": "Avenue", "postal_code": "M5G 1Z5", "city": "Toronto", "province": "ON", "fax": "416-555-0404"})
print("K", k["location_type_label"], k["location_subtype_label"], k["address"]); assert "location_type" in k and "address_type" not in k
# L legacy free-text address (no components) stays byte-for-byte
l3 = post("/internal/locations", {"entity_type": "professional", "entity_id": pid, "label": "Legacy", "location_type": "PRACTICE", "address": "2425 Bloor Street West, Suite 410A", "city": "Toronto", "province": "ON"})
assert l3["address"] == "2425 Bloor Street West, Suite 410A" and l3["street_name"] is None; print("L ok")
# street pool: add + search
st = post("/internal/address/streets", {"name": "QaTempStreet"}); print("street add:", st, "search:", [x["name"] for x in g("/internal/address/streets", q="QaTemp")])
print("types top:", [x["name"] for x in g("/internal/address/street-types", q="")][:6], "| dirs:", [x["name"] for x in g("/internal/address/street-directions")])
json.dump({"pid": pid}, open("/app/memory/legacy_access/tmp_ids.json", "w")); print("OK")
