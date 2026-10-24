"""ORM mapping of contract 1. migrations/001_init.sql is the source of truth for constraints."""
import uuid

from sqlalchemy import (
    BigInteger, Boolean, CHAR, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, Text, Uuid, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import mapped_column

from .db import Base


def _id():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Household(Base):
    __tablename__ = "household"
    id = _id()
    name = mapped_column(Text, nullable=False)
    owner_member_id = mapped_column(Uuid)
    created_at = _created()


class Member(Base):
    __tablename__ = "member"
    id = _id()
    household_id = mapped_column(ForeignKey("household.id"), nullable=False)
    name = mapped_column(Text, nullable=False)
    phone = mapped_column(Text)
    role = mapped_column(Text, nullable=False)  # owner | roommate
    split_weight = mapped_column(Integer, nullable=False, default=1)
    link_token = mapped_column(Text, unique=True, nullable=False)
    grantex_grant_id = mapped_column(Text)
    created_at = _created()


class Helper(Base):
    __tablename__ = "helper"
    id = _id()
    name = mapped_column(Text, nullable=False)
    whatsapp_e164 = mapped_column(Text, unique=True, nullable=False)
    lang = mapped_column(Text, nullable=False)  # kn | hi | ta | te | en
    created_at = _created()


class Employment(Base):
    __tablename__ = "employment"
    id = _id()
    household_id = mapped_column(ForeignKey("household.id"), nullable=False)
    helper_id = mapped_column(ForeignKey("helper.id"), nullable=False)
    role = mapped_column(Text, nullable=False)
    salary_paise = mapped_column(Integer, nullable=False)
    payday_dom = mapped_column(SmallInteger, nullable=False)
    weekly_off = mapped_column(ARRAY(SmallInteger), nullable=False, default=lambda: [6])  # 0 = Monday ... 6 = Sunday
    paid_leaves_per_month = mapped_column(Numeric(3, 1), nullable=False, default=2)
    deduct_extra_leave = mapped_column(Boolean, nullable=False, default=True)
    advance_auto_limit_paise = mapped_column(Integer, nullable=False)
    advance_monthly_limit_paise = mapped_column(Integer, nullable=False)
    grocery_auto_limit_paise = mapped_column(Integer, nullable=False)
    grocery_monthly_budget_paise = mapped_column(Integer, nullable=False)
    consent_at = mapped_column(DateTime(timezone=True))
    status = mapped_column(Text, nullable=False, default="active")


class HouseRule(Base):
    __tablename__ = "house_rule"
    household_id = mapped_column(ForeignKey("household.id"), primary_key=True)
    vote_rule = mapped_column(Text, nullable=False, default="majority")  # majority | all | any_one
    two_person_limit_paise = mapped_column(Integer, nullable=False, default=100000)
    emergency_limit_paise = mapped_column(Integer, nullable=False, default=200000)
    vote_timeout_h = mapped_column(Integer, nullable=False, default=12)


class Wallet(Base):
    __tablename__ = "wallet"
    id = _id()
    household_id = mapped_column(ForeignKey("household.id"), nullable=False)
    kind = mapped_column(Text, nullable=False)  # house | helper_spending
    employment_id = mapped_column(ForeignKey("employment.id"))
    provider = mapped_column(Text, nullable=False, default="simulated")
    external_ref = mapped_column(Text)


class Request(Base):
    __tablename__ = "request"
    id = _id()
    household_id = mapped_column(ForeignKey("household.id"), nullable=False)
    employment_id = mapped_column(ForeignKey("employment.id"), nullable=False)
    kind = mapped_column(Text, nullable=False)  # leave | advance | grocery_money | reimbursement | other
    amount_paise = mapped_column(Integer)
    leave_from = mapped_column(Date)
    leave_to = mapped_column(Date)
    half_day = mapped_column(Boolean, default=False)
    note = mapped_column(Text)
    source_message_id = mapped_column(Uuid)
    created_by = mapped_column(Text, nullable=False)  # 'helper' or 'member:<uuid>'
    status = mapped_column(Text, nullable=False, default="pending")
    votes_needed = mapped_column(Integer)
    rule_applied = mapped_column(Text)
    created_at = _created()
    decided_at = mapped_column(DateTime(timezone=True))


class Vote(Base):
    __tablename__ = "vote"
    id = _id()
    request_id = mapped_column(ForeignKey("request.id"), nullable=False)
    member_id = mapped_column(ForeignKey("member.id"), nullable=False)
    decision = mapped_column(Text, nullable=False)  # approve | reject
    at = _created()


class LeaveEntry(Base):
    __tablename__ = "leave_entry"
    id = _id()
    employment_id = mapped_column(ForeignKey("employment.id"), nullable=False)
    date = mapped_column(Date, nullable=False)
    kind = mapped_column(Text, nullable=False)  # paid | unpaid
    fraction = mapped_column(Numeric(2, 1), nullable=False, default=1.0)
    request_id = mapped_column(ForeignKey("request.id"))
    marked_by = mapped_column(Text, nullable=False)


class PayrollRun(Base):
    __tablename__ = "payroll_run"
    id = _id()
    employment_id = mapped_column(ForeignKey("employment.id"), nullable=False)
    month = mapped_column(CHAR(7), nullable=False)
    salary_paise = mapped_column(Integer)
    working_days = mapped_column(Integer)
    leave_days = mapped_column(Numeric(4, 1))
    unpaid_days = mapped_column(Numeric(4, 1))
    deduction_paise = mapped_column(Integer)
    advances_paise = mapped_column(Integer)
    net_paise = mapped_column(Integer)
    status = mapped_column(Text, nullable=False, default="computed")
    executed_at = mapped_column(DateTime(timezone=True))


class LedgerEntry(Base):
    __tablename__ = "ledger_entry"
    id = _id()
    household_id = mapped_column(ForeignKey("household.id"), nullable=False)
    wallet_id = mapped_column(ForeignKey("wallet.id"), nullable=False)
    direction = mapped_column(Text, nullable=False)  # credit | debit
    amount_paise = mapped_column(BigInteger, nullable=False)
    kind = mapped_column(Text, nullable=False)
    member_id = mapped_column(ForeignKey("member.id"))
    employment_id = mapped_column(ForeignKey("employment.id"))
    request_id = mapped_column(ForeignKey("request.id"))
    payroll_run_id = mapped_column(ForeignKey("payroll_run.id"))
    provider_txn_id = mapped_column(Text)
    month = mapped_column(CHAR(7), nullable=False)
    note = mapped_column(Text)
    created_at = _created()


class ContributionStatement(Base):
    __tablename__ = "contribution_statement"
    household_id = mapped_column(ForeignKey("household.id"), primary_key=True)
    member_id = mapped_column(ForeignKey("member.id"), primary_key=True)
    month = mapped_column(CHAR(7), primary_key=True)
    topups_paise = mapped_column(BigInteger, nullable=False)
    share_paise = mapped_column(BigInteger, nullable=False)
    balance_paise = mapped_column(BigInteger, nullable=False)


class Message(Base):
    __tablename__ = "message"
    id = _id()
    helper_id = mapped_column(ForeignKey("helper.id"))
    direction = mapped_column(Text)  # in | out
    wa_message_id = mapped_column(Text, unique=True)
    media_kind = mapped_column(Text)
    transcript = mapped_column(Text)
    lang = mapped_column(Text)
    agent_run_id = mapped_column(Uuid)
    reply_text = mapped_column(Text)
    latency_ms = mapped_column(JSONB)
    created_at = _created()


class AgentRun(Base):
    __tablename__ = "agent_run"
    id = _id()
    agent = mapped_column(Text)  # liaison | treasurer
    input = mapped_column(JSONB)
    tool_calls = mapped_column(JSONB)
    outcome = mapped_column(JSONB)
    runtime = mapped_column(Text)  # agenticorg | local
    started_at = mapped_column(DateTime(timezone=True))
    ended_at = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at = _created()
    household_id = mapped_column(Uuid)
    actor = mapped_column(Text, nullable=False)
    action = mapped_column(Text, nullable=False)
    entity = mapped_column(Text)
    entity_id = mapped_column(Uuid)
    rule_applied = mapped_column(Text)
    grantex_decision = mapped_column(Text)
    data_sent_to = mapped_column(JSONB)
    payload = mapped_column(JSONB)
    prev_hash = mapped_column(Text)
    hash = mapped_column(Text, nullable=False)


class Signup(Base):
    __tablename__ = "signup"
    id = _id()
    source = mapped_column(Text)  # landing | household | helper
    name = mapped_column(Text, nullable=False)
    phone = mapped_column(Text, nullable=False)
    pays_by = mapped_column(Text)
    created_at = _created()
