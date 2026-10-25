"use client";

import Link from "next/link";
import { useMeContext } from "@/lib/MeContext";
import { useApi } from "@/lib/useApi";
import { castVote, createGrant, dashboard } from "@/lib/api";
import { inr } from "@/lib/money";
import { SimulatedBadge } from "@/components/SimulatedBadge";
import { useState } from "react";

export default function DashboardPage() {
  const { me, token } = useMeContext();
  const { data, loading, error, reload } = useApi(() => dashboard(token, me.household_id), [token, me.household_id]);
  const [granting, setGranting] = useState(false);

  async function grantLimits() {
    setGranting(true);
    try {
      await createGrant(token, me.member_id);
      reload();
    } finally {
      setGranting(false);
    }
  }

  async function vote(requestId: string, decision: "approve" | "reject") {
    await castVote(token, requestId, decision);
    reload();
  }

  if (loading) return <p className="text-sm text-slate-500">Loading dashboard…</p>;
  if (error) return <p className="text-sm text-rose-600">Couldn&apos;t load the dashboard: {error.message}</p>;
  if (!data) return null;

  return (
    <div className="space-y-6">
      {data.alerts.length > 0 && (
        <div className="space-y-2">
          {data.alerts.map((a) => (
            <div
              key={a.code}
              className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300"
            >
              <span>{a.message}</span>
              {a.code.startsWith("grant_") && (
                <button
                  onClick={grantLimits}
                  disabled={granting}
                  className="rounded-md bg-amber-700 px-3 py-1 text-xs font-medium text-white hover:bg-amber-800 disabled:opacity-50"
                >
                  {granting ? "Granting…" : "Grant agent limits"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <section className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-500">House wallet</h2>
            <SimulatedBadge />
          </div>
          <p className="mt-2 text-3xl font-semibold text-slate-900 dark:text-slate-50">
            {inr(data.house_wallet.balance_paise)}
          </p>
          <Link href={`/h/${token}/payments`} className="mt-3 inline-block text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-400">
            Top up or view ledger →
          </Link>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-sm font-medium text-slate-500">This month&apos;s contributions</h2>
          <ul className="mt-2 space-y-1">
            {data.contributions.map((c) => (
              <li key={c.member_id} className="flex justify-between text-sm">
                <span className="text-slate-700 dark:text-slate-300">{c.name}</span>
                <span className="font-medium">
                  {inr(c.balance_paise)} {c.balance_paise >= 0 ? "credit" : "owed"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-medium text-slate-500">Helpers</h2>
        <div className="space-y-3">
          {data.helpers.map((h) => (
            <div
              key={h.employment_id}
              className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
            >
              <div className="flex items-center justify-between">
                <p className="font-medium text-slate-900 dark:text-slate-50">
                  {h.name} <span className="text-sm text-slate-500">· {h.role}</span>
                </p>
                <p className="text-sm text-slate-500">Next payday {h.next_payday}</p>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-sm text-slate-600 dark:text-slate-400 sm:grid-cols-4">
                <span>Salary {inr(h.salary_paise)}</span>
                <span>
                  Leave {h.leave.paid_used}/{h.leave.paid_allowed} paid
                </span>
                <span>
                  Advances {inr(h.advances.this_month_paise)}/{inr(h.advances.monthly_limit_paise)}
                </span>
                <span>Spending wallet {inr(h.grocery.spending_wallet_paise)}</span>
              </div>
            </div>
          ))}
          {data.helpers.length === 0 && <p className="text-sm text-slate-500">No helpers added yet.</p>}
        </div>
      </section>

      {data.open_votes.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-medium text-slate-500">Needs a vote</h2>
          <div className="space-y-3">
            {data.open_votes.map((v) => (
              <div
                key={v.request_id}
                className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 dark:border-amber-900 dark:bg-amber-950/20"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium text-slate-900 dark:text-slate-50">
                    {v.helper_name} — {v.kind.replace(/_/g, " ")}
                  </p>
                  {v.overdue && <span className="text-xs font-medium text-rose-600">overdue</span>}
                </div>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{v.context}</p>
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={() => vote(v.request_id, "approve")}
                    className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => vote(v.request_id, "reject")}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
