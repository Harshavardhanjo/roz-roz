"""Example payloads for contracts 2 and 3. Served by app/stub_api.py when USE_STUBS=true.
tests/test_contract_shapes.py checks that the real API returns at least these keys."""

HOUSEHOLD_ID = "7b1e0000-0000-4000-8000-000000000001"
OWNER_ID = "a41c0000-0000-4000-8000-000000000001"
ROOMMATE_ID = "b92d0000-0000-4000-8000-000000000002"
HELPER_ID = "c07f0000-0000-4000-8000-000000000001"
EMPLOYMENT_ID = "e9d20000-0000-4000-8000-000000000001"
REQUEST_ID = "55a00000-0000-4000-8000-000000000001"
VOTE_REQUEST_ID = "55a00000-0000-4000-8000-000000000002"

ME = {
    "member_id": OWNER_ID,
    "household_id": HOUSEHOLD_ID,
    "role": "owner",
    "name": "Harsha",
    "flats": [
        {
            "household_id": HOUSEHOLD_ID,
            "household_name": "HSR Flat 302",
            "member_id": OWNER_ID,
            "role": "owner",
            "token": "stub-owner-token",
            "link": "http://localhost:3000/h/stub-owner-token",
            "current": True,
        }
    ],
}

MEMBER_REMOVED = {
    "member_id": ROOMMATE_ID,
    "removed_at": "2026-10-24T18:00:00+05:30",
    "final_balance_paise": 133500,
    "month": "2026-10",
}

HELPER_CARD = {
    "employment_id": EMPLOYMENT_ID,
    "helper_id": HELPER_ID,
    "name": "Lakshmi",
    "role": "cook",
    "lang": "kn",
    "consented": True,
    "salary_paise": 1000000,
    "next_payday": "2026-10-31",
    "projected_net_paise": 813000,
    "leave": {"paid_allowed": 2.0, "paid_used": 2.0, "unpaid_days": 1.0},
    "advances": {"this_month_paise": 150000, "monthly_limit_paise": 200000},
    "grocery": {
        "budget_paise": 600000,
        "spent_paise": 370000,
        "budget_used_paise": 400000,
        "spending_wallet_paise": 30000,
    },
}

VOTE_CARD = {
    "request_id": VOTE_REQUEST_ID,
    "helper_name": "Lakshmi",
    "kind": "grocery_money",
    "amount_paise": 80000,
    "context": "₹800 for groceries; ₹4,000 of ₹6,000 used this month",
    "votes_needed": 1,
    "votes": [],
    "created_at": "2026-10-24T14:05:00+05:30",
    "overdue": False,
}

DASHBOARD = {
    "household": {"id": HOUSEHOLD_ID, "name": "HSR Flat 302"},
    "me": {"member_id": OWNER_ID, "role": "owner", "name": "Harsha", "grant_status": "active"},
    "house_wallet": {"balance_paise": 237000, "simulated": True},
    "helpers": [HELPER_CARD],
    "open_votes": [VOTE_CARD],
    "contributions": [
        {
            "member_id": OWNER_ID,
            "name": "Harsha",
            "topups_paise": 800000,
            "share_paise": 666500,
            "balance_paise": 133500,
        },
        {
            "member_id": ROOMMATE_ID,
            "name": "Arjun",
            "topups_paise": 800000,
            "share_paise": 666500,
            "balance_paise": 133500,
        },
    ],
    "alerts": [],
}

REQUEST = {
    "id": REQUEST_ID,
    "employment_id": EMPLOYMENT_ID,
    "helper_name": "Lakshmi",
    "kind": "advance",
    "status": "executed",
    "amount_paise": 50000,
    "leave_from": None,
    "leave_to": None,
    "half_day": False,
    "note": "from voice note",
    "rule_applied": "within the auto-approve and monthly limits",
    "created_by": "helper",
    "votes": [],
    "votes_needed": None,
    "created_at": "2026-10-24T13:40:00+05:30",
    "decided_at": "2026-10-24T13:40:03+05:30",
}

VOTE_REQUEST = {
    **REQUEST,
    "id": VOTE_REQUEST_ID,
    "kind": "grocery_money",
    "status": "needs_vote",
    "amount_paise": 80000,
    "note": "₹800 sabzi ke liye",
    "rule_applied": "above the auto-approve limit",
    "votes_needed": 1,
    "decided_at": None,
}

LEDGER_ENTRY = {
    "id": "1ed90000-0000-4000-8000-000000000001",
    "at": "2026-10-24T13:40:03+05:30",
    "wallet": "house",
    "direction": "debit",
    "kind": "advance",
    "amount_paise": 50000,
    "who": "Lakshmi",
    "request_id": REQUEST_ID,
    "provider_txn_id": "SIM-0A1B2C3D4E5F",
    "simulated": True,
    "note": "from voice note",
}

CONTRIBUTIONS = {
    "month": "2026-10",
    "cost_paise": 1333000,
    "members": [
        {
            "member_id": OWNER_ID,
            "name": "Harsha",
            "weight": 1,
            "topups_paise": 800000,
            "share_paise": 666500,
            "balance_paise": 133500,
            "suggested_topup_paise": 1266500,
        },
        {
            "member_id": ROOMMATE_ID,
            "name": "Arjun",
            "weight": 1,
            "topups_paise": 800000,
            "share_paise": 666500,
            "balance_paise": 133500,
            "suggested_topup_paise": 1266500,
        },
    ],
}

PAYROLL_RUN = {
    "payroll_run_id": "9a170000-0000-4000-8000-000000000001",
    "employment_id": EMPLOYMENT_ID,
    "month": "2026-10",
    "salary_paise": 1000000,
    "working_days": 27,
    "leave_days": 3.0,
    "unpaid_days": 1.0,
    "deduction_paise": 37000,
    "advances_paise": 150000,
    "net_paise": 813000,
    "status": "executed",
    "simulated": True,
    "executed_at": "2026-10-24T19:45:00+05:30",
}

AUDIT_ENTRY = {
    "at": "2026-10-24T13:40:03+05:30",
    "actor": "system:treasurer",
    "action": "approve_request",
    "entity": "request",
    "entity_id": REQUEST_ID,
    "rule_applied": "within the auto-approve and monthly limits",
    "grantex_decision": "allowed (2/2 grants, local)",
    "summary": "Auto-approved ₹500 advance for Lakshmi",
}

EMPLOYMENT_DETAIL = {
    "employment": HELPER_CARD,
    "terms": {
        "role": "cook",
        "lang": "kn",
        "whatsapp_e164": "+910000000001",
        "salary_paise": 1000000,
        "payday_dom": 31,
        "weekly_off": [6],
        "paid_leaves_per_month": 2.0,
        "deduct_extra_leave": True,
        "advance_auto_limit_paise": 50000,
        "advance_monthly_limit_paise": 200000,
        "grocery_auto_limit_paise": 50000,
        "grocery_monthly_budget_paise": 600000,
        "status": "active",
    },
    "leave_days": [
        {"date": "2026-10-08", "kind": "paid", "fraction": 1.0, "marked_by": "helper"},
        {"date": "2026-10-20", "kind": "paid", "fraction": 1.0, "marked_by": "helper"},
    ],
    "requests": [REQUEST, VOTE_REQUEST],
    "payroll": [PAYROLL_RUN],
}

STATS = {
    "total": 0,
    "by_source": {"landing": 0, "household": 0, "helper": 0},
    "last_hour": 0,
    "pays_by": {},
    "voice_median_latency_ms": None,
}

HELPER_CONTEXT = {
    "known": True,
    "helper_id": HELPER_ID,
    "name": "Lakshmi",
    "lang": "kn",
    "consented": True,
    "households": [
        {
            "household_id": HOUSEHOLD_ID,
            "name": "HSR Flat 302",
            "employment_id": EMPLOYMENT_ID,
            "consented": True,
            "paid_leave_left": 0.0,
            "advances_this_month_paise": 100000,
            "advance_auto_limit_paise": 50000,
            "advance_monthly_limit_paise": 200000,
            "grocery_left_paise": 200000,
            "spending_wallet_paise": 30000,
            "open_requests": [],
        }
    ],
}

OUTCOME_ADVANCE = {
    "status": "executed",
    "template": "advance_approved",
    "summary_slots": {"household": "HSR Flat 302", "amount": 500, "month_total": 1500},
}

TOOL_RESULTS = {
    "get_helper_context": HELPER_CONTEXT,
    "record_consent": {"consent_at": "2026-10-24T13:30:00+05:30"},
    "create_leave_request": {
        "request_id": VOTE_REQUEST_ID,
        "outcome": {
            "status": "needs_vote",
            "template": "leave_needs_vote",
            "summary_slots": {"household": "HSR Flat 302", "dates": "26 Oct", "left": 0},
        },
    },
    "create_advance_request": {"request_id": REQUEST_ID, "outcome": OUTCOME_ADVANCE},
    "create_grocery_request": {
        "request_id": VOTE_REQUEST_ID,
        "outcome": {
            "status": "needs_vote",
            "template": "grocery_needs_vote",
            "summary_slots": {"household": "HSR Flat 302", "amount": 800, "wallet": 300},
        },
    },
    "record_grocery_spend": {
        "ledger_entry_id": "1ed90000-0000-4000-8000-000000000003",
        "spending_wallet_paise": 0,
        "summary_slots": {"amount": 300, "item": "vegetables", "wallet": 0},
    },
    "record_cash_spend": {
        "request_id": "55a00000-0000-4000-8000-000000000003",
        "outcome": {
            "status": "executed",
            "template": "cash_recorded",
            "summary_slots": {"household": "HSR Flat 302", "amount": 120, "item": "coriander"},
        },
    },
    "get_balances": {
        "paid_leave_left": 0.0,
        "advances_this_month_paise": 150000,
        "grocery_left_paise": 200000,
        "spending_wallet_paise": 30000,
        "next_payday": "2026-10-31",
        "projected_net_paise": 813000,
        "summary_slots": {"left": 0, "month_total": 1500, "payday": "31 Oct", "projected": 8130},
    },
    "evaluate_request": {
        "decision": "AUTO",
        "votes_needed": 0,
        "rule_applied": "within the auto-approve and monthly limits",
        "context": {
            "used_paise": 100000,
            "limit_paise": 200000,
            "house_balance_paise": 1050000,
            "grants": "allowed (2/2 grants, local)",
            "auto_limit_paise": 50000,
        },
    },
    "check_grant": {
        "allowed": True,
        "checked": [
            {"member_id": OWNER_ID, "grant_id": "local_stub1", "allowed": True, "reason": "covered"},
            {"member_id": ROOMMATE_ID, "grant_id": "local_stub2", "allowed": True, "reason": "covered"},
        ],
    },
    "execute_request": {"status": "executed", "outcome": OUTCOME_ADVANCE},
    "open_vote": {"status": "needs_vote", "votes_needed": 1},
    "run_payroll": PAYROLL_RUN,
    "post_contributions": {"members": CONTRIBUTIONS["members"]},
}
