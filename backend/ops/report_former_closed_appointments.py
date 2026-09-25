"""READ-ONLY report — FORMER_CLOSED patients that have a linked appointment_request.

Makes NO writes of any kind. For each appointment_request linked to a
patient_status=="FORMER_CLOSED" directory patient, prints the patient in the
standard VIsita display format plus the appointment details, whether it was
imported/flagged, and whether it is EXCLUSIVELY linked to that closed patient
(i.e. not also tied to any ACTIVE patient).

Run (read-only, any environment):
    python -m ops.report_former_closed_appointments
"""
import os
import asyncio

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from motor.motor_asyncio import AsyncIOMotorClient

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(v):
    if not v:
        return "—"
    s = str(v)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
            return f"{y} {MONTHS[mo - 1]} - {d:02d}"
        except Exception:
            return s
    return s


def fmt_name(last, first):
    last = (last or "").strip().upper()
    first = " ".join(w[:1].upper() + w[1:].lower() for w in (first or "").strip().split())
    if last and first:
        return f"{last}, {first}"
    return last or first or "—"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    print(f"[READ-ONLY REPORT] DB={os.environ['DB_NAME']}")

    closed = await db.patient_directory.find(
        {"patient_status": "FORMER_CLOSED"},
        {"_id": 0, "id": 1, "visita_patient_id": 1, "first_name": 1, "last_name": 1,
         "date_of_birth": 1, "linked_patient_id": 1}).to_list(100000)
    by_id = {d["id"]: d for d in closed}
    by_vpid = {d["visita_patient_id"]: d for d in closed if d.get("visita_patient_id")}
    closed_ids = set(by_id)
    closed_vpids = set(by_vpid)

    active_pt_ids = {p["id"] for p in await db.patients.find(
        {"active_status": True}, {"_id": 0, "id": 1}).to_list(100000)}
    active_dir_ids = {d["id"] for d in await db.patient_directory.find(
        {"patient_status": "ACTIVE"}, {"_id": 0, "id": 1}).to_list(100000)}

    print(f"FORMER_CLOSED patients in directory: {len(closed_ids)}")

    rows = []
    async for a in db.appointment_requests.find({}, {"_id": 0}):
        dref = a.get("directory_id") if a.get("directory_id") in closed_ids else (
            a.get("linked_patient_id") if a.get("linked_patient_id") in closed_ids else (
                a.get("patient_id") if a.get("patient_id") in closed_ids else None))
        drec = by_id.get(dref) if dref else (
            by_vpid.get(a.get("visita_patient_id")) if a.get("visita_patient_id") in closed_vpids else None)
        if not drec:
            continue
        tied_active = (a.get("patient_id") in active_pt_ids
                       or a.get("linked_patient_id") in active_dir_ids
                       or a.get("directory_id") in active_dir_ids)
        imported = bool(a.get("original_imported_name")) or bool(a.get("patient_link_required")) \
            or (a.get("source") == "import") or bool(a.get("imported"))
        when = a.get("confirmed_display") or a.get("confirmed_date") or a.get("approved_date") \
            or a.get("preferred_date") or a.get("created_at")
        rows.append((drec, a, tied_active, imported, when))

    print(f"Appointment_requests linked to a FORMER_CLOSED patient: {len(rows)}\n")
    for drec, a, tied_active, imported, when in rows:
        print(fmt_name(drec.get("last_name"), drec.get("first_name")))
        print(f"  PIN: {drec.get('visita_patient_id') or 'Not assigned'} · DOB: {fmt_date(drec.get('date_of_birth'))}")
        print(f"  Directory / VISITA ID : {drec.get('id')}")
        print(f"  Appointment Ref ...... : {a.get('ref_number')}")
        print(f"  Date/Time ............ : {fmt_date(when) if len(str(when)) >= 10 and str(when)[4:5]=='-' else when}")
        print(f"  Status ............... : {a.get('status')}")
        print(f"  Imported / flagged ... : {'YES' if imported else 'no'}")
        print(f"  Exclusive to this pt . : {'YES' if not tied_active else 'NO — also tied to an ACTIVE patient (REVIEW)'}")
        print()

    if not rows:
        print("No FORMER_CLOSED patients currently have a linked appointment_request in this DB.")
    DB = AsyncIOMotorClient  # noqa - keep import used


if __name__ == "__main__":
    asyncio.run(main())
