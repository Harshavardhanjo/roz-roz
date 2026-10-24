from app.money import count, inr, rupees
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


def test_indian_rupee_formatting():
    assert inr(0) == "₹0"
    assert inr(50_000) == "₹500"
    assert inr(150_000) == "₹1,500"
    assert inr(123_456_789) == "₹12,34,567.89"
    assert inr(-37_000) == "-₹370"
    assert rupees(813_000) == 8130 and rupees(12_345) == 123.45
    assert count(2.0) == 2 and count(0.5) == 0.5
