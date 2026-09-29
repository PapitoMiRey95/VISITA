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
        assert d["available"] is True
        assert len(d["spheres"]) == 2, f"spheres={len(d['spheres'])}"
        assert len(d["areas"]) == 32, f"areas={len(d['areas'])}"
        assert len(d["specialties"]) == 115, f"specialties={len(d['specialties'])}"
        assert len(d["credentials"]) == 90, f"credentials={len(d['credentials'])}"
        assert len(d["languages"]) == 157, f"languages={len(d['languages'])}"
        assert len(d["practice_types"]) == 24, f"practice_types={len(d['practice_types'])}"
        assert len(d["primary_care_models"]) == 13, f"pcm={len(d['primary_care_models'])}"
        for coll in ("spheres", "areas", "specialties", "credentials", "languages"):
            assert all(str(x["id"]).startswith("v") for x in d[coll]), f"non-VIen id in {coll}"

    def test_aop_family_medicine_97(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/professionals/areas-of-practice",
                         params={"specialty_id": "vspec-family-medicine"}, headers=_h(admin_token))
        assert r.status_code == 200
        aop = r.json()
        assert len(aop) == 97, f"AOP fam med = {len(aop)}"
        for row in aop:
            assert row["specialty_id"] == "vspec-family-medicine"
            assert row["id"].startswith("vaop-")
            assert "category" in row and "name" in row and "sort_order" in row

    def test_aop_empty_for_non_configured(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/professionals/areas-of-practice",
                         params={"specialty_id": "vspec-cardiology"}, headers=_h(admin_token))
        assert r.status_code == 200
        assert r.json() == []


# ---------- Modern VIen-native taxonomy (no legacy Access IDs at runtime) ----------
class TestModernTaxonomy:
    def test_family_medicine_is_physician_specialty_with_vien_id(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/professionals/taxonomy", headers=_h(admin_token))
        d = r.json()
        fm = [s for s in d["specialties"] if s["name"] == "Family Medicine"]
        assert len(fm) == 1 and fm[0]["id"] == "vspec-family-medicine"
        assert fm[0]["area_id"] == "varea-physician"
        phys = [a for a in d["areas"] if a["id"] == "varea-physician"][0]
        assert phys["name"] == "Physician" and phys["required"] is True
        assert phys["sphere_id"] == "vsph-health"
        # No legacy Access numeric ids anywhere in the modern taxonomy
        for s in d["specialties"]:
            assert s["id"] not in ("133", "612")
        langs = [l for l in d["languages"] if l["name"] == "Portuguese"]
        assert len(langs) == 1 and langs[0]["id"] == "vlang-portuguese"
        creds = [c for c in d["credentials"] if c["name"] == "FRCPC"]
        assert len(creds) == 1 and creds[0]["id"] == "vcred-frcpc"
        models = [m["name"] for m in d["primary_care_models"]]
        assert "Family Health Group (FHG)" in models and "Family Integrated Group" not in " ".join(models)


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
            "sphere_id": "vsph-health",
            "area_id": "varea-physician",
            "specialty_id": "vspec-family-medicine",
            "registration_number": "REG-TEST-001",
            "credential_ids": ["vcred-md", "vcred-ccfp", "vcred-fcfp"],
            "language_ids": ["vlang-portuguese", "vlang-spanish"],
            "areas_of_practice_ids": ["vaop-007"],
            "practice_type_ids": ["vpt-01"],
            "primary_care_model_ids": ["vpcm-03"],
            "accepting_patients": True,
        }
        r = requests.post(f"{BASE_URL}/api/professionals", json=body, headers=_h(admin_token))
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        d = r.json()
        assert d["surname"] == "TEST_QAProf"
        assert d["sphere_id"] == "vsph-health" and d["area_id"] == "varea-physician" and d["specialty_id"] == "vspec-family-medicine"
        assert set(d["credential_ids"]) == {"vcred-md", "vcred-ccfp", "vcred-fcfp"}
        assert set(d["language_ids"]) == {"vlang-portuguese", "vlang-spanish"}
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
        body = {"surname": "TEST_QAProf", "language_ids": ["vlang-spanish"], "accepting_patients": False}
        r = requests.patch(f"{BASE_URL}/api/professionals/{pid}", json=body, headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        assert d["language_ids"] == ["vlang-spanish"]
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
