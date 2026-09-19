#!/usr/bin/env python3
"""One-time PRODUCTION import of Dr. Aguayo's existing Google Calendar schedule.

Runs entirely against the LIVE site's admin API (production DB is separate from
preview). Idempotent: re-running skips appointments/blocks that already exist.

Usage:
    python prod_import.py <BASE_URL> <ADMIN_IDENTIFIER> <ADMIN_PASSWORD>

Behaviour (matches the agreed rules):
  * imports 41 existing appointments as CONFIRMED — NO confirmation SMS/email
  * links to patient_directory when exactly one match, else flags PATIENT LINK REQUIRED
  * schedules the normal 24h reminder for linked appts still >24h away
  * sets Mon-Thu hours 11:30-17:00 and the recurring 3:00-3:30 PM daily break
  * blocks the fully-blocked days: 2026-09-29, 2026-09-30, 2026-10-01
  * does NOT copy any preview test bookings
"""
import json
import sys
import urllib.request

APPOINTMENTS = [
    {"date": "2026-09-21", "time": "11:00", "patient_name": "CHIRRILLO, Joseph"},
    {"date": "2026-09-21", "time": "11:30", "patient_name": "LOPEZ BOCANGEL, Lorenzo Carlos"},
    {"date": "2026-09-21", "time": "12:00", "patient_name": "MAIRA, Elena del Carmen"},
    {"date": "2026-09-21", "time": "12:30", "patient_name": "FELIX ALATA, Francisco"},
    {"date": "2026-09-21", "time": "13:00", "patient_name": "UZCATEGUI VALERO, Rita Isabel"},
    {"date": "2026-09-21", "time": "13:30", "patient_name": "VALERO UZCATEGUI, Heidy Nailed"},
    {"date": "2026-09-21", "time": "14:00", "patient_name": "PAZ, Jose"},
    {"date": "2026-09-21", "time": "14:30", "patient_name": "SARAUZ, Teresita de Jesus"},
    {"date": "2026-09-21", "time": "15:30", "patient_name": "GAZULA, Purnachandra Rao"},
    {"date": "2026-09-21", "time": "16:00", "patient_name": "MARTINEZ IGNACIO, Oscar"},
    {"date": "2026-09-21", "time": "16:30", "patient_name": "CADENA, Enrique Fernando"},

    {"date": "2026-09-22", "time": "11:30", "patient_name": "ESTRADA, Karla Vanessa"},
    {"date": "2026-09-22", "time": "12:00", "patient_name": "JUAREZ MALDONADO, Modesto Raul"},
    {"date": "2026-09-22", "time": "12:30", "patient_name": "OSORIO MONCADA, Luz Dari"},
    {"date": "2026-09-22", "time": "13:00", "patient_name": "GUERRERO, Laura Agripina"},
    {"date": "2026-09-22", "time": "13:30", "patient_name": "GARCIA, Mary Raquel"},
    {"date": "2026-09-22", "time": "14:00", "patient_name": "SENKIV, Lyudmyla"},
    {"date": "2026-09-22", "time": "14:30", "patient_name": "CORREIA, Nuno Acacio"},
    {"date": "2026-09-22", "time": "15:30", "patient_name": "GUTIERREZ NUNEZ, Darwin Steven"},
    {"date": "2026-09-22", "time": "16:00", "patient_name": "IZAO, Aracely"},
    {"date": "2026-09-22", "time": "16:30", "patient_name": "PINO INCLAN, Leonor"},

    {"date": "2026-09-23", "time": "11:30", "patient_name": "CARTAGENA, Joseph"},
    {"date": "2026-09-23", "time": "12:00", "patient_name": "FAZZARI, Leonardo"},
    {"date": "2026-09-23", "time": "12:30", "patient_name": "CAMACHO AGON, Sandra Patricia"},
    {"date": "2026-09-23", "time": "13:00", "patient_name": "DIMECH, Josephine"},
    {"date": "2026-09-23", "time": "13:30", "patient_name": "ORELLANA, Marta Claudina"},
    {"date": "2026-09-23", "time": "14:00", "patient_name": "BAGNASCO GONZALEZ, Maria Esther"},
    {"date": "2026-09-23", "time": "14:30", "patient_name": "MORALES, Santos Eugenio"},
    {"date": "2026-09-23", "time": "15:30", "patient_name": "MONROY, Oscar"},
    {"date": "2026-09-23", "time": "16:00", "patient_name": "PINEDA CABELLO, Efrain"},
    {"date": "2026-09-23", "time": "16:30", "patient_name": "SALAZAR CALDERON, Alvaro"},

    {"date": "2026-09-24", "time": "16:30", "patient_name": "CASTELLANOS GUERRERO, July"},

    {"date": "2026-09-28", "time": "11:30", "patient_name": "PEREIRA, Rita Geraldes"},
    {"date": "2026-09-28", "time": "12:00", "patient_name": "PEREIRA, Jose Fernando da Ponte"},
    {"date": "2026-09-28", "time": "13:00", "patient_name": "VIERA, Pablo Marcelo", "reason": "Phone appointment"},
    {"date": "2026-09-28", "time": "13:30", "patient_name": "MARTINEZ MENDEZ, Alejandra"},
    {"date": "2026-09-28", "time": "14:00", "patient_name": "CERRITOS MENDEZ, Adela"},
    {"date": "2026-09-28", "time": "14:30", "patient_name": "LOPEZ POSADAS, Reyna Berenisse"},
    {"date": "2026-09-28", "time": "15:30", "patient_name": "GUERRA, Manuel"},
    {"date": "2026-09-28", "time": "16:00", "patient_name": "GONZALEZ, Gabi Dinora"},
    {"date": "2026-09-28", "time": "16:30", "patient_name": "ARAYA, Oscar Miguel"},
]
BLOCKED_DAYS = ["2026-09-29", "2026-09-30", "2026-10-01"]


def _req(method, url, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "VIen-EMR-Importer/1.0")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or "{}")


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    base = sys.argv[1].rstrip("/")
    ident, pw = sys.argv[2], sys.argv[3]

    tok = _req("POST", f"{base}/api/auth/login", body={"identifier": ident, "password": pw})["token"]
    print("[1/4] logged in as admin")

    # Hours 11:30-17:00 Mon-Thu + recurring 3:00-3:30 PM break
    avail = _req("GET", f"{base}/api/admin/availability", token=tok)
    for k in ("mon", "tue", "wed", "thu"):
        avail.setdefault("days", {}).setdefault(k, {"enabled": True, "start": "11:30"})
        avail["days"][k]["enabled"] = True
        avail["days"][k]["end"] = "17:00"
    avail["break_start"], avail["break_end"] = "15:00", "15:30"
    _req("PUT", f"{base}/api/admin/availability", token=tok, body=avail)
    print("[2/4] set Mon-Thu 11:30-17:00 + daily break 15:00-15:30")

    res = _req("POST", f"{base}/api/internal/appointments/import", token=tok,
               body={"appointments": APPOINTMENTS, "breaks": [], "dry_run": False})
    print(f"[3/4] import -> created {res['created']}, linked {res['linked']}, "
          f"link_required {res['link_required']}, skipped_duplicate {res['skipped_duplicate']}")

    for d in BLOCKED_DAYS:
        r = _req("POST", f"{base}/api/internal/calendar/block-day", token=tok, body={"date": d})
        print(f"      block-day {d}: {r.get('slots_blocked')} slot(s) blocked")
    print("[4/4] done. Verify Admin calendar + Patient Portal availability.")


if __name__ == "__main__":
    main()
