from datetime import date

from app.services.leave import leave_days_in, split_paid_unpaid, working_days


def test_october_2026_working_days_sunday_off():
    assert len(working_days("2026-10", [6])) == 27


def test_leave_on_sunday_costs_nothing():
    assert leave_days_in(date(2026, 10, 25), date(2026, 10, 25), [6]) == 0  # 25 Oct 2026 is a Sunday


def test_monday_leave_and_half_day():
    assert leave_days_in(date(2026, 10, 26), date(2026, 10, 26), [6]) == 1
    assert leave_days_in(date(2026, 10, 26), date(2026, 10, 26), [6], half_day=True) == 0.5


def test_three_days_with_two_paid_left():
    assert split_paid_unpaid(3, 2, True) == (2, 1)
    assert split_paid_unpaid(3, 2, False) == (3, 0)
