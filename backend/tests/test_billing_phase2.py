"""Phase 2 Billing tests — invoices, payment proof, prepayment auto-invoice,
security, and void preservation. Runs against preview URL."""
import io
import os
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"

CREDS = {
    "admin":   ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!"),
    "staff":   ("staff@visita.demo", "Staff2026!"),
    "physician": ("PAGUAYO", "Newman2013_!"),
    "linda":   ("linda.nguyen@demo.com", "Patient2026!"),
    "maria":   ("maria.lopez@demo.com", "Patient2026!"),
    "pharmacy": ("1670dufferin", "Preview-Rotate-Test-9!"),
}


def _login(role):
    ident, pw = CREDS[role]
    r = requests.post(f"{BASE}/auth/login", json={"identifier": ident, "password": pw}, timeout=20)
    assert r.status_code == 200, f"login {role} failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json().get("user", {})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def toks():
    out = {}
    for k in ("admin", "staff", "linda", "maria", "pharmacy"):
        try:
            out[k], _ = _login(k)
        except AssertionError as e:
            pytest.skip(f"Cannot login {k}: {e}")
    # physician optional (temp pw may have changed)
    try:
        out["physician"], _ = _login("physician")
    except Exception:
        out["physician"] = None
    return out


def _linda_patient_id(toks):
    r = requests.get(f"{BASE}/internal/patients", params={"q": "Linda"}, headers=_h(toks["staff"]), timeout=20)
    assert r.status_code == 200
    for p in r.json():
        n = (p.get("first_name") or "") + " " + (p.get("last_name") or "")
        if "Linda" in n and "Nguyen" in n:
            return p["id"]
    pytest.skip("Linda Nguyen not found")


# ---------------- INVOICE AFTER SERVICE FLOW ----------------
class TestInvoiceLifecycle:
    def test_create_draft_and_issue(self, toks):
        pid = _linda_patient_id(toks)
        r = requests.post(f"{BASE}/internal/invoices", headers=_h(toks["staff"]), json={
            "patient_id": pid, "service_description": "TEST_ medical letter",
            "amount": 42.5, "payment_mode": "INVOICE_AFTER_SERVICE"
        }, timeout=20)
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["status"] == "DRAFT"
        assert inv["amount"] == 42.5
        assert inv["invoice_number"].startswith("INV-")
        assert "_id" not in inv
        inv_id = inv["id"]

        # patient should NOT see DRAFT
        r2 = requests.get(f"{BASE}/portal/invoices", headers=_h(toks["linda"]), timeout=20)
        assert r2.status_code == 200
        ids = [x["id"] for x in r2.json()]
        assert inv_id not in ids, "DRAFT invoice leaked to patient"

        # issue
        r3 = requests.post(f"{BASE}/internal/invoices/{inv_id}/issue", headers=_h(toks["staff"]), timeout=20)
        assert r3.status_code == 200
        assert r3.json()["status"] == "ISSUED"
        assert r3.json()["issue_date"]

        # visible to patient
        r4 = requests.get(f"{BASE}/portal/invoices", headers=_h(toks["linda"]), timeout=20)
        ids = [x["id"] for x in r4.json()]
        assert inv_id in ids
        mine = next(x for x in r4.json() if x["id"] == inv_id)
        assert mine["etransfer_email"] == "dufferinpatients@gmail.com"
        assert mine["payment_required"] is True
        pytest.inv_id_for_proof = inv_id

    def test_upload_proof_and_verify(self, toks):
        inv_id = pytest.inv_id_for_proof
        # patient uploads a JPG proof
        f = ("proof.jpg", io.BytesIO(b"\xff\xd8\xff\xe0" + b"0" * 200), "image/jpeg")
        r = requests.post(f"{BASE}/portal/invoices/{inv_id}/proof", headers=_h(toks["linda"]),
                          files={"file": f}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "PAYMENT_SUBMITTED"
        assert data["payment_proof"]["attachment_id"]
        att_id = data["payment_proof"]["attachment_id"]

        # staff can download
        r2 = requests.get(f"{BASE}/internal/invoices/{inv_id}/proof/{att_id}/download",
                          headers=_h(toks["staff"]), timeout=20)
        assert r2.status_code == 200
        assert r2.headers.get("content-type", "").startswith("image/jpeg")
        assert len(r2.content) > 100

        # patient can download own proof
        r3 = requests.get(f"{BASE}/portal/invoices/{inv_id}/proof/{att_id}/download",
                          headers=_h(toks["linda"]), timeout=20)
        assert r3.status_code == 200

        # physician CANNOT verify
        if toks.get("physician"):
            rp = requests.post(f"{BASE}/internal/invoices/{inv_id}/verify-payment",
                               headers=_h(toks["physician"]), timeout=20)
            assert rp.status_code == 403, f"physician should not verify: {rp.status_code}"

        # staff verifies -> PAID
        r4 = requests.post(f"{BASE}/internal/invoices/{inv_id}/verify-payment",
                           headers=_h(toks["staff"]), timeout=20)
        assert r4.status_code == 200
        assert r4.json()["status"] == "PAID"
        assert r4.json()["paid_at"]

    def test_void_preserves_record(self, toks):
        pid = _linda_patient_id(toks)
        r = requests.post(f"{BASE}/internal/invoices", headers=_h(toks["staff"]), json={
            "patient_id": pid, "service_description": "TEST_ void me",
            "amount": 10, "payment_mode": "INVOICE_AFTER_SERVICE"
        }, timeout=20)
        assert r.status_code == 200
        inv_id = r.json()["id"]

        # physician cannot void
        if toks.get("physician"):
            rp = requests.post(f"{BASE}/internal/invoices/{inv_id}/void",
                               headers=_h(toks["physician"]), json={"reason": "test"}, timeout=20)
            assert rp.status_code == 403

        rv = requests.post(f"{BASE}/internal/invoices/{inv_id}/void",
                           headers=_h(toks["staff"]), json={"reason": "TEST_void_reason"}, timeout=20)
        assert rv.status_code == 200
        assert rv.json()["status"] == "VOID"
        # still retrievable
        rg = requests.get(f"{BASE}/internal/invoices/{inv_id}", headers=_h(toks["staff"]), timeout=20)
        assert rg.status_code == 200
        assert rg.json()["status"] == "VOID"


# ---------------- PREPAYMENT AUTO-INVOICE ----------------
class TestPrepaymentAutoInvoice:
    def test_prepayment_mode_creates_issued_invoice(self, toks):
        # find or create a private request for Linda
        r = requests.get(f"{BASE}/internal/private-requests", headers=_h(toks["staff"]), timeout=20)
        assert r.status_code == 200
        def _pn(x):
            pn = x.get("patient_name")
            if isinstance(pn, dict):
                return f"{pn.get('first_name','')} {pn.get('last_name','')}"
            return str(pn or "")
        prs = [x for x in r.json() if "Linda" in _pn(x) and "Nguyen" in _pn(x)
               and x.get("status") not in ("CANCELLED", "DECLINED")]
        if not prs:
            pytest.skip("No open Linda private request to bill against")
        rid = prs[0]["id"]

        rp = requests.post(f"{BASE}/internal/private-requests/{rid}/payment-mode",
                           headers=_h(toks["staff"]),
                           json={"payment_mode": "PREPAYMENT_REQUIRED", "amount": 55,
                                 "service_description": "TEST_ prepay consult"}, timeout=20)
        assert rp.status_code == 200, rp.text
        body = rp.json()
        assert body["payment_mode"] == "PREPAYMENT_REQUIRED"
        assert body["invoice"] is not None
        assert body["invoice"]["status"] == "ISSUED"
        assert body["invoice"]["amount"] == 55.0

        # request now shows payment mode + status
        rd = requests.get(f"{BASE}/internal/private-requests/{rid}", headers=_h(toks["staff"]), timeout=20)
        assert rd.status_code == 200
        det = rd.json()
        assert det["payment_mode"] == "PREPAYMENT_REQUIRED"
        assert det["payment_status"] in ("PENDING", "PAYMENT_SUBMITTED")
        assert any(i["id"] == body["invoice"]["id"] for i in det.get("invoices", []))

        # Linda sees it
        rl = requests.get(f"{BASE}/portal/invoices", headers=_h(toks["linda"]), timeout=20)
        assert body["invoice"]["id"] in [x["id"] for x in rl.json()]


# ---------------- SECURITY ----------------
class TestSecurity:
    def test_cross_patient_forbidden(self, toks):
        # find a Linda invoice
        r = requests.get(f"{BASE}/portal/invoices", headers=_h(toks["linda"]), timeout=20)
        assert r.status_code == 200 and r.json()
        inv_id = r.json()[0]["id"]

        # Maria tries to open it
        rm = requests.get(f"{BASE}/portal/invoices/{inv_id}", headers=_h(toks["maria"]), timeout=20)
        assert rm.status_code == 404, f"Cross-patient access must 404, got {rm.status_code}"

    def test_pharmacy_role_forbidden(self, toks):
        r1 = requests.get(f"{BASE}/internal/invoices", headers=_h(toks["pharmacy"]), timeout=20)
        assert r1.status_code == 403
        r2 = requests.get(f"{BASE}/portal/invoices", headers=_h(toks["pharmacy"]), timeout=20)
        assert r2.status_code in (403, 400)

    def test_unauth_denied(self):
        assert requests.get(f"{BASE}/internal/invoices", timeout=20).status_code in (401, 403)
        assert requests.get(f"{BASE}/portal/invoices", timeout=20).status_code in (401, 403)

    def test_proof_not_public(self, toks):
        # use existing proof from earlier suite if available, else create one
        r = requests.get(f"{BASE}/portal/invoices", headers=_h(toks["linda"]), timeout=20)
        proofed = [x for x in r.json() if x.get("payment_proof")]
        if not proofed:
            pytest.skip("no proof invoice to check")
        inv = proofed[0]
        att = inv["payment_proof"]["attachment_id"]
        # no auth
        rn = requests.get(f"{BASE}/portal/invoices/{inv['id']}/proof/{att}/download", timeout=20)
        assert rn.status_code in (401, 403)
        # cross-patient
        rc = requests.get(f"{BASE}/portal/invoices/{inv['id']}/proof/{att}/download",
                          headers=_h(toks["maria"]), timeout=20)
        assert rc.status_code in (403, 404)
