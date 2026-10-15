"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/research", label: "Research" },
  { href: "/agents", label: "Agents" },
  { href: "/strategies", label: "Strategies" },
  { href: "/activity", label: "Activity" },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className="border-b border-[#2a3646] bg-[#11161d] px-5 py-6 md:border-r md:border-b-0">
        <p className="text-lg font-semibold tracking-tight">NomadQuant</p>
        <p className="mt-3 inline-flex rounded-md bg-[#3a2a10] px-2.5 py-1 text-xs font-semibold tracking-wide text-[#f5c16c]">
          PAPER ONLY
        </p>
        <nav className="mt-8 flex gap-2 overflow-x-auto md:flex-col">
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded-md px-3 py-2 text-sm ${
                  active ? "bg-[#1d2733] text-white" : "text-[#93a1b5] hover:bg-[#1a222c]"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="px-5 py-8 md:px-10">{children}</main>
    </div>
  );
}
