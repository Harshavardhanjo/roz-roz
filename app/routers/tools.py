"""Contract 3: POST /tools/{name}. Called by the liaison and treasurer agents."""
from fastapi import APIRouter, Depends
from pydantic import ValidationError

from .. import stubs
from ..config import settings
from ..deps import tools_auth
from ..schemas import TOOL_ARGS, ToolCall

router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(tools_auth)])

_idempotency: dict[str, dict] = {}  # TODO(Harsha): persist with a 24 h expiry

STUB_RESULTS = {
    "get_helper_context": stubs.HELPER_CONTEXT,
    "record_consent": {"consent_at": "2026-10-24T13:30:00+05:30"},
    "create_leave_request": {"request_id": stubs.VOTE_REQUEST_ID,
                             "outcome": {"status": "needs_vote", "summary_slots": {"dates": "26 Oct"}}},
    "create_advance_request": {"request_id": stubs.REQUEST_ID,
                               "outcome": {"status": "executed", "summary_slots": {"amount": 500, "month_total": 1500}}},
    "create_grocery_request": {"request_id": stubs.VOTE_REQUEST_ID,
                               "outcome": {"status": "needs_vote", "summary_slots": {"amount": 800}}},
    "record_grocery_spend": {"ledger_entry_id": "1ed90000-0000-4000-8000-000000000003", "spending_wallet_paise": 0},
    "record_cash_spend": {"request_id": "55a00000-0000-4000-8000-000000000003",
                          "outcome": {"status": "executed", "summary_slots": {"amount": 120}}},
    "get_balances": {"paid_leave_left": 0, "advances_this_month_paise": 150000, "grocery_left_paise": 230000,
                     "spending_wallet_paise": 30000, "next_payday": "2026-10-31", "projected_net_paise": 813000},
    "evaluate_request": {"decision": "AUTO", "votes_needed": 0, "rule_applied": "advance <= ₹500 and month total <= ₹2,000",
                         "context": {"used_paise": 100000, "limit_paise": 200000, "house_balance_paise": 237000}},
    "check_grant": {"allowed": True, "checked": []},
    "execute_request": {"status": "executed", "ledger_entry_ids": [], "provider_txn_id": "SIM-000124"},
    "open_vote": {"status": "needs_vote", "votes_needed": 1},
    "run_payroll": stubs.PAYROLL_RUN,
    "post_contributions": {"members": stubs.CONTRIBUTIONS["members"]},
}


@router.post("/{name}")
def call_tool(name: str, call: ToolCall):
    model = TOOL_ARGS.get(name)
    if model is None:
        return {"ok": False, "error": {"code": "unknown_tool", "message": name}}
    try:
        model.model_validate(call.args)
    except ValidationError as e:
        return {"ok": False, "error": {"code": "invalid_args", "message": e.errors(include_url=False)}}
    if call.idempotency_key in _idempotency:
        return _idempotency[call.idempotency_key]
    if settings.use_stubs:
        response = {"ok": True, "result": STUB_RESULTS[name]}
    else:
        # TODO(Harsha): dispatch to services in one DB transaction and write an audit_log row (actor=agent:<name>).
        response = {"ok": False, "error": {"code": "not_implemented", "message": name}}
    _idempotency[call.idempotency_key] = response
    return response
