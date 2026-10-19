"use client";

import { useEffect, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CrewAvatar } from "@/components/avatars/CrewAvatar";
import { runLab, type LabSession } from "@/lib/api";

const CHOICES = [
  ["replay_3m", "Last 3 months"],
  ["replay_12m", "Last 12 months"],
  ["replay_3y", "Last 3 years"],
  ["replay_full", "Full history"],
  ["mechanics", "BUY / HOLD / SELL"],
  ["crash_stress", "Crash and recovery"],
  ["observed_quote", "Quote readiness"],
] as const;

const SPEEDS = [1, 10, 100] as const;

export function SimulationLab() {
  const [scenario, setScenario] = useState<(typeof CHOICES)[number][0]>("replay_3y");
  const [session, setSession] = useState<LabSession | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(10);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!playing || !session) {
      return;
    }
    const timer = window.setInterval(() => {
      setIndex((current) => {
        if (current >= session.events.length - 1) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, speed === 1 ? 900 : speed === 10 ? 120 : 30);
    return () => window.clearInterval(timer);
  }, [playing, session, speed]);

  const event = session?.events[index];
  const cutoff = session ? throughOrEnd(session, index) : "";
  const marked = (session?.equity_curve ?? [])
    .filter((point) => point.status === "ok" && point.equity != null && point.session <= cutoff)
    .map((point) => ({ at: point.session, equity: Number(point.equity) }));
  const chart = marked.length
    ? marked
    : (session?.events.slice(0, index + 1) ?? []).map((item, position) => ({
        at: item.session ?? String(position),
        equity: Number(item.equity_usd),
      }));
  const through = event?.session ?? "";
  const market =
    session && through
      ? session.bars
          .filter((bar) => bar.session <= through)
          .map((bar) => ({ at: bar.session, close: Number(bar.close) }))
      : [];

  async function start() {
    setBusy(true);
    setError("");
    setPlaying(false);
    try {
      const result = await runLab(scenario);
      setSession(result);
      setIndex(0);
      setPlaying(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The simulation did not start.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="kicker">Simulation Lab</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Run $100 Simulation</h1>
          <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
            An isolated experiment. It does not touch the forward $100 book or send an Alpaca order.
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void start()}
          className="rounded-full bg-[var(--gold)] px-4 py-2 text-sm font-semibold text-[#140e02] disabled:opacity-60"
        >
          {busy ? "Running…" : "Run $100 Simulation"}
        </button>
      </header>

      <div className="flex flex-wrap gap-2">
        {CHOICES.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setScenario(id)}
            className={
              scenario === id
                ? "rounded-full bg-[var(--gold)] px-3 py-1 text-sm font-semibold text-[#140e02]"
                : "rounded-full border border-[var(--line)] px-3 py-1 text-sm text-[var(--muted)]"
            }
          >
            {label}
          </button>
        ))}
      </div>

      {error ? <p className="text-sm text-[var(--err)]">{error}</p> : null}

      {session && event ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full border border-[var(--gold)] px-3 py-1 text-xs tracking-wide text-[var(--gold)]">
              {event.label}
            </span>
            <span className="font-mono text-sm text-[var(--muted)]">{event.session ?? "fixture"}</span>
            <button type="button" className="ghost-button px-3 py-1 text-xs" onClick={() => setPlaying((value) => !value)}>
              {playing ? "Pause" : "Resume"}
            </button>
            <button
              type="button"
              className="ghost-button px-3 py-1 text-xs"
              onClick={() => {
                setIndex(0);
                setPlaying(true);
              }}
            >
              Restart
            </button>
            {SPEEDS.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setSpeed(item)}
                className={
                  speed === item
                    ? "rounded-full bg-[var(--gold)] px-2 py-1 text-xs font-semibold text-[#140e02]"
                    : "rounded-full border border-[var(--line)] px-2 py-1 text-xs"
                }
              >
                {item}×
              </button>
            ))}
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <Stat label="Starting" value="$100.00" />
            <Stat label="Cash now" value={money(event.cash_usd)} />
            <Stat label="Equity now" value={money(event.equity_usd)} />
            <Stat label="Decision" value={event.decision} />
          </div>

          <section className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
            <article className="panel p-4">
              <p className="kicker">Market through this date</p>
              <div className="h-56">
                {market.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={market}>
                      <XAxis dataKey="at" hide />
                      <YAxis domain={["auto", "auto"]} stroke="#9a917f" width={56} />
                      <Tooltip />
                      <Area dataKey="close" stroke="#e0b84f" fill="rgba(224,184,79,0.16)" />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="py-16 text-center text-sm text-[var(--muted)]">No stored closes for this step.</p>
                )}
              </div>
            </article>
            <article className="panel p-4">
              <p className="kicker">Equity</p>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chart}>
                    <XAxis dataKey="at" hide />
                    <YAxis domain={["auto", "auto"]} stroke="#9a917f" width={56} />
                    <Tooltip />
                    <Area dataKey="equity" stroke="#7ec8a3" fill="rgba(126,200,163,0.16)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </article>
          </section>

          <section className="grid gap-3 md:grid-cols-2">
            <article className="panel p-4 text-sm">
              <p className="kicker">This step</p>
              <p className="mt-2">Momentum {event.momentum ?? "not available"}</p>
              <p>Risk Guard {event.risk_verdict ?? "not evaluated"}</p>
              <p>{event.risk_reasons[0] ?? event.note ?? "No extra risk note."}</p>
              <p>
                Execution {event.side ?? "none"} {event.quantity ?? ""} @ {event.price ?? "—"} · costs{" "}
                {event.costs_usd ?? "0"}
              </p>
              <p>Holdings {Object.entries(event.holdings).map(([symbol, qty]) => `${symbol} ${qty}`).join(", ") || "cash only"}</p>
            </article>
            <article className="panel flex items-center gap-4 p-4">
              <CrewAvatar id="risk" mood={event.risk_verdict ? "working" : "idle"} size={72} />
              <div className="text-sm">
                <p className="font-semibold">Risk Guard</p>
                <p className="text-[var(--muted)]">
                  {event.risk_verdict
                    ? "This step used the deterministic risk check."
                    : "No risk stage ran on this step."}
                </p>
                <p className="mt-2 text-[var(--muted)]">
                  Researcher, Skeptic, and Reviewer stay idle. They do not change the strategy.
                </p>
              </div>
            </article>
          </section>

          <section className="grid gap-3 md:grid-cols-4">
            <Stat label="Ending" value={money(session.ending_usd)} />
            <Stat label="Buys / sells" value={`${session.buys} / ${session.sells}`} />
            <Stat label="Costs" value={money(session.costs_usd)} />
            <Stat label="Max drawdown" value={percent(session.max_drawdown)} />
          </section>
          <p className="text-sm text-[var(--warn)]">
            {session.limitations} Realized {money(session.realized_pnl_usd)}. Unrealized{" "}
            {money(session.unrealized_pnl_usd)}. Cash comparison {money(session.comparisons.cash)}. SPY
            buy-and-hold {session.comparisons.spy_buy_hold_price_only ?? "not computed"}.{" "}
            {session.comparisons.note} {session.comparisons.policy_constrained?.note}
          </p>
          <section className="panel p-4 text-sm">
            <p className="kicker">Approval drill</p>
            <p className="mt-2">
              Delivery {session.approval.delivery ?? session.approval.status}. SMTP used:{" "}
              {String(session.approval.smtp_used ?? false)}.
            </p>
            <ul className="mt-2 space-y-1">
              {session.approval.requests.map((item, position) => (
                <li key={`${item.action}-${position}`}>
                  {item.action} → {item.result}. Fill authorized: {String(item.fill_authorized)}.
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[var(--muted)]">
              Verification {session.verification.passed} of {session.verification.checked} checked cycles passed.
              A reused approval token was blocked: {String(session.approval.token_reuse_blocked ?? false)}.
              Accounting reconciliation: {session.reconciliation?.status ?? "not recorded"}.
              An approved email does not by itself authorize a fill.
            </p>
          </section>
        </>
      ) : null}
    </div>
  );
}

function throughOrEnd(session: LabSession, index: number): string {
  return session.events[index]?.session ?? session.events.at(-1)?.session ?? "";
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <article className="panel p-4">
      <p className="kicker">{label}</p>
      <p className="mt-2 font-mono text-xl">{value}</p>
    </article>
  );
}

function money(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value;
  }
  return number.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function percent(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value;
  }
  return `${(number * 100).toFixed(2)}%`;
}
