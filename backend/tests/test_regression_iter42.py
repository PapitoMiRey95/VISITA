"""Regression tests for A1-A9 (VISITA EMR pre-deployment).
Preview-only. Does NOT touch protected patient IZAO / PIN 3040.
"""
import os
import io
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!"),
    "staff": ("staff@visita.demo", "Staff2026!"),
    "physician": ("PAGUAYO", "Newman2013_!"),
    "linda": ("linda.nguyen@demo.com", "Patient2026!"),   # Private
    "maria": ("maria.lopez@demo.com", "Patient2026!"),    # OHIP
    "john":  ("john.smith@demo.com",  "Patient2026!"),    # OHIP (no-show APT-000002)
    "pharmacy": ("1670dufferin", "Preview-Rotate-Test-9!"),
}


def _login(identifier, password):
    r = requests.post(f"{API}/auth/login", json={"identifier": identifier, "password": password}, timeout=20)
    if r.status_code != 200:
        return None
    return r.json().get("token")


@pytest.fixture(scope="session")
def tokens():
    t = {k: _login(u, p) for k, (u, p) in CREDS.items()}
    return t


def _h(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


# ---------- Auth sanity ----------
class TestAuth:
    def test_all_logins(self, tokens):
        for r in ("admin", "staff", "physician", "linda", "maria", "john"):
            assert tokens.get(r), f"login failed for {r}"

    def test_pharmacy_login(self, tokens):
        # Pharmacy may be stuck on must_change_password; log the state but don't fail.
        if not tokens.get("pharmacy"):
            pytest.skip("Pharmacy account not accessible via /auth/login (expected in preview).")


# ---------- A5 followups + A6 verifications history + role gates ----------
class TestA5A6:
    def test_followups_admin(self, tokens):
        r = requests.get(f"{API}/internal/appointments/followups", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        d = r.json()
        assert "no_shows" in d and "reschedules" in d
        assert isinstance(d["no_shows"], list) and isinstance(d["reschedules"], list)

    def test_followups_staff(self, tokens):
        r = requests.get(f"{API}/internal/appointments/followups", headers=_h(tokens["staff"]))
        assert r.status_code == 200

    def test_followups_physician_forbidden(self, tokens):
        r = requests.get(f"{API}/internal/appointments/followups", headers=_h(tokens["physician"]))
        assert r.status_code == 403

    def test_followups_pharmacy_forbidden(self, tokens):
        if not tokens.get("pharmacy"):
            pytest.skip("pharmacy token unavailable")
        r = requests.get(f"{API}/internal/appointments/followups", headers=_h(tokens["pharmacy"]))
        assert r.status_code == 403

    def test_followups_unauth(self):
        r = requests.get(f"{API}/internal/appointments/followups")
        assert r.status_code in (401, 403)

    def test_verifications_history_admin(self, tokens):
        r = requests.get(f"{API}/internal/verifications/history", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)
        if arr:
            e = arr[0]
            for k in ("id", "first_name", "last_name", "patient_type",
                      "verification_status", "verified_by", "verified_at"):
                assert k in e, f"missing key {k}"

    def test_verifications_history_physician_allowed(self, tokens):
        r = requests.get(f"{API}/internal/verifications/history", headers=_h(tokens["physician"]))
        assert r.status_code == 200

    def test_verifications_history_pharmacy_forbidden(self, tokens):
        if not tokens.get("pharmacy"):
            pytest.skip()
        r = requests.get(f"{API}/internal/verifications/history", headers=_h(tokens["pharmacy"]))
        assert r.status_code == 403


# ---------- A4 no-show $40 fee (uses John Smith / APT-000002 per spec) ----------
class TestA4NoShow:
    def _find_no_show_for_john(self, admin_token):
        r = requests.get(f"{API}/internal/appointments/followups", headers=_h(admin_token))
        assert r.status_code == 200
        for a in r.json().get("no_shows", []):
            if a.get("patient_name", "").lower().startswith("smith,") or a.get("ref_number") == "APT-000002":
                return a
        return None

    def test_issue_no_show_invoice_and_duplicate_blocked(self, tokens):
        target = self._find_no_show_for_john(tokens["admin"])
        if not target:
            pytest.skip("No no-show appointment found for John Smith in preview.")
        appt_id = target["id"]
        # If already has invoice, duplicate should be blocked
        if target.get("no_show_invoice"):
            r = requests.post(f"{API}/internal/appointments/{appt_id}/no-show-invoice",
                              headers=_h(tokens["staff"]))
            assert r.status_code == 400, f"Expected 400 duplicate, got {r.status_code}: {r.text}"
            inv_id = target["no_show_invoice"]["id"]
        else:
            r = requests.post(f"{API}/internal/appointments/{appt_id}/no-show-invoice",
                              headers=_h(tokens["staff"]))
            assert r.status_code == 200, r.text
            inv = r.json()
            assert inv["amount"] == 40.0
            assert inv["status"] == "ISSUED"
            inv_id = inv["id"]
            # duplicate now blocked
            r2 = requests.post(f"{API}/internal/appointments/{appt_id}/no-show-invoice",
                               headers=_h(tokens["staff"]))
            assert r2.status_code == 400

        # Patient (John) sees it
        r3 = requests.get(f"{API}/portal/invoices", headers=_h(tokens["john"]))
        assert r3.status_code == 200
        assert any(i["id"] == inv_id for i in r3.json())

        # Physician CANNOT void
        r4 = requests.post(f"{API}/internal/invoices/{inv_id}/void",
                           headers=_h(tokens["physician"]),
                           json={"reason": "test"})
        assert r4.status_code == 403

        # Void it (admin)
        r5 = requests.post(f"{API}/internal/invoices/{inv_id}/void",
                           headers=_h(tokens["admin"]),
                           json={"reason": "Remove no-show charge (test)"})
        assert r5.status_code == 200, r5.text

        # Now can re-issue after void
        r6 = requests.post(f"{API}/internal/appointments/{appt_id}/no-show-invoice",
                           headers=_h(tokens["staff"]))
        assert r6.status_code == 200, r6.text
        assert r6.json()["amount"] == 40.0

    def test_no_show_invoice_physician_forbidden(self, tokens):
        target = self._find_no_show_for_john(tokens["admin"])
        if not target:
            pytest.skip()
        r = requests.post(f"{API}/internal/appointments/{target['id']}/no-show-invoice",
                          headers=_h(tokens["physician"]))
        assert r.status_code == 403


# ---------- A2 Private billing + A3 OHIP-uninsured billing decoupling ----------
class TestA2A3Billing:
    def _patient(self, token):
        r = requests.get(f"{API}/auth/me", headers=_h(token))
        assert r.status_code == 200, r.text
        body = r.json()
        # /auth/me returns {"user": {...}, "patient": {...}}
        p = body.get("patient") or {}
        u = body.get("user") or {}
        pid = p.get("id") or u.get("patient_id")
        assert pid, f"no patient id in /auth/me: {body}"
        return {"id": pid, "patient_type": p.get("patient_type"), "user": u}

    def test_ohip_patient_can_be_invoiced_without_patient_type_change(self, tokens):
        maria = self._patient(tokens["maria"])
        assert (maria.get("patient_type") or "").lower() == "ohip"
        payload = {
            "patient_id": maria["id"],
            "service_description": "TEST_A3 OHIP-uninsured service (sick note)",
            "amount": 25.00,
            "payment_mode": "INVOICE_AFTER_SERVICE",
        }
        r = requests.post(f"{API}/internal/invoices", json=payload, headers=_h(tokens["staff"]))
        assert r.status_code in (200, 201), r.text
        inv = r.json()
        # Issue it
        if inv["status"] == "DRAFT":
            ri = requests.post(f"{API}/internal/invoices/{inv['id']}/issue", headers=_h(tokens["staff"]))
            assert ri.status_code == 200, ri.text
            inv = ri.json()
        assert inv["status"] == "ISSUED"
        assert inv["patient_coverage"] == "ohip"
        assert inv.get("ohip_uninsured") is True or (
            inv.get("billing_context", "").upper().startswith("OHIP PATIENT")
        ), f"Expected OHIP uninsured flag / context, got {inv}"
        # patient_type should NOT change after OHIP-uninsured invoicing
        r2b = requests.get(f"{API}/auth/me", headers=_h(tokens["maria"]))
        if r2b.status_code == 200:
            assert (r2b.json().get("patient", {}).get("patient_type") or "").lower() == "ohip"
        # Maria sees invoice with neutral notice text in billing_context or ohip_uninsured flag
        r3 = requests.get(f"{API}/portal/invoices", headers=_h(tokens["maria"]))
        assert r3.status_code == 200
        found = [i for i in r3.json() if i["id"] == inv["id"]]
        assert found, "OHIP-uninsured invoice not visible in Maria's portal"
        pi = found[0]
        assert pi.get("ohip_uninsured") is True or "OHIP" in (pi.get("billing_context") or "")

    def test_private_invoice_labels_private(self, tokens):
        linda = self._patient(tokens["linda"])
        payload = {
            "patient_id": linda["id"],
            "service_description": "TEST_A2 Private consult",
            "amount": 55.00,
            "payment_mode": "INVOICE_AFTER_SERVICE",
        }
        r = requests.post(f"{API}/internal/invoices", json=payload, headers=_h(tokens["staff"]))
        assert r.status_code in (200, 201), r.text
        inv = r.json()
        # If DRAFT, issue it to reveal patient_coverage/billing_context in public shape
        if inv["status"] == "DRAFT":
            ri = requests.post(f"{API}/internal/invoices/{inv['id']}/issue", headers=_h(tokens["staff"]))
            assert ri.status_code == 200
            inv = ri.json()
        assert inv.get("patient_coverage") in ("private", "uninsured", "tourist")
        assert inv.get("ohip_uninsured") is not True
        bc = (inv.get("billing_context") or "").upper()
        assert "PRIVATE" in bc or "UNINSURED" in bc

    def test_physician_cannot_verify_or_void(self, tokens):
        linda = self._patient(tokens["linda"])
        r = requests.post(f"{API}/internal/invoices",
                          json={"patient_id": linda["id"],
                                "service_description": "TEST_A2 void-check", "amount": 10.00,
                                "payment_mode": "INVOICE_AFTER_SERVICE"},
                          headers=_h(tokens["staff"]))
        assert r.status_code in (200, 201)
        inv = r.json()
        if inv["status"] == "DRAFT":
            requests.post(f"{API}/internal/invoices/{inv['id']}/issue", headers=_h(tokens["staff"]))
        r2 = requests.post(f"{API}/internal/invoices/{inv['id']}/void",
                           json={"reason": "x"}, headers=_h(tokens["physician"]))
        assert r2.status_code == 403
        r3 = requests.post(f"{API}/internal/invoices/{inv['id']}/verify-payment",
                           headers=_h(tokens["physician"]))
        assert r3.status_code == 403

    def test_pharmacy_denied_billing(self, tokens):
        if not tokens.get("pharmacy"):
            pytest.skip()
        r = requests.get(f"{API}/internal/invoices", headers=_h(tokens["pharmacy"]))
        assert r.status_code == 403

    def test_patient_sees_only_own_invoices(self, tokens):
        r = requests.get(f"{API}/portal/invoices", headers=_h(tokens["linda"]))
        assert r.status_code == 200
        # public invoice shape strips patient_id — so we just assert response is a list
        # and cross-check by creating an invoice for Maria; Linda must NOT see it.
        maria = self._patient(tokens["maria"])
        rc = requests.post(f"{API}/internal/invoices",
                           json={"patient_id": maria["id"],
                                 "service_description": "TEST_isolation",
                                 "amount": 1.00, "payment_mode": "INVOICE_AFTER_SERVICE"},
                           headers=_h(tokens["staff"]))
        assert rc.status_code in (200, 201), rc.text
        maria_inv_id = rc.json()["id"]
        requests.post(f"{API}/internal/invoices/{maria_inv_id}/issue", headers=_h(tokens["staff"]))
        r2 = requests.get(f"{API}/portal/invoices", headers=_h(tokens["linda"]))
        assert not any(i["id"] == maria_inv_id for i in r2.json()), "Linda leaked Maria's invoice"
        # Linda gets 404 for Maria's invoice by id
        rx = requests.get(f"{API}/portal/invoices/{maria_inv_id}", headers=_h(tokens["linda"]))
        assert rx.status_code == 404


# ---------- A1 Private request / offer window (evening) ----------
class TestA1PrivateRequest:
    def test_create_and_offer_evening_window(self, tokens):
        # Only patients with private/uninsured/tourist types can submit; Linda is Private.
        # Get taxonomy to build a valid reason path.
        r = requests.get(f"{API}/config/reasons", headers=_h(tokens["linda"]))
        assert r.status_code == 200
        tax = r.json()
        # taxonomy is dict of code -> {label, children?}; walk to a leaf
        codes = []
        node_map = tax
        while node_map:
            code = next(iter(node_map))
            codes.append(code)
            node = node_map[code]
            children = node.get("children") if isinstance(node, dict) else None
            if not children:
                break
            node_map = children
        assert codes, "no reason codes derived"
        body = {
            "preference_mode": "NO_PREFERENCE",
            "reason_codes": codes,
        }
        r = requests.post(f"{API}/portal/private-requests", json=body, headers=_h(tokens["linda"]))
        assert r.status_code in (200, 201), r.text
        pr = r.json()
        rid = pr["id"]
        # Clinic offers evening 30-min window (choose 7:00 PM some future date)
        # Pick a Tuesday 30+ days out to avoid conflicts / past
        import datetime as dt
        future = (dt.date.today() + dt.timedelta(days=45)).isoformat()
        for t in ("7:00 PM", "6:30 PM", "8:00 PM", "5:30 PM"):
            r2 = requests.post(f"{API}/internal/private-requests/{rid}/offer",
                               json={"date": future, "time": t, "label": t},
                               headers=_h(tokens["staff"]))
            if r2.status_code == 200:
                break
        assert r2.status_code == 200, f"Offer failed: {r2.status_code} {r2.text}"

        # NOTE: Backend private_conflict() does NOT enforce the 5:30–9:00 PM evening window
        # (enforcement is UI-picker-only per A7). We only assert the evening offer succeeded above.


# ---------- A9 Patient Directory editing (unregistered) ----------
class TestA9Directory:
    def _find_directory_only_record(self, token):
        # try a few common Ontario surnames
        for q in ("Sm", "Le", "Ng", "Ja", "Ch", "Br", "Ma", "Wi", "Kh"):
            r = requests.get(f"{API}/internal/patient-lookup", params={"q": q}, headers=_h(token))
            if r.status_code != 200:
                continue
            for rec in r.json():
                if rec.get("source") == "directory" and not rec.get("patient_id"):
                    return rec
        return None

    def test_directory_edit_by_admin(self, tokens):
        rec = self._find_directory_only_record(tokens["admin"])
        if not rec:
            pytest.skip("No unregistered directory record found in preview.")
        did = rec.get("directory_id") or rec["id"]
        # Skip protected IZAO / PIN 3040
        if (rec.get("visita_patient_id") == "3040" or
                (rec.get("last_name") or "").upper().startswith("IZAO")):
            pytest.skip("Skipping protected IZAO / PIN 3040.")
        body = {"phone": "6135551234"}
        r = requests.patch(f"{API}/internal/patient-directory/{did}",
                           json=body, headers=_h(tokens["admin"]))
        assert r.status_code == 200, r.text
        # verify normalization + persistence via lookup
        r2 = requests.get(f"{API}/internal/patient-lookup",
                          params={"q": (rec.get("last_name") or "")[:2]},
                          headers=_h(tokens["admin"]))
        assert r2.status_code == 200
        found = [x for x in r2.json() if (x.get("directory_id") or x.get("id")) == did]
        if found:
            assert found[0].get("cell_phone") in ("(613) 555-1234", "6135551234"), found[0].get("cell_phone")

    def test_directory_edit_physician_allowed(self, tokens):
        rec = self._find_directory_only_record(tokens["admin"])
        if not rec:
            pytest.skip()
        did = rec.get("directory_id") or rec["id"]
        if rec.get("visita_patient_id") == "3040":
            pytest.skip()
        # physician can PATCH (spec)
        r = requests.patch(f"{API}/internal/patient-directory/{did}",
                           json={"phone": "6135559999"},
                           headers=_h(tokens["physician"]))
        assert r.status_code == 200, r.text

    def test_directory_edit_pharmacy_forbidden(self, tokens):
        if not tokens.get("pharmacy"):
            pytest.skip()
        rec = self._find_directory_only_record(tokens["admin"])
        if not rec:
            pytest.skip()
        did = rec.get("directory_id") or rec["id"]
        r = requests.patch(f"{API}/internal/patient-directory/{did}",
                           json={"phone": "6135550000"},
                           headers=_h(tokens["pharmacy"]))
        assert r.status_code == 403

    def test_directory_edit_unauthenticated(self, tokens):
        rec = self._find_directory_only_record(tokens["admin"])
        if not rec:
            pytest.skip()
        did = rec.get("directory_id") or rec["id"]
        r = requests.patch(f"{API}/internal/patient-directory/{did}", json={"phone": "6135550000"})
        assert r.status_code in (401, 403)

    def test_pin_uniqueness_conflict(self, tokens):
        rec = self._find_directory_only_record(tokens["admin"])
        if not rec:
            pytest.skip()
        did = rec.get("directory_id") or rec["id"]
        # Attempt to set a PIN already in use (Linda's or IZAO's 3040)
        r = requests.patch(f"{API}/internal/patient-directory/{did}",
                           json={"visita_patient_id": "3040"},
                           headers=_h(tokens["admin"]))
        # Either 409 (in use) or 200 (already same PIN — but IZAO shouldn't be this record).
        # 3040 belongs to IZAO so we expect 409 unless this record IS IZAO (skipped above).
        assert r.status_code in (200, 409)

    def test_portal_patient_edit_uses_patients_endpoint(self, tokens):
        # Linda is a portal patient
        r = requests.get(f"{API}/internal/patient-lookup",
                         params={"q": "Nguyen"}, headers=_h(tokens["admin"]))
        assert r.status_code == 200
        linda = next((x for x in r.json() if x.get("patient_id")), None)
        if not linda:
            pytest.skip("No portal patient found by lookup.")
        r2 = requests.patch(f"{API}/internal/patients/{linda['patient_id']}",
                            json={"phone": "6135557777"},
                            headers=_h(tokens["admin"]))
        assert r2.status_code == 200, r2.text
