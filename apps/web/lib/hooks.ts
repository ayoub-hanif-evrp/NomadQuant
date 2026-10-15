"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  loadEventHistogram,
  loadEvents,
  loadHealth,
  loadAllMarketBars,
  loadMarketBars,
  loadMarketData,
  loadObservability,
  loadOverview,
  loadResearchExperiments,
  loadResearchRun,
  loadResearchRunDecisions,
  loadResearchRunEquity,
  loadResearchRunReplay,
  loadResearchRuns,
  loadResearchRunTrades,
  loadResearchRunVerify,
  loadRuns,
  type MarketBarPage,
} from "@/lib/api";

export const QUERY_KEYS = {
  health: ["health"] as const,
  overview: ["overview"] as const,
  observability: ["observability"] as const,
  marketStatus: ["market-status"] as const,
  researchRuns: ["research-runs"] as const,
  researchExperiments: ["research-experiments"] as const,
};

export function useSystemHealth() {
  return useQuery({
    queryKey: QUERY_KEYS.health,
    queryFn: loadHealth,
    refetchInterval: 20_000,
  });
}

export function useOverviewBundle() {
  return useQuery({
    queryKey: QUERY_KEYS.overview,
    queryFn: loadOverview,
    refetchInterval: 45_000,
  });
}

export function useObservabilityOverview() {
  return useQuery({
    queryKey: QUERY_KEYS.observability,
    queryFn: loadObservability,
    refetchInterval: 20_000,
  });
}

export function useMarketStatus() {
  return useQuery({
    queryKey: QUERY_KEYS.marketStatus,
    queryFn: loadMarketData,
    staleTime: 60_000,
  });
}

export function useResearchRunsList() {
  return useQuery({
    queryKey: QUERY_KEYS.researchRuns,
    queryFn: () => loadResearchRuns(),
    staleTime: 30_000,
  });
}

export function useResearchExperimentsList() {
  return useQuery({
    queryKey: QUERY_KEYS.researchExperiments,
    queryFn: loadResearchExperiments,
    staleTime: 60_000,
  });
}

export function useEventsQuery(searchParams: string, enabled = true) {
  return useQuery({
    queryKey: ["events", searchParams],
    queryFn: () => loadEvents(searchParams),
    refetchInterval: 20_000,
    enabled,
  });
}

export function useEventHistogramQuery(searchParams: string, enabled = true) {
  return useQuery({
    queryKey: ["events-histogram", searchParams],
    queryFn: () => loadEventHistogram(searchParams),
    refetchInterval: 30_000,
    enabled,
  });
}

export function useRunsQuery(searchParams = "", enabled = true) {
  return useQuery({
    queryKey: ["audit-runs", searchParams],
    queryFn: () => loadRuns(searchParams),
    refetchInterval: 20_000,
    enabled,
  });
}

export function useMarketBarsQuery(
  params: { symbol: string; feed: string; start: string; end: string; fetchAll?: boolean } | null,
) {
  return useQuery({
    queryKey: ["market-bars", params],
    queryFn: async (): Promise<MarketBarPage & { complete: boolean; pages: number }> => {
      if (!params) {
        throw new Error("Missing bar params");
      }
      if (params.fetchAll) {
        return loadAllMarketBars(params);
      }
      const page = await loadMarketBars({ ...params, limit: 5000, offset: 0 });
      return {
        ...page,
        complete: page.items.length === page.total,
        pages: 1,
      };
    },
    enabled: params !== null,
    staleTime: 120_000,
  });
}

export function useResearchRunBundle(runId: number | null) {
  return useQuery({
    queryKey: ["research-run-bundle", runId],
    enabled: runId !== null,
    staleTime: 60_000,
    queryFn: async () => {
      if (runId === null) {
        throw new Error("Missing run");
      }
      const [detail, equity, trades, decisions, verify] = await Promise.all([
        loadResearchRun(runId),
        loadResearchRunEquity(runId),
        loadResearchRunTrades(runId),
        loadResearchRunDecisions(runId),
        loadResearchRunVerify(runId).catch(() => null),
      ]);
      let replay = null;
      let replayError: string | null = null;
      try {
        replay = await loadResearchRunReplay(runId);
      } catch (error) {
        replayError = error instanceof Error ? error.message : "Replay unavailable";
      }
      return {
        detail,
        equity: equity.items,
        trades: trades.items,
        tradesNote: trades.note,
        decisions: decisions.items,
        decisionsNote: decisions.note,
        verify,
        replay,
        replayError,
      };
    },
  });
}

export function useRefreshAll() {
  const client = useQueryClient();
  return async () => {
    await client.invalidateQueries();
  };
}
