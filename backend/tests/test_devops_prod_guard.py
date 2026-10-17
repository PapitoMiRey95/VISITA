import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import seed  # noqa: E402


class _Coll:
    def __init__(self):
        self.inserted = []

    async def find_one(self, *a, **k):
        return None

    async def insert_one(self, doc):
        self.inserted.append(doc)


async def _run_ops_block(monkeypatch, base_url):
    monkeypatch.setenv("APP_BASE_URL", base_url)
    monkeypatch.setenv("DEVELOPER_OPS_EMAIL", "ops@example.test")
    monkeypatch.setenv("DEVELOPER_OPS_TEMP_PASSWORD", "Tmp-Pass-1!")
    users = _Coll()
    src = open(seed.__file__).read()
    start = src.index("    # developer_ops maintenance account")
    end = src.index("    # Pharmacy portal account")
    block = "\n".join(l[4:] for l in src[start:end].splitlines())
    ns = {"os": seed.os, "db": type("DB", (), {"users": users})(), "authlib": type("A", (), {"hash_password": staticmethod(lambda p: "h")})(),
          "now_iso": seed.now_iso, "_is_production": seed._is_production}
    exec("async def _f():\n" + "\n".join("    " + l for l in block.splitlines()) + "\n", ns)
    await ns["_f"]()
    return users.inserted


def test_production_refuses_devops_provisioning(monkeypatch):
    assert asyncio.run(_run_ops_block(monkeypatch, "https://visitaemr.com")) == []


def test_preview_still_provisions_devops(monkeypatch):
    out = asyncio.run(_run_ops_block(monkeypatch, "https://visita-admin.preview.emergentagent.com"))
    assert len(out) == 1 and out[0]["role"] == "developer_ops" and out[0]["must_change_password"] is True
