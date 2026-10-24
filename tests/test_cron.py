"""Vercel Cron calls GET /api/cron/payday with Authorization: Bearer $CRON_SECRET."""

from conftest import Flat

CRON = {"Authorization": "Bearer test-cron"}


def test_cron_needs_the_secret(client):
    assert client.get("/api/cron/payday").status_code == 401
    assert client.get("/api/cron/payday", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_cron_pays_helpers_whose_payday_is_today_once(client):
    due = Flat(client, payday_dom=24)  # TODAY_OVERRIDE is 2026-10-24
    r = client.get("/api/cron/payday", headers=CRON)
    assert r.status_code == 200 and r.json() == {"paid": [due.eid]}
    runs = client.get(f"/api/employments/{due.eid}/payroll", headers=due.owner).json()
    assert [(run["month"], run["status"], run["net_paise"]) for run in runs] == [("2026-10", "executed", 1_000_000)]
    # A second call the same day pays nothing new.
    assert client.get("/api/cron/payday", headers=CRON).json() == {"paid": [due.eid]}
    assert len(client.get(f"/api/employments/{due.eid}/payroll", headers=due.owner).json()) == 1


def test_cron_skips_helpers_not_due(client):
    Flat(client, payday_dom=5)
    assert client.get("/api/cron/payday", headers=CRON).json() == {"paid": []}
