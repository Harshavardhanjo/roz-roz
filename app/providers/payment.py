"""All payments are simulated in the demo. Swap SimulatedProvider for a real provider later; flows don't change."""
import itertools
from typing import Protocol


class InsufficientFunds(Exception):
    pass


class PaymentProvider(Protocol):
    def balance(self, wallet_id: str) -> int: ...
    def credit(self, wallet_id: str, amount: int, ref: str) -> str: ...
    def debit(self, wallet_id: str, amount: int, ref: str) -> str: ...
    def transfer(self, src_wallet_id: str, dst: str, amount: int, ref: str) -> str: ...


class SimulatedProvider:
    """In-memory reference implementation. TODO(Harsha): back it with ledger_entry rows in the caller's transaction
    (balance = credits - debits) instead of the dict."""

    def __init__(self):
        self._balances: dict[str, int] = {}
        self._ids = itertools.count(1)

    def _txn(self) -> str:
        return f"SIM-{next(self._ids):06d}"

    def balance(self, wallet_id: str) -> int:
        return self._balances.get(wallet_id, 0)

    def credit(self, wallet_id: str, amount: int, ref: str) -> str:
        self._balances[wallet_id] = self.balance(wallet_id) + amount
        return self._txn()

    def debit(self, wallet_id: str, amount: int, ref: str) -> str:
        if self.balance(wallet_id) < amount:
            raise InsufficientFunds(wallet_id)
        self._balances[wallet_id] -= amount
        return self._txn()

    def transfer(self, src_wallet_id: str, dst: str, amount: int, ref: str) -> str:
        """dst is another wallet id, or 'helper:<id>' for money leaving to the helper."""
        txn = self.debit(src_wallet_id, amount, ref)
        if not dst.startswith("helper:"):
            self._balances[dst] = self.balance(dst) + amount
        return txn
