"""Each roommate's share of what the helpers cost this month."""
from dataclasses import dataclass

COST_KINDS = ("advance", "salary", "reimbursement", "grocery_spend")


@dataclass(frozen=True)
class ContributionRow:
    member_id: str
    topups_paise: int
    share_paise: int
    balance_paise: int


def split_cost(cost_paise: int, weights: dict[str, int], owner_id: str) -> dict[str, int]:
    """Integer shares by weight; the rounding remainder goes to the owner."""
    total = sum(weights.values())
    shares = {m: cost_paise * w // total for m, w in weights.items()}
    shares[owner_id] += cost_paise - sum(shares.values())
    return shares


def statement(cost_paise: int, weights: dict[str, int], owner_id: str, topups: dict[str, int],
              previous_balance: dict[str, int] | None = None) -> list[ContributionRow]:
    previous_balance = previous_balance or {}
    shares = split_cost(cost_paise, weights, owner_id)
    return [ContributionRow(m, topups.get(m, 0), shares[m],
                            previous_balance.get(m, 0) + topups.get(m, 0) - shares[m]) for m in weights]
