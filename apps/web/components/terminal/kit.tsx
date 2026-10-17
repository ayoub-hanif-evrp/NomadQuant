"use client";

import {
  useEffect,
  useRef,
  type ForwardRefExoticComponent,
  type HTMLAttributes,
  type ReactNode,
  type RefAttributes,
} from "react";
import { cn } from "@/lib/cn";

export type AnimatedHandle = { startAnimation: () => void; stopAnimation: () => void };

export type AnimatedIconComponent = ForwardRefExoticComponent<
  HTMLAttributes<HTMLDivElement> & { size?: number } & RefAttributes<AnimatedHandle>
>;

/**
 * Loops while `active` is true. Otherwise plays on hover, and once on mount when `intro` is set.
 * `active` must reflect real work, never a timer.
 */
export function AnimatedIcon({
  icon: Icon,
  active = false,
  intro = false,
  size = 24,
  className,
}: {
  icon: AnimatedIconComponent;
  active?: boolean;
  intro?: boolean;
  size?: number;
  className?: string;
}) {
  const ref = useRef<AnimatedHandle>(null);

  useEffect(() => {
    const handle = ref.current;
    if (!handle) {
      return;
    }
    if (!active) {
      handle.stopAnimation();
      return;
    }
    handle.startAnimation();
    const timer = window.setInterval(() => handle.startAnimation(), 1800);
    return () => window.clearInterval(timer);
  }, [active]);

  useEffect(() => {
    if (!intro) {
      return;
    }
    const handle = ref.current;
    handle?.startAnimation();
    const timer = window.setTimeout(() => handle?.stopAnimation(), 1400);
    return () => window.clearTimeout(timer);
  }, [intro]);

  return (
    <Icon
      ref={ref}
      size={size}
      className={cn("inline-flex items-center justify-center", className)}
      onMouseEnter={() => ref.current?.startAnimation()}
      onMouseLeave={() => {
        if (!active) {
          ref.current?.stopAnimation();
        }
      }}
    />
  );
}

export function formatUsd(value: number | string | null | undefined): string {
  const number = typeof value === "string" ? Number(value) : value;
  if (number === null || number === undefined || !Number.isFinite(number)) {
    return "—";
  }
  return number.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function formatDay(value: string | null | undefined, withWeekday = true): string {
  if (!value) {
    return "unknown";
  }
  const date = new Date(`${value.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("en-US", {
    weekday: withWeekday ? "short" : undefined,
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatNewYork(value: string | null | undefined): string {
  if (!value) {
    return "unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${date.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  })} New York`;
}

export function timeAgo(value: string | null | undefined, now = Date.now()): string {
  if (!value) {
    return "";
  }
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) {
    return "";
  }
  const minutes = Math.max(0, Math.round((now - then) / 60000));
  if (minutes < 1) {
    return "just now";
  }
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours} h ago`;
  }
  return `${Math.round(hours / 24)} days ago`;
}

export function Pill({
  tone,
  children,
  pulse = false,
}: {
  tone: "gold" | "ok" | "warn" | "err" | "muted" | "info";
  children: ReactNode;
  pulse?: boolean;
}) {
  const color = {
    gold: "border-[rgba(224,184,79,0.45)] bg-[rgba(224,184,79,0.1)] text-[var(--gold-soft)]",
    ok: "border-[rgba(230,207,139,0.4)] bg-[rgba(230,207,139,0.08)] text-[var(--ok)]",
    warn: "border-[rgba(240,154,74,0.45)] bg-[rgba(240,154,74,0.1)] text-[var(--warn)]",
    err: "border-[rgba(224,122,106,0.45)] bg-[rgba(224,122,106,0.1)] text-[var(--err)]",
    muted: "border-[var(--line)] bg-[rgba(255,255,255,0.03)] text-[var(--muted)]",
    info: "border-[rgba(159,179,200,0.4)] bg-[rgba(159,179,200,0.08)] text-[var(--info)]",
  }[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide",
        color,
      )}
    >
      {pulse ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}
