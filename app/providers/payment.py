"""Money movement. The demo uses SimulatedProvider: ledger_entry rows are the only record, no real money moves.

A real provider implements the same interface; flows and agents don't change. Every money-moving function takes the
caller's session and never commits, so a request's status change and its ledger entries land together."""

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..models import LedgerEntry, Wallet


class InsufficientFunds(ApiError):
    def __init__(self, wallet: Wallet, balance: int, amount: int):
        super().__init__(
            409,
            "insufficient_funds",
            f"{'House' if wallet.kind == 'house' else 'Spending'} wallet has {balance} paise; {amount} needed",
        )
        self.balance = balance
        self.amount = amount


@dataclass(frozen=True)
class EntryMeta:
    kind: str  # topup | advance | grocery_transfer | grocery_spend | reimbursement | salary | adjustment
    member_id: uuid.UUID | None = None
    employment_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None
    payroll_run_id: uuid.UUID | None = None
    note: str | None = None


class PaymentProvider(Protocol):
    name: str

    def balance(self, db: Session, wallet: Wallet) -> int: ...
    def credit(self, db: Session, wallet: Wallet, amount: int, meta: EntryMeta) -> LedgerEntry: ...
    def debit(self, db: Session, wallet: Wallet, amount: int, meta: EntryMeta) -> LedgerEntry: ...
    def transfer(self, db: Session, src: Wallet, dst: Wallet, amount: int, meta: EntryMeta) -> list[LedgerEntry]: ...


def _signed_sum():
    return func.coalesce(
        func.sum(case((LedgerEntry.direction == "credit", LedgerEntry.amount_paise), else_=-LedgerEntry.amount_paise)),
        0,
    )


class SimulatedProvider:
    name = "simulated"

    def balance(self, db: Session, wallet: Wallet) -> int:
        return int(db.scalar(select(_signed_sum()).where(LedgerEntry.wallet_id == wallet.id)))

    def credit(self, db: Session, wallet: Wallet, amount: int, meta: EntryMeta) -> LedgerEntry:
        self._check_amount(amount)
        return self._post(db, wallet, "credit", amount, meta, self._txn_id())

    def debit(self, db: Session, wallet: Wallet, amount: int, meta: EntryMeta) -> LedgerEntry:
        self._check_amount(amount)
        self._lock(db, wallet)
        balance = self.balance(db, wallet)
        if balance < amount:
            raise InsufficientFunds(wallet, balance, amount)
        return self._post(db, wallet, "debit", amount, meta, self._txn_id())

    def transfer(self, db: Session, src: Wallet, dst: Wallet, amount: int, meta: EntryMeta) -> list[LedgerEntry]:
        """Between two of the household's wallets (house -> helper spending). One transaction id for both legs."""
        self._check_amount(amount)
        self._lock(db, src)
        balance = self.balance(db, src)
        if balance < amount:
            raise InsufficientFunds(src, balance, amount)
        txn = self._txn_id()
        return [self._post(db, src, "debit", amount, meta, txn), self._post(db, dst, "credit", amount, meta, txn)]

    @staticmethod
    def _check_amount(amount: int) -> None:
        if not isinstance(amount, int) or amount <= 0:
            raise ApiError(400, "invalid_amount", "Amount must be a positive number of paise")

    @staticmethod
    def _lock(db: Session, wallet: Wallet) -> None:
        # Serialises balance checks on this wallet until the transaction ends.
        db.execute(select(Wallet.id).where(Wallet.id == wallet.id).with_for_update())

    @staticmethod
    def _txn_id() -> str:
        return "SIM-" + uuid.uuid4().hex[:12].upper()

    @staticmethod
    def _post(db: Session, wallet: Wallet, direction: str, amount: int, meta: EntryMeta, txn: str) -> LedgerEntry:
        entry = LedgerEntry(
            household_id=wallet.household_id,
            wallet_id=wallet.id,
            direction=direction,
            amount_paise=amount,
            kind=meta.kind,
            member_id=meta.member_id,
            employment_id=meta.employment_id,
            request_id=meta.request_id,
            payroll_run_id=meta.payroll_run_id,
            provider_txn_id=txn,
            month=clock.current_month(),
            note=meta.note,
            created_at=clock.now(),
        )
        db.add(entry)
        db.flush()
        return entry


provider: PaymentProvider = SimulatedProvider()


def house_wallet(db: Session, household_id: uuid.UUID) -> Wallet:
    return db.scalars(select(Wallet).where(Wallet.household_id == household_id, Wallet.kind == "house")).one()


def spending_wallet(db: Session, employment_id: uuid.UUID) -> Wallet:
    return db.scalars(
        select(Wallet).where(Wallet.employment_id == employment_id, Wallet.kind == "helper_spending")
    ).one()
