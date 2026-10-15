import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function DataTableShell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("panel overflow-hidden", className)}>
      <div className="overflow-x-auto">{children}</div>
    </div>
  );
}

export function DataTable({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <table className={cn("w-full min-w-[640px] border-collapse text-left text-xs", className)}>
      {children}
    </table>
  );
}

export function DataTableHead({ children }: { children: ReactNode }) {
  return (
    <thead className="border-b border-[var(--line)] bg-[rgba(0,0,0,0.22)] text-[var(--muted)]">
      {children}
    </thead>
  );
}

export function DataTableBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-[var(--line)]">{children}</tbody>;
}

export function DataTableRow({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <tr className={cn("transition-colors hover:bg-[rgba(255,255,255,0.02)]", className)}>{children}</tr>
  );
}

export function DataTableHeaderCell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <th
      scope="col"
      className={cn("kicker px-3 py-2.5 font-semibold first:pl-4 last:pr-4", className)}
    >
      {children}
    </th>
  );
}

export function DataTableCell({
  children,
  className,
  mono,
}: {
  children: ReactNode;
  className?: string;
  mono?: boolean;
}) {
  return (
    <td
      className={cn(
        "px-3 py-2.5 text-[var(--ink)] first:pl-4 last:pr-4",
        mono && "font-mono text-[11px]",
        className,
      )}
    >
      {children}
    </td>
  );
}
