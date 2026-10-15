"""READ-ONLY identity discovery. Never writes. Run: python3 discovery_identity.py"""
import asyncio
import os
import re
from collections import Counter, defaultdict

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()


def nh(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def nm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().upper())


def disp(d, portal=False):
    last = " ".join(x for x in [d.get("last_name"), d.get("second_last_name")] if x)
    first = " ".join(x for x in [d.get("first_name"), d.get("middle_name")] if x)
    return f"{last.upper()}, {first}"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    dirs = await db.patient_directory.find({}, {"_id": 0}).to_list(100000)
    pats = await db.patients.find({}, {"_id": 0}).to_list(100000)
    print("== SCHEMA ==")
    print("patient_directory keys:", sorted(Counter(k for d in dirs for k in d).items(), key=lambda x: -x[1]))
    print("patients keys:", sorted(Counter(k for p in pats for k in p).items(), key=lambda x: -x[1]))
    print("\n== COUNTS ==")
    print("directory total", len(dirs), "status", Counter(d.get("patient_status") for d in dirs))
    print("directory with second_last_name/middle_name:", sum(1 for d in dirs if d.get("second_last_name")), sum(1 for d in dirs if d.get("middle_name")))
    print("directory last_name w/ space (compound):", sum(1 for d in dirs if " " in (d.get("last_name") or "").strip()),
          " first_name w/ space:", sum(1 for d in dirs if " " in (d.get("first_name") or "").strip()))
    print("patients total", len(pats), "verification", Counter(p.get("verification_status") for p in pats),
          "portal_status", Counter(p.get("portal_status") for p in pats))
    print("patients with middle/second_last:", sum(1 for p in pats if p.get("middle_name")), sum(1 for p in pats if p.get("second_last_name")))
    print("patients linked (matched_directory_id):", sum(1 for p in pats if p.get("matched_directory_id")),
          " identity_linked=True:", sum(1 for p in pats if p.get("identity_linked")))
    print("directory linked_patient_id set:", sum(1 for d in dirs if d.get("linked_patient_id")))

    dir_by_id = {d["id"]: d for d in dirs}
    pat_by_id = {p["id"]: p for p in pats}
    dir_by_hcn = defaultdict(list)
    for d in dirs:
        h = nh(d.get("health_card_number")) or d.get("norm_hcn")
        if h:
            dir_by_hcn[h].append(d)
    pat_by_hcn = defaultdict(list)
    for p in pats:
        h = nh(p.get("health_card_number"))
        if h:
            pat_by_hcn[h].append(p)

    print("\n== B. VERIFIED portal, matched_directory_id = null ==")
    B = [p for p in pats if p.get("verification_status") == "verified" and not p.get("matched_directory_id")]
    print(len(B))
    for p in B:
        h = nh(p.get("health_card_number"))
        cands = dir_by_hcn.get(h, []) if h else []
        dobc = [d for d in dirs if d.get("norm_dob") == p.get("date_of_birth") and nm(d.get("last_name")).startswith(nm(p.get("last_name")).split(" ")[0]) and nm(d.get("first_name")).split(" ")[0] == nm(p.get("first_name")).split(" ")[0]]
        print(f"  {disp(p)} | DOB {p.get('date_of_birth')} | PIN {p.get('visita_patient_id')} | hcn={'Y' if h else 'N'} | portal_status={p.get('portal_status')} is_unclaimed={p.get('is_unclaimed')} demo={p.get('is_demo')}"
              f"\n     HCN-dir-candidates={[(disp(d), d.get('visita_patient_id'), d.get('patient_status'), d.get('linked_patient_id')) for d in cands]}"
              f"\n     DOB+name-dir-candidates={[(disp(d), d.get('visita_patient_id'), d.get('patient_status')) for d in dobc][:3]}")

    print("\n== A. exact-HCN portal<->directory pairs ==")
    A = []
    for h, ps in pat_by_hcn.items():
        ds = dir_by_hcn.get(h)
        if ds:
            for p in ps:
                for d in ds:
                    A.append((p, d))
    print(len(A))
    cls = Counter()
    for p, d in A:
        if p.get("matched_directory_id") == d["id"] and d.get("linked_patient_id") == p["id"]:
            c = "ALREADY_LINKED"
        elif p.get("matched_directory_id") == d["id"] or d.get("linked_patient_id") == p["id"]:
            c = "HALF_LINKED"
        elif d.get("linked_patient_id") and d.get("linked_patient_id") != p["id"]:
            c = "DIR_LINKED_TO_OTHER_PORTAL"
        elif p.get("date_of_birth") == d.get("norm_dob") or p.get("date_of_birth") == (d.get("date_of_birth") or "")[:10]:
            c = "SAFE_LINK_CANDIDATE(HCN+DOB)"
        else:
            c = "AMBIGUOUS_REVIEW(HCN match, DOB differs)"
        cls[c] += 1
        if c != "ALREADY_LINKED":
            print(f"  [{c}] portal={disp(p)} ({p.get('verification_status')}, PIN {p.get('visita_patient_id')}, DOB {p.get('date_of_birth')})  dir={disp(d)} (PIN {d.get('visita_patient_id')}, DOB {d.get('norm_dob')}, {d.get('patient_status')})")
    print("  classes:", dict(cls))

    print("\n== C. multiple portal accounts sharing one HCN ==")
    C = {h: ps for h, ps in pat_by_hcn.items() if len(ps) > 1}
    print(len(C))
    for h, ps in C.items():
        print("  ", [(disp(p), p.get("verification_status"), p.get("matched_directory_id") and "linked") for p in ps])

    print("\n== D. multiple directory records sharing one HCN ==")
    D = {h: ds for h, ds in dir_by_hcn.items() if len(ds) > 1}
    print(len(D))
    for h, ds in list(D.items())[:15]:
        print("  ", [(disp(d), d.get("visita_patient_id"), d.get("patient_status"), d.get("norm_dob")) for d in ds])

    print("\n== E. one directory record with >1 portal candidate (by matched_directory_id or HCN) ==")
    cand = defaultdict(set)
    for p in pats:
        if p.get("matched_directory_id"):
            cand[p["matched_directory_id"]].add(p["id"])
        h = nh(p.get("health_card_number"))
        for d in dir_by_hcn.get(h, []) if h else []:
            cand[d["id"]].add(p["id"])
    E = {k: v for k, v in cand.items() if len(v) > 1}
    print(len(E))
    for k, v in E.items():
        d = dir_by_id.get(k, {})
        print("  dir", disp(d), d.get("visita_patient_id"), "->", [(disp(pat_by_id[x]), pat_by_id[x].get("verification_status")) for x in v])

    print("\n== Half-links: matched_directory_id set but directory.linked_patient_id mismatch ==")
    for p in pats:
        m = p.get("matched_directory_id")
        if m:
            d = dir_by_id.get(m)
            if not d:
                print("  DANGLING matched_directory_id", disp(p), m)
            elif d.get("linked_patient_id") != p["id"]:
                print("  MISMATCH", disp(p), p.get("verification_status"), "dir.linked_patient_id=", d.get("linked_patient_id"))

    print("\n== G. linked pairs whose names differ (name component loss) ==")
    for p in pats:
        m = p.get("matched_directory_id")
        d = dir_by_id.get(m) if m else None
        if d and nm(disp(p)) != nm(disp(d)):
            print(f"  portal={disp(p)}  dir={disp(d)}  verified={p.get('verification_status')}")

    print("\n== F. (search-visible) verified portal w/o link whose name+DOB matches an ACTIVE directory record ==")
    for p in B:
        for d in dirs:
            if d.get("patient_status") != "ACTIVE" or d.get("norm_dob") != p.get("date_of_birth"):
                continue
            if nm(d.get("first_name")).split(" ")[0] == nm(p.get("first_name")).split(" ")[0] and nm(d.get("last_name")).split(" ")[0] == nm(p.get("last_name")).split(" ")[0]:
                print(f"  portal={disp(p)} PIN {p.get('visita_patient_id')}  <->  dir={disp(d)} PIN {d.get('visita_patient_id')}  linked_to={d.get('linked_patient_id')}  hcn portal={nh(p.get('health_card_number'))[:3]}… dir={(d.get('norm_hcn') or '')[:3]}…")

    print("\n== Angie Guardo pattern (any source) ==")
    for d in dirs:
        if "GUARDO" in nm(d.get("last_name")):
            print("  dir:", d.get("first_name"), "|", d.get("last_name"), "|", d.get("norm_dob"), d.get("visita_patient_id"), d.get("patient_status"), "linked=", d.get("linked_patient_id"))
    for p in pats:
        if "GUARDO" in nm(p.get("last_name")) or "GUARDO" in nm(p.get("second_last_name")):
            print("  portal:", p.get("first_name"), "|", p.get("middle_name"), "|", p.get("last_name"), "|", p.get("second_last_name"), p.get("date_of_birth"), p.get("verification_status"), "matched=", p.get("matched_directory_id"))

    print("\n== Audit: patient_linked / identity_linked / verify_patient counts ==")
    for a in ["verify_patient", "patient_linked", "identity_linked", "register", "directory_match_suggested"]:
        print("  ", a, await db.audit_logs.count_documents({"action": a}))


asyncio.run(main())
