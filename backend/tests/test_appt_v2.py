"""VISITA appointment v2 workflow tests: availability, slot-based requests,
staff offer, patient selection, admin availability config, notifications."""
import os
import uuid
import copy
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://visita-admin.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("kevinrodriguez9528@gmail.com", "VisitaAdmin2026!")
STAFF = ("staff@visita.demo", "Staff2026!")
MARIA = ("maria.lopez@demo.com", "Patient2026!")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok(): return _login(*ADMIN)


@pytest.fixture(scope="module")
def staff_tok(): return _login(*STAFF)


@pytest.fixture(scope="module")
def maria_tok(): return _login(*MARIA)


@pytest.fixture(scope="module")
def fresh_patient():
    """Register + verify a new patient so offer/select tests can run deterministically."""
    email = f"test_p2_{uuid.uuid4().hex[:8]}@demo.com"
    reg = requests.post(f"{API}/auth/register", json={
        "patient_type": "OHIP", "first_name": "TEST", "last_name": "PatientV2",
        "date_of_birth": "1990-01-01", "phone": "555-9999", "email": email,
        "password": "Patient2026!", "health_card_number": "1111222233AB",
        "health_card_version": "AB", "province": "ON",
    })
    assert reg.status_code == 200, reg.text
    tok = reg.json()["token"]
    # verify via staff
    staff_tok = _login(*STAFF)
    v = requests.get(f"{API}/internal/verifications", headers=_h(staff_tok)).json()
    mine = [x for x in v if x["email"] == email][0]
    r = requests.post(f"{API}/internal/verifications/{mine['id']}", headers=_h(staff_tok),
                      json={"decision": "verified"})
    assert r.status_code == 200
    return {"email": email, "tok": tok, "patient_id": mine["id"]}


# ------------------ AVAILABILITY SLOTS ------------------
class TestAvailabilitySlots:
    def test_slots_shape_and_days(self, maria_tok):
        r = requests.get(f"{API}/availability/slots?days=14", headers=_h(maria_tok))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["timezone"] == "America/Toronto"
        assert d["duration"] == 30
        slots = d["slots"]
        assert len(slots) > 0
        allowed_weekdays = {"Monday", "Tuesday", "Wednesday", "Thursday"}
        for s in slots:
            assert s["weekday"] in allowed_weekdays, f"Unexpected weekday: {s}"
            hh, mm = s["time"].split(":")
            minutes = int(hh) * 60 + int(mm)
            assert 11 * 60 + 30 <= minutes < 16 * 60 + 30, f"Out-of-hours slot: {s}"
            for k in ("date", "weekday", "time", "label", "display"):
                assert k in s


# ------------------ PATIENT SLOT-BASED REQUESTS ------------------
class TestPatientSlotRequests:
    def test_success_with_valid_slots(self, maria_tok):
        slots = requests.get(f"{API}/availability/slots?days=14",
                             headers=_h(maria_tok)).json()["slots"][:3]
        r = requests.post(f"{API}/portal/appointments", headers=_h(maria_tok),
                          json={"reason": "TEST_v2_valid", "options": slots})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "requested"
        assert len(d["preferred_options"]) == 3

    def test_empty_options_rejected(self, maria_tok):
        r = requests.post(f"{API}/portal/appointments", headers=_h(maria_tok),
                          json={"reason": "TEST_v2_empty", "options": []})
        assert r.status_code == 400

    def test_out_of_hours_sunday_rejected(self, maria_tok):
        # 2026-01-25 is a Sunday
        bad = [{"date": "2026-01-25", "time": "12:00", "label": "12:00 PM"}]
        r = requests.post(f"{API}/portal/appointments", headers=_h(maria_tok),
                          json={"reason": "TEST_v2_sunday", "options": bad})
        assert r.status_code == 400
        assert "available hours" in r.text.lower() or "outside" in r.text.lower()

    def test_out_of_hours_early_time_rejected(self, maria_tok):
        # Grab a valid date (Mon-Thu) but with an out-of-hours time 09:00
        slots = requests.get(f"{API}/availability/slots?days=14",
                             headers=_h(maria_tok)).json()["slots"]
        d = slots[0]["date"]
        r = requests.post(f"{API}/portal/appointments", headers=_h(maria_tok),
                          json={"reason": "TEST_v2_early",
                                "options": [{"date": d, "time": "09:00", "label": "9:00 AM"}]})
        assert r.status_code == 400


# ------------------ STAFF DIRECT APPROVE + VALIDATION ------------------
class TestStaffApprove:
    def test_approve_valid_and_counter(self, staff_tok, fresh_patient):
        slots = requests.get(f"{API}/availability/slots?days=14",
                             headers=_h(fresh_patient["tok"])).json()["slots"][:3]
        p = requests.post(f"{API}/portal/appointments", headers=_h(fresh_patient["tok"]),
                          json={"reason": "TEST_v2_approve", "options": slots})
        assert p.status_code == 200
        aid = p.json()["id"]
        slot = slots[0]

        # Counter delta unreliable with parallel workers; verify the specific appt is confirmed.
        r = requests.patch(f"{API}/internal/appointments/{aid}", headers=_h(staff_tok),
                           json={"action": "approve",
                                 "confirmed_date": slot["date"], "confirmed_time": slot["time"],
                                 "confirmed_display": slot["display"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "confirmed"
        assert d["approved_by"]
        assert d["confirmed_display"]
        # verify no longer in requested queue
        q = requests.get(f"{API}/internal/appointments?status=requested", headers=_h(staff_tok)).json()
        assert not any(x["id"] == aid for x in q)
    def test_approve_invalid_time_rejected(self, staff_tok, fresh_patient):
        slots = requests.get(f"{API}/availability/slots?days=14",
                             headers=_h(fresh_patient["tok"])).json()["slots"][:3]
        p = requests.post(f"{API}/portal/appointments", headers=_h(fresh_patient["tok"]),
                          json={"reason": "TEST_v2_bad_approve", "options": slots})
        aid = p.json()["id"]
        r = requests.patch(f"{API}/internal/appointments/{aid}", headers=_h(staff_tok),
                           json={"action": "approve",
                                 "confirmed_date": "2026-01-25", "confirmed_time": "09:00"})
        assert r.status_code == 400
        assert "availab" in r.text.lower() or "outside" in r.text.lower()


# ------------------ OFFER -> SELECT -> CONFIRMED ------------------
class TestOfferSelect:
    def test_offer_select_flow(self, staff_tok, fresh_patient):
        pat_tok = fresh_patient["tok"]
        slots = requests.get(f"{API}/availability/slots?days=14",
                             headers=_h(pat_tok)).json()["slots"]
        req_slots = slots[:3]
        offer_slots = slots[3:5]

        p = requests.post(f"{API}/portal/appointments", headers=_h(pat_tok),
                          json={"reason": "TEST_v2_offer", "options": req_slots})
        assert p.status_code == 200
        aid = p.json()["id"]

        c0 = requests.get(f"{API}/internal/counters", headers=_h(staff_tok)).json()["counters"]["appointments"]

        r = requests.patch(f"{API}/internal/appointments/{aid}", headers=_h(staff_tok),
                           json={"action": "offer", "offered_slots": offer_slots})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "alternatives_offered"
        assert len(r.json()["offered_slots"]) == 2

        # counter delta unreliable in parallel; assert this appt no longer in requested queue
        q = requests.get(f"{API}/internal/appointments?status=requested", headers=_h(staff_tok)).json()
        assert not any(x["id"] == aid for x in q)

        # patient overview
        o = requests.get(f"{API}/portal/overview", headers=_h(pat_tok)).json()
        mine = [x for x in o["appointments"] if x["id"] == aid][0]
        assert mine["raw_status"] == "alternatives_offered"
        assert len(mine["offered_slots"]) == 2

        # patient selects
        sel = requests.post(f"{API}/portal/appointments/{aid}/select",
                            headers=_h(pat_tok), json={"index": 0})
        assert sel.status_code == 200, sel.text
        d = sel.json()
        assert d["status"] == "confirmed"
        assert d["approved_by"] == "Patient selection"
        assert d["confirmed_display"]

        # can't select again
        sel2 = requests.post(f"{API}/portal/appointments/{aid}/select",
                             headers=_h(pat_tok), json={"index": 0})
        assert sel2.status_code == 400

    def test_select_not_in_alternatives_offered(self, staff_tok, fresh_patient):
        pat_tok = fresh_patient["tok"]
        slots = requests.get(f"{API}/availability/slots?days=14",
                             headers=_h(pat_tok)).json()["slots"][:3]
        p = requests.post(f"{API}/portal/appointments", headers=_h(pat_tok),
                          json={"reason": "TEST_v2_no_offer", "options": slots})
        aid = p.json()["id"]
        r = requests.post(f"{API}/portal/appointments/{aid}/select",
                          headers=_h(pat_tok), json={"index": 0})
        assert r.status_code == 400


# ------------------ NOTIFICATIONS INTEGRATION ------------------
class TestNotifications:
    def test_confirm_creates_outbound_and_in_portal(self, staff_tok, fresh_patient):
        pat_tok = fresh_patient["tok"]
        slots = requests.get(f"{API}/availability/slots?days=14", headers=_h(pat_tok)).json()["slots"][:3]
        secret_reason = "TEST_secret_reason_" + uuid.uuid4().hex[:6]
        p = requests.post(f"{API}/portal/appointments", headers=_h(pat_tok),
                          json={"reason": secret_reason, "options": slots})
        aid = p.json()["id"]
        slot = slots[0]
        requests.patch(f"{API}/internal/appointments/{aid}", headers=_h(staff_tok),
                       json={"action": "approve", "confirmed_date": slot["date"],
                             "confirmed_time": slot["time"], "confirmed_display": slot["display"]})

        o = requests.get(f"{API}/portal/overview", headers=_h(pat_tok)).json()
        notes = o["notifications"]
        assert any("confirmed" in (n.get("title","") + n.get("body","")).lower() for n in notes)
        # verify reason NOT leaked in in-portal note body/title
        for n in notes:
            assert secret_reason not in (n.get("title") or "")
            assert secret_reason not in (n.get("body") or "")

    def test_offer_creates_in_portal_note(self, staff_tok, fresh_patient):
        pat_tok = fresh_patient["tok"]
        slots = requests.get(f"{API}/availability/slots?days=14", headers=_h(pat_tok)).json()["slots"]
        p = requests.post(f"{API}/portal/appointments", headers=_h(pat_tok),
                          json={"reason": "TEST_v2_note_offer", "options": slots[:3]})
        aid = p.json()["id"]
        requests.patch(f"{API}/internal/appointments/{aid}", headers=_h(staff_tok),
                       json={"action": "offer", "offered_slots": slots[3:5]})
        o = requests.get(f"{API}/portal/overview", headers=_h(pat_tok)).json()
        notes = o["notifications"]
        assert any("time" in (n.get("title","") + n.get("body","")).lower() for n in notes)


# ------------------ ADMIN AVAILABILITY CONFIG ------------------
class TestAdminAvailability:
    def test_admin_get(self, admin_tok):
        r = requests.get(f"{API}/admin/availability", headers=_h(admin_tok))
        assert r.status_code == 200
        d = r.json()
        assert d["days"]["mon"]["enabled"] is True
        assert d["days"]["fri"]["enabled"] is False

    def test_staff_forbidden_get(self, staff_tok):
        r = requests.get(f"{API}/admin/availability", headers=_h(staff_tok))
        assert r.status_code == 403

    def test_staff_forbidden_put(self, staff_tok):
        r = requests.put(f"{API}/admin/availability", headers=_h(staff_tok), json={"days": {}})
        assert r.status_code == 403

    def test_admin_enable_friday_shows_slots(self, admin_tok, maria_tok):
        original = requests.get(f"{API}/admin/availability", headers=_h(admin_tok)).json()
        try:
            new_cfg = copy.deepcopy(original)
            new_cfg["days"]["fri"] = {"enabled": True, "start": "11:30", "end": "16:30"}
            new_cfg.pop("_id", None)
            r = requests.put(f"{API}/admin/availability", headers=_h(admin_tok), json=new_cfg)
            assert r.status_code == 200, r.text
            slots = requests.get(f"{API}/availability/slots?days=14",
                                 headers=_h(maria_tok)).json()["slots"]
            assert any(s["weekday"] == "Friday" for s in slots), "Friday slots not present after enable"
        finally:
            # restore
            restore = copy.deepcopy(original)
            restore.pop("_id", None)
            restore["days"]["fri"] = {"enabled": False, "start": "11:30", "end": "16:30"}
            requests.put(f"{API}/admin/availability", headers=_h(admin_tok), json=restore)


# ------------------ REGRESSION: NO 'suggest' action ------------------
class TestRegressionSuggestGone:
    def test_suggest_action_not_effective(self, staff_tok, fresh_patient):
        pat_tok = fresh_patient["tok"]
        slots = requests.get(f"{API}/availability/slots?days=14", headers=_h(pat_tok)).json()["slots"][:3]
        p = requests.post(f"{API}/portal/appointments", headers=_h(pat_tok),
                          json={"reason": "TEST_v2_regress_suggest", "options": slots})
        aid = p.json()["id"]
        r = requests.patch(f"{API}/internal/appointments/{aid}", headers=_h(staff_tok),
                           json={"action": "suggest", "staff_note": "old"})
        # Should be 200 but status NOT change to 'suggested' (new backend ignores unknown action)
        # We just require it did NOT get a 'suggested' status. offered_slots empty.
        if r.status_code == 200:
            assert r.json()["status"] != "suggested"
