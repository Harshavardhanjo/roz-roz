"""Payroll maths: salary - unpaid leave - advances this month, paid in full once."""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


class NegativeNetPay(ValueError):
    """Advances exceed what's payable; the advance limit should prevent this. Flag to the owner."""


@dataclass(frozen=True)
class PayrollResult:
    salary_paise: int
    working_days: int
    leave_days: float
    unpaid_days: float
    deduction_paise: int
    advances_paise: int
    net_paise: int


def round_to_rupee(paise: Decimal) -> int:
    return int((paise / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100


def compute_payroll(salary_paise: int, working_days: int, leave_days: float, paid_leaves_per_month: float,
                    deduct_extra_leave: bool, advances_paise: int) -> PayrollResult:
    unpaid = max(0.0, leave_days - paid_leaves_per_month) if deduct_extra_leave else 0.0
    deduction = round_to_rupee(Decimal(str(unpaid)) * salary_paise / working_days) if unpaid else 0
    net = salary_paise - deduction - advances_paise
    if net < 0:
        raise NegativeNetPay(f"net {net} < 0")
    return PayrollResult(salary_paise, working_days, leave_days, unpaid, deduction, advances_paise, net)


def payday_in(month: str, payday_dom: int):
    """Payday for the month; a day past the month's end falls on its last day."""
    from .leave import month_bounds
    start, end = month_bounds(month)
    return start.replace(day=min(payday_dom, end.day))
