"""Professionals module Phase-2 tests: taxonomy import, AOP, RBAC, CRUD, data safety.

Cleans up: deletes any professional_profiles doc it creates via Mongo (no API DELETE).
Never modifies providers/organizations/users/patients/pharmacy/Rx collections."""
import os
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
# fallback for tests container: read from frontend/.env
if not BASE_URL:
    try:
        with open("/app/frontend/.env") as f:
            for ln in f:
                if ln.startswith("REACT_APP_BACKEND_URL"):
                    BASE_URL = ln.split("=", 1)[1].strip().strip('"').rstrip("/")
    except Exception:
        pass

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
STAFF = ("staff@visita.demo", "Staff2026!")
PHYSICIAN = ("PAGUAYO", "Newman2013_!")
PHARM = ("1670dufferin", "PharmNew2026!")


def _login(identifier, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": identifier, "password": password}, timeout=15)
    if r.status_code != 200:
        # try email field
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": identifier, "password": password}, timeout=15)
    return r


@pytest.fixture(scope="module")
def admin_token():
    r = _login(*ADMIN)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_token():
    r = _login(*STAFF)
    if r.status_code != 200:
        pytest.skip(f"staff login failed: {r.status_code}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def physician_token():
    r = _login(*PHYSICIAN)
    if r.status_code != 200:
        pytest.skip(f"physician login failed: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def pharmacy_token():
    r = _login(*PHARM)
    if r.status_code != 200:
        pytest.skip(f"pharmacy login failed: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- Taxonomy counts ----------
class TestTaxonomy:
    def test_taxonomy_counts_and_flags(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/professionals/taxonomy", headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        assert d["imported"] is True
        assert len(d["spheres"]) == 2, f"spheres={len(d['spheres'])}"
        assert len(d["areas"]) == 58, f"areas={len(d['areas'])}"
        assert len(d["specialties"]) == 247, f"specialties={len(d['specialties'])}"
        assert len(d["credentials"]) == 235, f"credentials={len(d['credentials'])}"
        assert len(d["languages"]) == 158, f"languages={len(d['languages'])}"
        assert len(d["practice_types"]) == 24, f"practice_types={len(d['practice_types'])}"
        assert len(d["primary_care_models"]) == 13, f"pcm={len(d['primary_care_models'])}"

    def test_aop_family_medicine_97(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/professionals/areas-of-practice",
                         params={"specialty_id": "133"}, headers=_h(admin_token))
        assert r.status_code == 200
        aop = r.json()
        assert len(aop) == 97, f"AOP fam med = {len(aop)}"
        for row in aop:
            assert row["specialty_id"] == "133"
            assert row["id"].startswith("vaop-")
            assert "category" in row and "name" in row and "sort_order" in row

    def test_aop_empty_for_non_configured(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/professionals/areas-of-practice",
                         params={"specialty_id": "75"}, headers=_h(admin_token))
        assert r.status_code == 200
        assert r.json() == []


# ---------- Data-safety: legacy orphans + Portuguese + FRCPC dup preservation ----------
class TestDataSafety:
    def test_legacy_orphans_and_duplicates(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/professionals/taxonomy", headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        sp_by_id = {str(s["id"]): s for s in d["specialties"]}
        assert "155" in sp_by_id and sp_by_id["155"]["speciality"] == "Book Keeper"
        assert str(sp_by_id["155"]["area_id"]) == "2"
        assert "193" in sp_by_id and sp_by_id["193"]["speciality"] == "Paralegal"
        assert str(sp_by_id["193"]["area_id"]) == "96"

        langs = {str(l["id"]): l for l in d["languages"]}
        assert "103" in langs and "104" in langs
        assert langs["103"].get("favourite", False) is False
        assert langs["104"].get("favourite", False) is True
        assert langs["103"]["language"].lower().startswith("portug")
        assert langs["104"]["language"].lower().startswith("portug")

        frcpc = [c for c in d["credentials"] if str(c.get("credentials", "")).upper() == "FRCPC"]
        ids = sorted(str(c["id"]) for c in frcpc)
        assert set(["432", "433", "434"]).issubset(set(ids)), f"FRCPC ids={ids}"
        assert len(frcpc) >= 3


# ---------- RBAC ----------
class TestRBAC:
    def test_physician_can_view_but_not_create(self, physician_token):
        r = requests.get(f"{BASE_URL}/api/professionals", headers=_h(physician_token))
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/professionals/taxonomy", headers=_h(physician_token))
        assert r.status_code == 200
        r = requests.post(f"{BASE_URL}/api/professionals",
                          json={"surname": "TEST_RBAC"}, headers=_h(physician_token))
        assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_staff_can_view_but_not_create(self, staff_token):
        r = requests.get(f"{BASE_URL}/api/professionals", headers=_h(staff_token))
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/professionals/taxonomy", headers=_h(staff_token))
        assert r.status_code == 200
        r = requests.post(f"{BASE_URL}/api/professionals",
                          json={"surname": "TEST_RBAC"}, headers=_h(staff_token))
        assert r.status_code == 403

    def test_pharmacy_taxonomy_ok_create_forbidden(self, pharmacy_token):
        r = requests.get(f"{BASE_URL}/api/professionals/taxonomy", headers=_h(pharmacy_token))
        assert r.status_code == 200
        r = requests.post(f"{BASE_URL}/api/professionals",
                          json={"surname": "TEST_RBAC"}, headers=_h(pharmacy_token))
        assert r.status_code == 403


# ---------- CRUD lifecycle: create, patch, mongo-delete ----------
class TestProfessionalCRUD:
    created_id = None

    def test_create_family_medicine_profile(self, admin_token):
        body = {
            "surname": "TEST_QAProf",
            "first_name": "QA",
            "sphere_id": "1",
            "area_id": "36",
            "specialty_id": "133",
            "registration_number": "REG-TEST-001",
            "credential_ids": ["432", "433", "434"],
            "language_ids": ["103", "104"],
            "areas_of_practice_ids": ["vaop-007"],
            "practice_type_ids": ["vpt-01"],
            "primary_care_model_ids": ["vpcm-03"],
            "accepting_patients": True,
        }
        r = requests.post(f"{BASE_URL}/api/professionals", json=body, headers=_h(admin_token))
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        d = r.json()
        assert d["surname"] == "TEST_QAProf"
        assert d["sphere_id"] == "1" and d["area_id"] == "36" and d["specialty_id"] == "133"
        assert set(d["credential_ids"]) == {"432", "433", "434"}
        assert set(d["language_ids"]) == {"103", "104"}
        assert d["areas_of_practice_ids"] == ["vaop-007"]
        assert d["practice_type_ids"] == ["vpt-01"]
        assert d["primary_care_model_ids"] == ["vpcm-03"]
        assert "display_name" in d and "TEST_QAProf" in d["display_name"]
        assert "id" in d
        TestProfessionalCRUD.created_id = d["id"]

        # verify via GET
        g = requests.get(f"{BASE_URL}/api/professionals/{d['id']}", headers=_h(admin_token))
        assert g.status_code == 200
        assert g.json()["registration_number"] == "REG-TEST-001"

    def test_patch_profile(self, admin_token):
        pid = TestProfessionalCRUD.created_id
        assert pid, "no created id"
        body = {"surname": "TEST_QAProf", "language_ids": ["103"], "accepting_patients": False}
        r = requests.patch(f"{BASE_URL}/api/professionals/{pid}", json=body, headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        assert d["language_ids"] == ["103"]
        assert d["accepting_patients"] is False

        g = requests.get(f"{BASE_URL}/api/professionals/{pid}", headers=_h(admin_token))
        assert g.json()["accepting_patients"] is False

    def test_create_requires_surname(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/professionals",
                          json={"surname": ""}, headers=_h(admin_token))
        assert r.status_code == 400

    def test_zzz_cleanup_created_profile(self, admin_token):
        """Cleanup via Mongo (no DELETE endpoint). Leaves professional_profiles empty."""
        pid = TestProfessionalCRUD.created_id
        if not pid:
            return
        # read Mongo url from backend env
        mongo_url = None
        db_name = None
        with open("/app/backend/.env") as f:
            for ln in f:
                if ln.startswith("MONGO_URL"):
                    mongo_url = ln.split("=", 1)[1].strip().strip('"')
                if ln.startswith("DB_NAME"):
                    db_name = ln.split("=", 1)[1].strip().strip('"')
        assert mongo_url and db_name

        async def _del():
            c = AsyncIOMotorClient(mongo_url)
            res = await c[db_name].professional_profiles.delete_one({"id": pid})
            c.close()
            return res.deleted_count

        n = asyncio.get_event_loop().run_until_complete(_del()) if False else asyncio.run(_del())
        assert n == 1

        # verify gone
        g = requests.get(f"{BASE_URL}/api/professionals/{pid}", headers=_h(admin_token))
        assert g.status_code == 404
