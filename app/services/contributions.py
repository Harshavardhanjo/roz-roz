"""Each member's share of what the helpers cost this month, and their running balance.

Cost = money actually spent on helpers: advances, salaries and cash repaid (house wallet) plus grocery spends (spending
wallets). Money moved into a spending wallet is still the household's until it's spent."""

import uuid
from collections.abc import Hashable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import clock
from ..models import ContributionStatement, Employment, Household, LedgerEntry, Member

COST_KINDS = ("advance", "salary", "reimbursement", "grocery_spend")


@dataclass(frozen=True)
class ContributionRow:
    member_id: Hashable
    topups_paise: int
    share_paise: int
    balance_paise: int


def split_cost(cost_paise: int, weights: dict, owner_id: Hashable) -> dict:
    """Integer shares by weight; the rounding remainder goes to the owner."""
    total = sum(weights.values())
    shares = {m: cost_paise * w // total for m, w in weights.items()}
    shares[owner_id] += cost_paise - sum(shares.values())
    return shares


def statement(
    cost_paise: int, weights: dict, owner_id: Hashable, topups: dict, previous_balance: dict | None = None
) -> list[ContributionRow]:
    previous_balance = previous_balance or {}
    shares = split_cost(cost_paise, weights, owner_id)
    return [
        ContributionRow(m, topups.get(m, 0), shares[m], previous_balance.get(m, 0) + topups.get(m, 0) - shares[m])
        for m in weights
    ]


# ---- database ----


def month_cost(db: Session, household_id: uuid.UUID, month: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
                LedgerEntry.household_id == household_id,
                LedgerEntry.month == month,
                LedgerEntry.direction == "debit",
                LedgerEntry.kind.in_(COST_KINDS),
            )
        )
    )


def _topups(db: Session, household_id: uuid.UUID, month: str) -> dict:
    rows = db.execute(
        select(LedgerEntry.member_id, func.sum(LedgerEntry.amount_paise))
        .where(
            LedgerEntry.household_id == household_id,
            LedgerEntry.month == month,
            LedgerEntry.kind == "topup",
            LedgerEntry.direction == "credit",
        )
        .group_by(LedgerEntry.member_id)
    ).all()
    return {m: int(total) for m, total in rows}


def _previous_balances(db: Session, household_id: uuid.UUID, month: str) -> dict:
    prev = clock.previous_month(month)
    return {
        r.member_id: int(r.balance_paise)
        for r in db.scalars(
            select(ContributionStatement).where(
                ContributionStatement.household_id == household_id, ContributionStatement.month == prev
            )
        )
    }


def monthly_budget(db: Session, household_id: uuid.UUID) -> int:
    """What a normal month should cost: salaries plus grocery budgets of active helpers."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Employment.salary_paise + Employment.grocery_monthly_budget_paise), 0)).where(
                Employment.household_id == household_id, Employment.status == "active"
            )
        )
    )


def compute(db: Session, household_id: uuid.UUID, month: str) -> dict:
    household = db.get(Household, household_id)
    members = list(db.scalars(select(Member).where(Member.household_id == household_id).order_by(Member.created_at)))
    weights = {m.id: m.split_weight for m in members}
    cost = month_cost(db, household_id, month)
    rows = statement(
        cost,
        weights,
        household.owner_member_id,
        _topups(db, household_id, month),
        _previous_balances(db, household_id, month),
    )
    budget = monthly_budget(db, household_id)
    total_weight = sum(weights.values())
    by_id = {m.id: m for m in members}
    return {
        "month": month,
        "cost_paise": cost,
        "members": [
            {
                "member_id": str(r.member_id),
                "name": by_id[r.member_id].name,
                "weight": weights[r.member_id],
                "topups_paise": r.topups_paise,
                "share_paise": r.share_paise,
                "balance_paise": r.balance_paise,
                "suggested_topup_paise": max(0, budget * weights[r.member_id] // total_weight - r.balance_paise),
            }
            for r in rows
        ],
    }


def post(db: Session, household_id: uuid.UUID, month: str) -> dict:
    """Compute and store the month's statement (re-run safely; the latest numbers win)."""
    result = compute(db, household_id, month)
    for row in result["members"]:
        values = {
            "household_id": household_id,
            "member_id": uuid.UUID(row["member_id"]),
            "month": month,
            "topups_paise": row["topups_paise"],
            "share_paise": row["share_paise"],
            "balance_paise": row["balance_paise"],
        }
        db.execute(
            insert(ContributionStatement)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["household_id", "member_id", "month"],
                set_={k: values[k] for k in ("topups_paise", "share_paise", "balance_paise")},
            )
        )
    return result
