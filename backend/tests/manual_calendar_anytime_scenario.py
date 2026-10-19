"""Preview-only scenario: physician/admin any-time manual booking. Creates appointments for a
demo patient, verifies calendar/portal/availability behaviour, then deletes what it created."""
import os
import sys
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
PATIENT = ("john.smith@demo.com", "Patient2026!")


def login(ident, pw):
    r = requests.post(f"{API}/auth/login", json={"identifier": ident, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["user"]


def hdr(t):
    return {"Authorization": f"Bearer {t}"}


def next_weekday(wd, weeks_ahead=2):
    d = date.today() + timedelta(days=7 * weeks_ahead)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d.isoformat()


def main():
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    admin_tok, _ = login(*ADMIN)
    pat_tok, pat_user = login(*PATIENT)
    patient = db.patients.find_one({"id": pat_user.get("patient_id")}) or db.patients.find_one({"email": PATIENT[0]})
    pid = patient["id"]
    created, results, ok = [], [], True

    def book(tok, ds, t, manual=True, label=""):
        nonlocal ok
        r = requests.post(f"{API}/internal/calendar/book", headers=hdr(tok),
                          json={"patient_id": pid, "date": ds, "time": t, "reason": f"QA {label}", "manual": manual}, timeout=20)
        if r.status_code == 200:
            created.append(r.json()["id"])
        return r

    sat, sun, mon = next_weekday(5), next_weekday(6), next_weekday(0, 3)
    # 1) admin: weekday after-hours 19:00
    r = book(admin_tok, mon, "19:00", label="weekday 7pm"); results.append(("admin weekday 19:00", r.status_code, r.json().get("status") if r.ok else r.json().get("detail"))); ok &= r.status_code == 200
    # 2) Saturday 18:00 — different weeks to avoid the one-per-day rule
    r = book(admin_tok, sat, "18:00", label="sat"); results.append(("admin Saturday 18:00", r.status_code, r.json().get("status") if r.ok else r.json().get("detail"))); ok &= r.status_code == 200
    # 3) Sunday 20:00
    r = book(admin_tok, sun, "20:00", label="sun"); results.append(("admin Sunday 20:00", r.status_code, r.json().get("status") if r.ok else r.json().get("detail"))); ok &= r.status_code == 200
    # 4) arbitrary 20:15 on a Tuesday, 4 weeks ahead
    tue = next_weekday(1, 4)
    r = book(admin_tok, tue, "20:15", label="20:15"); results.append(("admin Tuesday 20:15", r.status_code, r.json().get("status") if r.ok else r.json().get("detail"))); ok &= r.status_code == 200
    # 5) same slot again -> 409 (slot lock) or same-day conflict
    r = book(admin_tok, tue, "20:15", label="dup"); results.append(("duplicate same slot", r.status_code, r.json().get("detail") if not r.ok else "BOOKED?!")); ok &= r.status_code in (409, 400)
    # 6) non-manual after-hours still rejected (normal rule intact)
    r = book(admin_tok, next_weekday(2, 5), "19:00", manual=False, label="nonmanual"); results.append(("non-manual after-hours", r.status_code, r.json().get("detail") if not r.ok else "BOOKED?!")); ok &= r.status_code == 400
    # 7) patient denied
    r = requests.post(f"{API}/internal/calendar/book", headers=hdr(pat_tok), json={"patient_id": pid, "date": sun, "time": "21:00", "manual": True}, timeout=20)
    results.append(("patient manual booking", r.status_code, r.json().get("detail"))); ok &= r.status_code in (401, 403)
    # 8) staff denied for manual (role check)
    try:
        staff_tok, _ = login("staff@visita.demo", "Staff2026!")
        r = requests.post(f"{API}/internal/calendar/book", headers=hdr(staff_tok), json={"patient_id": pid, "date": next_weekday(3, 6), "time": "21:00", "manual": True}, timeout=20)
        results.append(("staff manual booking", r.status_code, r.json().get("detail"))); ok &= r.status_code == 403
    except AssertionError:
        results.append(("staff manual booking", "skipped", "staff login unavailable"))
    # 9) patient availability must not include any created times
    slots = requests.get(f"{API}/availability/slots", headers=hdr(pat_tok), params={"days": 60}, timeout=20).json()["slots"]
    leaked = [s for s in slots if (s["date"], s["time"]) in {(mon, "19:00"), (sat, "18:00"), (sun, "20:00"), (tue, "20:15")}]
    weekend = [s for s in slots if date.fromisoformat(s["date"]).weekday() >= 5]
    results.append(("patient availability leak", len(leaked), f"weekend slots offered: {len(weekend)}")); ok &= not leaked and not weekend
    # 10) calendar shows them (incl. closed days)
    cal = requests.get(f"{API}/internal/calendar", headers=hdr(admin_tok), params={"start": sat, "days": 2}, timeout=20).json()
    shown = {(d["date"], a["time"]) for d in cal["days"] for a in d["appointments"]}
    closed_flags = {d["date"]: d["closed"] for d in cal["days"]}
    results.append(("calendar shows Sat/Sun appts", (sat, "18:00") in shown and (sun, "20:00") in shown, closed_flags)); ok &= (sat, "18:00") in shown and (sun, "20:00") in shown
    # 11) portal shows them
    ov = requests.get(f"{API}/portal/overview", headers=hdr(pat_tok), timeout=20).json()
    port = str(ov)
    results.append(("portal overview includes appts", all(c in port for c in created), len(created)))
    ok &= all(c in port for c in created)
    # 12) notification created
    notif = db.notifications.count_documents({"patient_id": pid, "title": "Appointment confirmed"})
    results.append(("portal notifications (Appointment confirmed) total", notif, ""))
    # 13) source metadata
    a = db.appointment_requests.find_one({"id": created[0]}) if created else {}
    results.append(("source metadata", (a or {}).get("booked_from"), (a or {}).get("status")))
    # cleanup
    db.appointment_requests.delete_many({"id": {"$in": created}})
    db.appointment_slots.delete_many({"appointment_id": {"$in": created}})
    db.appointment_day_locks.delete_many({"appointment_id": {"$in": created}})
    db.appointment_reminders.delete_many({"appointment_id": {"$in": created}})
    for row in results:
        print(f"{row[0]:42s} -> {row[1]} | {row[2]}")
    print("cleanup remaining:", db.appointment_requests.count_documents({"id": {"$in": created}}))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
