"""Auth, scoping and the error format: every error is {"error": {"code", "message"}}."""

import uuid

from conftest import Flat, tool


def error_code(response) -> str:
    body = response.json()
    assert set(body) == {"error"} and {"code", "message"} <= set(body["error"]), body
    return body["error"]["code"]


def test_missing_and_bad_tokens(client):
    assert client.get("/api/me").status_code == 403
    assert error_code(client.get("/api/me")) == "missing_token"
    assert error_code(client.get("/api/me", headers={"X-Roz-Token": "nope"})) == "bad_token"


def test_roommates_cannot_do_owner_things(client):
    flat = Flat(client)
    r = client.post(f"/api/households/{flat.hid}/members", headers=flat.roommate, json={"name": "X", "phone": "1"})
    assert r.status_code == 403 and error_code(r) == "owner_only"
    r = client.post(f"/api/employments/{flat.eid}/payroll/run", headers=flat.roommate, json={"month": "2026-10"})
    assert r.status_code == 403


def test_other_households_are_invisible(client):
    mine, theirs = Flat(client), None
    r = client.post("/api/households", json={"household_name": "Other", "owner_name": "Z", "owner_phone": "9000000099"})
    theirs = {"X-Roz-Token": r.json()["token"]}
    assert client.get(f"/api/households/{mine.hid}/dashboard", headers=theirs).status_code == 404
    assert client.get(f"/api/employments/{mine.eid}", headers=theirs).status_code == 404
    rid = mine.ask("create_advance_request", "e1", amount_paise=60_000)["request_id"]
    r = client.post(f"/api/requests/{rid}/votes", headers=theirs, json={"decision": "approve"})
    assert r.status_code == 404 and error_code(r) == "not_found"


def test_members_grant_only_for_themselves(client):
    flat = Flat(client)
    r = client.post(f"/api/members/{flat.roommate_id}/grant", headers=flat.owner)
    assert r.status_code == 403 and error_code(r) == "own_grant_only"


def test_votes_conflict_once_decided_or_repeated(client):
    flat = Flat(client, advance_monthly_limit_paise=80_000)
    flat.ask("create_advance_request", "e2", amount_paise=50_000)
    rid = flat.ask("create_advance_request", "e3", amount_paise=50_000)["request_id"]  # needs both votes
    assert (
        client.post(f"/api/requests/{rid}/votes", headers=flat.owner, json={"decision": "approve"}).status_code == 200
    )
    r = client.post(f"/api/requests/{rid}/votes", headers=flat.owner, json={"decision": "approve"})
    assert r.status_code == 409 and error_code(r) == "already_voted"
    client.post(f"/api/requests/{rid}/votes", headers=flat.roommate, json={"decision": "reject"})
    r = client.post(f"/api/requests/{rid}/votes", headers=flat.roommate, json={"decision": "approve"})
    assert r.status_code == 409


def test_validation_errors_are_400(client):
    flat = Flat(client)
    r = client.post(f"/api/households/{flat.hid}/topups", headers=flat.owner, json={"amount_paise": -5})
    assert r.status_code == 400 and error_code(r) == "invalid_request"
    r = client.get(f"/api/households/{flat.hid}/ledger?month=2026-13", headers=flat.owner)
    assert r.status_code == 400 and error_code(r) == "invalid_month"
    r = client.post(
        f"/api/households/{flat.hid}/helpers",
        headers=flat.owner,
        json={
            "name": "Bad",
            "whatsapp_e164": "123",
            "lang": "kn",
            "role": "maid",
            "salary_paise": 500_000,
            "payday_dom": 5,
            "advance_auto_limit_paise": 0,
            "advance_monthly_limit_paise": 0,
            "grocery_auto_limit_paise": 0,
            "grocery_monthly_budget_paise": 0,
        },
    )
    assert r.status_code == 400 and error_code(r) == "invalid_phone"


def test_limits_must_be_consistent(client):
    flat = Flat(client)
    r = client.patch(
        f"/api/employments/{flat.eid}", headers=flat.owner, json={"advance_monthly_limit_paise": 1_000_000}
    )
    assert r.status_code == 400 and error_code(r) == "invalid_limits"


def test_tools_need_the_token_and_known_tools(client):
    r = client.post("/tools/get_balances", json={"args": {}, "idempotency_key": "k"})
    assert r.status_code == 401
    body = tool(client, "transfer_everything", "k2")
    assert body == {"ok": False, "error": {"code": "unknown_tool", "message": "transfer_everything"}}
    body = tool(client, "get_balances", "k3", employment_id=str(uuid.uuid4()))
    assert body["ok"] is False and body["error"]["code"] == "not_found"


def test_admin_reset_needs_the_admin_token(client):
    assert client.post("/api/admin/reset-demo").status_code == 401
