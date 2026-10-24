"""End-to-end flows through the public API and agent tools, against Postgres."""

from datetime import date

from conftest import Flat, tool

from app.services import audit


def test_small_advance_is_auto_approved_and_paid(client, db):
    flat = Flat(client)
    result = flat.ask("create_advance_request", "a1", amount_paise=50_000, note="naale beku")
    assert result["outcome"] == {
        "status": "executed",
        "template": "advance_approved",
        "summary_slots": {"household": "Test Flat", "amount": 500, "month_total": 500},
    }
    assert flat.balance() == 1_600_000 - 50_000
    card = flat.dashboard()["helpers"][0]
    assert card["advances"]["this_month_paise"] == 50_000
    assert card["projected_net_paise"] == 1_000_000 - 50_000
    actions = [e["action"] for e in client.get(f"/api/households/{flat.hid}/audit", headers=flat.owner).json()]
    assert {"create_request", "approve_request", "execute_request"} <= set(actions)
    assert audit.verify(db)


def test_advance_above_auto_limit_goes_to_one_vote_in_a_two_person_flat(client):
    flat = Flat(client)
    result = flat.ask("create_advance_request", "a2", amount_paise=60_000)
    assert result["outcome"]["status"] == "needs_vote"
    vote_card = flat.dashboard()["open_votes"][0]
    assert vote_card["votes_needed"] == 1
    assert vote_card["context"] == "₹600 advance; ₹0 of ₹2,000 used this month"
    r = client.post(f"/api/requests/{result['request_id']}/votes", headers=flat.roommate, json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "executed"
    assert flat.balance() == 1_600_000 - 60_000


def test_rejected_vote_moves_no_money(client):
    flat = Flat(client)
    rid = flat.ask("create_advance_request", "a3", amount_paise=60_000)["request_id"]
    r = client.post(f"/api/requests/{rid}/votes", headers=flat.owner, json={"decision": "reject"})
    # One approval is needed out of two voters, so a single rejection doesn't end it yet.
    assert r.json()["status"] == "needs_vote"
    r = client.post(f"/api/requests/{rid}/votes", headers=flat.roommate, json={"decision": "reject"})
    assert r.json()["status"] == "rejected"
    assert flat.balance() == 1_600_000


def test_over_the_monthly_limit_needs_everyone(client):
    flat = Flat(client, advance_monthly_limit_paise=80_000)
    flat.ask("create_advance_request", "a4", amount_paise=50_000)
    result = flat.ask("create_advance_request", "a5", amount_paise=50_000)
    assert result["outcome"]["status"] == "needs_vote"
    assert flat.dashboard()["open_votes"][0]["votes_needed"] == 2


def test_missing_grant_sends_small_requests_to_a_vote(client):
    flat = Flat(client, grant=False)
    assert flat.ask("create_advance_request", "a6", amount_paise=10_000)["outcome"]["status"] == "needs_vote"
    assert flat.dashboard()["me"]["grant_status"] == "missing"


def test_terms_changed_after_grant_make_it_outdated(client):
    flat = Flat(client)
    r = client.patch(f"/api/employments/{flat.eid}", headers=flat.owner, json={"advance_auto_limit_paise": 80_000})
    assert r.status_code == 200
    assert flat.dashboard()["me"]["grant_status"] == "outdated"
    # The old grant covered up to ₹500, so ₹700 now needs a vote even though the new auto limit is ₹800.
    assert flat.ask("create_advance_request", "a7", amount_paise=70_000)["outcome"]["status"] == "needs_vote"
    client.post(f"/api/members/{flat.owner_id}/grant", headers=flat.owner)
    client.post(f"/api/members/{flat.roommate_id}/grant", headers=flat.roommate)
    assert flat.ask("create_advance_request", "a8", amount_paise=70_000)["outcome"]["status"] == "executed"


def test_low_house_balance_waits_for_a_topup(client):
    flat = Flat(client, topup_each=10_000)
    result = flat.ask("create_advance_request", "a9", amount_paise=50_000)
    assert result["outcome"]["template"] == "needs_topup"
    alerts = {a["code"] for a in flat.dashboard()["alerts"]}
    assert {"needs_topup", "low_balance"} <= alerts


def test_leave_within_paid_balance_then_beyond_it(client):
    flat = Flat(client)
    first = flat.ask("create_leave_request", "l1", leave_from="2026-10-26", leave_to="2026-10-27")
    assert first["outcome"]["status"] == "executed"
    assert first["outcome"]["summary_slots"] == {"household": "Test Flat", "dates": "26–27 Oct", "left": 0}
    second = flat.ask("create_leave_request", "l2", leave_from="2026-10-28", leave_to="2026-10-28")
    assert second["outcome"]["status"] == "needs_vote"
    assert "it would be unpaid" in flat.dashboard()["open_votes"][0]["context"]
    client.post(f"/api/requests/{second['request_id']}/votes", headers=flat.roommate, json={"decision": "approve"})
    card = flat.dashboard()["helpers"][0]
    assert card["leave"] == {"paid_allowed": 2.0, "paid_used": 2.0, "unpaid_days": 1.0}
    detail = client.get(f"/api/employments/{flat.eid}", headers=flat.owner).json()
    assert [d["kind"] for d in detail["leave_days"]] == ["paid", "paid", "unpaid"]


def test_leave_on_a_weekly_off_costs_nothing(client):
    flat = Flat(client)
    result = flat.ask("create_leave_request", "l3", leave_from="2026-10-25", leave_to="2026-10-25")  # a Sunday
    assert result["outcome"]["status"] == "executed"
    assert flat.dashboard()["helpers"][0]["leave"]["paid_used"] == 0


def test_the_same_day_cannot_be_recorded_twice(client):
    flat = Flat(client)
    r = client.post(f"/api/employments/{flat.eid}/absences", headers=flat.roommate, json={"date": "2026-10-26"})
    assert r.status_code == 201
    r = client.post(f"/api/employments/{flat.eid}/absences", headers=flat.owner, json={"date": "2026-10-26"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "leave_exists"


def test_groceries_move_to_the_spending_wallet_and_spends_come_out_of_it(client):
    flat = Flat(client)
    moved = flat.ask("create_grocery_request", "g1", amount_paise=50_000)
    assert moved["outcome"]["status"] == "executed"
    assert moved["outcome"]["summary_slots"]["wallet"] == 500
    spent = flat.ask("record_grocery_spend", "g2", amount_paise=35_000, item_note="tarakaari")
    assert spent["spending_wallet_paise"] == 15_000
    too_much = tool(client, "record_grocery_spend", "g3", employment_id=flat.eid, amount_paise=20_000, item_note="more")
    assert too_much["ok"] is False and too_much["error"]["code"] == "insufficient_funds"
    grocery = flat.dashboard()["helpers"][0]["grocery"]
    assert grocery == {
        "budget_paise": 600_000,
        "spent_paise": 35_000,
        "budget_used_paise": 50_000,
        "spending_wallet_paise": 15_000,
    }


def test_cash_spend_is_repaid_from_the_house_wallet(client):
    flat = Flat(client)
    result = flat.ask("record_cash_spend", "c1", amount_paise=12_000, item_note="kothambari")
    assert result["outcome"]["template"] == "cash_recorded"
    assert result["outcome"]["summary_slots"]["item"] == "kothambari"
    assert flat.balance() == 1_600_000 - 12_000


def test_payroll_pays_salary_minus_unpaid_leave_and_advances(client):
    flat = Flat(client)
    for i in range(3):
        flat.ask("create_advance_request", f"p{i}", amount_paise=50_000)
    for day in ("2026-10-08", "2026-10-20", "2026-10-26"):
        r = client.post(f"/api/employments/{flat.eid}/absences", headers=flat.owner, json={"date": day})
        assert r.status_code == 201, r.text
    run = client.post(f"/api/employments/{flat.eid}/payroll/run", headers=flat.owner, json={"month": "2026-10"}).json()
    assert (
        run["working_days"],
        run["unpaid_days"],
        run["deduction_paise"],
        run["advances_paise"],
        run["net_paise"],
        run["status"],
    ) == (27, 1.0, 37_000, 150_000, 813_000, "executed")
    again = client.post(
        f"/api/employments/{flat.eid}/payroll/run", headers=flat.owner, json={"month": "2026-10"}
    ).json()
    assert again["payroll_run_id"] == run["payroll_run_id"]
    assert flat.balance() == 1_600_000 - 150_000 - 813_000
    contrib = client.get(f"/api/households/{flat.hid}/contributions", headers=flat.owner).json()
    assert contrib["cost_paise"] == 963_000
    assert [(m["share_paise"], m["balance_paise"]) for m in contrib["members"]] == [(481_500, 318_500)] * 2
    assert flat.dashboard()["helpers"][0]["next_payday"] == "2026-11-30"


def test_payroll_waits_for_a_topup_when_the_wallet_is_short(client):
    flat = Flat(client, topup_each=100_000)
    run = client.post(f"/api/employments/{flat.eid}/payroll/run", headers=flat.owner, json={"month": "2026-10"}).json()
    assert run["status"] == "needs_topup"
    client.post(f"/api/households/{flat.hid}/topups", headers=flat.roommate, json={"amount_paise": 900_000})
    run = client.post(f"/api/employments/{flat.eid}/payroll/run", headers=flat.owner, json={"month": "2026-10"}).json()
    assert run["status"] == "executed" and run["net_paise"] == 1_000_000


def test_helper_context_and_balances_for_the_liaison(client):
    flat = Flat(client)
    flat.ask("create_advance_request", "h1", amount_paise=50_000)
    ctx = tool(client, "get_helper_context", "h2", whatsapp_e164="919811100009")["result"]
    assert ctx["known"] and ctx["consented"] and ctx["name"] == "Lakshmi"
    (hh,) = ctx["households"]
    assert hh["advances_this_month_paise"] == 50_000 and hh["paid_leave_left"] == 2.0
    assert tool(client, "get_helper_context", "h3", whatsapp_e164="+919999999999")["result"] == {"known": False}
    bal = flat.ask("get_balances", "h4")
    assert bal["summary_slots"] == {"left": 2, "month_total": 500, "payday": "31 Oct", "projected": 9500}


def test_helper_without_consent_cannot_file_requests(client):
    flat = Flat(client)
    second = client.post(
        f"/api/households/{flat.hid}/helpers",
        headers=flat.owner,
        json={
            "name": "Ramesh",
            "whatsapp_e164": "9811100010",
            "lang": "hi",
            "role": "driver",
            "salary_paise": 1_800_000,
            "payday_dom": 1,
            "advance_auto_limit_paise": 0,
            "advance_monthly_limit_paise": 0,
            "grocery_auto_limit_paise": 0,
            "grocery_monthly_budget_paise": 0,
        },
    ).json()
    r = tool(client, "create_advance_request", "n1", employment_id=second["employment_id"], amount_paise=10_000)
    assert r["ok"] is False and r["error"]["code"] == "no_consent"
    assert second["whatsapp_link"] == "https://wa.me/919000000000?text=Namaste"


def test_treasurer_tools_cannot_execute_around_the_rules(client, db):
    from app.models import Employment
    from app.services import requests as reqs

    flat = Flat(client)
    emp = db.get(Employment, flat.eid)
    req = reqs.create(db, emp, "advance", "helper", amount_paise=90_000)
    db.commit()
    evaluated = tool(client, "evaluate_request", "t1", request_id=str(req.id))["result"]
    assert evaluated["decision"] == "VOTE"
    refused = tool(client, "execute_request", "t2", request_id=str(req.id))
    assert refused["ok"] is False and refused["error"]["code"] == "not_auto_approvable"
    opened = tool(client, "open_vote", "t3", request_id=str(req.id), context_text="Rs 900 advance")["result"]
    assert opened == {"status": "needs_vote", "votes_needed": 1}
    assert flat.balance() == 1_600_000


def test_tool_calls_are_idempotent(client):
    flat = Flat(client)
    first = tool(client, "create_advance_request", "same-key", employment_id=flat.eid, amount_paise=50_000)
    second = tool(client, "create_advance_request", "same-key", employment_id=flat.eid, amount_paise=50_000)
    assert first == second
    assert flat.balance() == 1_600_000 - 50_000


def test_stats_count_distinct_real_people(client):
    Flat(client)
    client.post("/api/signups", json={"name": "Meera", "phone": "+91 90000 00099", "pays_by": "cash"})
    client.post("/api/signups", json={"name": "Meera", "phone": "9000000099", "pays_by": "cash"})
    stats = client.get("/api/stats").json()
    assert stats["by_source"] == {"landing": 1, "household": 2, "helper": 1}
    assert stats["total"] == 4 and stats["pays_by"] == {"cash": 1}


def test_ledger_page_names_who_and_marks_simulated(client):
    flat = Flat(client)
    flat.ask("create_advance_request", "l9", amount_paise=50_000)
    entries = client.get(f"/api/households/{flat.hid}/ledger", headers=flat.owner).json()["entries"]
    advance = next(e for e in entries if e["kind"] == "advance")
    assert advance["who"] == "Lakshmi" and advance["simulated"] and advance["provider_txn_id"].startswith("SIM-")
    assert {e["who"] for e in entries if e["kind"] == "topup"} == {"Asha", "Ravi"}


def test_dates_are_validated(client):
    flat = Flat(client)
    r = tool(
        client, "create_leave_request", "d1", employment_id=flat.eid, leave_from="2026-10-28", leave_to="2026-10-26"
    )
    assert r["ok"] is False and r["error"]["code"] == "invalid_dates"
    far = date(2027, 6, 1).isoformat()
    r = tool(client, "create_leave_request", "d2", employment_id=flat.eid, leave_from=far, leave_to=far)
    assert r["error"]["code"] == "invalid_dates"
