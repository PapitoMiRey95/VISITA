"""Phase C: Results & Reports push-based release flow tests."""
import os
import io
import time
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

ADMIN = {"email": "kevinrodriguez9528@gmail.com", "password": "VisitaAdmin2026!"}
MARIA = {"email": "maria.lopez@demo.com", "password": "Patient2026!"}
LINDA = {"email": "linda.nguyen@demo.com", "password": "Patient2026!"}
MARIA_ID = "06f6ee08-58f7-4286-82f5-7c845de99ce1"
BLD_ID = "9f8bc920-e8db-485d-b109-ef7e1a8b5177"

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _login(email, password, portal=False):
    s = requests.Session()
    url = f"{BASE}/api/auth/login"
    r = s.post(url, json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    token = r.json().get("token")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def admin():
    return _login(**ADMIN)


@pytest.fixture(scope="module")
def maria():
    return _login(**MARIA, portal=True)


@pytest.fixture(scope="module")
def linda():
    return _login(**LINDA, portal=True)


@pytest.fixture
def internal_attachment(admin):
    """Upload an internal PDF attached to Maria's bloodwork; cleanup afterwards."""
    files = {"file": ("TEST_results.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    r = admin.post(f"{BASE}/api/internal/bloodwork/{BLD_ID}/attachments", files=files)
    assert r.status_code in (200, 201), f"upload failed {r.status_code} {r.text}"
    att = r.json()
    att_id = att.get("id") or att.get("att_id") or att.get("_id")
    assert att_id, f"no att id in {att}"
    yield att_id
    # cleanup
    admin.delete(f"{BASE}/api/internal/attachments/{att_id}")


class TestReleaseFlow:
    def test_before_release_patient_cannot_see_or_download(self, admin, maria, internal_attachment):
        att_id = internal_attachment
        # Not in portal list
        r = maria.get(f"{BASE}/api/portal/documents")
        assert r.status_code == 200
        payload = r.json()
        docs = payload if isinstance(payload, list) else payload.get("documents", [])
        ids = [d.get("id") or d.get("att_id") for d in docs]
        assert att_id not in ids
        # Direct download 404
        r2 = maria.get(f"{BASE}/api/portal/documents/{att_id}/download")
        assert r2.status_code == 404

    def test_release_then_patient_sees_with_metadata(self, admin, maria, internal_attachment):
        att_id = internal_attachment
        body = {
            "result_category": "Laboratory",
            "result_subtype": "Bloodwork",
            "reviewed_by": "Dr. Pablo Aguayo",
            "notify": False,
        }
        r = admin.post(f"{BASE}/api/internal/attachments/{att_id}/share", json=body)
        assert r.status_code == 200, f"share failed {r.status_code} {r.text}"

        # Patient list contains it
        r2 = maria.get(f"{BASE}/api/portal/documents")
        assert r2.status_code == 200
        payload = r2.json()
        docs = payload if isinstance(payload, list) else payload.get("documents", [])
        match = next((d for d in docs if (d.get("id") or d.get("att_id")) == att_id), None)
        assert match, f"released doc not in portal: {docs}"
        assert match.get("reviewed_by") == "Dr. Pablo Aguayo"
        # type_label should be subtype
        assert match.get("type_label") in ("Bloodwork", "Laboratory") 
        # Download works
        r3 = maria.get(f"{BASE}/api/portal/documents/{att_id}/download")
        assert r3.status_code == 200
        assert r3.content.startswith(b"%PDF")

    def test_other_patient_404_after_release(self, admin, linda, internal_attachment):
        att_id = internal_attachment
        admin.post(
            f"{BASE}/api/internal/attachments/{att_id}/share",
            json={"result_category": "Laboratory", "result_subtype": "Bloodwork",
                  "reviewed_by": "Dr. Pablo Aguayo", "notify": False},
        )
        r = linda.get(f"{BASE}/api/portal/documents/{att_id}/download")
        assert r.status_code == 404


class TestEmptyAndLegacy:
    def test_portal_documents_endpoint_ok(self, maria):
        r = maria.get(f"{BASE}/api/portal/documents")
        assert r.status_code == 200

    def test_old_document_request_endpoint_still_exists(self, maria):
        # Should exist (not deleted) but UI no longer calls it
        r = maria.post(f"{BASE}/api/portal/document-requests", json={"kind": "result", "notes": "TEST"})
        # Accept any non-404 (could be 200/201/400)
        assert r.status_code != 404
