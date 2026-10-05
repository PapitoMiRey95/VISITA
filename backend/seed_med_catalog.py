"""Idempotent, additive seed of common Family Medicine medications for the
smart medication search. Safe to re-run. Does NOT delete or overwrite existing
medication_catalog rows (upsert by a dedicated search key). No DIN/strength/
dosage/route is fabricated — this is a SEARCH catalog only."""
import asyncio
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

env = dotenv_values("/app/backend/.env")

# (generic, brand, [aliases/search terms])
MEDS = [
    ("Metformin", "Glucophage", ["diabetes"]),
    ("Empagliflozin", "Jardiance", ["diabetes", "sglt2"]),
    ("Dapagliflozin", "Forxiga", ["diabetes", "sglt2"]),
    ("Sitagliptin", "Januvia", ["diabetes"]),
    ("Gliclazide", "Diamicron", ["diabetes"]),
    ("Semaglutide", "Ozempic", ["rybelsus", "diabetes", "glp1"]),
    ("Insulin glargine", "Lantus", ["basaglar", "insulin", "diabetes"]),
    ("Amlodipine", "Norvasc", ["blood pressure", "hypertension"]),
    ("Ramipril", "Altace", ["ace", "blood pressure"]),
    ("Perindopril", "Coversyl", ["ace", "blood pressure"]),
    ("Lisinopril", "Zestril", ["ace", "blood pressure"]),
    ("Candesartan", "Atacand", ["arb", "blood pressure"]),
    ("Telmisartan", "Micardis", ["arb", "blood pressure"]),
    ("Losartan", "Cozaar", ["arb", "blood pressure"]),
    ("Hydrochlorothiazide", None, ["hctz", "diuretic", "blood pressure"]),
    ("Indapamide", None, ["diuretic"]),
    ("Bisoprolol", None, ["beta blocker"]),
    ("Metoprolol", None, ["beta blocker"]),
    ("Spironolactone", "Aldactone", ["diuretic"]),
    ("Atorvastatin", "Lipitor", ["cholesterol", "statin"]),
    ("Rosuvastatin", "Crestor", ["cholesterol", "statin"]),
    ("Simvastatin", "Zocor", ["cholesterol", "statin"]),
    ("Ezetimibe", "Ezetrol", ["cholesterol"]),
    ("Levothyroxine", "Synthroid", ["eltroxin", "thyroid"]),
    ("Pantoprazole", "Pantoloc", ["ppi", "reflux", "stomach"]),
    ("Omeprazole", "Losec", ["ppi", "reflux", "stomach"]),
    ("Esomeprazole", "Nexium", ["ppi", "reflux"]),
    ("Famotidine", "Pepcid", ["reflux", "stomach"]),
    ("Domperidone", None, ["nausea"]),
    ("Salbutamol", "Ventolin", ["inhaler", "asthma", "puffer"]),
    ("Budesonide/Formoterol", "Symbicort", ["inhaler", "asthma", "copd"]),
    ("Fluticasone/Salmeterol", "Advair", ["inhaler", "asthma", "copd"]),
    ("Fluticasone furoate/Vilanterol", "Breo Ellipta", ["inhaler", "copd"]),
    ("Tiotropium", "Spiriva", ["inhaler", "copd"]),
    ("Montelukast", "Singulair", ["asthma", "allergy"]),
    ("Cetirizine", "Reactine", ["allergy", "antihistamine"]),
    ("Loratadine", "Claritin", ["allergy", "antihistamine"]),
    ("Desloratadine", "Aerius", ["allergy", "antihistamine"]),
    ("Bilastine", "Blexten", ["allergy", "antihistamine"]),
    ("Fluticasone nasal spray", None, ["allergy", "nasal"]),
    ("Sertraline", "Zoloft", ["ssri", "depression", "anxiety"]),
    ("Escitalopram", "Cipralex", ["ssri", "depression", "anxiety"]),
    ("Citalopram", "Celexa", ["ssri", "depression"]),
    ("Fluoxetine", "Prozac", ["ssri", "depression"]),
    ("Venlafaxine", "Effexor", ["snri", "depression", "anxiety"]),
    ("Duloxetine", "Cymbalta", ["snri", "depression", "pain"]),
    ("Bupropion", "Wellbutrin", ["depression"]),
    ("Mirtazapine", "Remeron", ["depression"]),
    ("Trazodone", None, ["sleep", "depression"]),
    ("Acetaminophen", "Tylenol", ["pain", "fever"]),
    ("Naproxen", "Naprosyn", ["nsaid", "pain", "inflammation"]),
    ("Celecoxib", "Celebrex", ["nsaid", "pain", "arthritis"]),
    ("Diclofenac", "Voltaren", ["nsaid", "pain"]),
    ("Tamsulosin", "Flomax", ["prostate", "urology"]),
    ("Finasteride", "Proscar", ["prostate", "hair"]),
    ("Dutasteride", "Avodart", ["prostate"]),
    ("Mirabegron", "Myrbetriq", ["bladder"]),
    ("Solifenacin", "Vesicare", ["bladder"]),
    ("Allopurinol", None, ["gout", "uric acid"]),
    ("Colchicine", None, ["gout"]),
    ("Alendronate", "Fosamax", ["bone", "osteoporosis"]),
    ("Gabapentin", None, ["nerve pain", "neuropathy"]),
    ("Pregabalin", "Lyrica", ["nerve pain", "neuropathy"]),
    ("Valacyclovir", "Valtrex", ["antiviral", "herpes", "shingles"]),
]


def _key(generic):
    return "search:" + "".join(c for c in generic.lower() if c.isalnum())


async def main():
    c = AsyncIOMotorClient(env["MONGO_URL"])
    db = c[env["DB_NAME"]]
    inserted = updated = 0
    for generic, brand, aliases in MEDS:
        terms = [generic]
        if brand:
            terms.append(brand)
        terms += aliases
        res = await db.medication_catalog.update_one(
            {"catalog_key": _key(generic)},
            {"$set": {"drug": generic, "brand": brand, "search_terms": terms,
                      "catalog_source": "family_med_seed"},
             "$setOnInsert": {"catalog_key": _key(generic)}},
            upsert=True,
        )
        if res.upserted_id:
            inserted += 1
        else:
            updated += 1
    total = await db.medication_catalog.count_documents({})
    print(f"seed complete: inserted={inserted} updated={updated} catalog_total={total}")


if __name__ == "__main__":
    asyncio.run(main())
