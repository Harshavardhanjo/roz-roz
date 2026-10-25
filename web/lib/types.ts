// Types mirroring the backend's contract 2 response shapes (see app/services/views.py
// and app/stubs.py in the backend repo). Money is always integer paise.

export type Role = "owner" | "roommate";

export type ApiErrorBody = {
  error: { code: string; message: string | Array<Record<string, unknown>> };
};

export type Flat = {
  household_id: string;
  household_name: string;
  member_id: string;
  role: Role;
  token: string;
  link: string;
  current: boolean;
};

export type Me = {
  member_id: string;
  household_id: string;
  role: Role;
  name: string;
  flats: Flat[];
};

export type HouseholdCreateResponse = {
  household_id: string;
  member_id: string;
  token: string;
  link: string;
};

export type MemberCreateResponse = {
  member_id: string;
  token: string;
  link: string;
};

export type GrantStatus = "active" | "outdated" | "missing";

export type Alert = { code: string; message: string };

export type HelperCard = {
  employment_id: string;
  helper_id: string;
  name: string;
  role: string;
  lang: string;
  consented: boolean;
  salary_paise: number;
  next_payday: string;
  projected_net_paise: number;
  leave: { paid_allowed: number; paid_used: number; unpaid_days: number };
  advances: { this_month_paise: number; monthly_limit_paise: number };
  grocery: {
    budget_paise: number;
    spent_paise: number;
    budget_used_paise: number;
    spending_wallet_paise: number;
  };
};

export type VoteEntry = { member_id: string; name: string; decision: "approve" | "reject" };

export type VoteCard = {
  request_id: string;
  helper_name: string;
  kind: RequestKind;
  amount_paise: number;
  context: string;
  votes_needed: number;
  votes: VoteEntry[];
  created_at: string;
  overdue: boolean;
};

export type ContributionRow = {
  member_id: string;
  name: string;
  topups_paise: number;
  share_paise: number;
  balance_paise: number;
};

export type Dashboard = {
  household: { id: string; name: string };
  me: { member_id: string; role: Role; name: string; grant_status: GrantStatus };
  house_wallet: { balance_paise: number; simulated: true };
  helpers: HelperCard[];
  open_votes: VoteCard[];
  contributions: ContributionRow[];
  alerts: Alert[];
};

export type RequestKind = "leave" | "advance" | "grocery_money" | "reimbursement" | "other";
export type RequestStatus =
  | "pending"
  | "auto_approved"
  | "needs_vote"
  | "needs_topup"
  | "approved"
  | "rejected"
  | "executed";

export type RequestOut = {
  id: string;
  employment_id: string;
  helper_name: string;
  kind: RequestKind;
  status: RequestStatus;
  amount_paise: number;
  leave_from: string | null;
  leave_to: string | null;
  half_day: boolean;
  note: string | null;
  rule_applied: string;
  created_by: string;
  votes: VoteEntry[];
  votes_needed: number | null;
  created_at: string;
  decided_at: string | null;
};

export type LedgerEntryOut = {
  id: string;
  at: string;
  wallet: "house" | "spending";
  direction: "credit" | "debit";
  kind: "topup" | "advance" | "grocery_transfer" | "grocery_spend" | "reimbursement" | "salary" | "adjustment";
  amount_paise: number;
  who: string | null;
  request_id: string | null;
  provider_txn_id: string;
  simulated: true;
  note: string | null;
};

export type LedgerPage = { month: string; entries: LedgerEntryOut[] };

export type ContributionDetail = ContributionRow & { weight: number; suggested_topup_paise: number };

export type ContributionsResponse = {
  month: string;
  cost_paise: number;
  members: ContributionDetail[];
};

export type TopupResponse = { ledger_entry_id: string; house_balance_paise: number };

export type PayrollRun = {
  payroll_run_id: string;
  employment_id: string;
  month: string;
  salary_paise: number;
  working_days: number;
  leave_days: number;
  unpaid_days: number;
  deduction_paise: number;
  advances_paise: number;
  net_paise: number;
  status: "executed" | "needs_topup";
  simulated: true;
  executed_at: string | null;
};

export type AuditEntry = {
  at: string;
  actor: string;
  action: string;
  entity: string;
  entity_id: string | null;
  rule_applied: string;
  grantex_decision: string;
  summary: string | null;
};

export type EmploymentTerms = {
  role: string;
  lang: string;
  whatsapp_e164: string;
  salary_paise: number;
  payday_dom: number;
  weekly_off: number[];
  paid_leaves_per_month: number;
  deduct_extra_leave: boolean;
  advance_auto_limit_paise: number;
  advance_monthly_limit_paise: number;
  grocery_auto_limit_paise: number;
  grocery_monthly_budget_paise: number;
  status: "active" | "ended";
};

export type EmploymentDetail = {
  employment: HelperCard;
  terms: EmploymentTerms;
  leave_days: { date: string; kind: string; fraction: number; marked_by: string }[];
  requests: RequestOut[];
  payroll: PayrollRun[];
};

export type Stats = {
  total: number;
  by_source: Record<string, number>;
  last_hour: number;
  pays_by: Record<string, number>;
  voice_median_latency_ms: number | null;
};

export type ResetDemoResponse = {
  household_id: string;
  owner: { name: string; token: string; link: string };
  roommate: { name: string; token: string; link: string };
  helpers: { name: string; whatsapp_e164: string; employment_id: string }[];
  month: string;
};
