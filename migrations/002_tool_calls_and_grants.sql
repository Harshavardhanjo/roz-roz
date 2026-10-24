-- Internal tables (no effect on the web or tool contracts).

-- Idempotency for POST /tools/{name}: a repeated idempotency_key returns the stored response.
create table if not exists tool_call (
  idempotency_key text primary key,
  tool text not null,
  response jsonb not null,
  created_at timestamptz default now()
);

-- Each member's grant to the treasurer agent (Grantex-style scopes). member.grantex_grant_id points at the active one.
create table if not exists agent_grant (
  id text primary key,
  member_id uuid not null references member,
  household_id uuid not null references household,
  scopes jsonb not null,
  status text not null default 'active' check (status in ('active', 'revoked')),
  provider text not null default 'local',
  created_at timestamptz default now(),
  revoked_at timestamptz
);
create index if not exists agent_grant_member_idx on agent_grant (member_id, status);

create index if not exists ledger_entry_household_month_idx on ledger_entry (household_id, month);
create index if not exists ledger_entry_wallet_idx on ledger_entry (wallet_id);
create index if not exists request_household_status_idx on request (household_id, status);
create index if not exists leave_entry_employment_date_idx on leave_entry (employment_id, date);
