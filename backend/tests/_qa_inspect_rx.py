# QA helper: list prescription_requests created since /tmp/qa_start (used by UI regression for verification + cleanup)
import sys
from pymongo import MongoClient
db = MongoClient("mongodb://localhost:27017")["test_database"]
since = open("/tmp/qa_start").read().strip()
for r in db.prescription_requests.find({"created_at": {"$gte": since}}, {"_id": 0}).sort("created_at", 1):
    print(r["id"], r.get("ref_number"), r.get("source"), r.get("request_mode"), r.get("request_mode_label"),
          [(c.get("drug"), c.get("entry_source")) for c in r.get("medications_structured") or []], r.get("patient_note"), r.get("requested_months"), r.get("supply_type"))
print("maria meds:", sorted((m["id"][:8], m.get("active")) for m in db.patient_medications.find({"patient_id": "06f6ee08-58f7-4286-82f5-7c845de99ce1"})))
if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
    n = db.prescription_requests.delete_many({"created_at": {"$gte": since}}).deleted_count
    print("deleted requests", n)
