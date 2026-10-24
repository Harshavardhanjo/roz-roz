"""Approval rules (HLD pseudocode). Pure functions; agents reach them only through tools."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Decision:
    kind: Literal["AUTO", "VOTE", "NEEDS_TOPUP"]
    votes_needed: int = 0
    rule_applied: str = ""
    context: dict = field(default_factory=dict)


def votes_needed(n_roommates: int, amount_paise: int, vote_rule: str, two_person_limit_paise: int) -> int:
    """n_roommates counts everyone who votes (owner included)."""
    if vote_rule == "all":
        return n_roommates
    if vote_rule == "any_one" or n_roommates <= 1:
        return 1
    if n_roommates == 2:
        return 1 if amount_paise <= two_person_limit_paise else 2
    return n_roommates // 2 + 1  # strict majority


def evaluate_money_request(
    amount_paise: int,
    used_this_month_paise: int,
    auto_limit_paise: int,
    monthly_limit_paise: int,
    house_balance_paise: int,
    grants_ok: bool,
    n_roommates: int,
    vote_rule: str,
    two_person_limit_paise: int,
) -> Decision:
    """advance, grocery_money and reimbursement (the latter two use the grocery limits)."""
    ctx = {
        "used_paise": used_this_month_paise,
        "limit_paise": monthly_limit_paise,
        "house_balance_paise": house_balance_paise,
    }
    if house_balance_paise < amount_paise:
        return Decision("NEEDS_TOPUP", 0, "house wallet below amount", ctx)
    if used_this_month_paise + amount_paise > monthly_limit_paise:
        return Decision("VOTE", n_roommates, "over the monthly limit: everyone agrees", ctx)
    if amount_paise <= auto_limit_paise and grants_ok:
        return Decision("AUTO", 0, "within the auto-approve and monthly limits", ctx)
    reason = (
        "above the auto-approve limit" if amount_paise > auto_limit_paise else "a roommate's grant doesn't cover it"
    )
    return Decision("VOTE", votes_needed(n_roommates, amount_paise, vote_rule, two_person_limit_paise), reason, ctx)


def evaluate_leave(
    days: float,
    paid_leave_left: float,
    deduct_extra_leave: bool,
    n_roommates: int,
    vote_rule: str,
    two_person_limit_paise: int,
) -> Decision:
    ctx = {"days": days, "paid_leave_left": paid_leave_left}
    if days <= paid_leave_left:
        return Decision("AUTO", 0, "within paid leave", ctx)
    note = "unpaid" if deduct_extra_leave else "paid"
    return Decision(
        "VOTE",
        votes_needed(n_roommates, 0, vote_rule, two_person_limit_paise),
        f"beyond paid leave (would be {note})",
        ctx,
    )
