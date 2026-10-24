"use client";

import { useMemo, useState } from "react";
import { useMeContext } from "@/lib/MeContext";
import { useApi } from "@/lib/useApi";
import { contributions as fetchContributions, dashboard as fetchDashboard, ledger as fetchLedger } from "@/lib/api";
import { inr } from "@/lib/money";
import { SimulatedBadge } from "@/components/SimulatedBadge";
import { PaymentModal } from "./PaymentModal";

function lastMonths(n: number): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  const now = new Date();
  for (let i = 0; i < n; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = d.toLocaleDateString("en-IN", { month: "long", year: "numeric" });
    out.push({ value, label });
  }
  return out;
}

export default function PaymentsPage() {
  const { me, token } = useMeContext();
  const months = useMemo(() => lastMonths(6), []);
  const [month, setMonth] = useState(months[0].value);
  const [modalOpen, setModalOpen] = useState(false);

  const ledgerQuery = useApi(() => fetchLedger(token, me.household_id, month), [token, me.household_id, month]);
  const contribQuery = useApi(
    () => fetchContributions(token, me.household_id, month),
    [token, me.household_id, month]
  );
  // The dashboard's house_wallet balance is the running total across all months, unlike
  // the ledger view below (which is filtered to the selected month) — fetched separately.
  const balanceQuery = useApi(() => fetchDashboard(token, me.household_id), [token, me.household_id]);

  function onPaid() {
    setModalOpen(false);
    ledgerQuery.reload();
    contribQuery.reload();
    balanceQuery.reload();
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-medium text-slate-500">House wallet</h1>
              <SimulatedBadge />
            </div>
            <p className="mt-1 text-4xl font-semibold text-slate-900 dark:text-slate-50">
              {balanceQuery.data ? inr(balanceQuery.data.house_wallet.balance_paise) : "…"}
            </p>
            <p className="mt-1 text-xs text-slate-400">No real money moves in this demo — every entry below is simulated.</p>
          </div>
          <button
            onClick={() => setModalOpen(true)}
            className="rounded-lg bg-emerald-600 px-5 py-2.5 font-medium text-white shadow-sm hover:bg-emerald-700"
          >
            Top up (mock payment)
          </button>
        </div>
      </section>

      {contribQuery.data && (
        <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-sm font-medium text-slate-500">
            This month&apos;s contributions ({contribQuery.data.month})
          </h2>
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="pb-2 font-normal">Who</th>
                <th className="pb-2 font-normal">Topped up</th>
                <th className="pb-2 font-normal">Share</th>
                <th className="pb-2 font-normal">Balance</th>
                <th className="pb-2 font-normal">Suggested next top-up</th>
              </tr>
            </thead>
            <tbody>
              {contribQuery.data.members.map((m) => (
                <tr key={m.member_id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-2 font-medium text-slate-800 dark:text-slate-200">
                    {m.name} {m.member_id === me.member_id && <span className="text-slate-400">(you)</span>}
                  </td>
                  <td className="py-2">{inr(m.topups_paise)}</td>
                  <td className="py-2">{inr(m.share_paise)}</td>
                  <td className={`py-2 font-medium ${m.balance_paise >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                    {inr(m.balance_paise)} {m.balance_paise >= 0 ? "credit" : "owed"}
                  </td>
                  <td className="py-2">{inr(Math.max(0, m.suggested_topup_paise))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-500">Ledger</h2>
          <select
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            {months.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>

        {ledgerQuery.loading && <p className="mt-3 text-sm text-slate-500">Loading…</p>}
        {ledgerQuery.error && <p className="mt-3 text-sm text-rose-600">{ledgerQuery.error.message}</p>}

        {ledgerQuery.data && (
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="pb-2 font-normal">When</th>
                <th className="pb-2 font-normal">Wallet</th>
                <th className="pb-2 font-normal">Kind</th>
                <th className="pb-2 font-normal">Who</th>
                <th className="pb-2 font-normal text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {ledgerQuery.data.entries.map((e) => (
                <tr key={e.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-2 text-slate-500">{new Date(e.at).toLocaleString("en-IN")}</td>
                  <td className="py-2 capitalize">{e.wallet}</td>
                  <td className="py-2">{e.kind.replace(/_/g, " ")}</td>
                  <td className="py-2">{e.who ?? "—"}</td>
                  <td className={`py-2 text-right font-medium ${e.direction === "credit" ? "text-emerald-600" : "text-rose-600"}`}>
                    {e.direction === "credit" ? "+" : "-"}
                    {inr(e.amount_paise)}
                  </td>
                </tr>
              ))}
              {ledgerQuery.data.entries.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-4 text-center text-slate-400">
                    No transactions this month.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </section>

      {modalOpen && (
        <PaymentModal
          token={token}
          householdId={me.household_id}
          onClose={() => setModalOpen(false)}
          onPaid={onPaid}
        />
      )}
    </div>
  );
}
