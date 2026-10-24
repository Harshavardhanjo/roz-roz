"""Request models for contract 2 (web API) and contract 3 (agent tools). Money is integer paise."""
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Month = Field(pattern=r"^\d{4}-\d{2}$")
MAX_PAISE = 10_000_000


# ---- Contract 2: web API bodies ----

class HouseholdCreate(BaseModel):
    household_name: str
    owner_name: str
    owner_phone: str


class MemberCreate(BaseModel):
    name: str
    phone: str
    split_weight: int = Field(default=1, ge=1)


class HelperCreate(BaseModel):
    name: str
    whatsapp_e164: str
    lang: Literal["kn", "hi", "ta", "te", "en"]
    role: str
    salary_paise: int = Field(gt=0, le=MAX_PAISE)
    payday_dom: int = Field(ge=1, le=31)  # shorter months pay on their last day
    weekly_off: list[int] = Field(default_factory=lambda: [6])
    paid_leaves_per_month: float = 2
    deduct_extra_leave: bool = True
    advance_auto_limit_paise: int = Field(ge=0, le=MAX_PAISE)
    advance_monthly_limit_paise: int = Field(ge=0, le=MAX_PAISE)
    grocery_auto_limit_paise: int = Field(ge=0, le=MAX_PAISE)
    grocery_monthly_budget_paise: int = Field(ge=0, le=MAX_PAISE)


class RulesUpdate(BaseModel):
    vote_rule: Literal["majority", "all", "any_one"] = "majority"
    two_person_limit_paise: int = Field(default=100000, ge=0)
    emergency_limit_paise: int = Field(default=200000, ge=0)


class VoteCreate(BaseModel):
    decision: Literal["approve", "reject"]


class AbsenceCreate(BaseModel):
    date: date
    fraction: float = Field(default=1.0, ge=0.5, le=1.0)


class TopupCreate(BaseModel):
    amount_paise: int = Field(gt=0, le=MAX_PAISE)


class PayrollRunCreate(BaseModel):
    month: str = Month


class SignupCreate(BaseModel):
    source: Literal["landing", "household", "helper"] = "landing"
    name: str
    phone: str
    pays_by: Literal["cash", "upi", "bank", "other"] | None = None


# ---- Contract 3: agent tool calls ----

class ToolCall(BaseModel):
    args: dict
    idempotency_key: str
    agent_run_id: UUID | None = None


class GetHelperContextArgs(BaseModel):
    whatsapp_e164: str


class RecordConsentArgs(BaseModel):
    helper_id: UUID
    employment_ids: list[UUID]


class CreateLeaveRequestArgs(BaseModel):
    employment_id: UUID
    leave_from: date
    leave_to: date
    half_day: bool = False
    note: str | None = None
    source_message_id: UUID | None = None


class CreateMoneyRequestArgs(BaseModel):
    """create_advance_request and create_grocery_request."""
    employment_id: UUID
    amount_paise: int = Field(gt=0, le=MAX_PAISE)
    note: str | None = None
    source_message_id: UUID | None = None


class RecordSpendArgs(BaseModel):
    """record_grocery_spend and record_cash_spend."""
    employment_id: UUID
    amount_paise: int = Field(gt=0, le=MAX_PAISE)
    item_note: str
    source_message_id: UUID | None = None


class EmploymentArgs(BaseModel):
    employment_id: UUID


class RequestArgs(BaseModel):
    request_id: UUID


class OpenVoteArgs(BaseModel):
    request_id: UUID
    context_text: str


class RunPayrollArgs(BaseModel):
    employment_id: UUID
    month: str = Month


class PostContributionsArgs(BaseModel):
    household_id: UUID
    month: str = Month


TOOL_ARGS: dict[str, type[BaseModel]] = {
    # liaison
    "get_helper_context": GetHelperContextArgs,
    "record_consent": RecordConsentArgs,
    "create_leave_request": CreateLeaveRequestArgs,
    "create_advance_request": CreateMoneyRequestArgs,
    "create_grocery_request": CreateMoneyRequestArgs,
    "record_grocery_spend": RecordSpendArgs,
    "record_cash_spend": RecordSpendArgs,
    "get_balances": EmploymentArgs,
    # treasurer
    "evaluate_request": RequestArgs,
    "check_grant": RequestArgs,
    "execute_request": RequestArgs,
    "open_vote": OpenVoteArgs,
    "run_payroll": RunPayrollArgs,
    "post_contributions": PostContributionsArgs,
}
