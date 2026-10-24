"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, createSignup } from "@/lib/api";
import { getLastToken, rememberToken } from "@/lib/session";
import type { ResetDemoResponse } from "@/lib/types";

export default function LandingPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [signedUp, setSignedUp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const last = getLastToken();
    if (last) setToken(last);
  }, []);

  async function submitSignup(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createSignup(name, phone, "landing");
      setSignedUp(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  function openFlat(e: React.FormEvent) {
    e.preventDefault();
    if (token.trim()) router.push(`/h/${token.trim()}`);
  }

  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  async function resetDemo() {
    setResetting(true);
    setResetError(null);
    try {
      const res = await fetch("/api/admin/reset-demo", { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? "Reset failed");
      const demo = body as ResetDemoResponse;
      rememberToken(demo.owner.token);
      router.push(`/h/${demo.owner.token}`);
    } catch (err) {
      setResetError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center bg-slate-50 px-4 py-12 dark:bg-slate-950">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <h1 className="text-3xl font-semibold text-emerald-700 dark:text-emerald-400">Roz Roz</h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Household employee management for shared flats. Helpers send WhatsApp voice notes — leave, advances,
            groceries — and the household handles the rest. All payments in this demo are simulated.
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-sm font-medium text-slate-500">Open your flat</h2>
          <form onSubmit={openFlat} className="mt-2 flex gap-2">
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Paste your magic link token"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
            />
            <button type="submit" className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700">
              Open
            </button>
          </form>
          <p className="mt-2 text-xs text-slate-400">
            No flat yet?{" "}
            <a href="/setup" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
              Set one up
            </a>{" "}
            or{" "}
            <button
              onClick={resetDemo}
              disabled={resetting}
              className="font-medium text-emerald-700 hover:underline disabled:opacity-50 dark:text-emerald-400"
            >
              {resetting ? "loading demo…" : "load the demo flat"}
            </button>
            .
          </p>
          {resetError && <p className="mt-1 text-xs text-rose-600">{resetError}</p>}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-sm font-medium text-slate-500">Get notified</h2>
          {signedUp ? (
            <p className="mt-2 text-sm text-emerald-700 dark:text-emerald-400">Thanks — you&apos;re on the list!</p>
          ) : (
            <form onSubmit={submitSignup} className="mt-2 space-y-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Name"
                required
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              />
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="Phone"
                required
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              />
              {error && <p className="text-sm text-rose-600">{error}</p>}
              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded-lg bg-slate-900 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
              >
                {submitting ? "Signing up…" : "Sign up"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
