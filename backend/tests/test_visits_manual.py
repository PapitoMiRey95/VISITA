"""Phase 2A1 Visits API E2E (Preview). Creates test visits for 2 patients and deletes them at the end."""
import asyncio
import json
import os
import sys
import urllib.request
import urllib.error

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
API = [l.split("=", 1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL")][0]


def call(method, path, body=None, jwt=None, params=""):
    h = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 visits-test"}
    if jwt:
        h["Authorization"] = f"Bearer {jwt}"
    req = urllib.request.Request(API + path + params, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def login(identifier, pw):
    s, d = call("POST", "/api/auth/login", {"email": identifier, "password": pw})
    assert s == 200, (s, d)
    return d["token"], d["user"]


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    phys, pu = login("PAGUAYO", "Newman2013_!")
    staff, _ = login("staff@visita.demo", "Staff2026!")
    admin, _ = login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
    created = []
    try:
        # patients: portal (maria, linked?) + directory-only
        s, res = call("GET", "/api/internal/patient-lookup", jwt=phys, params="?q=ROMERO")
        d_only = next(r for r in res if r["source"] == "directory")
        dref = f"directory:{d_only['directory_id']}"
        maria = await db.patients.find_one({"email": "maria.lopez@demo.com"}, {"_id": 0, "id": 1, "matched_directory_id": 1})
        pref = f"directory:{maria['matched_directory_id']}" if maria.get("matched_directory_id") else f"patient:{maria['id']}"
        print("refs:", dref, pref)

        # staff forbidden
        s, _ = call("POST", "/api/internal/visits", {"patient_ref": dref, "encounter_type": "IN_CLINIC"}, jwt=staff); assert s == 403, s
        s, _ = call("GET", "/api/internal/visits/active", jwt=staff, params=f"?patient_ref={dref}"); assert s == 403
        # active none
        s, d = call("GET", "/api/internal/visits/active", jwt=phys, params=f"?patient_ref={dref}"); assert s == 200 and d["active"] is None
        # bad type
        s, _ = call("POST", "/api/internal/visits", {"patient_ref": dref, "encounter_type": "DIABETES"}, jwt=phys); assert s == 400
        # create directory-only
        s, v1 = call("POST", "/api/internal/visits", {"patient_ref": dref, "encounter_type": "TELEPHONE"}, jwt=phys); assert s == 200, v1
        created.append(v1["id"])
        assert v1["status"] == "IN_PROGRESS" and v1["practice_id"] == pu["practice_id"] and v1["physician_user_id"] == pu["id"]
        assert v1["patient_ref"] == dref and v1["directory_id"] == d_only["directory_id"] and v1["ref_number"].startswith("VIS-")
        assert v1["patient_snapshot"]["last_name"] and v1["patient_snapshot"]["date_of_birth"]
        print("created", v1["ref_number"], "snapshot", v1["patient_snapshot"])
        # 409 second
        s, d = call("POST", "/api/internal/visits", {"patient_ref": dref, "encounter_type": "IN_CLINIC"}, jwt=phys)
        assert s == 409 and d["detail"]["visit_id"] == v1["id"], (s, d)
        # active now
        s, d = call("GET", "/api/internal/visits/active", jwt=phys, params=f"?patient_ref={dref}"); assert d["active"]["id"] == v1["id"]
        # portal patient create via patient_id only (server resolves to directory ref if linked)
        s, v2 = call("POST", "/api/internal/visits", {"patient_id": maria["id"], "encounter_type": "IN_CLINIC"}, jwt=phys); assert s == 200, v2
        created.append(v2["id"]); assert v2["patient_ref"] == pref and v2["patient_id"] == maria["id"]
        # read + context
        s, full = call("GET", f"/api/internal/visits/{v2['id']}", jwt=phys); assert s == 200 and "context" in full and "server_time" in full
        print("context keys:", {k: (len(v) if isinstance(v, list) else v) for k, v in full["context"].items()})
        # admin read ok; staff read 403
        s, _ = call("GET", f"/api/internal/visits/{v2['id']}", jwt=admin); assert s == 200
        s, _ = call("GET", f"/api/internal/visits/{v2['id']}", jwt=staff); assert s == 403
        # soap save
        s, d = call("PATCH", f"/api/internal/visits/{v1['id']}/soap", {"subjective": "Headache x3d", "plan": "Rest"}, jwt=phys)
        assert s == 200 and sorted(d["changed"]) == ["plan", "subjective"] and d["save_count"] == 1 and not d["noop"]
        # no-op
        s, d = call("PATCH", f"/api/internal/visits/{v1['id']}/soap", {"subjective": "Headache x3d"}, jwt=phys)
        assert d["noop"] and d["save_count"] == 1
        n_audit = await db.audit_logs.count_documents({"action": "visit_soap_saved", "entity_id": v1["id"]}); assert n_audit == 1, n_audit
        a = await db.audit_logs.find_one({"action": "visit_soap_saved", "entity_id": v1["id"]}, {"_id": 0, "meta": 1})
        assert "Headache" not in json.dumps(a), a
        # exit / resume
        s, d = call("POST", f"/api/internal/visits/{v1['id']}/exit", jwt=phys); assert s == 200 and d["exited_at"] and d["status"] == "IN_PROGRESS"
        s, d = call("GET", "/api/internal/visits/active", jwt=phys, params=f"?patient_ref={dref}"); assert d["active"]["exited_at"]
        s, d = call("POST", f"/api/internal/visits/{v1['id']}/resume", jwt=phys); assert s == 200 and d["resumed_at"]
        vdoc = await db.visits.find_one({"id": v1["id"]}, {"_id": 0}); assert vdoc["exited_at"] is None and vdoc["soap"]["subjective"] == "Headache x3d"
        # history
        s, d = call("GET", f"/api/internal/patients/{dref}/visits", jwt=phys); assert s == 200 and d["visits"][0]["id"] == v1["id"] and "soap" not in d["visits"][0]
        # cross-practice: simulate by direct DB tweak on v2 then read
        await db.visits.update_one({"id": v2["id"]}, {"$set": {"practice_id": "other-practice"}})
        s, _ = call("GET", f"/api/internal/visits/{v2['id']}", jwt=phys); assert s == 404, s
        s, _ = call("PATCH", f"/api/internal/visits/{v2['id']}/soap", {"plan": "x"}, jwt=phys); assert s == 404
        # unique index exists
        idx = await db.visits.index_information(); assert "one_active_visit" in idx and idx["one_active_visit"].get("unique")
        # by-ref lookup
        s, d = call("GET", "/api/internal/patient-lookup/by-ref", jwt=phys, params=f"?patient_ref={dref}"); assert s == 200 and d["directory_id"] == d_only["directory_id"]
        acts = [a["action"] async for a in db.audit_logs.find({"entity_id": {"$in": created}}, {"_id": 0, "action": 1})]
        print("audit actions:", sorted(set(acts)))
        print("ALL PASS")
    finally:
        await db.visits.delete_many({"id": {"$in": created}})
        await db.audit_logs.delete_many({"entity_id": {"$in": created}})


asyncio.run(main())
