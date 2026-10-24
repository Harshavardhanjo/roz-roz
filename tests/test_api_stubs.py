from fastapi.testclient import TestClient

from app.main import app
from app.stubs import HOUSEHOLD_ID

client = TestClient(app)
H = {"X-Roz-Token": "demo"}


def test_dashboard_stub():
    r = client.get(f"/api/households/{HOUSEHOLD_ID}/dashboard", headers=H)
    assert r.status_code == 200 and r.json()["helpers"][0]["projected_net_paise"] == 813_000


def test_token_required():
    assert client.get("/api/me").status_code == 403


def test_tool_validation_and_stub():
    auth = {"Authorization": "Bearer change-me"}
    bad = client.post("/tools/create_advance_request", headers=auth, json={"args": {"amount_paise": -1}, "idempotency_key": "k1"})
    assert bad.json()["ok"] is False
    ok = client.post("/tools/get_helper_context", headers=auth,
                     json={"args": {"whatsapp_e164": "+910000000000"}, "idempotency_key": "k2"})
    assert ok.json()["result"]["known"] is True


def test_whatsapp_verify():
    r = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "change-me", "hub.challenge": "42"})
    assert r.text == "42"
