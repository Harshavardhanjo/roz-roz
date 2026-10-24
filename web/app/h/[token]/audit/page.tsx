"use client";

import { useMeContext } from "@/lib/MeContext";
import { useApi } from "@/lib/useApi";
import { auditLog } from "@/lib/api";

export default function AuditPage() {
  const { me, token } = useMeContext();
  const { data, loading, error } = useApi(() => auditLog(token, me.household_id, 100), [token, me.household_id]);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-rose-600">{error.message}</p>;

  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Audit log</h1>
      {data?.length === 0 && <p className="text-sm text-slate-500">No audit entries yet.</p>}
      {data?.map((entry, i) => (
        <div
          key={`${entry.entity_id ?? entry.entity}-${i}`}
          className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-slate-900 dark:text-slate-50">{entry.action}</span>
            <span className="text-slate-400">{new Date(entry.at).toLocaleString("en-IN")}</span>
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{entry.summary}</p>
          <p className="mt-1 text-xs text-slate-400">
            actor: {entry.actor} · entity: {entry.entity}
            {entry.rule_applied && ` · rule: ${entry.rule_applied}`}
            {entry.grantex_decision && ` · grantex: ${entry.grantex_decision}`}
          </p>
        </div>
      ))}
    </div>
  );
}
