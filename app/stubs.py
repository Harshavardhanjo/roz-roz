"""Contract 2 example payloads. Returned while USE_STUBS=true so the web app and agents never wait."""

HOUSEHOLD_ID = "7b1e0000-0000-4000-8000-000000000001"
OWNER_ID = "a41c0000-0000-4000-8000-000000000001"
ROOMMATE_ID = "b92d0000-0000-4000-8000-000000000002"
HELPER_ID = "c07f0000-0000-4000-8000-000000000001"
EMPLOYMENT_ID = "e9d20000-0000-4000-8000-000000000001"
REQUEST_ID = "55a00000-0000-4000-8000-000000000001"
VOTE_REQUEST_ID = "55a00000-0000-4000-8000-000000000002"

ME = {"member_id": OWNER_ID, "household_id": HOUSEHOLD_ID, "role": "owner", "name": "Harsha"}

DASHBOARD = {
    "household": {"id": HOUSEHOLD_ID, "name": "HSR Flat 302"},
    "me": {"member_id": OWNER_ID, "role": "owner", "name": "Harsha"},
    "house_wallet": {"balance_paise": 237000, "simulated": True},
    "helpers": [{
        "employment_id": EMPLOYMENT_ID, "helper_id": HELPER_ID, "name": "Lakshmi", "role": "cook", "lang": "kn",
        "consented": True, "salary_paise": 1000000, "next_payday": "2026-10-31", "projected_net_paise": 813000,
        "leave": {"paid_allowed": 2, "paid_used": 2, "unpaid_days": 1},
        "advances": {"this_month_paise": 150000, "monthly_limit_paise": 200000},
        "grocery": {"budget_paise": 600000, "spent_paise": 370000, "spending_wallet_paise": 30000},
    }],
    "open_votes": [{
        "request_id": VOTE_REQUEST_ID, "helper_name": "Lakshmi", "kind": "grocery_money", "amount_paise": 80000,
        "context": "₹800 for groceries; ₹3,700 of ₹6,000 used this month", "votes_needed": 1,
        "votes": [], "created_at": "2026-10-24T14:05:00+05:30",
    }],
    "contributions": [
        {"member_id": OWNER_ID, "name": "Harsha", "topups_paise": 800000, "share_paise": 666500, "balance_paise": 133500},
        {"member_id": ROOMMATE_ID, "name": "Arjun", "topups_paise": 800000, "share_paise": 666500, "balance_paise": 133500},
    ],
}

REQUEST = {
    "id": REQUEST_ID, "employment_id": EMPLOYMENT_ID, "helper_name": "Lakshmi", "kind": "advance", "status": "executed",
    "amount_paise": 50000, "leave_from": None, "leave_to": None, "half_day": False, "note": "from voice note",
    "rule_applied": "advance <= ₹500 and month total <= ₹2,000", "created_by": "helper",
    "votes": [], "created_at": "2026-10-24T13:40:00+05:30", "decided_at": "2026-10-24T13:40:03+05:30",
}

VOTE_REQUEST = {
    **REQUEST, "id": VOTE_REQUEST_ID, "kind": "grocery_money", "status": "needs_vote", "amount_paise": 80000,
    "note": "₹800 sabzi ke liye", "rule_applied": "grocery > ₹500 auto limit", "votes_needed": 1, "decided_at": None,
}

LEDGER_ENTRY = {
    "id": "1ed90000-0000-4000-8000-000000000001", "at": "2026-10-24T13:40:03+05:30", "wallet": "house",
    "direction": "debit", "kind": "advance", "amount_paise": 50000, "who": "Lakshmi", "request_id": REQUEST_ID,
    "provider_txn_id": "SIM-000123", "simulated": True,
}

CONTRIBUTIONS = {
    "month": "2026-10", "cost_paise": 1333000,
    "members": [
        {"member_id": OWNER_ID, "name": "Harsha", "weight": 1, "topups_paise": 800000, "share_paise": 666500,
         "balance_paise": 133500, "suggested_topup_paise": 666500},
        {"member_id": ROOMMATE_ID, "name": "Arjun", "weight": 1, "topups_paise": 800000, "share_paise": 666500,
         "balance_paise": 133500, "suggested_topup_paise": 666500},
    ],
}

PAYROLL_RUN = {
    "payroll_run_id": "9a170000-0000-4000-8000-000000000001", "employment_id": EMPLOYMENT_ID, "month": "2026-10",
    "salary_paise": 1000000, "working_days": 27, "leave_days": 3.0, "unpaid_days": 1.0, "deduction_paise": 37000,
    "advances_paise": 150000, "net_paise": 813000, "status": "executed", "simulated": True,
}

AUDIT_ENTRY = {
    "at": "2026-10-24T13:40:03+05:30", "actor": "agent:treasurer", "action": "approve_request", "entity": "request",
    "entity_id": REQUEST_ID, "rule_applied": "advance <= ₹500 and month total <= ₹2,000",
    "grantex_decision": "allowed (2/2 grants)", "summary": "Auto-approved ₹500 advance for Lakshmi",
}

HELPER_CONTEXT = {
    "known": True, "helper_id": HELPER_ID, "name": "Lakshmi", "lang": "kn", "consented": True,
    "households": [{
        "household_id": HOUSEHOLD_ID, "name": "HSR Flat 302", "employment_id": EMPLOYMENT_ID, "paid_leave_left": 0,
        "advances_this_month_paise": 100000, "advance_auto_limit_paise": 50000, "advance_monthly_limit_paise": 200000,
        "grocery_left_paise": 230000, "spending_wallet_paise": 30000, "open_requests": [],
    }],
}
