import pytest

from app.providers.payment import InsufficientFunds, SimulatedProvider
from app.services.audit import chain_hash, verify_chain


def test_audit_chain_detects_tampering():
    rows, prev = [], None
    for i in range(3):
        content = {"action": "approve_request", "n": i}
        h = chain_hash(prev, content)
        rows.append({**content, "prev_hash": prev, "hash": h})
        prev = h
    assert verify_chain(rows)
    rows[1]["n"] = 99
    assert not verify_chain(rows)


def test_simulated_provider_month():
    p = SimulatedProvider()
    p.credit("house", 1_600_000, "topups")
    for _ in range(3):
        p.transfer("house", "helper:lakshmi", 50_000, "advance")
    p.transfer("house", "spend", 400_000, "grocery_transfer")
    p.debit("spend", 370_000, "grocery_spend")
    p.transfer("house", "helper:lakshmi", 813_000, "salary")
    assert (p.balance("house"), p.balance("spend")) == (237_000, 30_000)
    with pytest.raises(InsufficientFunds):
        p.debit("spend", 40_000, "too much")
