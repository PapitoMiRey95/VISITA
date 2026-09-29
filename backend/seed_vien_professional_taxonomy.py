"""VIen Professional Construct — MODERN VIen-native taxonomy seed (runtime source).

Writes ONLY the vien_professional_* collections used by the modern Professional
Profile editor / self-onboarding. Legacy Access-origin professional_* collections
are NEVER read, written, or referenced here (reference data for the deferred
Legacy Access Directory / Referral project).

Idempotent: every doc is upserted by a deterministic slug-based VIen id, so IDs
never change between reruns and reruns never create duplicates. Never runs at
server startup — invoke explicitly:

    python seed_vien_professional_taxonomy.py

Hierarchy: Sphere → Professional Area → Specialty → Areas of Practice.
Family Medicine is a Specialty under Professional Area = Physician
(id vspec-family-medicine). The approved 97 Areas of Practice options attach to it.
"""
import asyncio
import os
import re
import unicodedata
from pathlib import Path

import openpyxl
from motor.motor_asyncio import AsyncIOMotorClient

from seed_professional_taxonomy import AOP_CATEGORIES, PRACTICE_TYPES, PRIMARY_CARE_MODELS

FAMILY_MEDICINE_ID = "vspec-family-medicine"
LEGACY_LANGUAGE_SOURCE = Path(__file__).parent / "taxonomy_sources" / "tblLanguage.xlsx"  # name vocabulary only


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.replace("&", " and ").replace("+", " plus ")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


SPHERES = [("Health", 1), ("Non-Health", 2)]

# (name, sphere, requires registration number)
AREAS = [
    ("Physician", "Health", True), ("Nurse Practitioner", "Health", True),
    ("Registered Nurse", "Health", True), ("Registered Practical Nurse", "Health", True),
    ("Physician Assistant", "Health", False), ("Pharmacist", "Health", True),
    ("Social Worker", "Health", True), ("Dietitian", "Health", True),
    ("Physiotherapist", "Health", True), ("Occupational Therapist", "Health", True),
    ("Psychologist", "Health", True), ("Psychotherapist", "Health", True),
    ("Chiropractor", "Health", True), ("Dentist", "Health", True),
    ("Dental Hygienist", "Health", True), ("Optometrist", "Health", True),
    ("Midwife", "Health", True), ("Speech-Language Pathologist", "Health", True),
    ("Audiologist", "Health", True), ("Respiratory Therapist", "Health", True),
    ("Kinesiologist", "Health", True), ("Massage Therapist", "Health", True),
    ("Naturopathic Doctor", "Health", True), ("Chiropodist / Podiatrist", "Health", True),
    ("Paramedic", "Health", False), ("Medical Laboratory Technologist", "Health", True),
    ("Medical Radiation Technologist", "Health", True), ("Other Health Professional", "Health", False),
    ("Practice Administrator / Manager", "Non-Health", False), ("Lawyer", "Non-Health", False),
    ("Accountant", "Non-Health", False), ("Other Non-Health Professional", "Non-Health", False),
]

SPECIALTIES = {
    "Physician": [
        "Family Medicine", "General Practice", "Emergency Medicine", "Hospital Medicine",
        "Internal Medicine", "Cardiology", "Respirology", "Gastroenterology", "Nephrology",
        "Endocrinology & Metabolism", "Rheumatology", "Hematology", "Medical Oncology",
        "Radiation Oncology", "Infectious Diseases", "Geriatric Medicine", "Palliative Medicine",
        "Neurology", "Psychiatry", "Dermatology", "Pediatrics", "Obstetrics & Gynecology",
        "General Surgery", "Orthopedic Surgery", "Neurosurgery", "Cardiac Surgery",
        "Thoracic Surgery", "Vascular Surgery", "Plastic Surgery", "Urology",
        "Otolaryngology (ENT)", "Ophthalmology", "Anesthesiology", "Diagnostic Radiology",
        "Nuclear Medicine", "Pathology", "Physical Medicine & Rehabilitation",
        "Public Health & Preventive Medicine", "Occupational Medicine", "Sports Medicine",
        "Pain Medicine", "Allergy & Clinical Immunology", "Critical Care Medicine",
        "Medical Genetics", "Addiction Medicine", "Sleep Medicine",
    ],
    "Nurse Practitioner": ["Primary Health Care", "Adult", "Pediatrics", "Anesthesia"],
    "Registered Nurse": ["General Nursing", "Community Nursing", "Mental Health Nursing", "Palliative Nursing"],
    "Registered Practical Nurse": ["General Practical Nursing"],
    "Physician Assistant": ["Primary Care", "Emergency Medicine", "Surgery"],
    "Pharmacist": ["Community Pharmacy", "Hospital Pharmacy", "Clinical Pharmacy", "Long-Term Care Pharmacy"],
    "Social Worker": ["Clinical Social Work", "Medical Social Work", "Community Social Work"],
    "Dietitian": ["Clinical Dietetics", "Community Nutrition", "Diabetes Education"],
    "Physiotherapist": ["Orthopedic Physiotherapy", "Neurological Physiotherapy", "Pelvic Health", "Cardiorespiratory Physiotherapy"],
    "Occupational Therapist": ["General Occupational Therapy", "Mental Health OT", "Pediatric OT", "Hand Therapy"],
    "Psychologist": ["Clinical Psychology", "Neuropsychology", "Child & Adolescent Psychology", "Health Psychology"],
    "Psychotherapist": ["Registered Psychotherapy", "Counselling"],
    "Chiropractor": ["General Chiropractic"],
    "Dentist": ["General Dentistry", "Orthodontics", "Oral & Maxillofacial Surgery", "Periodontics", "Endodontics", "Pediatric Dentistry"],
    "Dental Hygienist": ["General Dental Hygiene"],
    "Optometrist": ["General Optometry"],
    "Midwife": ["Registered Midwifery"],
    "Speech-Language Pathologist": ["General Speech-Language Pathology"],
    "Audiologist": ["Clinical Audiology"],
    "Respiratory Therapist": ["General Respiratory Therapy"],
    "Kinesiologist": ["General Kinesiology"],
    "Massage Therapist": ["General Massage Therapy"],
    "Naturopathic Doctor": ["General Naturopathic Medicine"],
    "Chiropodist / Podiatrist": ["General Chiropody / Podiatry"],
    "Paramedic": ["Primary Care Paramedic", "Advanced Care Paramedic", "Critical Care Paramedic"],
    "Medical Laboratory Technologist": ["General Medical Laboratory Technology"],
    "Medical Radiation Technologist": ["Radiography", "Nuclear Medicine Technology", "Radiation Therapy", "Magnetic Resonance"],
    "Other Health Professional": ["Other"],
    "Practice Administrator / Manager": ["Practice Management", "Medical Office Administration"],
    "Lawyer": ["Health Law", "General Practice Law"],
    "Accountant": ["Chartered Professional Accountant", "Bookkeeping"],
    "Other Non-Health Professional": ["Other"],
}

# (label, description) — one entry per credential label, no duplicates.
CREDENTIALS = [
    ("MD", "Doctor of Medicine"), ("MDCM", "Doctor of Medicine and Master of Surgery (McGill)"),
    ("DO", "Doctor of Osteopathic Medicine"), ("MBBS", "Bachelor of Medicine, Bachelor of Surgery"),
    ("MBChB", "Bachelor of Medicine, Bachelor of Surgery"),
    ("CCFP", "Certificant, College of Family Physicians of Canada"),
    ("CCFP (EM)", "Certificate of Added Competence in Emergency Medicine"),
    ("CCFP (PC)", "Certificate of Added Competence in Palliative Care"),
    ("CCFP (COE)", "Certificate of Added Competence in Care of the Elderly"),
    ("CCFP (AM)", "Certificate of Added Competence in Addiction Medicine"),
    ("CCFP (SEM)", "Certificate of Added Competence in Sport and Exercise Medicine"),
    ("FCFP", "Fellow, College of Family Physicians of Canada"),
    ("FRCPC", "Fellow, Royal College of Physicians of Canada"),
    ("FRCSC", "Fellow, Royal College of Surgeons of Canada"),
    ("LMCC", "Licentiate of the Medical Council of Canada"),
    ("ABFM", "Diplomate, American Board of Family Medicine"),
    ("FACP", "Fellow, American College of Physicians"), ("FACC", "Fellow, American College of Cardiology"),
    ("FACS", "Fellow, American College of Surgeons"), ("FAAP", "Fellow, American Academy of Pediatrics"),
    ("DTM&H", "Diploma in Tropical Medicine and Hygiene"),
    ("Dip. Sport Med.", "Diploma in Sport Medicine (CASEM)"),
    ("PhD", "Doctor of Philosophy"), ("DSc", "Doctor of Science"), ("DrPH", "Doctor of Public Health"),
    ("MSc", "Master of Science"), ("MPH", "Master of Public Health"), ("MHSc", "Master of Health Science"),
    ("MHA", "Master of Health Administration"), ("MBA", "Master of Business Administration"),
    ("MEd", "Master of Education"), ("MA", "Master of Arts"), ("BSc", "Bachelor of Science"),
    ("BA", "Bachelor of Arts"), ("BHSc", "Bachelor of Health Sciences"),
    ("NP", "Nurse Practitioner"), ("NP-PHC", "Nurse Practitioner — Primary Health Care"),
    ("RN(EC)", "Registered Nurse (Extended Class)"), ("RN", "Registered Nurse"),
    ("RPN", "Registered Practical Nurse"), ("BScN", "Bachelor of Science in Nursing"),
    ("MN", "Master of Nursing"), ("MScN", "Master of Science in Nursing"),
    ("RPh", "Registered Pharmacist"), ("PharmD", "Doctor of Pharmacy"),
    ("BScPhm", "Bachelor of Science in Pharmacy"), ("ACPR", "Accredited Canadian Pharmacy Residency"),
    ("RSW", "Registered Social Worker"), ("MSW", "Master of Social Work"), ("BSW", "Bachelor of Social Work"),
    ("RD", "Registered Dietitian"), ("PDt", "Professional Dietitian"),
    ("PT", "Physiotherapist"), ("MScPT", "Master of Science in Physical Therapy"), ("MPT", "Master of Physical Therapy"),
    ("OT Reg. (Ont.)", "Registered Occupational Therapist (Ontario)"), ("MScOT", "Master of Science in Occupational Therapy"),
    ("C.Psych.", "Registered Psychologist"), ("C.Psych.Assoc.", "Registered Psychological Associate"),
    ("RP", "Registered Psychotherapist"),
    ("DC", "Doctor of Chiropractic"), ("DDS", "Doctor of Dental Surgery"), ("DMD", "Doctor of Dental Medicine"),
    ("RDH", "Registered Dental Hygienist"), ("OD", "Doctor of Optometry"), ("RM", "Registered Midwife"),
    ("SLP", "Speech-Language Pathologist"), ("Reg. CASLPO", "Registered with CASLPO"),
    ("Aud", "Audiologist"), ("RRT", "Registered Respiratory Therapist"), ("R.Kin", "Registered Kinesiologist"),
    ("RMT", "Registered Massage Therapist"), ("ND", "Naturopathic Doctor"),
    ("D.Ch", "Diploma in Chiropody"), ("DPM", "Doctor of Podiatric Medicine"),
    ("PA", "Physician Assistant"), ("CCPA", "Canadian Certified Physician Assistant"),
    ("PCP", "Primary Care Paramedic"), ("ACP", "Advanced Care Paramedic"), ("CCP", "Critical Care Paramedic"),
    ("MLT", "Medical Laboratory Technologist"), ("MRT(R)", "Medical Radiation Technologist (Radiography)"),
    ("MRT(N)", "Medical Radiation Technologist (Nuclear Medicine)"),
    ("MRT(T)", "Medical Radiation Technologist (Radiation Therapy)"),
    ("MRT(MR)", "Medical Radiation Technologist (Magnetic Resonance)"),
    ("CDE", "Certified Diabetes Educator"), ("CHE", "Certified Health Executive"),
    ("LLB", "Bachelor of Laws"), ("JD", "Juris Doctor"), ("CPA", "Chartered Professional Accountant"),
]


def build_spheres():
    return [{"id": f"vsph-{slug(n)}", "name": n, "sort_order": i} for n, i in SPHERES]


def build_areas():
    return [{"id": f"varea-{slug(n)}", "sphere_id": f"vsph-{slug(s)}", "name": n,
             "required": req, "active": True, "sort_order": i}
            for i, (n, s, req) in enumerate(AREAS, 1)]


def build_specialties():
    out, n = [], 0
    for area, names in SPECIALTIES.items():
        for name in names:
            n += 1
            out.append({"id": f"vspec-{slug(name)}" if area == "Physician" else f"vspec-{slug(area)}-{slug(name)}",
                        "area_id": f"varea-{slug(area)}", "name": name, "active": True, "sort_order": n})
    assert any(s["id"] == FAMILY_MEDICINE_ID for s in out)
    assert len({s["id"] for s in out}) == len(out)
    return out


def build_credentials():
    out = [{"id": f"vcred-{slug(l)}", "name": l, "description": d, "active": True, "sort_order": i}
           for i, (l, d) in enumerate(CREDENTIALS, 1)]
    assert len({c["id"] for c in out}) == len(out)
    return out


def build_languages():
    """Name vocabulary from the Access language export (labels only; Access IDs NOT reused).
    Exact-duplicate labels (Portuguese) collapse into one modern entry."""
    ws = openpyxl.load_workbook(LEGACY_LANGUAGE_SOURCE, data_only=True).active
    seen, out = {}, []
    for _id, name, fav in list(ws.iter_rows(values_only=True))[1:]:
        if not name:
            continue
        name = str(name).strip()
        if name in seen:
            seen[name]["favourite"] = seen[name]["favourite"] or bool(fav)
            continue
        seen[name] = {"id": f"vlang-{slug(name)}", "name": name, "favourite": bool(fav), "active": True}
        out.append(seen[name])
    for i, d in enumerate(sorted(out, key=lambda x: x["name"]), 1):
        d["sort_order"] = i
    return out


def build_aop():
    out, n = [], 0
    for category, names in AOP_CATEGORIES:
        for name in names:
            n += 1
            out.append({"id": f"vaop-{n:03d}", "specialty_id": FAMILY_MEDICINE_ID,
                        "category": category, "name": name, "active": True, "sort_order": n})
    return out


def build_practice_types():
    return [{"id": f"vpt-{i:02d}", "name": n, "active": True, "sort_order": i}
            for i, n in enumerate(PRACTICE_TYPES, 1)]


def build_models():
    return [{"id": f"vpcm-{i:02d}", "name": n, "abbreviation": a, "active": True, "sort_order": i}
            for i, (n, a) in enumerate(PRIMARY_CARE_MODELS, 1)]


BUILDERS = [
    ("vien_professional_spheres", build_spheres),
    ("vien_professional_areas", build_areas),
    ("vien_professional_specialties", build_specialties),
    ("vien_professional_credentials", build_credentials),
    ("vien_professional_languages", build_languages),
    ("vien_professional_areas_of_practice", build_aop),
    ("vien_professional_practice_types", build_practice_types),
    ("vien_professional_primary_care_models", build_models),
]


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    print("=== VIen-native Professional taxonomy seed (idempotent upsert) ===")
    for coll, build in BUILDERS:
        docs = build()
        for d in docs:
            await db[coll].update_one({"id": d["id"]}, {"$set": d}, upsert=True)
        print(f"  {coll}: seeded {len(docs)} -> in db {await db[coll].count_documents({})}")
    print("Family Medicine specialty id:", FAMILY_MEDICINE_ID)
    print("Profiles untouched:", await db.professional_profiles.count_documents({}))
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
