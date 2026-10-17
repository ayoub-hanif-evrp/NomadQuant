"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className,
  "aria-label": ariaLabel,
}: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex rounded-[var(--radius)] border border-[var(--line)] bg-[rgba(0,0,0,0.2)] p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-[10px] px-3 py-1.5 text-xs font-medium transition-colors",
              active
                ? "bg-[rgba(224,184,79,0.12)] text-[var(--cyan)]"
                : "text-[var(--muted)] hover:text-[var(--ink)]",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Tabs({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: Array<{ id: string; label: string; panel: ReactNode }>;
  active: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];

  return (
    <div className={className}>
      <div
        role="tablist"
        className="flex flex-wrap gap-1 border-b border-[var(--line)] pb-2"
      >
        {tabs.map((tab) => {
          const selected = tab.id === active;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => onChange(tab.id)}
              className={cn(
                "rounded-[var(--radius)] px-3 py-1.5 text-xs font-medium",
                selected
                  ? "bg-[rgba(224,184,79,0.1)] text-[var(--cyan)]"
                  : "text-[var(--muted)] hover:bg-[rgba(255,255,255,0.03)] hover:text-[var(--ink)]",
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="pt-4">
        {current?.panel}
      </div>
    </div>
  );
}
