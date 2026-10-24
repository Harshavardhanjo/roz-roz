from app.services.contributions import split_cost, statement


def test_worked_example():
    rows = statement(1_333_000, {"harsha": 1, "arjun": 1}, "harsha", {"harsha": 800_000, "arjun": 800_000})
    assert [(r.share_paise, r.balance_paise) for r in rows] == [(666_500, 133_500), (666_500, 133_500)]


def test_remainder_goes_to_owner():
    assert split_cost(1_000_001, {"owner": 1, "rm": 1}, "owner") == {"owner": 500_001, "rm": 500_000}
