"use client";

import { useMeContext } from "@/lib/MeContext";
import { useApi } from "@/lib/useApi";
import { castVote, dashboard } from "@/lib/api";
import { inr } from "@/lib/money";

export default function VotesPage() {
  const { me, token } = useMeContext();
  const { data, loading, error, reload } = useApi(() => dashboard(token, me.household_id), [token, me.household_id]);

  async function vote(requestId: string, decision: "approve" | "reject") {
    await castVote(token, requestId, decision);
    reload();
  }

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-rose-600">{error.message}</p>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Open votes</h1>
      {data.open_votes.length === 0 && <p className="text-sm text-slate-500">Nothing needs a vote right now.</p>}
      {data.open_votes.map((v) => (
        <div
          key={v.request_id}
          className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="flex items-center justify-between">
            <p className="font-medium text-slate-900 dark:text-slate-50">
              {v.helper_name} — {v.kind.replace(/_/g, " ")} {v.amount_paise > 0 && `(${inr(v.amount_paise)})`}
            </p>
            {v.overdue && <span className="text-xs font-medium text-rose-600">overdue</span>}
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{v.context}</p>
          <p className="mt-1 text-xs text-slate-400">
            {v.votes.length} of {v.votes_needed} needed ·{" "}
            {v.votes.map((vt) => `${vt.name}: ${vt.decision}`).join(", ") || "no votes yet"}
          </p>
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
  );
}
