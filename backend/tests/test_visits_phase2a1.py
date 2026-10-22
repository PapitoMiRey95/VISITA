"""Phase 2A1 Visits backend regression. Creates test visits and cleans them up at the end.
Avoids the pre-existing VIS-000004 ROMERO active visit (left intentionally)."""
import asyncio
import json
import os
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
    phys, pu = login("PAGUAYO", os.environ["TEST_PHYSICIAN_PASSWORD"])
    staff, _ = login("staff@visita.demo", os.environ["TEST_STAFF_PASSWORD"])
    admin, _ = login("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
    created = []
    try:
        # directory patient LOPEZ IGLESIAS Sarai (no existing active visit)
        s, res = call("GET", "/api/internal/patient-lookup", jwt=phys, params="?q=LOPEZ")
        d_only = next(r for r in res if r["source"] == "directory" and r.get("directory_id") == "c3951a2f-22e0-411d-b12c-01c490490cfc")
        dref = f"directory:{d_only['directory_id']}"
        # portal patient maria (no matched_directory_id -> pref = patient:<id>)
        maria = await db.patients.find_one({"email": "maria.lopez@demo.com"}, {"_id": 0, "id": 1, "matched_directory_id": 1})
        pref = f"directory:{maria['matched_directory_id']}" if maria.get("matched_directory_id") else f"patient:{maria['id']}"
        print("refs:", dref, pref)

        # staff forbidden
        s, _ = call("POST", "/api/internal/visits", {"patient_ref": dref, "encounter_type": "IN_CLINIC"}, jwt=staff); assert s == 403, s
        s, _ = call("GET", "/api/internal/visits/active", jwt=staff, params=f"?patient_ref={dref}"); assert s == 403
        # active none
        s, d = call("GET", "/api/internal/visits/active", jwt=phys, params=f"?patient_ref={dref}"); assert s == 200 and d["active"] is None, d
        # bad type
        s, _ = call("POST", "/api/internal/visits", {"patient_ref": dref, "encounter_type": "DIABETES"}, jwt=phys); assert s == 400
        # create directory-only
        s, v1 = call("POST", "/api/internal/visits", {"patient_ref": dref, "encounter_type": "TELEPHONE"}, jwt=phys); assert s == 200, v1
        created.append(v1["id"])
        assert v1["status"] == "IN_PROGRESS" and v1["practice_id"] == pu["practice_id"] and v1["physician_user_id"] == pu["id"]
        assert v1["patient_ref"] == dref and v1["directory_id"] == d_only["directory_id"] and v1["ref_number"].startswith("VIS-")
        assert v1["patient_snapshot"]["last_name"] and v1["patient_snapshot"]["date_of_birth"]
        assert v1["save_count"] == 0 and all(v1["soap"][k] == "" for k in ("subjective", "objective", "assessment", "plan"))
        print("created", v1["ref_number"], "snapshot_last=", v1["patient_snapshot"]["last_name"])
        # 409 second (same patient same physician)
        s, d = call("POST", "/api/internal/visits", {"patient_ref": dref, "encounter_type": "IN_CLINIC"}, jwt=phys)
        assert s == 409 and d["detail"]["visit_id"] == v1["id"] and d["detail"]["ref_number"] == v1["ref_number"], (s, d)
        # count unchanged
        n = await db.visits.count_documents({"patient_ref": dref, "physician_user_id": pu["id"], "status": "IN_PROGRESS"})
        assert n == 1, n
        # active now
        s, d = call("GET", "/api/internal/visits/active", jwt=phys, params=f"?patient_ref={dref}"); assert d["active"]["id"] == v1["id"]

        # portal patient create via patient_id only
        s, v2 = call("POST", "/api/internal/visits", {"patient_id": maria["id"], "encounter_type": "IN_CLINIC"}, jwt=phys); assert s == 200, v2
        created.append(v2["id"])
        assert v2["patient_ref"] == pref and v2["patient_id"] == maria["id"]

        # read + context
        s, full = call("GET", f"/api/internal/visits/{v2['id']}", jwt=phys); assert s == 200 and "context" in full and "server_time" in full
        ctx = full["context"]
        for k in ("medications_active", "recent_appointments", "documents"):
            assert k in ctx
        assert ctx["recent_appointments"] is None and ctx["documents"] is None  # not loaded on the critical path
        for k in ("diagnoses", "pmhx", "allergies"):
            assert ctx[k] is None, (k, ctx[k])
        # audit visit_read
        rd = await db.audit_logs.count_documents({"action": "visit_read", "entity_id": v2["id"]}); assert rd >= 1

        # admin can read, staff cannot, admin cannot write
        s, _ = call("GET", f"/api/internal/visits/{v2['id']}", jwt=admin); assert s == 200
        s, _ = call("GET", f"/api/internal/visits/{v2['id']}", jwt=staff); assert s == 403
        s, _ = call("PATCH", f"/api/internal/visits/{v2['id']}/soap", {"plan": "x"}, jwt=admin); assert s == 403, s
        s, _ = call("POST", f"/api/internal/visits/{v2['id']}/exit", jwt=admin); assert s == 403

        # soap save - change
        s, d = call("PATCH", f"/api/internal/visits/{v1['id']}/soap", {"subjective": "Headache x3d", "plan": "Rest"}, jwt=phys)
        assert s == 200 and sorted(d["changed"]) == ["plan", "subjective"] and d["save_count"] == 1 and not d["noop"] and d["last_saved_at"]
        # no-op identical content
        s, d = call("PATCH", f"/api/internal/visits/{v1['id']}/soap", {"subjective": "Headache x3d"}, jwt=phys)
        assert d["noop"] and d["save_count"] == 1
        # audit row count == 1 and no note text leaked
        n_audit = await db.audit_logs.count_documents({"action": "visit_soap_saved", "entity_id": v1["id"]}); assert n_audit == 1, n_audit
        a = await db.audit_logs.find_one({"action": "visit_soap_saved", "entity_id": v1["id"]}, {"_id": 0, "meta": 1})
        assert "Headache" not in json.dumps(a) and "Rest" not in json.dumps(a), a
        assert "fields_changed" in a["meta"] and "save_count" in a["meta"]

        # exit / resume
        s, d = call("POST", f"/api/internal/visits/{v1['id']}/exit", jwt=phys); assert s == 200 and d["exited_at"] and d["status"] == "IN_PROGRESS"
        s, d = call("GET", "/api/internal/visits/active", jwt=phys, params=f"?patient_ref={dref}"); assert d["active"]["exited_at"]
        s, d = call("POST", f"/api/internal/visits/{v1['id']}/resume", jwt=phys); assert s == 200 and d["resumed_at"]
        vdoc = await db.visits.find_one({"id": v1["id"]}, {"_id": 0}); assert vdoc["exited_at"] is None and vdoc["soap"]["subjective"] == "Headache x3d"

        # history (no soap)
        s, d = call("GET", f"/api/internal/patients/{dref}/visits", jwt=phys); assert s == 200
        row = next(r for r in d["visits"] if r["id"] == v1["id"])
        assert "soap" not in row

        # cross-practice 404 on v2
        await db.visits.update_one({"id": v2["id"]}, {"$set": {"practice_id": "other-practice"}})
        try:
            s, _ = call("GET", f"/api/internal/visits/{v2['id']}", jwt=phys); assert s == 404, s
            s, _ = call("PATCH", f"/api/internal/visits/{v2['id']}/soap", {"plan": "x"}, jwt=phys); assert s == 404
        finally:
            await db.visits.update_one({"id": v2["id"]}, {"$set": {"practice_id": pu["practice_id"]}})

        # unique index
        idx = await db.visits.index_information(); assert "one_active_visit" in idx and idx["one_active_visit"].get("unique")
        # by-ref lookup
        s, d = call("GET", "/api/internal/patient-lookup/by-ref", jwt=phys, params=f"?patient_ref={dref}")
        assert s == 200 and d["directory_id"] == d_only["directory_id"]
        print("ALL PASS, created ids:", created)
    finally:
        await db.visits.delete_many({"id": {"$in": created}})
        await db.audit_logs.delete_many({"entity_id": {"$in": created}})


asyncio.run(main())
