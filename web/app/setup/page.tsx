"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, createHousehold } from "@/lib/api";
import { rememberToken } from "@/lib/session";

export default function SetupPage() {
  const router = useRouter();
  const [householdName, setHouseholdName] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [ownerPhone, setOwnerPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await createHousehold(householdName, ownerName, ownerPhone);
      rememberToken(res.token);
      router.push(`/h/${res.token}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center bg-slate-50 px-4 py-12 dark:bg-slate-950">
      <form
        onSubmit={submit}
        className="w-full max-w-md space-y-4 rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900"
      >
        <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Set up your household</h1>
        <div>
          <label className="block text-sm font-medium text-slate-600 dark:text-slate-400">Household name</label>
          <input
            value={householdName}
            onChange={(e) => setHouseholdName(e.target.value)}
            placeholder="HSR Flat 302"
            required
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-600 dark:text-slate-400">Your name (owner)</label>
          <input
            value={ownerName}
            onChange={(e) => setOwnerName(e.target.value)}
            required
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-600 dark:text-slate-400">Your phone</label>
          <input
            value={ownerPhone}
            onChange={(e) => setOwnerPhone(e.target.value)}
            required
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </div>
        {error && <p className="text-sm text-rose-600">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-emerald-600 py-2.5 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {submitting ? "Creating…" : "Create household"}
        </button>
        <p className="text-xs text-slate-400">
          You can add helpers and roommates from the dashboard once your household is created.
        </p>
      </form>
    </div>
  );
}
