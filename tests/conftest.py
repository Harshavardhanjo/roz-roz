"""Integration tests run against a real Postgres (TEST_DATABASE_URL). The schema is rebuilt once per session from
migrations/*.sql and every table is truncated before each test."""

import os
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:54329/rozroz_test"
)
os.environ.update(
    USE_STUBS="false",
    AGENT_RUNTIME="off",
    ENABLE_SCHEDULER="false",
    TODAY_OVERRIDE="2026-10-24",
    TOOLS_TOKEN="test-tools",
    ADMIN_TOKEN="test-admin",
    WEB_ORIGIN="http://localhost:3000",
    WA_BUSINESS_NUMBER="919000000000",
    DEMO_HELPER_E164="+919811100001",
    DEMO_HELPER2_E164="+919811100002",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from seed.demo_seed import TABLES  # noqa: E402

TOOLS = {"Authorization": "Bearer test-tools"}


@pytest.fixture(scope="session", autouse=True)
def schema():
    with engine.begin() as conn:
        conn.execute(text("drop schema public cascade; create schema public"))
        for path in sorted(Path(__file__).resolve().parent.parent.joinpath("migrations").glob("*.sql")):
            conn.exec_driver_sql(path.read_text())
    yield


@pytest.fixture(autouse=True)
def clean():
    with engine.begin() as conn:
        conn.execute(text(f"truncate {', '.join(TABLES)} restart identity cascade"))
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="session")
def client():
    with TestClient(create_app()) as c:
        yield c


def tool(client: TestClient, name: str, key: str, **args) -> dict:
    """Call an agent tool; returns the parsed response body."""
    return client.post(f"/tools/{name}", headers=TOOLS, json={"args": args, "idempotency_key": key}).json()


class Flat:
    """A household built through the public API: owner + one roommate, both granted, one consented cook."""

    def __init__(self, client: TestClient, topup_each: int = 800_000, grant: bool = True, **terms):
        r = client.post(
            "/api/households", json={"household_name": "Test Flat", "owner_name": "Asha", "owner_phone": "9000000011"}
        ).json()
        self.client, self.hid = client, r["household_id"]
        self.owner = {"X-Roz-Token": r["token"]}
        self.owner_id = r["member_id"]
        m = client.post(
            f"/api/households/{self.hid}/members", headers=self.owner, json={"name": "Ravi", "phone": "9000000012"}
        ).json()
        self.roommate, self.roommate_id = {"X-Roz-Token": m["token"]}, m["member_id"]
        body = {
            "name": "Lakshmi",
            "whatsapp_e164": "+91 98111 00009",
            "lang": "kn",
            "role": "cook",
            "salary_paise": 1_000_000,
            "payday_dom": 31,
            "weekly_off": [6],
            "paid_leaves_per_month": 2,
            "deduct_extra_leave": True,
            "advance_auto_limit_paise": 50_000,
            "advance_monthly_limit_paise": 200_000,
            "grocery_auto_limit_paise": 50_000,
            "grocery_monthly_budget_paise": 600_000,
        } | terms
        h = client.post(f"/api/households/{self.hid}/helpers", headers=self.owner, json=body)
        assert h.status_code == 201, h.text
        self.eid, self.helper_id = h.json()["employment_id"], h.json()["helper_id"]
        consent = tool(
            client, "record_consent", f"consent-{self.eid}", helper_id=self.helper_id, employment_ids=[self.eid]
        )
        assert consent["ok"], consent
        if grant:
            for headers, mid in ((self.owner, self.owner_id), (self.roommate, self.roommate_id)):
                assert client.post(f"/api/members/{mid}/grant", headers=headers).status_code == 201
        for headers in (self.owner, self.roommate):
            if topup_each:
                assert (
                    client.post(
                        f"/api/households/{self.hid}/topups", headers=headers, json={"amount_paise": topup_each}
                    ).status_code
                    == 201
                )

    def dashboard(self, headers=None) -> dict:
        return self.client.get(f"/api/households/{self.hid}/dashboard", headers=headers or self.owner).json()

    def balance(self) -> int:
        return self.dashboard()["house_wallet"]["balance_paise"]

    def ask(self, name: str, key: str, **args) -> dict:
        r = tool(self.client, name, key, employment_id=self.eid, **args)
        assert r["ok"], r
        return r["result"]
