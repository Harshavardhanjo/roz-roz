-- Contract 1 (LLD overview tab). Owned by Harsha. Money is integer paise; ledger amounts are positive.
-- payday_dom 29-31: shorter months pay on their last day (services.payroll.payday_in).
create table if not exists household (id uuid primary key, name text not null, owner_member_id uuid, created_at timestamptz default now());

create table if not exists member (id uuid primary key, household_id uuid not null references household,
  name text not null, phone text, role text not null check (role in ('owner','roommate')),
  split_weight int not null default 1, link_token text unique not null, grantex_grant_id text, created_at timestamptz default now());

create table if not exists helper (id uuid primary key, name text not null, whatsapp_e164 text unique not null,
  lang text not null check (lang in ('kn','hi','ta','te','en')), created_at timestamptz default now());

create table if not exists employment (id uuid primary key, household_id uuid not null references household, helper_id uuid not null references helper,
  role text not null, salary_paise int not null, payday_dom smallint not null check (payday_dom between 1 and 31),
  weekly_off smallint[] not null default '{6}',
  paid_leaves_per_month numeric(3,1) not null default 2, deduct_extra_leave boolean not null default true,
  advance_auto_limit_paise int not null, advance_monthly_limit_paise int not null,
  grocery_auto_limit_paise int not null, grocery_monthly_budget_paise int not null,
  consent_at timestamptz, status text not null default 'active', unique (household_id, helper_id));

create table if not exists house_rule (household_id uuid primary key references household,
  vote_rule text not null default 'majority' check (vote_rule in ('majority','all','any_one')),
  two_person_limit_paise int not null default 100000, emergency_limit_paise int not null default 200000, vote_timeout_h int not null default 12);

create table if not exists wallet (id uuid primary key, household_id uuid not null references household,
  kind text not null check (kind in ('house','helper_spending')), employment_id uuid references employment,
  provider text not null default 'simulated', external_ref text);

create table if not exists request (id uuid primary key, household_id uuid not null references household, employment_id uuid not null references employment,
  kind text not null check (kind in ('leave','advance','grocery_money','reimbursement','other')),
  amount_paise int, leave_from date, leave_to date, half_day boolean default false, note text,
  source_message_id uuid, created_by text not null,
  status text not null default 'pending' check (status in ('pending','auto_approved','needs_vote','needs_topup','approved','rejected','executed')),
  votes_needed int, rule_applied text, created_at timestamptz default now(), decided_at timestamptz);

create table if not exists vote (id uuid primary key, request_id uuid not null references request, member_id uuid not null references member,
  decision text not null check (decision in ('approve','reject')), at timestamptz default now(), unique (request_id, member_id));

create table if not exists leave_entry (id uuid primary key, employment_id uuid not null references employment, date date not null,
  kind text not null check (kind in ('paid','unpaid')), fraction numeric(2,1) not null default 1.0,
  request_id uuid references request, marked_by text not null, unique (employment_id, date));

create table if not exists payroll_run (id uuid primary key, employment_id uuid not null references employment, month char(7) not null,
  salary_paise int, working_days int, leave_days numeric(4,1), unpaid_days numeric(4,1),
  deduction_paise int, advances_paise int, net_paise int, status text not null default 'computed', executed_at timestamptz,
  unique (employment_id, month));

create table if not exists ledger_entry (id uuid primary key, household_id uuid not null references household, wallet_id uuid not null references wallet,
  direction text not null check (direction in ('credit','debit')), amount_paise bigint not null check (amount_paise > 0),
  kind text not null check (kind in ('topup','advance','grocery_transfer','grocery_spend','reimbursement','salary','adjustment')),
  member_id uuid references member, employment_id uuid references employment, request_id uuid references request,
  payroll_run_id uuid references payroll_run, provider_txn_id text, month char(7) not null, note text, created_at timestamptz default now());

create table if not exists contribution_statement (household_id uuid references household, member_id uuid references member, month char(7),
  topups_paise bigint not null, share_paise bigint not null, balance_paise bigint not null, primary key (household_id, member_id, month));

create table if not exists message (id uuid primary key, helper_id uuid references helper, direction text check (direction in ('in','out')),
  wa_message_id text unique, media_kind text, transcript text, lang text, agent_run_id uuid, reply_text text,
  latency_ms jsonb, created_at timestamptz default now());

create table if not exists agent_run (id uuid primary key, agent text check (agent in ('liaison','treasurer')), input jsonb, tool_calls jsonb,
  outcome jsonb, runtime text check (runtime in ('agenticorg','local')), started_at timestamptz, ended_at timestamptz);

create table if not exists audit_log (id bigserial primary key, at timestamptz default now(), household_id uuid, actor text not null,
  action text not null, entity text, entity_id uuid, rule_applied text, grantex_decision text, data_sent_to jsonb,
  payload jsonb, prev_hash text, hash text not null);

create table if not exists signup (id uuid primary key, source text check (source in ('landing','household','helper')),
  name text not null, phone text not null, pays_by text, created_at timestamptz default now(), unique (phone, source));
