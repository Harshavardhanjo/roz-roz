"""Demo state (LLD overview, "Demo seed"). Built through the same services the app uses, so the audit log, ledger and
requests look exactly like real use.

Run:  python -m seed.demo_seed            (prints the owner and roommate links)
API:  POST /api/admin/reset-demo with X-Admin-Token"""

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.db import session_scope
from app.models import Request
from app.providers.payment import EntryMeta, house_wallet, provider, spending_wallet
from app.schemas import HelperCreate, RulesUpdate
from app.services import grants, households, leave, requests

TABLES = (
    "tool_call",
    "agent_grant",
    "audit_log",
    "signup",
    "message",
    "agent_run",
    "contribution_statement",
    "ledger_entry",
    "payroll_run",
    "leave_entry",
    "vote",
    "request",
    "wallet",
    "house_rule",
    "employment",
    "helper",
    "member",
    "person",
    "household",
)


def _working_day_on_or_after(d: date, weekly_off: list[int]) -> date:
    while d.weekday() in weekly_off:
        d += timedelta(days=1)
    return d


def reset(db: Session) -> dict:
    db.execute(text(f"truncate {', '.join(TABLES)} restart identity cascade"))

    household, owner = households.create_household(db, "HSR Flat 302", "Harsha", "+919000000001")
    arjun = households.add_member(db, household, "Arjun", "+919000000002", 1, owner)
    households.update_rules(db, household, RulesUpdate(vote_rule="majority", two_person_limit_paise=100_000), owner)

    _, lakshmi = households.add_helper(
        db,
        household,
        HelperCreate(
            name="Lakshmi",
            whatsapp_e164=settings.demo_helper_e164,
            lang="kn",
            role="cook",
            salary_paise=1_000_000,
            payday_dom=31,
            weekly_off=[6],
            paid_leaves_per_month=2,
            deduct_extra_leave=True,
            advance_auto_limit_paise=50_000,
            advance_monthly_limit_paise=200_000,
            grocery_auto_limit_paise=50_000,
            grocery_monthly_budget_paise=600_000,
        ),
        owner,
    )
    _, ramesh = households.add_helper(
        db,
        household,
        HelperCreate(
            name="Ramesh",
            whatsapp_e164=settings.demo_helper2_e164,
            lang="hi",
            role="driver",
            salary_paise=1_800_000,
            payday_dom=1,
            weekly_off=[6],
            paid_leaves_per_month=2,
            deduct_extra_leave=True,
            advance_auto_limit_paise=50_000,
            advance_monthly_limit_paise=300_000,
            grocery_auto_limit_paise=0,
            grocery_monthly_budget_paise=0,
        ),
        owner,
    )

    now = clock.now()
    for emp in (lakshmi, ramesh):
        emp.consent_at = now
    grants.create_grant(db, owner)
    grants.create_grant(db, arjun)

    for m in (owner, arjun):
        provider.credit(db, house_wallet(db, household.id), 800_000, EntryMeta(kind="topup", member_id=m.id))

    # Two ₹500 advances, auto-approved within the rules.
    for _ in range(2):
        _process(db, requests.create(db, lakshmi, "advance", "helper", amount_paise=50_000, note="seed"))

    # ₹4,000 for groceries: above the ₹500 auto limit, so both roommates vote.
    grocery = requests.create(db, lakshmi, "grocery_money", "helper", amount_paise=400_000, note="monthly groceries")
    _process(db, grocery)
    requests.vote(db, grocery, owner, "approve")
    requests.vote(db, grocery, arjun, "approve")

    wallet = spending_wallet(db, lakshmi.id)
    for amount, item in ((210_000, "vegetables and rice"), (160_000, "milk, oil and dal")):
        provider.debit(db, wallet, amount, EntryMeta(kind="grocery_spend", employment_id=lakshmi.id, note=item))

    # Paid leave on the 8th and 20th (moved to the next working day), if those are already past this month.
    month = clock.current_month()
    start, _ = leave.month_bounds(month)
    for d in sorted({_working_day_on_or_after(start.replace(day=day), list(lakshmi.weekly_off)) for day in (8, 20)}):
        if d < clock.today():
            _process(db, requests.create(db, lakshmi, "leave", "helper", leave_from=d, leave_to=d))

    db.flush()
    return {
        "household_id": str(household.id),
        "owner": {"name": owner.name, "token": owner.link_token, "link": households.member_link(owner)},
        "roommate": {"name": arjun.name, "token": arjun.link_token, "link": households.member_link(arjun)},
        "helpers": [
            {"name": "Lakshmi", "whatsapp_e164": settings.demo_helper_e164, "employment_id": str(lakshmi.id)},
            {"name": "Ramesh", "whatsapp_e164": settings.demo_helper2_e164, "employment_id": str(ramesh.id)},
        ],
        "month": month,
    }


def _process(db: Session, req: Request) -> None:
    requests.auto_process(db, req, actor="system:treasurer")


def main() -> None:
    with session_scope() as db:
        result = reset(db)
    print(f"Demo household {result['household_id']} ({result['month']})")
    print(f"  owner    {result['owner']['link']}")
    print(f"  roommate {result['roommate']['link']}")
    for h in result["helpers"]:
        print(f"  helper   {h['name']} {h['whatsapp_e164']}")


if __name__ == "__main__":
    main()
