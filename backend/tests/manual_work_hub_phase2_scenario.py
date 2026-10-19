"""Preview scenario for Work Hub Phase 2 (priority, overdue, sorting, Call/Book, signed handoff). Self-cleaning
unless KEEP=1 (leaves the mixed-sort fixture in place for UI screenshots)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
KEEP = os.environ.get("KEEP") == "1"


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


def create(tok, **kw):
    body = {"category": "MESSAGE", "send_to": "CLINIC", **kw}
    r = requests.post(f"{API}/internal/work", headers=H(tok), json=body, timeout=20)
    assert r.status_code == 200, r.text
    ids.append(r.json()["id"])
    return r.json()


def lookup(name):
    return requests.get(f"{API}/internal/patient-lookup", headers=H(doc), params={"q": name}).json()[0]


def pat_fields(p):
    return {"patient_id": p.get("patient_id"), "directory_id": p.get("directory_id"), "patient_name": f"{p['last_name'].upper()}, {p['first_name']}"}


now = datetime.now(timezone.utc)
iso = lambda d: d.isoformat()  # noqa: E731
base_adm = cnt(adm)

# A/B — mixed fixture, all owned by CLINIC (doctor sends)
restrepo = lookup("Restrepo") if requests.get(f"{API}/internal/patient-lookup", headers=H(doc), params={"q": "Restrepo"}).json() else lookup("Smith")
urrea = lookup("Urrea") if requests.get(f"{API}/internal/patient-lookup", headers=H(doc), params={"q": "Urrea"}).json() else lookup("Romero")
w_asap = create(doc, category="CALL_BOOK_PATIENT", priority="ASAP", message="Arrange urgent follow-up", due_at=iso(now + timedelta(days=3)), **pat_fields(restrepo))
w_over = create(doc, category="RESULTS", priority="NORMAL", message="Review abnormal result and arrange follow-up", due_at=iso(now - timedelta(days=2, hours=1)), **pat_fields(restrepo))
w_today = create(doc, category="APPOINTMENT_CALL", priority="NORMAL", message="Confirm tomorrow's appointment", due_at=iso(now + timedelta(minutes=30)))
w_b1 = create(doc, category="CALL_BOOK_PATIENT", priority="B1", message="B1 this week — book follow-up", **pat_fields(urrea))
w_b2 = create(doc, category="CALL_BOOK_PATIENT", priority="B2", message="Review MRI / plan exams", **pat_fields(urrea))
w_norm = create(doc, category="ADMIN_OTHER", priority="NORMAL", message="Order printer toner")
check("priority stored", [w_asap["priority"], w_b1["priority"], w_b2["priority"], w_norm["priority"]] == ["ASAP", "B1", "B2", "NORMAL"])
check("Call/Book keeps patient identity", w_b2["patient_id"] == urrea.get("patient_id") and w_b2["directory_id"] == urrea.get("directory_id") and w_b2["patient_name"])
check("reason in history", w_b2["events"][0]["text"] == "Review MRI / plan exams")
order = [i["id"] for i in view(adm, "my") if i["id"] in ids]
expected = [w_asap["id"], w_over["id"], w_today["id"], w_b1["id"], w_b2["id"], w_norm["id"]]
check("My Work ordering ASAP→overdue→today→B1→B2→rest", order == expected, str([expected.index(x) for x in order]))
check("doctor Sent shows all 6", sum(1 for i in view(doc, "sent") if i["id"] in ids) == 6)
check("admin counter +6", cnt(adm) == base_adm + 6, f"{base_adm}->{cnt(adm)}")
check("bad priority 400", requests.post(f"{API}/internal/work", headers=H(doc), json={"category": "MESSAGE", "message": "x", "send_to": "CLINIC", "priority": "URGENT"}).status_code == 400)
# C — overdue derived only; completed hides it
check("overdue item still NEW", w_over["status"] == "NEW")
# priority change by admin + by doctor with events
r = requests.post(f"{API}/internal/work/{w_b2['id']}/action", headers=H(adm), json={"action": "priority", "priority": "B1"})
check("admin B2→B1", r.status_code == 200 and r.json()["priority"] == "B1" and r.json()["events"][-1]["type"] == "PRIORITY_CHANGED" and r.json()["events"][-1]["from_priority"] == "B2")
r = requests.post(f"{API}/internal/work/{w_b2['id']}/action", headers=H(doc), json={"action": "priority", "priority": "ASAP"})
check("doctor (non-owner) B1→ASAP allowed", r.status_code == 200 and r.json()["priority"] == "ASAP")
check("same priority no-op", len(requests.post(f"{API}/internal/work/{w_b2['id']}/action", headers=H(doc), json={"action": "priority", "priority": "ASAP"}).json()["events"]) == 3)
requests.post(f"{API}/internal/work/{w_b2['id']}/action", headers=H(adm), json={"action": "priority", "priority": "B2"})
# F — signed document flow
base_adm2, base_doc = cnt(adm), cnt(doc)
cart = lookup("Cartagena")
w_doc = create(adm, category="INSURANCE_FORM", send_to="PHYSICIAN", priority="B1", message="Please sign Hearing Aid form", **pat_fields(cart))
check("doctor counter +1", cnt(doc) == base_doc + 1)
check("admin cannot 'signed' (not owner / not physician)", requests.post(f"{API}/internal/work/{w_doc['id']}/action", headers=H(adm), json={"action": "signed"}).status_code in (400, 403))
check("admin (non-owner) cannot complete", requests.post(f"{API}/internal/work/{w_doc['id']}/action", headers=H(adm), json={"action": "complete"}).status_code == 403)
r = requests.post(f"{API}/internal/work/{w_doc['id']}/action", headers=H(doc), json={"action": "signed", "note": "Document signed. Please send."})
s = r.json()
check("signed → owner CLINIC, NEW, signed flag, same ref", r.status_code == 200 and s["owner_role"] == "CLINIC" and s["status"] == "NEW" and s["signed"] is True and s["ref_number"] == w_doc["ref_number"])
check("DOCUMENT_SIGNED event", s["events"][-1]["type"] == "DOCUMENT_SIGNED" and s["events"][-1]["text"] == "Document signed. Please send.")
check("not completed", s["completed_at"] is None)
check("doctor counter back, admin +1", cnt(doc) == base_doc and cnt(adm) == base_adm2 + 1)
check("admin My Work shows signed", any(i["id"] == w_doc["id"] and i["signed"] for i in view(adm, "my")))
check("doctor 'signed' on CLINIC-owned item rejected", requests.post(f"{API}/internal/work/{w_doc['id']}/action", headers=H(doc), json={"action": "signed"}).status_code == 403)
requests.post(f"{API}/internal/work/{w_doc['id']}/action", headers=H(adm), json={"action": "reply", "note": "Faxed to supplier"})
r = requests.post(f"{API}/internal/work/{w_doc['id']}/action", headers=H(adm), json={"action": "complete"})
check("completed with full history", r.status_code == 200 and [e["type"] for e in r.json()["events"]] == ["created", "DOCUMENT_SIGNED", "reply", "completed"])
check("completed not in admin My Work; in Completed", not any(i["id"] == w_doc["id"] for i in view(adm, "my")) and any(i["id"] == w_doc["id"] for i in view(adm, "completed")))
# G — security regression
check("patient 403", requests.post(f"{API}/internal/work/{w_norm['id']}/action", headers=H(pat), json={"action": "priority", "priority": "ASAP"}).status_code == 403)
db.work_items.update_one({"id": w_norm["id"]}, {"$set": {"practice_id": "other-zzz"}})
check("cross-practice 404", requests.post(f"{API}/internal/work/{w_norm['id']}/action", headers=H(adm), json={"action": "priority", "priority": "ASAP"}).status_code == 404)
db.work_items.update_one({"id": w_norm["id"]}, {"$set": {"practice_id": w_asap["practice_id"]}})
# H — regression: waiting / reopen / handoff still fine
r = requests.post(f"{API}/internal/work/{w_norm['id']}/action", headers=H(adm), json={"action": "waiting", "waiting_until": iso(now + timedelta(days=2))})
check("waiting ok", r.status_code == 200 and r.json()["status"] == "WAITING")
r = requests.post(f"{API}/internal/work/{w_norm['id']}/action", headers=H(adm), json={"action": "handoff", "note": "Doctor please decide"})
check("handoff ok", r.status_code == 200 and r.json()["owner_role"] == "PHYSICIAN")
r = requests.post(f"{API}/internal/work/{w_doc['id']}/action", headers=H(adm), json={"action": "reopen"})
check("reopen event type", r.status_code == 200 and r.json()["events"][-1]["type"] == "reopened")
requests.post(f"{API}/internal/work/{w_doc['id']}/action", headers=H(adm), json={"action": "complete"})
requests.post(f"{API}/internal/work/{w_norm['id']}/action", headers=H(doc), json={"action": "handoff"})
requests.post(f"{API}/internal/work/{w_norm['id']}/action", headers=H(adm), json={"action": "in_progress"})

print("\n".join(out))
if KEEP:
    print("KEEP=1 — fixture left in place:", len(ids), "items")
else:
    db.work_items.delete_many({"id": {"$in": ids}})
    print("cleanup remaining:", db.work_items.count_documents({"id": {"$in": ids}}))
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
