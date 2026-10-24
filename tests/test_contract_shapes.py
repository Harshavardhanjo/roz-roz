"""The real API must return every key the example payloads (app/stubs.py) promise, at every nesting level.
This is what keeps the Next.js app and the agents (built against the stubs) working on the real backend."""

from conftest import Flat, tool

from app import stubs


def missing_keys(expected, actual, path="$") -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path} is {type(actual).__name__}, expected object"]
        out = []
        for key, value in expected.items():
            if key not in actual:
                out.append(f"{path}.{key}")
            else:
                out += missing_keys(value, actual[key], f"{path}.{key}")
        return out
    if isinstance(expected, list) and expected and isinstance(actual, list) and actual:
        return missing_keys(expected[0], actual[0], f"{path}[0]")
    return []


def assert_shape(expected, actual):
    assert missing_keys(expected, actual) == []


def _flat_with_activity(client) -> Flat:
    flat = Flat(client)
    flat.ask("create_advance_request", "s1", amount_paise=50_000, note="from voice note")
    flat.ask("create_grocery_request", "s2", amount_paise=80_000)  # above the auto limit: opens a vote
    client.post(f"/api/employments/{flat.eid}/payroll/run", headers=flat.owner, json={"month": "2026-10"})
    return flat


def test_web_api_shapes(client):
    flat = _flat_with_activity(client)
    h, hid = flat.owner, flat.hid
    assert_shape(stubs.ME, client.get("/api/me", headers=h).json())
    assert_shape(stubs.DASHBOARD, flat.dashboard())
    assert_shape(stubs.EMPLOYMENT_DETAIL, client.get(f"/api/employments/{flat.eid}", headers=h).json())
    requests_ = client.get(f"/api/households/{hid}/requests", headers=h).json()
    assert_shape(stubs.REQUEST, requests_[0])
    assert_shape({"entries": [stubs.LEDGER_ENTRY]}, client.get(f"/api/households/{hid}/ledger", headers=h).json())
    assert_shape(stubs.CONTRIBUTIONS, client.get(f"/api/households/{hid}/contributions", headers=h).json())
    assert_shape(stubs.AUDIT_ENTRY, client.get(f"/api/households/{hid}/audit", headers=h).json()[0])
    assert_shape(stubs.PAYROLL_RUN, client.get(f"/api/employments/{flat.eid}/payroll", headers=h).json()[0])
    assert_shape(stubs.STATS, client.get("/api/stats").json())


def test_tool_shapes(client):
    flat = Flat(client)
    results = {
        "get_helper_context": tool(client, "get_helper_context", "x1", whatsapp_e164="+919811100009"),
        "create_advance_request": tool(
            client, "create_advance_request", "x2", employment_id=flat.eid, amount_paise=50_000
        ),
        "create_leave_request": tool(
            client, "create_leave_request", "x3", employment_id=flat.eid, leave_from="2026-10-26", leave_to="2026-10-26"
        ),
        "create_grocery_request": tool(
            client, "create_grocery_request", "x4", employment_id=flat.eid, amount_paise=80_000
        ),
        "record_cash_spend": tool(
            client, "record_cash_spend", "x5", employment_id=flat.eid, amount_paise=12_000, item_note="coriander"
        ),
        "get_balances": tool(client, "get_balances", "x6", employment_id=flat.eid),
    }
    vote_id = results["create_grocery_request"]["result"]["request_id"]
    results |= {
        "evaluate_request": tool(client, "evaluate_request", "x7", request_id=vote_id),
        "check_grant": tool(client, "check_grant", "x8", request_id=vote_id),
        "open_vote": tool(client, "open_vote", "x9", request_id=vote_id, context_text="groceries"),
        "run_payroll": tool(client, "run_payroll", "x10", employment_id=flat.eid, month="2026-10"),
        "post_contributions": tool(client, "post_contributions", "x11", household_id=flat.hid, month="2026-10"),
    }
    for name, response in results.items():
        assert response["ok"], (name, response)
        assert missing_keys(stubs.TOOL_RESULTS[name], response["result"]) == [], name


def test_every_template_named_by_an_outcome_exists():
    from app.agents.templates import TEMPLATES
    from app.services.views import _template

    for kind in ("leave", "advance", "grocery_money", "reimbursement", "other"):
        for status in ("executed", "needs_vote", "needs_topup", "rejected"):
            assert _template(kind, status) in TEMPLATES, (kind, status)
