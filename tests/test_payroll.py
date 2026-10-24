from datetime import date

import pytest

from app.services.payroll import NegativeNetPay, compute_payroll, payday_in


def test_worked_example():
    r = compute_payroll(1_000_000, 27, 3, 2, True, 150_000)
    assert (r.unpaid_days, r.deduction_paise, r.net_paise) == (1, 37_000, 813_000)


def test_no_deduction_when_household_doesnt_deduct():
    r = compute_payroll(1_000_000, 27, 3, 2, False, 150_000)
    assert (r.deduction_paise, r.net_paise) == (0, 850_000)


def test_negative_net_is_refused():
    with pytest.raises(NegativeNetPay):
        compute_payroll(100_000, 27, 0, 2, True, 150_000)


def test_payday_31_in_short_month():
    assert payday_in("2026-11", 31) == date(2026, 11, 30)
    assert payday_in("2026-10", 31) == date(2026, 10, 31)
