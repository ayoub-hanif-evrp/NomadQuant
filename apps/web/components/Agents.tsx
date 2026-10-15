"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Badge,
  Drawer,
  EmptyState,
  ErrorState,
  MetricCard,
  PageIntro,
  Panel,
  Skeleton,
  toneFor,
} from "@/components/ui";
import { loadAgentRun, loadAgentRuns, loadAgentStatus } from "@/lib/api";

const STAGES = ["researcher", "skeptic", "reviewer"] as const;

export function Agents() {
  const status = useQuery({
    queryKey: ["agent-status"],
    queryFn: loadAgentStatus,
    refetchInterval: 20_000,
  });
  const runs = useQuery({
    queryKey: ["agent-runs"],
    queryFn: () => loadAgentRuns("?limit=50"),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const active = items.some((item) => item.status === "running" || item.status === "started");
      return active ? 5_000 : 30_000;
    },
  });

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const detail = useQuery({
    queryKey: ["agent-run", selectedId],
    enabled: selectedId !== null,
    queryFn: () => loadAgentRun(selectedId as number),
    refetchInterval: (query) =>
      query.state.data?.status === "running" || query.state.data?.status === "started" ? 4_000 : false,
  });

  const [toolOpen, setToolOpen] = useState<Record<string, unknown> | null>(null);
  const [filter, setFilter] = useState("");

  const filteredRuns = useMemo(() => {
    const items = runs.data?.items ?? [];
    const q = filter.trim().toLowerCase();
    if (!q) {
      return items;
    }
    return items.filter(
      (item) =>
        String(item.id).includes(q) ||
        item.model.toLowerCase().includes(q) ||
        item.verdict.toLowerCase().includes(q) ||
        item.status.toLowerCase().includes(q),
    );
  }, [runs.data, filter]);

  const ollamaOk = status.data?.ollama.available === true;
  const counts = useMemo(() => {
    const items = runs.data?.items ?? [];
    return {
      active: items.filter((i) => i.status === "running" || i.status === "started").length,
      completed: items.filter((i) => i.status === "succeeded").length,
      failed: items.filter((i) => i.status === "failed").length,
    };
  }, [runs.data]);

  return (
    <div className="flex flex-col gap-6">
      <PageIntro
        title="Agents"
        note="Local Ollama research reviews only. Runs are retrospective examinations of stored backtests — not predictions, not broker orders, and not started from this UI."
      />

      {status.isLoading ? <Skeleton className="h-28 w-full" lines={4} /> : null}
      {status.isError ? (
        <ErrorState title="Agent status unavailable" note="API could not serve /api/agents/status." />
      ) : null}

      {status.data ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Ollama"
            value={ollamaOk ? "connected" : "disconnected"}
            hint={status.data.ollama.base_url}
          />
          <MetricCard
            label="Configured model"
            value={status.data.configured_model || "(pass --model)"}
            hint={`${status.data.ollama.models.length} installed locally`}
          />
          <MetricCard label="Agent runs" value={String(status.data.run_count)} />
          <MetricCard
            label="Order tools"
            value={status.data.order_tools_available ? "present" : "absent"}
            hint="Paper mode · submission disabled"
          />
        </div>
      ) : null}

      {status.data && !ollamaOk ? (
        <EmptyState
          title="Ollama disconnected"
          note="Start Ollama on 127.0.0.1:11434, then run a review from PowerShell. The dashboard only displays stored runs."
        />
      ) : null}

      <Panel>
        <h2 className="text-sm font-semibold">Start a research review (CLI)</h2>
        <pre className="mt-3 overflow-x-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
{`uv run nomadquant-agent status
uv run nomadquant-agent run --research-run-id 2 --model qwen3.5:9b
uv run nomadquant-agent inspect --run-id <agent-run-id>`}
        </pre>
        <p className="mt-2 text-xs text-[var(--muted)]">
          Label: {status.data?.label ?? "retrospective_research_review"}. Prompt{" "}
          {status.data?.prompt_version ?? "…"} · tools {status.data?.tool_schema_version ?? "…"}.
        </p>
      </Panel>

      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard label="Active" value={String(counts.active)} />
        <MetricCard label="Completed" value={String(counts.completed)} />
        <MetricCard label="Failed" value={String(counts.failed)} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <Panel>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Runs</h2>
            <input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter"
              className="w-28 rounded-lg border border-[var(--line)] bg-black/25 px-2 py-1 text-xs"
            />
          </div>
          {runs.isLoading ? <Skeleton lines={5} /> : null}
          {(filteredRuns.length === 0 && !runs.isLoading) ? (
            <EmptyState
              title="No agent runs yet"
              note="Use the CLI commands above against an existing research backtest run."
            />
          ) : (
            <ul className="space-y-2">
              {filteredRuns.map((run) => (
                <li key={run.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(run.id)}
                    className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${
                      selectedId === run.id
                        ? "border-[rgba(103,240,224,0.35)] bg-[rgba(103,240,224,0.08)]"
                        : "border-[var(--line)] hover:bg-[rgba(255,255,255,0.03)]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs">#{run.id}</span>
                      <Badge tone={toneFor(run.status)}>{run.status}</Badge>
                    </div>
                    <p className="mt-1 truncate text-xs text-[var(--muted)]">
                      research #{run.research_run_id} · {run.model}
                    </p>
                    {run.verdict ? (
                      <p className="mt-1 truncate text-[11px] text-[var(--muted)]">{run.verdict}</p>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="space-y-4">
          {!selectedId ? (
            <EmptyState
              title="Select an agent run"
              note="Inspect Researcher → Skeptic → Reviewer stages, tool calls, and the saved memo."
            />
          ) : null}
          {detail.isLoading ? <Skeleton className="h-64 w-full" lines={8} /> : null}
          {detail.isError ? (
            <ErrorState title="Run detail unavailable" note="Could not load the selected agent run." />
          ) : null}
          {detail.data ? (
            <>
              <Panel>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="kicker">RETROSPECTIVE · NOT A TRADE</p>
                    <h2 className="mt-1 text-lg font-semibold">Agent run #{detail.data.id}</h2>
                    <p className="mt-1 text-sm text-[var(--muted)]">{detail.data.summary || detail.data.label}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge tone={toneFor(detail.data.status)}>{detail.data.status}</Badge>
                    {detail.data.verdict ? (
                      <Badge tone="info">{detail.data.verdict}</Badge>
                    ) : null}
                    <Link
                      href="/research"
                      className="rounded-full border border-[rgba(103,240,224,0.3)] px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--cyan)]"
                    >
                      Research #{detail.data.research_run_id}
                    </Link>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-[var(--muted)]">
                  <span>model={detail.data.model}</span>
                  <span>as_of={String(detail.data.as_of ?? "—")}</span>
                  <span>prompt={String(detail.data.prompt_version ?? "—")}</span>
                  <span>tools={String(detail.data.tool_schema_version ?? "—")}</span>
                </div>
              </Panel>

              <Panel>
                <h3 className="mb-3 text-sm font-semibold">Workflow</h3>
                <div className="grid gap-3 md:grid-cols-3">
                  {STAGES.map((name, index) => {
                    const stage = (detail.data?.stages ?? []).find(
                      (item) => String(item.name ?? item.role ?? "") === name,
                    );
                    return (
                      <div key={name} className="rounded-xl border border-[var(--line)] p-3">
                        <p className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
                          {index + 1}. {name}
                        </p>
                        <div className="mt-2 flex items-center justify-between gap-2">
                          <Badge tone={toneFor(String(stage?.status ?? "pending"))}>
                            {String(stage?.status ?? "pending")}
                          </Badge>
                          <span className="font-mono text-[11px] text-[var(--muted)]">
                            {stage?.latency_ms != null ? `${stage.latency_ms} ms` : "—"}
                          </span>
                        </div>
                        <p className="mt-2 text-[11px] text-[var(--muted)]">
                          calls {String(stage?.model_calls ?? 0)} · tokens{" "}
                          {String(
                            (Number(stage?.prompt_tokens) || 0) +
                              (Number(stage?.completion_tokens) || 0) ||
                              "n/a",
                          )}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </Panel>

              <Panel>
                <h3 className="mb-3 text-sm font-semibold">Tool-call chronology</h3>
                {(detail.data.tool_calls?.length ?? 0) === 0 ? (
                  <p className="text-sm text-[var(--muted)]">No tool calls recorded.</p>
                ) : (
                  <ul className="divide-y divide-[var(--line)]">
                    {detail.data.tool_calls.map((call, index) => (
                      <li key={String(call.id ?? index)}>
                        <button
                          type="button"
                          className="flex w-full flex-wrap items-center gap-3 py-2 text-left text-sm"
                          onClick={() => setToolOpen(call)}
                        >
                          <span className="font-mono text-[11px] text-[var(--muted)]">
                            #{String(call.seq ?? index)}
                          </span>
                          <Badge tone={toneFor(String(call.status ?? "info"))}>
                            {String(call.tool_name)}
                          </Badge>
                          <span className="text-[11px] text-[var(--muted)]">
                            {String(call.stage_name ?? "")}
                          </span>
                          <span className="ml-auto font-mono text-[11px] text-[var(--muted)]">
                            {call.latency_ms != null ? `${call.latency_ms} ms` : ""}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel>
                <h3 className="mb-3 text-sm font-semibold">Artifacts</h3>
                {(detail.data.artifacts?.length ?? 0) === 0 ? (
                  <p className="text-sm text-[var(--muted)]">No saved memos yet.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {detail.data.artifacts.map((item, index) => (
                      <li
                        key={String(item.id ?? index)}
                        className="rounded-xl border border-[var(--line)] px-3 py-2"
                      >
                        <p className="font-mono text-xs text-[var(--cyan)]">
                          {String(item.kind)} · {String(item.name)}
                        </p>
                        <p className="mt-1 text-[11px] text-[var(--muted)]">
                          {String(item.byte_size ?? 0)} bytes · {String(item.sha256 ?? "").slice(0, 12)}…
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>

              {detail.data.error_message_safe ? (
                <ErrorState title="Run error" note={detail.data.error_message_safe} />
              ) : null}
            </>
          ) : null}
        </div>
      </div>

      <Drawer open={toolOpen !== null} onClose={() => setToolOpen(null)} title="Tool call">
        {toolOpen ? (
          <pre className="overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 font-mono text-[11px] text-[var(--muted)]">
            {JSON.stringify(toolOpen, null, 2)}
          </pre>
        ) : null}
      </Drawer>
    </div>
  );
}
