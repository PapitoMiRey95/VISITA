"""Tests for new patient portal profile sex/address endpoints (iteration_26)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to reading frontend/.env directly
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.strip().split("=", 1)[1].rstrip("/")

PASSWORD = "Patient2026!"


def _login(identifier):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"identifier": identifier, "password": PASSWORD}, timeout=20)
    assert r.status_code == 200, f"login failed for {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def john_token():
    return _login("john.smith@demo.com")


@pytest.fixture(scope="module")
def carlos_token():
    return _login("carlos.perez@demo.com")


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------- Sex endpoint ----------------
def test_sex_reject_invalid(john_token):
    r = requests.post(f"{BASE_URL}/api/portal/profile/sex",
                      json={"sex": "Other"}, headers=_h(john_token), timeout=15)
    assert r.status_code == 400, r.text


def test_sex_reject_empty(john_token):
    r = requests.post(f"{BASE_URL}/api/portal/profile/sex",
                      json={"sex": ""}, headers=_h(john_token), timeout=15)
    assert r.status_code == 400


def test_sex_accept_and_persist(john_token):
    # save
    r = requests.post(f"{BASE_URL}/api/portal/profile/sex",
                      json={"sex": "Male"}, headers=_h(john_token), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("sex") == "Male"
    # verify overview reflects
    o = requests.get(f"{BASE_URL}/api/portal/overview", headers=_h(john_token), timeout=15)
    assert o.status_code == 200
    assert o.json()["patient"]["sex"] == "Male"


def test_sex_all_options_carlos(carlos_token):
    for v in ["Male", "Female", "X"]:
        r = requests.post(f"{BASE_URL}/api/portal/profile/sex",
                          json={"sex": v}, headers=_h(carlos_token), timeout=15)
        assert r.status_code == 200, f"{v}: {r.text}"
        assert r.json()["sex"] == v
    # confirm last value persisted
    o = requests.get(f"{BASE_URL}/api/portal/overview", headers=_h(carlos_token), timeout=15).json()
    assert o["patient"]["sex"] == "X"


# ---------------- Address endpoint ----------------
def test_address_instant_update_and_persist(john_token):
    payload = {"address": "123 TEST Main St", "unit": "4B",
               "city": "Toronto", "province": "ON", "postal_code": "M5V 2T6"}
    r = requests.post(f"{BASE_URL}/api/portal/profile/address",
                      json=payload, headers=_h(john_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    for k, v in payload.items():
        assert body.get(k) == v
    # persistence via overview
    o = requests.get(f"{BASE_URL}/api/portal/overview", headers=_h(john_token), timeout=15).json()
    pt = o["patient"]
    for k, v in payload.items():
        assert pt.get(k) == v, f"overview {k}={pt.get(k)} != {v}"


def test_address_partial_update(carlos_token):
    payload = {"address": "789 TEST Bay St", "unit": "", "city": "Toronto",
               "province": "ON", "postal_code": "M5H 2N1"}
    r = requests.post(f"{BASE_URL}/api/portal/profile/address",
                      json=payload, headers=_h(carlos_token), timeout=15)
    assert r.status_code == 200
    # empty unit should be normalized to None per code
    assert r.json().get("unit") in (None, "")


def test_sex_endpoint_requires_auth():
    r = requests.post(f"{BASE_URL}/api/portal/profile/sex",
                      json={"sex": "Male"}, timeout=15)
    assert r.status_code in (401, 403)


def test_address_endpoint_requires_auth():
    r = requests.post(f"{BASE_URL}/api/portal/profile/address",
                      json={"address": "x"}, timeout=15)
    assert r.status_code in (401, 403)
