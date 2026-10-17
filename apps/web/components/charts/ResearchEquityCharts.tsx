"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ResearchEquityPoint, ResearchSimulatedTrade } from "@/lib/api";

const STRATEGY_COLORS: Record<string, string> = {
  spy_tsmom_12_1: "#e8c766",
  spy_buy_hold: "#f09a4a",
  cash: "#a39a87",
  tsmom_6m: "#c79a6b",
};

function colorFor(id: string, index: number): string {
  return STRATEGY_COLORS[id] ?? ["#e8c766", "#f09a4a", "#e6cf8b", "#9a917f", "#f0a3a3"][index % 5];
}

function alignEquity(
  points: ResearchEquityPoint[],
  windowFilter: string | "all",
  strategies: string[],
): Array<Record<string, string | number | null>> {
  const byDate = new Map<string, Record<string, string | number | null>>();
  for (const point of points) {
    if (windowFilter !== "all" && point.window !== windowFilter) {
      continue;
    }
    if (!strategies.includes(point.strategy_id)) {
      continue;
    }
    const row = byDate.get(point.session_date) ?? { session_date: point.session_date };
    row[point.strategy_id] = Number(point.equity);
    row[`${point.strategy_id}__dd`] = Number(point.drawdown);
    row[`${point.strategy_id}__cash`] = Number(point.cash);
    row[`${point.strategy_id}__exposure`] = Number(point.exposure);
    byDate.set(point.session_date, row);
  }
  return [...byDate.values()].sort((a, b) =>
    String(a.session_date).localeCompare(String(b.session_date)),
  );
}

export function ResearchEquityChart({
  points,
  windowFilter,
  visibleStrategies,
  trades,
  primaryStrategy,
}: {
  points: ResearchEquityPoint[];
  windowFilter: string | "all";
  visibleStrategies: string[];
  trades: ResearchSimulatedTrade[];
  primaryStrategy: string;
}) {
  const data = useMemo(
    () => alignEquity(points, windowFilter, visibleStrategies),
    [points, windowFilter, visibleStrategies],
  );
  const tradeDates = useMemo(() => {
    const set = new Set(
      trades.filter((trade) => trade.strategy_id === primaryStrategy).map((t) => t.session_date),
    );
    return set;
  }, [trades, primaryStrategy]);

  if (data.length < 2) {
    return <p className="text-sm text-[var(--muted)]">Not enough equity points for this window.</p>;
  }

  return (
    <div className="h-[360px] w-full" role="img" aria-label="Equity comparison chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="rgba(224,184,79,0.08)" />
          <XAxis dataKey="session_date" tick={{ fill: "#a39a87", fontSize: 11 }} minTickGap={40} />
          <YAxis tick={{ fill: "#a39a87", fontSize: 11 }} width={56} domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{
              background: "#0e0c09",
              border: "1px solid rgba(224,184,79,0.2)",
              borderRadius: 12,
            }}
            labelStyle={{ color: "#f3ede0" }}
          />
          <Legend />
          {visibleStrategies.map((id, index) => (
            <Line
              key={id}
              type="monotone"
              dataKey={id}
              name={id}
              stroke={colorFor(id, index)}
              dot={(props) => {
                const date = String(props.payload?.session_date ?? "");
                if (id === primaryStrategy && tradeDates.has(date)) {
                  return (
                    <circle
                      cx={props.cx}
                      cy={props.cy}
                      r={3.5}
                      fill={colorFor(id, index)}
                      stroke="#080706"
                    />
                  );
                }
                return <g />;
              }}
              strokeWidth={2}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ResearchDrawdownChart({
  points,
  windowFilter,
  strategies,
}: {
  points: ResearchEquityPoint[];
  windowFilter: string | "all";
  strategies: string[];
}) {
  const data = useMemo(
    () =>
      alignEquity(points, windowFilter, strategies).map((row) => {
        const next: Record<string, string | number | null> = { session_date: row.session_date };
        for (const id of strategies) {
          const value = row[`${id}__dd`];
          next[id] = typeof value === "number" ? value * 100 : null;
        }
        return next;
      }),
    [points, windowFilter, strategies],
  );

  if (data.length < 2) {
    return <p className="text-sm text-[var(--muted)]">Drawdown series unavailable for this window.</p>;
  }

  return (
    <div className="h-[260px] w-full" role="img" aria-label="Drawdown chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="rgba(224,184,79,0.08)" />
          <XAxis dataKey="session_date" tick={{ fill: "#a39a87", fontSize: 11 }} minTickGap={40} />
          <YAxis
            tick={{ fill: "#a39a87", fontSize: 11 }}
            width={48}
            tickFormatter={(value: number) => `${value.toFixed(0)}%`}
            label={{
              value: "Drawdown % (negative = underwater)",
              angle: -90,
              position: "insideLeft",
              fill: "#a39a87",
              fontSize: 10,
            }}
          />
          <Tooltip
            contentStyle={{
              background: "#0e0c09",
              border: "1px solid rgba(224,184,79,0.2)",
              borderRadius: 12,
            }}
            formatter={(value) => [`${Number(value).toFixed(2)}%`, "Drawdown"]}
          />
          <Legend />
          {strategies.map((id, index) => (
            <Area
              key={id}
              type="monotone"
              dataKey={id}
              name={id}
              stroke={colorFor(id, index)}
              fill={colorFor(id, index)}
              fillOpacity={0.15}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      <p className="mt-1 text-[11px] text-[var(--muted)]">
        Drawdown is stored as a non-positive fraction of peak equity; chart shows percent (e.g. −20 =
        20% underwater).
      </p>
    </div>
  );
}

export function ResearchExposureChart({
  points,
  windowFilter,
  strategyId,
}: {
  points: ResearchEquityPoint[];
  windowFilter: string | "all";
  strategyId: string;
}) {
  const data = useMemo(
    () =>
      alignEquity(points, windowFilter, [strategyId]).map((row) => {
        const exposure = row[`${strategyId}__exposure`];
        return {
          session_date: row.session_date,
          cash_usd: row[`${strategyId}__cash`] ?? null,
          exposure_pct: typeof exposure === "number" ? exposure * 100 : null,
        };
      }),
    [points, windowFilter, strategyId],
  );

  if (data.length < 2) {
    return <p className="text-sm text-[var(--muted)]">Exposure series unavailable.</p>;
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="h-[240px] w-full" role="img" aria-label="Simulated cash USD">
        <p className="mb-1 text-[11px] text-[var(--muted)]">Cash (USD)</p>
        <ResponsiveContainer width="100%" height="90%">
          <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="rgba(224,184,79,0.08)" />
            <XAxis dataKey="session_date" tick={{ fill: "#a39a87", fontSize: 11 }} minTickGap={40} />
            <YAxis
              tick={{ fill: "#a39a87", fontSize: 11 }}
              width={56}
              tickFormatter={(value: number) => `$${value.toFixed(0)}`}
            />
            <Tooltip
              contentStyle={{
                background: "#0e0c09",
                border: "1px solid rgba(224,184,79,0.2)",
                borderRadius: 12,
              }}
              formatter={(value) => [`$${Number(value).toFixed(2)}`, "Cash (USD)"]}
            />
            <Area
              type="monotone"
              dataKey="cash_usd"
              name="Cash (USD)"
              stroke="#a39a87"
              fill="#a39a87"
              fillOpacity={0.2}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="h-[240px] w-full" role="img" aria-label="Simulated exposure percent">
        <p className="mb-1 text-[11px] text-[var(--muted)]">Exposure (% of equity, 0–100)</p>
        <ResponsiveContainer width="100%" height="90%">
          <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="rgba(224,184,79,0.08)" />
            <XAxis dataKey="session_date" tick={{ fill: "#a39a87", fontSize: 11 }} minTickGap={40} />
            <YAxis
              tick={{ fill: "#a39a87", fontSize: 11 }}
              width={48}
              domain={[0, 100]}
              tickFormatter={(value: number) => `${value}%`}
            />
            <Tooltip
              contentStyle={{
                background: "#0e0c09",
                border: "1px solid rgba(224,184,79,0.2)",
                borderRadius: 12,
              }}
              formatter={(value) => [`${Number(value).toFixed(1)}%`, "Exposure"]}
            />
            <Area
              type="monotone"
              dataKey="exposure_pct"
              name="Exposure %"
              stroke="#e8c766"
              fill="#e8c766"
              fillOpacity={0.2}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
