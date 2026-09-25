"""Test isolation of internal attachment endpoints for patient/pharmacy roles."""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
PATIENT = ("maria.lopez@demo.com", "Patient2026!")


def _login(identifier, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": identifier, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def patient_token():
    return _login(*PATIENT)


def _first_imaging_id(admin_token):
    r = requests.get(f"{BASE_URL}/api/internal/imaging",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data:
        pytest.skip("No imaging requests in queue to test")
    return data[0]["id"]


def test_patient_cannot_list_internal_imaging_attachments(admin_token, patient_token):
    imaging_id = _first_imaging_id(admin_token)
    r = requests.get(f"{BASE_URL}/api/internal/imaging/{imaging_id}/attachments",
                     headers={"Authorization": f"Bearer {patient_token}"}, timeout=15)
    assert r.status_code == 403, f"Expected 403 for patient, got {r.status_code}: {r.text}"


def test_patient_cannot_upload_internal_imaging_attachment(admin_token, patient_token):
    imaging_id = _first_imaging_id(admin_token)
    files = {"file": ("t.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")}
    r = requests.post(f"{BASE_URL}/api/internal/imaging/{imaging_id}/attachments",
                      headers={"Authorization": f"Bearer {patient_token}"},
                      files=files, timeout=15)
    assert r.status_code == 403, f"Expected 403 for patient upload, got {r.status_code}: {r.text}"


def test_admin_disallowed_type_returns_400(admin_token):
    imaging_id = _first_imaging_id(admin_token)
    files = {"file": ("t.txt", io.BytesIO(b"hello world"), "text/plain")}
    r = requests.post(f"{BASE_URL}/api/internal/imaging/{imaging_id}/attachments",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, timeout=15)
    assert r.status_code == 400, f"Expected 400 for disallowed type, got {r.status_code}: {r.text}"


def test_admin_can_upload_list_download_delete_png(admin_token):
    imaging_id = _first_imaging_id(admin_token)
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
    files = {"file": ("test.png", io.BytesIO(png), "image/png")}
    r = requests.post(f"{BASE_URL}/api/internal/imaging/{imaging_id}/attachments",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, timeout=15)
    assert r.status_code in (200, 201), r.text
    att_id = r.json().get("id")
    assert att_id

    # list
    r2 = requests.get(f"{BASE_URL}/api/internal/imaging/{imaging_id}/attachments",
                      headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r2.status_code == 200
    assert any(a["id"] == att_id for a in r2.json())

    # download
    r3 = requests.get(f"{BASE_URL}/api/internal/attachments/{att_id}/download",
                      headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r3.status_code == 200

    # delete
    r4 = requests.delete(f"{BASE_URL}/api/internal/attachments/{att_id}",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r4.status_code in (200, 204)

    # verify gone
    r5 = requests.get(f"{BASE_URL}/api/internal/imaging/{imaging_id}/attachments",
                      headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r5.status_code == 200
    assert not any(a["id"] == att_id for a in r5.json())
