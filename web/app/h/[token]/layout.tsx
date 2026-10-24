"use client";

import Link from "next/link";
import { usePathname, useParams } from "next/navigation";
import { useMe } from "@/lib/session";
import { MeProvider } from "@/lib/MeContext";

function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
        active
          ? "bg-emerald-600 text-white"
          : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
      }`}
    >
      {label}
    </Link>
  );
}

export default function FlatLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const pathname = usePathname();
  const { me, loading, error } = useMe(token);

  const tabs = [
    { href: `/h/${token}`, label: "Dashboard" },
    { href: `/h/${token}/payments`, label: "Payments" },
    { href: `/h/${token}/votes`, label: "Votes" },
    { href: `/h/${token}/audit`, label: "Audit" },
  ];

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-lg font-semibold text-emerald-700 dark:text-emerald-400">
              Roz Roz
            </Link>
            {me && (
              <span className="text-sm text-slate-500 dark:text-slate-400">
                {me.flats.find((f) => f.current)?.household_name ?? "your flat"} · {me.name} ({me.role})
              </span>
            )}
          </div>
          <nav className="flex flex-wrap gap-1">
            {tabs.map((t) => (
              <NavLink key={t.href} href={t.href} label={t.label} active={pathname === t.href} />
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6">
        {loading && <p className="text-sm text-slate-500">Loading your flat…</p>}
        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
            <p className="font-medium">Couldn&apos;t open this link ({error.code}).</p>
            <p className="mt-1">{error.message}</p>
            <p className="mt-2">
              <Link href="/" className="underline">
                Back to the Roz Roz home page
              </Link>
            </p>
          </div>
        )}
        {me && !error && <MeProvider value={{ me, token }}>{children}</MeProvider>}
      </main>
    </div>
  );
}
