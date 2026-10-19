"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import {
  Badge,
  EmptyState,
  ErrorState,
  PageIntro,
  Panel,
  ProvenanceChip,
  SegmentedControl,
  Skeleton,
} from "@/components/ui";
import { useMarketBarsQuery, useMarketStatus } from "@/lib/hooks";

const MarketCandleChart = dynamic(
  () => import("@/components/charts/MarketCandleChart").then((mod) => mod.MarketCandleChart),
  {
    ssr: false,
    loading: () => <Skeleton className="h-[420px] w-full" />,
  },
);

type RangeKey = "3M" | "6M" | "1Y" | "ALL";
type FeedKey = "sip" | "iex";

function shiftMonths(iso: string, months: number): string {
  const date = new Date(`${iso}T12:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + months);
  return date.toISOString().slice(0, 10);
}

export function MarketData() {
  const statusQuery = useMarketStatus();
  const [symbol, setSymbol] = useState<"SPY" | "QQQ">("SPY");
  const [range, setRange] = useState<RangeKey>("1Y");
  const [mode, setMode] = useState<"candle" | "line">("candle");
  const [feed, setFeed] = useState<FeedKey>("sip");

  const availableFeeds = useMemo(() => {
    const rows = statusQuery.data?.coverage.filter((item) => item.symbol === symbol) ?? [];
    const feeds = [...new Set(rows.map((row) => row.feed))].filter(
      (item): item is FeedKey => item === "sip" || item === "iex",
    );
    return feeds;
  }, [statusQuery.data, symbol]);

  const activeFeed: FeedKey | null =
    availableFeeds.length === 0
      ? null
      : availableFeeds.includes(feed)
        ? feed
        : availableFeeds[0];

  const coverage = statusQuery.data?.coverage.find(
    (item) => item.symbol === symbol && item.feed === activeFeed,
  );

  const window = useMemo(() => {
    // Chart window comes only from the selected symbol/feed coverage — never a cross-feed span.
    const latest = coverage?.stored_latest_session ?? null;
    const earliest = coverage?.stored_earliest_session ?? null;
    if (!latest || !earliest) {
      return null;
    }
    if (range === "ALL") {
      return { start: earliest, end: latest, fetchAll: true as const };
    }
    const months = range === "3M" ? -3 : range === "6M" ? -6 : -12;
    const start = shiftMonths(latest, months);
    return {
      start: start < earliest ? earliest : start,
      end: latest,
      fetchAll: (coverage?.bar_count ?? 0) > 5000,
    };
  }, [coverage, range]);

  const barsQuery = useMarketBarsQuery(
    window && activeFeed
      ? {
          symbol,
          feed: activeFeed,
          start: window.start,
          end: window.end,
          fetchAll: window.fetchAll || range === "ALL",
        }
      : null,
  );

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Market Explorer"
        note="Interactive historical daily OHLCV from the local Alpaca store. Delayed research data — not a live quote stream. Feeds are never mixed."
      />

      {statusQuery.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      {statusQuery.isError ? (
        <ErrorState
          title="Market status unavailable"
          note={statusQuery.error instanceof Error ? statusQuery.error.message : "Request failed."}
        />
      ) : null}

      {statusQuery.data ? (
        <div className="flex flex-wrap gap-2">
          <ProvenanceChip source={`provider=${barsQuery.data?.provider ?? "alpaca"}`} />
          <ProvenanceChip source={`feed=${activeFeed ?? "none"}`} />
          <ProvenanceChip source={`adjustment=${barsQuery.data?.adjustment ?? "raw"}`} />
          <ProvenanceChip source="timeframe=1Day" />
          <Badge tone="warn">Historical / delayed</Badge>
          {coverage ? (
            <Badge tone={coverage.gap_count === 0 ? "ok" : "warn"}>
              {coverage.bar_count} bars · gaps {coverage.gap_count}
            </Badge>
          ) : (
            <Badge tone="warn">
              No coverage for {symbol}/{activeFeed ?? "—"}
            </Badge>
          )}
          {coverage?.latest_session ? (
            <Badge tone="info">Latest session {coverage.latest_session}</Badge>
          ) : null}
          {barsQuery.data && !barsQuery.data.complete ? (
            <Badge tone="err">Incomplete page — not full history</Badge>
          ) : null}
        </div>
      ) : null}

      <Panel className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SegmentedControl
            value={symbol}
            onChange={(value) => setSymbol(value as "SPY" | "QQQ")}
            options={[
              { value: "SPY", label: "SPY" },
              { value: "QQQ", label: "QQQ" },
            ]}
          />
          {availableFeeds.length > 0 && activeFeed ? (
            <SegmentedControl
              value={activeFeed}
              onChange={(value) => setFeed(value as FeedKey)}
              options={availableFeeds.map((item) => ({
                value: item,
                label: item.toUpperCase(),
              }))}
              aria-label="Market feed"
            />
          ) : (
            <Badge tone="warn">No stored feed for {symbol}</Badge>
          )}
          <SegmentedControl
            value={range}
            onChange={(value) => setRange(value as RangeKey)}
            options={[
              { value: "3M", label: "3M" },
              { value: "6M", label: "6M" },
              { value: "1Y", label: "1Y" },
              { value: "ALL", label: "ALL" },
            ]}
          />
          <SegmentedControl
            value={mode}
            onChange={(value) => setMode(value as "candle" | "line")}
            options={[
              { value: "candle", label: "Candles" },
              { value: "line", label: "Line" },
            ]}
          />
        </div>

        {!window || !activeFeed ? (
          <EmptyState
            title="No local bars for charting"
            note={`No ${symbol}/${activeFeed ?? "feed"} coverage in the local store. Feeds are never substituted.`}
          />
        ) : barsQuery.isLoading ? (
          <Skeleton className="h-[420px] w-full" />
        ) : barsQuery.isError ? (
          <ErrorState
            title="Bars could not be loaded"
            note={barsQuery.error instanceof Error ? barsQuery.error.message : "Request failed."}
          />
        ) : barsQuery.data && barsQuery.data.items.length === 0 ? (
          <EmptyState
            title="Empty window"
            note={`No ${symbol} ${activeFeed} bars between ${window.start} and ${window.end}.`}
          />
        ) : barsQuery.data ? (
          <>
            <MarketCandleChart bars={barsQuery.data.items} mode={mode} />
            <p className="text-xs leading-5 text-[var(--muted)]">
              {barsQuery.data.caveat} Charting by TradingView Lightweight Charts (Apache-2.0).
              Showing {barsQuery.data.items.length} of {barsQuery.data.total} sessions
              {barsQuery.data.complete
                ? " (complete window)."
                : " — incomplete; not labeled as full history."}
              {barsQuery.data.pages > 1 ? ` Loaded across ${barsQuery.data.pages} pages.` : null}
            </p>
          </>
        ) : null}
      </Panel>

      {statusQuery.data ? (
        <Panel>
          <h2 className="text-sm font-semibold">Dataset coverage</h2>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-[var(--muted)]">
                <tr>
                  <th className="py-2 pr-4">Symbol</th>
                  <th className="py-2 pr-4">Feed</th>
                  <th className="py-2 pr-4">Bars</th>
                  <th className="py-2 pr-4">Range</th>
                  <th className="py-2 pr-4">Gaps</th>
                </tr>
              </thead>
              <tbody>
                {statusQuery.data.coverage.map((row) => (
                  <tr key={`${row.symbol}-${row.feed}`} className="border-t border-[var(--line)]">
                    <td className="py-2 pr-4 font-mono">{row.symbol}</td>
                    <td className="py-2 pr-4">{row.feed}</td>
                    <td className="py-2 pr-4">{row.bar_count}</td>
                    <td className="py-2 pr-4 text-[var(--muted)]">
                      {row.earliest_session ?? "—"} → {row.latest_session ?? "—"}
                    </td>
                    <td className="py-2 pr-4">{row.gap_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {statusQuery.data.warnings.length > 0 ? (
            <ul className="mt-4 space-y-1 text-sm text-[var(--warn)]">
              {statusQuery.data.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
          <p className="mt-3 text-xs text-[var(--muted)]">{statusQuery.data.caveat}</p>
        </Panel>
      ) : null}
    </div>
  );
}
