"use client";

import { useState } from "react";
import { ApiError, topup } from "@/lib/api";
import { inr, paiseFromRupeeInput } from "@/lib/money";

type Step = "form" | "processing" | "success";
type Method = "upi" | "card" | "netbanking";

const METHODS: { id: Method; label: string }[] = [
  { id: "upi", label: "UPI" },
  { id: "card", label: "Card" },
  { id: "netbanking", label: "Netbanking" },
];

const QUICK_AMOUNTS = [500, 1000, 2000, 5000];

export function PaymentModal({
  token,
  householdId,
  onClose,
  onPaid,
}: {
  token: string;
  householdId: string;
  onClose: () => void;
  onPaid: () => void;
}) {
  const [step, setStep] = useState<Step>("form");
  const [amount, setAmount] = useState("1000");
  const [method, setMethod] = useState<Method>("upi");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ ledgerEntryId: string; balancePaise: number } | null>(null);

  const amountPaise = paiseFromRupeeInput(amount);

  async function pay() {
    if (amountPaise <= 0) {
      setError("Enter an amount greater than zero.");
      return;
    }
    setError(null);
    setStep("processing");

    // Purely cosmetic delay so the mock payment flow reads like a real gateway;
    // the actual money movement is the topup() call below, nothing here is simulated client-side.
    await new Promise((resolve) => setTimeout(resolve, 900));

    try {
      const res = await topup(token, householdId, amountPaise);
      setResult({ ledgerEntryId: res.ledger_entry_id, balancePaise: res.house_balance_paise });
      setStep("success");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setStep("form");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900">
        {step === "form" && (
          <>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Top up house wallet</h2>
              <button onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Close">
                ✕
              </button>
            </div>
            <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
              Mock payment — this is a simulated gateway, no real money moves.
            </p>

            <label className="mt-4 block text-sm font-medium text-slate-600 dark:text-slate-400">Amount (₹)</label>
            <input
              type="number"
              min={1}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-lg dark:border-slate-700 dark:bg-slate-800"
            />
            <div className="mt-2 flex gap-2">
              {QUICK_AMOUNTS.map((a) => (
                <button
                  key={a}
                  onClick={() => setAmount(String(a))}
                  className="rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  ₹{a}
                </button>
              ))}
            </div>

            <label className="mt-4 block text-sm font-medium text-slate-600 dark:text-slate-400">
              Payment method
            </label>
            <div className="mt-1 grid grid-cols-3 gap-2">
              {METHODS.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setMethod(m.id)}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium ${
                    method === m.id
                      ? "border-emerald-600 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                      : "border-slate-300 text-slate-600 dark:border-slate-700 dark:text-slate-300"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}

            <button
              onClick={pay}
              className="mt-5 w-full rounded-lg bg-emerald-600 py-2.5 font-medium text-white hover:bg-emerald-700"
            >
              Pay {amountPaise > 0 ? inr(amountPaise) : ""}
            </button>
          </>
        )}

        {step === "processing" && (
          <div className="flex flex-col items-center justify-center py-8">
            <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-emerald-600" />
            <p className="mt-4 text-sm text-slate-500">Processing your {method.toUpperCase()} payment…</p>
          </div>
        )}

        {step === "success" && result && (
          <div className="py-2 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-2xl text-emerald-700 dark:bg-emerald-900/40">
              ✓
            </div>
            <h2 className="mt-3 text-lg font-semibold text-slate-900 dark:text-slate-50">Payment successful</h2>
            <p className="mt-1 text-sm text-slate-500">{inr(amountPaise)} added to the house wallet.</p>
            <dl className="mt-4 space-y-1 rounded-lg bg-slate-50 p-3 text-left text-xs text-slate-500 dark:bg-slate-800">
              <div className="flex justify-between">
                <dt>Transaction</dt>
                <dd className="font-mono">{result.ledgerEntryId.slice(0, 8)}…</dd>
              </div>
              <div className="flex justify-between">
                <dt>New house balance</dt>
                <dd>{inr(result.balancePaise)}</dd>
              </div>
            </dl>
            <button
              onClick={onPaid}
              className="mt-5 w-full rounded-lg bg-slate-900 py-2.5 font-medium text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
