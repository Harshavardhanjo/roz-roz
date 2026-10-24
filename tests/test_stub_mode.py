"""USE_STUBS=true serves the example payloads with no database, for building the web app and agents."""

from fastapi.testclient import TestClient

from app import stubs
from app.main import create_app

stub = TestClient(create_app(use_stubs=True))
H = {"X-Roz-Token": "anything"}


def test_dashboard_and_errors():
    assert stub.get(f"/api/households/{stubs.HOUSEHOLD_ID}/dashboard", headers=H).json() == stubs.DASHBOARD
    r = stub.get("/api/me")
    assert r.status_code == 403 and r.json()["error"]["code"] == "missing_token"


def test_tools():
    auth = {"Authorization": "Bearer test-tools"}
    bad = stub.post(
        "/tools/create_advance_request", headers=auth, json={"args": {"amount_paise": -1}, "idempotency_key": "k"}
    )
    assert bad.json()["ok"] is False and bad.json()["error"]["code"] == "invalid_args"
    ok = stub.post(
        "/tools/get_helper_context",
        headers=auth,
        json={"args": {"whatsapp_e164": "+910000000000"}, "idempotency_key": "k2"},
    )
    assert ok.json()["result"] == stubs.HELPER_CONTEXT


def test_whatsapp_verify():
    r = stub.get(
        "/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "change-me", "hub.challenge": "42"}
    )
    assert r.text == "42"
