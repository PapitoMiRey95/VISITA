"""Security regression tests for seed_all() hardening.

Verifies:
- Admin password is NEVER overwritten on startup (create-if-missing only).
- No default admin/physician password fallback.
- Demo data is NOT seeded unless ALLOW_DEMO_SEEDING is explicitly enabled.
- An existing physician password is never overwritten.
Runs against a throwaway database so it never touches app data.
"""
import os
import sys
import uuid
import asyncio

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

sys.path.insert(0, "/app/backend")
import auth as authlib  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from seed import seed_all  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _new_db():
    client = AsyncIOMotorClient(MONGO_URL)
    name = f"seedtest_{uuid.uuid4().hex[:8]}"
    return client, client[name], name


def _clear_flags(monkeypatch):
    monkeypatch.delenv("ALLOW_DEMO_SEEDING", raising=False)
    monkeypatch.delenv("ALLOW_DATA_MIGRATIONS", raising=False)


def test_admin_password_not_overwritten(monkeypatch):
    _clear_flags(monkeypatch)
    client, db, name = _new_db()
    try:
        monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
        old_hash = authlib.hash_password("OriginalPass123!")
        _run(db.users.insert_one({
            "email": "owner@example.com", "password_hash": old_hash,
            "name": "Owner", "role": "admin", "active": True,
        }))
        monkeypatch.setenv("ADMIN_PASSWORD", "AttackerKnownPass!")
        _run(seed_all(db, authlib))
        doc = _run(db.users.find_one({"email": "owner@example.com"}))
        assert authlib.verify_password("OriginalPass123!", doc["password_hash"]), "admin password was overwritten!"
        assert not authlib.verify_password("AttackerKnownPass!", doc["password_hash"])
    finally:
        _run(client.drop_database(name))
        client.close()


def test_no_default_admin_when_env_missing(monkeypatch):
    _clear_flags(monkeypatch)
    client, db, name = _new_db()
    try:
        monkeypatch.delenv("ADMIN_EMAIL", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        _run(seed_all(db, authlib))
        assert _run(db.users.find_one({"email": "admin@example.com"})) is None
        assert _run(db.users.count_documents({"role": "admin"})) == 0
    finally:
        _run(client.drop_database(name))
        client.close()


def test_demo_not_seeded_without_flag(monkeypatch):
    _clear_flags(monkeypatch)
    client, db, name = _new_db()
    try:
        monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
        monkeypatch.setenv("ADMIN_PASSWORD", "OriginalPass123!")
        _run(seed_all(db, authlib))
        assert _run(db.users.find_one({"email": "staff@visita.demo"})) is None
        assert _run(db.users.find_one({"email": "maria.lopez@demo.com"})) is None
        assert _run(db.app_meta.find_one({"id": "seeded_v1"})) is None
    finally:
        _run(client.drop_database(name))
        client.close()


def test_demo_seeded_with_flag(monkeypatch):
    _clear_flags(monkeypatch)
    client, db, name = _new_db()
    try:
        monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
        monkeypatch.setenv("ADMIN_PASSWORD", "OriginalPass123!")
        monkeypatch.setenv("ALLOW_DEMO_SEEDING", "true")
        _run(seed_all(db, authlib))
        assert _run(db.users.find_one({"email": "staff@visita.demo"})) is not None
        assert _run(db.app_meta.find_one({"id": "seeded_v1"})) is not None
    finally:
        _run(client.drop_database(name))
        client.close()


def test_existing_physician_not_overwritten(monkeypatch):
    _clear_flags(monkeypatch)
    client, db, name = _new_db()
    try:
        monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
        monkeypatch.setenv("ADMIN_PASSWORD", "OriginalPass123!")
        monkeypatch.setenv("PHYSICIAN_USERNAME", "PAGUAYO")
        monkeypatch.setenv("PHYSICIAN_TEMP_PASSWORD", "SomeTemp#2026")
        phys_hash = authlib.hash_password("RealDoctorPass!")
        _run(db.users.insert_one({
            "username": "PAGUAYO", "role": "physician", "name": "Dr. Pablo Aguayo",
            "password_hash": phys_hash, "active": True, "must_change_password": False,
        }))
        _run(seed_all(db, authlib))
        doc = _run(db.users.find_one({"role": "physician"}))
        assert authlib.verify_password("RealDoctorPass!", doc["password_hash"]), "physician password was overwritten!"
        assert doc.get("must_change_password") is False
    finally:
        _run(client.drop_database(name))
        client.close()
