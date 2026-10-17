"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  Bot,
  ChevronLeft,
  ChevronRight,
  Command,
  FlaskConical,
  HeartPulse,
  LayoutDashboard,
  LineChart,
  Menu,
  RefreshCw,
  Search,
  ShieldAlert,
  Workflow,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { cn } from "@/lib/cn";
import { connectionLabel, connectionState, connectionTone } from "@/lib/connection";
import { useRefreshAll, useSystemHealth } from "@/lib/hooks";
import { CopilotPanel } from "@/components/terminal/CopilotPanel";
import { Badge, StatusDot } from "@/components/ui";

type NavItem = {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  available: boolean;
};

type NavGroup = { title: string; items: NavItem[] };

const NAV: NavGroup[] = [
  {
    title: "Guided",
    items: [
      { href: "/", label: "Home", icon: LayoutDashboard, available: true },
      { href: "/decisions", label: "Intelligence", icon: Workflow, available: true },
      { href: "/agents", label: "Agents", icon: Bot, available: true },
      { href: "/market", label: "Markets", icon: LineChart, available: true },
      { href: "/portfolio", label: "Portfolio", icon: LineChart, available: true },
      { href: "/approvals", label: "Approvals", icon: ShieldAlert, available: true },
      { href: "/advanced", label: "Advanced", icon: FlaskConical, available: true },
    ],
  },
];

const WORKBENCH: NavItem[] = [
  { href: "/workbench", label: "Command Center", icon: LayoutDashboard, available: true },
  { href: "/market-data", label: "Market Explorer", icon: LineChart, available: true },
  { href: "/research", label: "Research Lab", icon: FlaskConical, available: true },
  { href: "/activity", label: "Activity", icon: Activity, available: true },
  { href: "/runs", label: "Runs & Jobs", icon: Workflow, available: true },
  { href: "/health", label: "System Health", icon: HeartPulse, available: true },
  { href: "/strategies", label: "Risk Policy Lab", icon: ShieldAlert, available: true },
  { href: "/shadow", label: "Shadow Operations", icon: Workflow, available: true },
];

const FLAT_NAV = [...NAV.flatMap((group) => group.items), ...WORKBENCH];

function pageTitle(pathname: string): string {
  if (pathname.startsWith("/approvals/respond/")) {
    return "Confirm approval";
  }
  const match = FLAT_NAV.find((item) => item.href === pathname);
  return match?.label ?? "NomadQuant";
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const health = useSystemHealth();
  const refreshAll = useRefreshAll();
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    try {
      return localStorage.getItem("nq-sidebar-collapsed") === "1";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [manualRefreshAt, setManualRefreshAt] = useState<number | null>(null);

  const lastRefreshMs = manualRefreshAt ?? health.dataUpdatedAt ?? null;
  const lastRefresh = lastRefreshMs ? new Date(lastRefreshMs) : null;

  useEffect(() => {
    try {
      localStorage.setItem("nq-sidebar-collapsed", collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
      if (event.key === "Escape") {
        setPaletteOpen(false);
        setMobileOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refreshAll();
      setManualRefreshAt(Date.now());
    } finally {
      setRefreshing(false);
    }
  }, [refreshAll]);

  const navigate = useCallback(
    (href: string) => {
      setMobileOpen(false);
      setPaletteOpen(false);
      router.push(href);
    },
    [router],
  );

  const apiState = connectionState({
    isLoading: health.isLoading,
    isError: health.isError,
    isFetching: health.isFetching,
    dataUpdatedAt: health.dataUpdatedAt,
    error: health.error,
    staleAfterMs: 60_000,
  });
  const brokerTone =
    apiState === "loading" || apiState === "disconnected"
      ? "info"
      : health.data?.broker_status === "connected"
        ? "ok"
        : health.data?.broker_status === "error"
          ? "err"
          : "warn";

  const sidebar = (
    <aside
      className={cn(
        "flex h-full flex-col border-[var(--line)] bg-[rgba(6,10,16,0.96)] transition-[width] duration-200",
        collapsed ? "w-[72px]" : "w-[248px]",
        "border-r",
      )}
    >
      <div className={cn("flex items-center gap-3 px-4 py-5", collapsed && "justify-center px-2")}>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[rgba(103,240,224,0.28)] bg-[rgba(103,240,224,0.08)] font-mono text-sm font-semibold text-[var(--cyan)]">
          NQ
        </div>
        {!collapsed ? (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold tracking-tight">NomadQuant</p>
            <p className="truncate text-[11px] text-[var(--muted)]">Research terminal</p>
          </div>
        ) : null}
      </div>
      {!collapsed ? (
        <p className="mx-4 mb-3 inline-flex w-fit rounded-full border border-[rgba(240,195,108,0.35)] bg-[rgba(240,195,108,0.08)] px-2.5 py-1 text-[10px] font-semibold tracking-wide text-[var(--warn)]">
          PAPER ONLY
        </p>
      ) : null}
      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {NAV.map((group) => (
          <div key={group.title} className="mb-4">
            {!collapsed ? (
              <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">
                {group.title}
              </p>
            ) : null}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname === item.href || pathname.startsWith(`${item.href}/`);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      title={collapsed ? item.label : undefined}
                      onClick={() => setMobileOpen(false)}
                      className={cn(
                        "group flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors",
                        active
                          ? "bg-[rgba(103,240,224,0.12)] text-[var(--cyan)]"
                          : "text-[var(--muted)] hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--ink)]",
                        !item.available && "opacity-55",
                        collapsed && "justify-center px-2",
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0" aria-hidden />
                      {!collapsed ? (
                        <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
                          <span className="truncate">{item.label}</span>
                          {!item.available ? (
                            <span className="shrink-0 text-[10px] uppercase tracking-wide text-[var(--muted)]">
                              soon
                            </span>
                          ) : null}
                        </span>
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <button
        type="button"
        className="m-3 hidden items-center justify-center gap-2 rounded-xl border border-[var(--line)] px-3 py-2 text-xs text-[var(--muted)] hover:bg-[rgba(255,255,255,0.04)] md:flex"
        onClick={() => setCollapsed((value) => !value)}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        {!collapsed ? <span>Collapse</span> : null}
      </button>
    </aside>
  );

  return (
    <div className="flex min-h-screen bg-[var(--bg)]">
      <div className="hidden md:block">{sidebar}</div>
      {mobileOpen ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/55"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
          />
          <div className="relative z-10 h-full shadow-2xl">{sidebar}</div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex flex-wrap items-center gap-3 border-b border-[var(--line)] bg-[rgba(7,11,16,0.92)] px-4 py-3 backdrop-blur-md md:px-6">
          <button
            type="button"
            className="rounded-lg border border-[var(--line)] p-2 text-[var(--muted)] md:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] uppercase tracking-[0.12em] text-[var(--muted)]">NomadQuant</p>
            <h1 className="truncate text-base font-semibold tracking-tight">{pageTitle(pathname)}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={connectionTone(apiState)}>
              <StatusDot tone={connectionTone(apiState)} />
              API {connectionLabel(apiState)}
            </Badge>
            <Badge tone={brokerTone}>
              Broker{" "}
              {apiState === "loading"
                ? "…"
                : apiState === "disconnected"
                  ? "unreachable"
                  : (health.data?.broker_status ?? "unknown")}
            </Badge>
            <Badge tone="warn">Paper · no orders</Badge>
            {lastRefresh ? (
              <span className="hidden text-[11px] text-[var(--muted)] lg:inline">
                Updated {lastRefresh.toLocaleTimeString()}
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => void onRefresh()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--line)] px-2.5 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--ink)]"
              aria-label="Refresh data"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
              Refresh
            </button>
            <button
              type="button"
              onClick={() => setCopilotOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[rgba(103,240,224,0.28)] px-2.5 py-1.5 text-xs text-[var(--cyan)]"
            >
              Copilot
            </button>
            <button
              type="button"
              onClick={() => setPaletteOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--line)] px-2.5 py-1.5 text-xs text-[var(--muted)]"
            >
              <Command className="h-3.5 w-3.5" />
              Ctrl+K
            </button>
          </div>
        </header>
        <main className="min-w-0 flex-1 px-4 py-6 md:px-6 md:py-8">{children}</main>
      </div>

      {paletteOpen ? (
        <CommandPalette onClose={() => setPaletteOpen(false)} onNavigate={navigate} />
      ) : null}
      {copilotOpen ? <CopilotPanel onClose={() => setCopilotOpen(false)} /> : null}
    </div>
  );
}

function CommandPalette({
  onClose,
  onNavigate,
}: {
  onClose: () => void;
  onNavigate: (href: string) => void;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return FLAT_NAV;
    }
    return FLAT_NAV.filter(
      (item) => item.label.toLowerCase().includes(q) || item.href.toLowerCase().includes(q),
    );
  }, [query]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const first = filtered[0];
    if (first) {
      onNavigate(first.href);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/55 px-4 pt-[12vh]">
      <button type="button" className="absolute inset-0" aria-label="Close command palette" onClick={onClose} />
      <div className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--bg-2)] shadow-2xl">
        <form onSubmit={submit} className="flex items-center gap-2 border-b border-[var(--line)] px-4 py-3">
          <Search className="h-4 w-4 text-[var(--muted)]" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Go to page…"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--muted)]"
          />
          <button type="button" onClick={onClose} className="text-[var(--muted)]" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </form>
        <ul className="max-h-80 overflow-y-auto p-2">
          {filtered.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <button
                  type="button"
                  className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-[rgba(103,240,224,0.08)]"
                  onClick={() => onNavigate(item.href)}
                >
                  <Icon className="h-4 w-4 text-[var(--cyan)]" />
                  <span className="flex-1">{item.label}</span>
                  {!item.available ? (
                    <span className="text-[10px] uppercase text-[var(--muted)]">not configured</span>
                  ) : (
                    <span className="font-mono text-[11px] text-[var(--muted)]">{item.href}</span>
                  )}
                </button>
              </li>
            );
          })}
          {filtered.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-[var(--muted)]">No matching routes</li>
          ) : null}
        </ul>
      </div>
    </div>
  );
}
