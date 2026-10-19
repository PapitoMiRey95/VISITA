"""Preview scenario for the new Work Hub (work_items). Self-cleaning."""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def login(i, p):
    r = requests.post(f"{API}/auth/login", json={"identifier": i, "password": p}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
adm = login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
doc = login("PAGUAYO", "Aguayo-Preview-2026#Tmp")
pat = login("john.smith@demo.com", "Patient2026!")
ids, ok, out = [], True, []


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    out.append(f"{'PASS' if cond else 'FAIL'}  {name} {extra}")


def view(tok, v):
    return requests.get(f"{API}/internal/work", headers=H(tok), params={"view": v}).json()["items"]


def cnt(tok):
    return requests.get(f"{API}/internal/counters", headers=H(tok)).json()["counters"].get("work_hub")


base_adm, base_doc = cnt(adm), cnt(doc)
# 1) Clinic -> Doctor with patient
p = requests.get(f"{API}/internal/patient-lookup", headers=H(adm), params={"q": "Smith"}).json()[0]
r = requests.post(f"{API}/internal/work", headers=H(adm), json={"category": "INSURANCE_FORM", "message": "Complete insurance form", "send_to": "PHYSICIAN",
                  "patient_id": p.get("patient_id"), "directory_id": p.get("directory_id"), "patient_name": f"{p['last_name'].upper()}, {p['first_name']}"})
check("admin create -> doctor", r.status_code == 200, r.text[:80]); w = r.json(); ids.append(w["id"])
check("ref WRK- & status NEW & owner PHYSICIAN", w["ref_number"].startswith("WRK-") and w["status"] == "NEW" and w["owner_role"] == "PHYSICIAN")
check("doctor My Work has it", any(i["id"] == w["id"] for i in view(doc, "my")))
check("admin My Work does NOT have it", not any(i["id"] == w["id"] for i in view(adm, "my")))
check("admin Sent has it", any(i["id"] == w["id"] for i in view(adm, "sent")))
check("doctor counter +1", cnt(doc) == base_doc + 1, f"{base_doc}->{cnt(doc)}")
# 2) Doctor -> Clinic with reply
r = requests.post(f"{API}/internal/work/{w['id']}/action", headers=H(doc), json={"action": "handoff", "note": "Signed. Please fax."})
check("doctor handoff", r.status_code == 200 and r.json()["owner_role"] == "CLINIC" and r.json()["status"] == "NEW")
w2 = r.json()
check("same item/ref, events=2 (created, handoff)", w2["ref_number"] == w["ref_number"] and [e["type"] for e in w2["events"]] == ["created", "handoff"])
check("handoff text kept", w2["events"][1]["text"] == "Signed. Please fax.")
check("admin My Work has it now", any(i["id"] == w["id"] for i in view(adm, "my")))
check("doctor Sent empty for it, admin Sent still has it", not any(i["id"] == w["id"] for i in view(doc, "sent")) and any(i["id"] == w["id"] for i in view(adm, "sent")))
check("doctor counter back to base", cnt(doc) == base_doc)
check("admin counter +1", cnt(adm) == base_adm + 1)
# 3) Waiting future -> leaves My Work; waiting past -> still actionable
fut = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
r = requests.post(f"{API}/internal/work/{w['id']}/action", headers=H(adm), json={"action": "waiting", "waiting_until": fut})
check("waiting future", r.status_code == 200 and r.json()["status"] == "WAITING")
check("left admin My Work", not any(i["id"] == w["id"] for i in view(adm, "my")))
check("in Waiting view", any(i["id"] == w["id"] for i in view(adm, "waiting")))
check("admin counter back to base", cnt(adm) == base_adm)
past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
requests.post(f"{API}/internal/work/{w['id']}/action", headers=H(adm), json={"action": "waiting", "waiting_until": past})
check("due waiting item visible in My Work again", any(i["id"] == w["id"] for i in view(adm, "my")))
# 4) Complete
r = requests.post(f"{API}/internal/work/{w['id']}/action", headers=H(adm), json={"action": "complete"})
check("complete", r.status_code == 200 and r.json()["status"] == "COMPLETED" and r.json()["completed_by"])
check("not in My Work; in Completed", not any(i["id"] == w["id"] for i in view(adm, "my")) and any(i["id"] == w["id"] for i in view(adm, "completed")))
check("handoff after complete rejected", requests.post(f"{API}/internal/work/{w['id']}/action", headers=H(adm), json={"action": "handoff"}).status_code == 400)
# 5) No patient, doctor -> clinic
r = requests.post(f"{API}/internal/work", headers=H(doc), json={"category": "ADMIN_OTHER", "message": "Order printer toner", "send_to": "CLINIC"})
check("doctor create no patient", r.status_code == 200 and r.json()["patient_name"] is None); ids.append(r.json()["id"])
check("admin My Work has it", any(i["id"] == ids[1] for i in view(adm, "my")))
# 6) Validation
check("bad category 400", requests.post(f"{API}/internal/work", headers=H(adm), json={"category": "X", "message": "m", "send_to": "CLINIC"}).status_code == 400)
check("empty message 400", requests.post(f"{API}/internal/work", headers=H(adm), json={"category": "LEGAL", "message": " ", "send_to": "CLINIC"}).status_code == 400)
# 7) Security
check("patient list 403", requests.get(f"{API}/internal/work", headers=H(pat)).status_code == 403)
check("patient create 403", requests.post(f"{API}/internal/work", headers=H(pat), json={"category": "LEGAL", "message": "x", "send_to": "CLINIC"}).status_code == 403)
check("patient action 403", requests.post(f"{API}/internal/work/{ids[1]}/action", headers=H(pat), json={"action": "complete"}).status_code == 403)
check("unauth 401", requests.get(f"{API}/internal/work").status_code == 401)
# cross-practice: temporarily re-stamp item to another practice id and confirm 404 for admin
db.work_items.update_one({"id": ids[1]}, {"$set": {"practice_id": "other-practice-zzz"}})
check("cross-practice get 404", requests.get(f"{API}/internal/work/{ids[1]}", headers=H(adm)).status_code == 404)
check("cross-practice action 404", requests.post(f"{API}/internal/work/{ids[1]}/action", headers=H(adm), json={"action": "complete"}).status_code == 404)
check("cross-practice not listed", not any(i["id"] == ids[1] for i in view(adm, "my")))
# audit separate from events
check("audit rows exist", db.audit_logs.count_documents({"entity_type": "work_item", "entity_id": ids[0]}) >= 4)
# cleanup
db.work_items.delete_many({"id": {"$in": ids}})
print("\n".join(out)); print("cleanup remaining:", db.work_items.count_documents({"id": {"$in": ids}})); print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
