"""Post-UI-approval DB checks + re-approve dedup check + cleanup for sofia.martinez."""
import os, requests, json
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://visita-admin.preview.emergentagent.com"
client = MongoClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]

SOFIA_ID = "21244c47-d3de-4579-89fe-7a7aaf6fc3c5"
SUBJ = "Your VIsita EMR account has been verified"
TITLE = "Account verified"

p = db.patients.find_one({"id": SOFIA_ID}, {"_id": 0})
print("verification_status:", p.get("verification_status"))
print("portal_status:", p.get("portal_status"))
print("verified_by:", p.get("verified_by"))
print("verified_at:", p.get("verified_at"))
print("email:", p.get("email"))
print("first_name:", p.get("first_name"), "last_name:", p.get("last_name"))
print("patient_type:", p.get("patient_type"))

emails = list(db.outbound_notifications.find({"patient_id": SOFIA_ID, "subject": SUBJ}, {"_id": 0}))
print("emails count:", len(emails))
for e in emails:
    print("  channel=", e["channel"], "status=", e["status"], "to=", e["to"])

notes = list(db.notifications.find({"patient_id": SOFIA_ID, "title": TITLE}, {"_id": 0}))
print("notes count:", len(notes))
for n in notes:
    print("  msg=", n.get("message"))

# Re-approve via API (equivalent to re-clicking Verify)
r = requests.post(f"{BASE_URL}/api/auth/login", json={"identifier": "staff@visita.demo", "password": "Staff2026!"}, timeout=10)
tok = r.json()["token"]
r2 = requests.post(f"{BASE_URL}/api/internal/verifications/{SOFIA_ID}",
                   headers={"Authorization": f"Bearer {tok}"}, json={"decision": "verified"}, timeout=10)
print("re-approve status:", r2.status_code, r2.text)

e2 = db.outbound_notifications.count_documents({"patient_id": SOFIA_ID, "subject": SUBJ})
n2 = db.notifications.count_documents({"patient_id": SOFIA_ID, "title": TITLE})
print("emails count after re-approve:", e2)
print("notes count after re-approve:", n2)
assert e2 == 1 and n2 == 1, "DEDUP FAILURE"

# Check no clinical info in email row (subject already checked); look at email doc fields
print("email doc keys:", list(emails[0].keys()))

# --- CLEANUP: restore sofia to pending, wipe rows we created ---
db.patients.update_one({"id": SOFIA_ID}, {
    "$set": {"verification_status": "pending", "portal_status": "PENDING_VERIFICATION"},
    "$unset": {"verified_by": "", "verified_at": ""},
})
deleted_emails = db.outbound_notifications.delete_many({"patient_id": SOFIA_ID, "subject": SUBJ}).deleted_count
deleted_notes = db.notifications.delete_many({"patient_id": SOFIA_ID, "title": TITLE}).deleted_count
print("cleanup: deleted_emails=", deleted_emails, "deleted_notes=", deleted_notes)

after = db.patients.find_one({"id": SOFIA_ID}, {"_id": 0})
print("after restore verification_status:", after.get("verification_status"),
      "portal_status:", after.get("portal_status"),
      "verified_by:", after.get("verified_by"),
      "verified_at:", after.get("verified_at"))
