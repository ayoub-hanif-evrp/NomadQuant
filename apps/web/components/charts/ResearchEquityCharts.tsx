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
  spy_tsmom_12_1: "#67f0e0",
  spy_buy_hold: "#f0c36c",
  cash: "#8ea3ab",
  tsmom_6m: "#9b87ff",
};

function colorFor(id: string, index: number): string {
  return STRATEGY_COLORS[id] ?? ["#67f0e0", "#f0c36c", "#7dde9e", "#93a1b5", "#f0a3a3"][index % 5];
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
          <CartesianGrid stroke="rgba(94,214,201,0.08)" />
          <XAxis dataKey="session_date" tick={{ fill: "#8ea3ab", fontSize: 11 }} minTickGap={40} />
          <YAxis tick={{ fill: "#8ea3ab", fontSize: 11 }} width={56} domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{
              background: "#0d151c",
              border: "1px solid rgba(94,214,201,0.2)",
              borderRadius: 12,
            }}
            labelStyle={{ color: "#e8f3f2" }}
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
                      stroke="#070b10"
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
          <CartesianGrid stroke="rgba(94,214,201,0.08)" />
          <XAxis dataKey="session_date" tick={{ fill: "#8ea3ab", fontSize: 11 }} minTickGap={40} />
          <YAxis
            tick={{ fill: "#8ea3ab", fontSize: 11 }}
            width={48}
            tickFormatter={(value: number) => `${value.toFixed(0)}%`}
          />
          <Tooltip
            contentStyle={{
              background: "#0d151c",
              border: "1px solid rgba(94,214,201,0.2)",
              borderRadius: 12,
            }}
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
      alignEquity(points, windowFilter, [strategyId]).map((row) => ({
        session_date: row.session_date,
        cash: row[`${strategyId}__cash`] ?? null,
        exposure: row[`${strategyId}__exposure`] ?? null,
      })),
    [points, windowFilter, strategyId],
  );

  if (data.length < 2) {
    return <p className="text-sm text-[var(--muted)]">Exposure series unavailable.</p>;
  }

  return (
    <div className="h-[240px] w-full" role="img" aria-label="Cash and exposure chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="rgba(94,214,201,0.08)" />
          <XAxis dataKey="session_date" tick={{ fill: "#8ea3ab", fontSize: 11 }} minTickGap={40} />
          <YAxis tick={{ fill: "#8ea3ab", fontSize: 11 }} width={56} />
          <Tooltip
            contentStyle={{
              background: "#0d151c",
              border: "1px solid rgba(94,214,201,0.2)",
              borderRadius: 12,
            }}
          />
          <Legend />
          <Area
            type="monotone"
            dataKey="cash"
            name="Cash"
            stroke="#8ea3ab"
            fill="#8ea3ab"
            fillOpacity={0.2}
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="exposure"
            name="Exposure"
            stroke="#67f0e0"
            fill="#67f0e0"
            fillOpacity={0.2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
