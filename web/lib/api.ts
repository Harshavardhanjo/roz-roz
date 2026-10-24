// Typed client for the Roz Roz backend (contract 2: the web API). Auth is a member's
// link token sent as X-Roz-Token; every error comes back as {"error": {"code", "message"}}.
// See backend docs/CHANGES_FOR_TEAM.md for the full contract this mirrors.

import type {
  ApiErrorBody,
  ContributionsResponse,
  Dashboard,
  EmploymentDetail,
  GrantStatus,
  HouseholdCreateResponse,
  LedgerPage,
  Me,
  MemberCreateResponse,
  PayrollRun,
  RequestOut,
  Stats,
  TopupResponse,
  AuditEntry,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(
  path: string,
  opts: { token?: string; method?: string; body?: unknown } = {}
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.token) headers["X-Roz-Token"] = opts.token;

  const res = await fetch(`${BASE_URL}${path}`, {
    method: opts.method ?? (opts.body ? "POST" : "GET"),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    cache: "no-store",
  });

  if (!res.ok) {
    let code = "unknown_error";
    let message = `Request failed with status ${res.status}`;
    try {
      const body = (await res.json()) as ApiErrorBody;
      code = body.error.code;
      message = Array.isArray(body.error.message)
        ? body.error.message.map((e) => JSON.stringify(e)).join("; ")
        : body.error.message;
    } catch {
      // response wasn't JSON; keep the generic message
    }
    throw new ApiError(res.status, code, message);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- households & members ----

export function createHousehold(householdName: string, ownerName: string, ownerPhone: string) {
  return request<HouseholdCreateResponse>("/api/households", {
    method: "POST",
    body: { household_name: householdName, owner_name: ownerName, owner_phone: ownerPhone },
  });
}

export function me(token: string) {
  return request<Me>("/api/me", { token });
}

export function linkFlat(token: string, otherToken: string) {
  return request<Me>("/api/me/link", { token, method: "POST", body: { other_token: otherToken } });
}

export function removeMember(token: string, memberId: string) {
  return request<{ member_id: string; removed_at: string; final_balance_paise: number; month: string }>(
    `/api/members/${memberId}`,
    { token, method: "DELETE" }
  );
}

export function addMember(token: string, householdId: string, name: string, phone: string, splitWeight = 1) {
  return request<MemberCreateResponse>(`/api/households/${householdId}/members`, {
    token,
    method: "POST",
    body: { name, phone, split_weight: splitWeight },
  });
}

export function updateMemberWeight(token: string, memberId: string, splitWeight: number) {
  return request<{ member_id: string; split_weight: number }>(`/api/members/${memberId}`, {
    token,
    method: "PATCH",
    body: { split_weight: splitWeight },
  });
}

export function putRules(
  token: string,
  householdId: string,
  rules: { vote_rule: "majority" | "all" | "any_one"; two_person_limit_paise: number; emergency_limit_paise: number }
) {
  return request(`/api/households/${householdId}/rules`, { token, method: "PUT", body: rules });
}

export function createGrant(token: string, memberId: string) {
  return request<{ grant_id: string; scopes: string[]; status: GrantStatus }>(`/api/members/${memberId}/grant`, {
    token,
    method: "POST",
  });
}

export function dashboard(token: string, householdId: string) {
  return request<Dashboard>(`/api/households/${householdId}/dashboard`, { token });
}

// ---- helpers / employments ----

export type HelperCreateInput = {
  name: string;
  whatsapp_e164: string;
  lang: "kn" | "hi" | "ta" | "te" | "en";
  role: string;
  salary_paise: number;
  payday_dom: number;
  weekly_off?: number[];
  paid_leaves_per_month?: number;
  deduct_extra_leave?: boolean;
  advance_auto_limit_paise: number;
  advance_monthly_limit_paise: number;
  grocery_auto_limit_paise: number;
  grocery_monthly_budget_paise: number;
};

export function addHelper(token: string, householdId: string, body: HelperCreateInput) {
  return request<{ helper_id: string; employment_id: string; whatsapp_link: string | null }>(
    `/api/households/${householdId}/helpers`,
    { token, method: "POST", body }
  );
}

export function patchEmployment(token: string, employmentId: string, body: Record<string, unknown>) {
  return request<EmploymentDetail>(`/api/employments/${employmentId}`, { token, method: "PATCH", body });
}

export function employmentDetail(token: string, employmentId: string) {
  return request<EmploymentDetail>(`/api/employments/${employmentId}`, { token });
}

export function markAbsent(token: string, employmentId: string, date: string, fraction = 1.0) {
  return request(`/api/employments/${employmentId}/absences`, { token, method: "POST", body: { date, fraction } });
}

export function runPayroll(token: string, employmentId: string, month: string) {
  return request<PayrollRun>(`/api/employments/${employmentId}/payroll/run`, {
    token,
    method: "POST",
    body: { month },
  });
}

export function payrollHistory(token: string, employmentId: string) {
  return request<PayrollRun[]>(`/api/employments/${employmentId}/payroll`, { token });
}

// ---- requests & votes ----

export function listRequests(token: string, householdId: string, status?: string) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<RequestOut[]>(`/api/households/${householdId}/requests${qs}`, { token });
}

export function castVote(token: string, requestId: string, decision: "approve" | "reject") {
  return request<RequestOut>(`/api/requests/${requestId}/votes`, { token, method: "POST", body: { decision } });
}

// ---- ledger, contributions, payments ----

export function ledger(token: string, householdId: string, month?: string) {
  const qs = month ? `?month=${encodeURIComponent(month)}` : "";
  return request<LedgerPage>(`/api/households/${householdId}/ledger${qs}`, { token });
}

export function contributions(token: string, householdId: string, month?: string) {
  const qs = month ? `?month=${encodeURIComponent(month)}` : "";
  return request<ContributionsResponse>(`/api/households/${householdId}/contributions${qs}`, { token });
}

export function topup(token: string, householdId: string, amountPaise: number) {
  return request<TopupResponse>(`/api/households/${householdId}/topups`, {
    token,
    method: "POST",
    body: { amount_paise: amountPaise },
  });
}

// ---- audit ----

export function auditLog(token: string, householdId: string, limit = 50) {
  return request<AuditEntry[]>(`/api/households/${householdId}/audit?limit=${limit}`, { token });
}

// ---- signups / stats (public, no token) ----

export function createSignup(
  name: string,
  phone: string,
  source: "landing" | "household" | "helper" = "landing",
  paysBy?: "cash" | "upi" | "bank" | "other"
) {
  return request<{ ok: true }>("/api/signups", {
    method: "POST",
    body: { name, phone, source, pays_by: paysBy },
  });
}

export function stats() {
  return request<Stats>("/api/stats");
}
