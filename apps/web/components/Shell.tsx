"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/activity", label: "Activity" },
  { href: "/runs", label: "Runs" },
  { href: "/market-data", label: "Market Data" },
  { href: "/decisions", label: "Decisions" },
  { href: "/agents", label: "Agents" },
  { href: "/research", label: "Research Lab" },
  { href: "/strategies", label: "Strategies" },
  { href: "/health", label: "Health" },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState("");

  function search(event: FormEvent) {
    event.preventDefault();
    const value = query.trim();
    router.push(value ? `/activity?q=${encodeURIComponent(value)}` : "/activity");
  }

  return (
    <div className="min-h-screen md:grid md:grid-cols-[248px_1fr]">
      <aside className="border-b border-[var(--line)] bg-[rgba(8,16,20,0.92)] px-5 py-6 md:border-r md:border-b-0">
        <p className="text-lg font-semibold tracking-tight">NomadQuant</p>
        <p className="mt-1 text-xs text-[var(--muted)]">Local research console</p>
        <p className="mt-4 inline-flex rounded-full border border-[rgba(240,195,108,0.35)] bg-[rgba(240,195,108,0.08)] px-2.5 py-1 text-xs font-semibold tracking-wide text-[var(--warn)]">
          PAPER ONLY
        </p>
        <nav className="mt-8 flex gap-2 overflow-x-auto md:flex-col">
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded-xl px-3 py-2 text-sm ${
                  active
                    ? "bg-[rgba(103,240,224,0.12)] text-[var(--cyan)] shadow-[0_0_24px_rgba(103,240,224,0.08)]"
                    : "text-[var(--muted)] hover:bg-[rgba(255,255,255,0.04)]"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-5 py-4 md:px-8">
          <p className="text-xs tracking-wide text-[var(--muted)]">
            127.0.0.1 · order submission disabled · $100 internal limit
          </p>
          <form onSubmit={search} className="flex gap-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search activity"
              className="w-52 rounded-xl border border-[var(--line)] bg-[rgba(0,0,0,0.25)] px-3 py-2 text-sm outline-none placeholder:text-[var(--muted)]"
            />
            <button
              type="submit"
              className="rounded-xl border border-[rgba(103,240,224,0.3)] px-3 py-2 text-sm text-[var(--cyan)]"
            >
              Search
            </button>
          </form>
        </header>
        <main className="px-5 py-8 md:px-8">{children}</main>
      </div>
    </div>
  );
}
