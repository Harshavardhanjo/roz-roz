"""The demo seed plus the live demo steps must reproduce the numbers in the pitch and LLD."""

from conftest import tool

from app.services import audit

ADMIN = {"X-Admin-Token": "test-admin"}


def test_demo_runs_end_to_end_with_the_documented_numbers(client, db):
    seed = client.post("/api/admin/reset-demo", headers=ADMIN).json()
    owner = {"X-Roz-Token": seed["owner"]["token"]}
    roommate = {"X-Roz-Token": seed["roommate"]["token"]}
    hid = seed["household_id"]
    lakshmi = seed["helpers"][0]["employment_id"]

    dash = client.get(f"/api/households/{hid}/dashboard", headers=owner).json()
    assert dash["house_wallet"]["balance_paise"] == 1_100_000  # ₹16,000 in; ₹1,000 advances and ₹4,000 groceries out
    card = next(h for h in dash["helpers"] if h["name"] == "Lakshmi")
    assert card["leave"]["paid_used"] == 2.0
    assert card["grocery"]["spending_wallet_paise"] == 30_000

    # Live: "Somavara baralla, aidu nooru advance beku"
    advance = tool(client, "create_advance_request", "demo-1", employment_id=lakshmi, amount_paise=50_000)["result"]
    assert advance["outcome"]["status"] == "executed"
    leave = tool(
        client, "create_leave_request", "demo-2", employment_id=lakshmi, leave_from="2026-10-26", leave_to="2026-10-26"
    )["result"]
    assert leave["outcome"]["status"] == "needs_vote"
    voted = client.post(f"/api/requests/{leave['request_id']}/votes", headers=roommate, json={"decision": "approve"})
    assert voted.json()["status"] == "executed"

    run = client.post(f"/api/employments/{lakshmi}/payroll/run", headers=owner, json={"month": "2026-10"}).json()
    assert (run["deduction_paise"], run["advances_paise"], run["net_paise"]) == (37_000, 150_000, 813_000)

    contrib = client.get(f"/api/households/{hid}/contributions", headers=owner).json()
    assert contrib["cost_paise"] == 1_333_000
    assert [(m["share_paise"], m["balance_paise"]) for m in contrib["members"]] == [(666_500, 133_500)] * 2

    dash = client.get(f"/api/households/{hid}/dashboard", headers=owner).json()
    assert dash["house_wallet"]["balance_paise"] == 237_000
    assert audit.verify(db)


def test_reset_is_repeatable(client):
    first = client.post("/api/admin/reset-demo", headers=ADMIN).json()
    second = client.post("/api/admin/reset-demo", headers=ADMIN).json()
    assert first["owner"]["token"] != second["owner"]["token"]
    assert client.get("/api/me", headers={"X-Roz-Token": first["owner"]["token"]}).status_code == 403
