from app.services.rules import evaluate_leave, evaluate_money_request, votes_needed

TWO = dict(n_roommates=2, vote_rule="majority", two_person_limit_paise=100_000)


def money(amount, used, balance=1_000_000, grants_ok=True):
    return evaluate_money_request(amount, used, 50_000, 200_000, balance, grants_ok, **TWO)


def test_auto_within_limits():
    assert money(50_000, 100_000).kind == "AUTO"


def test_above_auto_limit_needs_one_vote_in_two_person_flat():
    d = money(60_000, 0)
    assert (d.kind, d.votes_needed) == ("VOTE", 1)


def test_over_monthly_limit_needs_everyone():
    d = money(50_000, 180_000)
    assert (d.kind, d.votes_needed) == ("VOTE", 2)


def test_low_house_balance():
    assert money(50_000, 0, balance=30_000).kind == "NEEDS_TOPUP"


def test_grant_refusal_goes_to_vote():
    assert money(50_000, 0, grants_ok=False).kind == "VOTE"


def test_majority_sizes():
    assert votes_needed(3, 0, "majority", 0) == 2
    assert votes_needed(4, 0, "majority", 0) == 3
    assert votes_needed(2, 150_000, "majority", 100_000) == 2


def test_leave_beyond_paid_balance_goes_to_vote():
    assert evaluate_leave(1, 0, True, **TWO).kind == "VOTE"
    assert evaluate_leave(1, 2, True, **TWO).kind == "AUTO"
