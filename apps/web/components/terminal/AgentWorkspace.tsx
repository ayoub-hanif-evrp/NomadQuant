"use client";

import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainIcon } from "@/components/icons/animated/brain";
import { EarthIcon } from "@/components/icons/animated/earth";
import { EyeIcon } from "@/components/icons/animated/eye";
import { GaugeIcon } from "@/components/icons/animated/gauge";
import { ScanTextIcon } from "@/components/icons/animated/scan-text";
import { ShieldCheckIcon } from "@/components/icons/animated/shield-check";
import { AnimatedIcon, formatDay, Pill, timeAgo, type AnimatedIconComponent } from "@/components/terminal/kit";
import {
  analyzeNews,
  loadAgentRun,
  loadAgentRuns,
  loadAgentStatus,
  loadNews,
  loadHomeOverview,
  loadResearchRuns,
  refreshNews,
  startResearchReview,
  type AgentRunDetail,
} from "@/lib/api";
import { cn } from "@/lib/cn";

type AgentKey = "scout" | "researcher" | "skeptic" | "reviewer" | "verifier" | "risk";
type AgentStatusKey = "idle" | "queued" | "working" | "done" | "flagged" | "failed";
type ToolCall = { tool: string; status: string; ms: number; at: string; args: string };
type AgentView = { status: AgentStatusKey; now: string; tools: ToolCall[]; found: string };

const CREW: Array<{
  key: AgentKey;
  name: string;
  persona: string;
  icon: AnimatedIconComponent;
  model: boolean;
  toolbox: string;
}> = [
  {
    key: "scout",
    name: "News Scout",
    persona: "Goes out to the internet and brings back real headlines.",
    icon: EarthIcon,
    model: false,
    toolbox: "Alpaca News API over HTTPS",
  },
  {
    key: "researcher",
    name: "Researcher",
    persona: "Reads the evidence and writes the first report.",
    icon: BrainIcon,
    model: true,
    toolbox: "read_run_card, read_experiment, read_market_data, inspect_data_quality",
  },
  {
    key: "skeptic",
    name: "Skeptic",
    persona: "Questions every claim and hunts for weak spots.",
    icon: EyeIcon,
    model: true,
    toolbox: "list_research_evidence, read_run_card",
  },
  {
    key: "reviewer",
    name: "Reviewer",
    persona: "Weighs both sides and writes the verdict.",
    icon: ScanTextIcon,
    model: true,
    toolbox: "verify_backtest, save_research_memo",
  },
  {
    key: "verifier",
    name: "Verifier",
    persona: "Checks every number against stored records. Not an AI model.",
    icon: ShieldCheckIcon,
    model: false,
    toolbox: "deterministic number check",
  },
  {
    key: "risk",
    name: "Risk Guard",
    persona: "Applies fixed risk rules before any simulated trade. Not an AI model.",
    icon: GaugeIcon,
    model: false,
    toolbox: "risk policy, position and cash limits",
  },
];

const STAGE_ORDER: AgentKey[] = ["researcher", "skeptic", "reviewer", "verifier"];
const FINDING_KEYS = [
  "confirmed_findings",
  "summary",
  "findings",
  "claims",
  "cost_notes",
  "look_ahead_notes",
  "concerns",
  "assumptions",
];

function stageKey(stage: Record<string, unknown>): AgentKey | null {
  const text = `${stage.role ?? ""} ${stage.name ?? ""}`.toLowerCase();
  for (const key of ["researcher", "skeptic", "reviewer"] as const) {
    if (text.includes(key)) {
      return key;
    }
  }
  return null;
}

function firstFinding(output: unknown): string {
  if (!output || typeof output !== "object") {
    return "";
  }
  const report = (output as Record<string, unknown>).report;
  if (!report || typeof report !== "object") {
    return "";
  }
  const record = report as Record<string, unknown>;
  for (const key of FINDING_KEYS) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value.slice(0, 260);
    }
    if (Array.isArray(value)) {
      const text = value.find((item) => typeof item === "string" && item.trim());
      if (typeof text === "string") {
        return text.slice(0, 260);
      }
    }
  }
  return "";
}

function toolsFor(detail: AgentRunDetail | undefined, key: AgentKey): ToolCall[] {
  return (detail?.tool_calls ?? [])
    .filter((call) => String(call.stage_name ?? "").toLowerCase().includes(key))
    .map((call) => ({
      tool: String(call.tool_name ?? "tool"),
      status: String(call.status ?? ""),
      ms: Number(call.latency_ms ?? 0),
      at: String(call.created_at ?? ""),
      args: JSON.stringify(call.arguments ?? {}).slice(0, 80),
    }));
}

function mapStatus(value: string): AgentStatusKey {
  const status = value.toLowerCase();
  if (status === "running") {
    return "working";
  }
  if (status === "failed" || status === "error") {
    return "failed";
  }
  if (status === "succeeded" || status === "completed" || status === "ok") {
    return "done";
  }
  return "idle";
}

export function AgentWorkspace() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["agent-flow"], queryFn: loadAgentStatus });
  const runs = useQuery({
    queryKey: ["agent-runs"],
    queryFn: () => loadAgentRuns("?limit=8"),
    refetchInterval: (query) =>
      (query.state.data?.items ?? []).some((item) => item.status === "running") ? 3000 : 20_000,
  });
  const research = useQuery({ queryKey: ["research-runs-picker"], queryFn: () => loadResearchRuns() });
  const news = useQuery({ queryKey: ["news"], queryFn: loadNews });
  const overview = useQuery({ queryKey: ["home-overview"], queryFn: loadHomeOverview });
  const running = (runs.data?.items ?? []).find((item) => item.status === "running");
  const [chosenRun, setChosenRun] = useState<number | null>(null);
  const runId = chosenRun ?? running?.id ?? runs.data?.items[0]?.id ?? null;
  const detail = useQuery({
    queryKey: ["agent-run", runId],
    queryFn: () => loadAgentRun(runId as number),
    enabled: runId !== null,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });
  const [replayStep, setReplayStep] = useState<number | null>(null);
  const [fetchingNews, setFetchingNews] = useState(false);
  const [analysis, setAnalysis] = useState<{
    state: "running" | "done" | "error";
    headline: string;
    report?: Record<string, string>;
    model?: string;
    message?: string;
  } | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [researchRunId, setResearchRunId] = useState("");
  const [model, setModel] = useState("");
  const [reviewNote, setReviewNote] = useState("");

  useEffect(() => {
    if (replayStep === null) {
      return;
    }
    const timer = window.setTimeout(
      () => setReplayStep((step) => (step === null || step >= STAGE_ORDER.length ? null : step + 1)),
      1600,
    );
    return () => window.clearTimeout(timer);
  }, [replayStep]);

  const live = detail.data?.status === "running";
  const mode: "live" | "replay" | "recorded" | "idle" =
    replayStep !== null ? "replay" : live ? "live" : detail.data ? "recorded" : "idle";
  const analysing = analysis?.state === "running";

  const views = useMemo(() => {
    const result = {} as Record<AgentKey, AgentView>;
    const data = detail.data;
    const stages = data?.stages ?? [];
    for (const key of ["researcher", "skeptic", "reviewer"] as const) {
      const stage = stages.find((item) => stageKey(item) === key);
      const tools = toolsFor(data, key);
      let state: AgentStatusKey = stage ? mapStatus(String(stage.status ?? "")) : live ? "queued" : "idle";
      if (replayStep !== null) {
        const index = STAGE_ORDER.indexOf(key);
        state = index < replayStep ? state : index === replayStep ? "working" : "queued";
      }
      if (analysing) {
        state = "working";
      }
      const latest = tools.at(-1);
      result[key] = {
        status: state,
        now:
          analysing
            ? "Reading the selected headline with the local model."
            : state === "working"
              ? latest
                ? `Using ${latest.tool}…`
                : `Thinking with ${data?.model ?? "the local model"}…`
              : state === "done"
                ? `Finished in ${(Number(stage?.latency_ms ?? 0) / 1000).toFixed(1)} s`
                : state === "failed"
                  ? String(stage?.error_message_safe || "This stage failed.")
                  : state === "queued"
                    ? "Waiting for the previous agent."
                    : "Waiting for a task.",
        tools: replayStep !== null && STAGE_ORDER.indexOf(key) > replayStep ? [] : tools,
        found: stage ? firstFinding(stage.output) : "",
      };
    }
    let verifier: AgentStatusKey = "idle";
    if (data && !live) {
      verifier = data.verdict.includes("fail") ? "flagged" : data.verdict ? "done" : "idle";
    } else if (live) {
      verifier = result.reviewer.status === "done" ? "working" : "queued";
    }
    if (replayStep !== null) {
      verifier = replayStep < 3 ? "queued" : replayStep === 3 ? "working" : verifier;
    }
    result.verifier = {
      status: verifier,
      now:
        verifier === "flagged"
          ? "Found numbers that do not match the stored records."
          : verifier === "done"
            ? "All checked numbers match the stored records."
            : verifier === "working"
              ? "Comparing every number with stored metrics…"
              : "Runs after the Reviewer.",
      tools: [],
      found: data?.verdict ? `Verdict: ${data.verdict.replaceAll("_", " ")}` : "",
    };
    const latestFetch = news.data?.fetches[0];
    result.scout = {
      status: fetchingNews ? "working" : latestFetch ? (latestFetch.status === "ok" ? "done" : "failed") : "idle",
      now: fetchingNews
        ? `Connecting to ${news.data?.source ?? "Alpaca News API"}…`
        : latestFetch
          ? `Last trip ${timeAgo(latestFetch.finished_at ?? latestFetch.started_at)}: ${latestFetch.detail}`
          : "Has not been sent out yet.",
      tools: (news.data?.fetches ?? []).slice(0, 3).map((item) => ({
        tool: "alpaca_news_api",
        status: item.status,
        ms: item.duration_ms,
        at: item.started_at,
        args: `${item.article_count} headlines`,
      })),
      found: news.data?.items[0] ? `Latest: ${news.data.items[0].headline}` : "",
    };
    const checks = overview.data?.trading.recent_decisions ?? [];
    result.risk = {
      status: "idle",
      now: "Runs only when a simulated trade is proposed. No proposal is waiting.",
      tools: [],
      found: checks.length
        ? `Recent daily checks: ${checks.map((item) => `${formatDay(item.session, false)} ${item.result.toLowerCase()}`).join(", ")}.`
        : "",
    };
    return result;
  }, [analysing, detail.data, fetchingNews, live, news.data, overview.data, replayStep]);

  async function fetchNews() {
    setFetchingNews(true);
    try {
      await refreshNews();
    } finally {
      setFetchingNews(false);
      await queryClient.invalidateQueries({ queryKey: ["news"] });
    }
  }

  async function analyze(articleId: string, headline: string) {
    setAnalysis({ state: "running", headline });
    try {
      const result = (await analyzeNews(articleId)) as {
        status: string;
        model?: string;
        report?: Record<string, string>;
      };
      setAnalysis({ state: "done", headline, report: result.report, model: result.model });
    } catch (exc) {
      setAnalysis({ state: "error", headline, message: exc instanceof Error ? exc.message : "Analysis failed." });
    }
  }

  const events = useMemo(() => buildEvents(detail.data, news.data?.fetches ?? []), [detail.data, news.data]);

  return (
    <div className="mx-auto mb-8 max-w-7xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="kicker">Agents</p>
          <h1 className="mt-1 text-4xl font-semibold tracking-tight">
            <span className="gold-text">Your AI research crew</span>
          </h1>
          <p className="mt-2 max-w-2xl text-base text-[var(--muted)]">
            Six specialists. Three use the local model, three are fixed rules. None of them can place an order. An
            icon moves only while that agent is really working.
          </p>
        </div>
        <ModeBadge mode={mode} runId={runId} />
      </header>

      <section className="panel overflow-x-auto p-5">
        <div className="flex min-w-[720px] items-center justify-between gap-1">
          {CREW.map((agent, index) => (
            <div key={agent.key} className="flex flex-1 items-center">
              <RailAvatar agent={agent} view={views[agent.key]} />
              {index < CREW.length - 1 ? (
                <Connector
                  active={views[CREW[index + 1].key].status === "working"}
                  dashed={agent.key === "verifier"}
                />
              ) : null}
            </div>
          ))}
        </div>
        <p className="mt-3 text-center text-xs text-[var(--muted)]">
          The Risk Guard is a separate lane. Model agents never feed it, and it never asks a model.
        </p>
      </section>

      <section className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-[var(--muted)]">Recorded reviews:</span>
        {(runs.data?.items ?? []).map((run) => (
          <button
            key={run.id}
            type="button"
            onClick={() => {
              setChosenRun(run.id);
              setReplayStep(null);
            }}
            className={cn(
              "rounded-full px-3 py-1 text-sm",
              run.id === runId
                ? "bg-[var(--gold)] font-semibold text-[#140e02]"
                : "border border-[var(--line)] text-[var(--muted)] hover:text-[var(--ink)]",
            )}
          >
            Run {run.id} · {formatDay(run.created_at, false)}
          </button>
        ))}
        <button
          type="button"
          disabled={!detail.data || live}
          onClick={() => setReplayStep(0)}
          className="ghost-button px-3 py-1 text-sm disabled:opacity-40"
        >
          Replay recorded activity
        </button>
        <button
          type="button"
          onClick={() => {
            const installed = status.data?.ollama.models ?? [];
            setModel(["qwen3.5:9b", "gemma4:12b"].find((name) => installed.includes(name)) ?? installed[0] ?? "");
            setReviewOpen((open) => !open);
          }}
          className="gold-button px-4 py-1.5 text-sm"
        >
          Run research review
        </button>
        <button
          type="button"
          disabled={fetchingNews}
          onClick={() => void fetchNews()}
          className="ghost-button px-3 py-1 text-sm"
        >
          {fetchingNews ? "Scout is fetching…" : "Send the News Scout"}
        </button>
      </section>

      {mode === "replay" ? (
        <p className="rounded-xl border border-[rgba(240,154,74,0.4)] bg-[rgba(240,154,74,0.08)] px-4 py-2 text-sm text-[var(--warn)]">
          REPLAY of a stored run. This is not a live model call.
        </p>
      ) : null}
      {!running ? (
        <p className="text-sm text-[var(--muted)]">No review is running. Agents stay idle until you start one.</p>
      ) : null}

      <AnimatePresence>
        {reviewOpen ? (
          <motion.form
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="panel space-y-3 overflow-hidden p-5"
            onSubmit={(event) => {
              event.preventDefault();
              const id = Number(researchRunId);
              if (!Number.isInteger(id) || id < 1 || !model) {
                setReviewNote("Choose a stored research run and an installed model.");
                return;
              }
              setReviewNote("Starting one local review. This does not trade.");
              void startResearchReview({ researchRunId: id, model })
                .then(() => {
                  setReviewNote("Review started. Watch the crew above.");
                  setReviewOpen(false);
                  setChosenRun(null);
                  void runs.refetch();
                })
                .catch((exc: unknown) => setReviewNote(exc instanceof Error ? exc.message : "The review did not start."));
            }}
          >
            <p className="text-base">
              This loads one installed local model and reviews a stored backtest. It takes about a minute on this
              computer, does not download anything, and cannot place an order.
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block text-sm">
                Research run
                <select
                  className="mt-1 w-full rounded-xl border border-[var(--line)] bg-[var(--bg-2)] px-3 py-2"
                  value={researchRunId}
                  onChange={(event) => setResearchRunId(event.target.value)}
                >
                  <option value="">Select a stored run</option>
                  {(research.data?.items ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.id} · {item.label} · {formatDay(item.created_at, false)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                Installed model
                <select
                  className="mt-1 w-full rounded-xl border border-[var(--line)] bg-[var(--bg-2)] px-3 py-2"
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                >
                  {(status.data?.ollama.models ?? []).map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="flex gap-2">
              <button type="submit" className="gold-button px-4 py-1.5 text-sm">
                Start local review
              </button>
              <button type="button" className="ghost-button px-4 py-1.5 text-sm" onClick={() => setReviewOpen(false)}>
                Cancel
              </button>
            </div>
          </motion.form>
        ) : null}
      </AnimatePresence>
      {reviewNote ? <p className="text-sm text-[var(--gold-soft)]">{reviewNote}</p> : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {CREW.map((agent, index) => (
          <AgentCard key={agent.key} agent={agent} view={views[agent.key]} index={index} />
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <div className="panel p-5">
          <p className="kicker">Ask the crew about a headline</p>
          <h2 className="mt-1 text-xl font-semibold">News analysis</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            One local model call writes the Researcher, Skeptic, and Reviewer views of a headline. It is an
            interpretation, never a strategy change.
          </p>
          {news.data?.items.length ? (
            <ul className="mt-3 divide-y divide-[var(--line)]">
              {news.data.items.slice(0, 5).map((item) => (
                <li key={item.id} className="flex items-start justify-between gap-3 py-3">
                  <div>
                    <p className="text-sm">{item.headline}</p>
                    <p className="text-xs text-[var(--muted)]">
                      {item.source} · {timeAgo(item.published_at)}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={analysing}
                    onClick={() => void analyze(item.id, item.headline)}
                    className="ghost-button shrink-0 px-3 py-1 text-xs disabled:opacity-40"
                  >
                    Analyze
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-[var(--muted)]">
              No headlines yet. Send the News Scout first.
            </p>
          )}
          <AnimatePresence>
            {analysis ? (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className={cn(
                  "mt-4 space-y-2 rounded-2xl border border-[var(--line-strong)] p-4",
                  analysing && "working-sheen",
                )}
              >
                <p className="text-sm font-semibold">{analysis.headline}</p>
                {analysis.state === "running" ? (
                  <p className="text-sm text-[var(--gold-soft)]">The crew is reading this headline…</p>
                ) : analysis.state === "error" ? (
                  <p className="text-sm text-[var(--err)]">{analysis.message}</p>
                ) : (
                  <>
                    {(["researcher", "skeptic", "reviewer"] as const).map((role) => (
                      <p key={role} className="text-sm">
                        <span className="font-semibold capitalize text-[var(--gold)]">{role}: </span>
                        {analysis.report?.[role] ?? "No text."}
                      </p>
                    ))}
                    <p className="text-xs text-[var(--muted)]">
                      {analysis.model ? `Model ${analysis.model}. ` : "No model was available. "}
                      Check: {analysis.report?.verification ?? "none"}.
                    </p>
                  </>
                )}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>

        <div className="panel p-5">
          <p className="kicker">What happened, in order</p>
          <h2 className="mt-1 text-xl font-semibold">Activity log</h2>
          {events.length ? (
            <ol className="mt-3 max-h-[420px] space-y-2 overflow-y-auto pr-1">
              {events.map((event) => (
                <motion.li
                  key={event.id}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex gap-3 rounded-xl border border-[var(--line)] px-3 py-2"
                >
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: event.color }} />
                  <div className="min-w-0">
                    <p className="text-sm">{event.text}</p>
                    <p className="font-mono text-xs text-[var(--muted)]">
                      {new Date(event.at).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </p>
                  </div>
                </motion.li>
              ))}
            </ol>
          ) : (
            <p className="mt-4 text-sm text-[var(--muted)]">Nothing has happened yet.</p>
          )}
        </div>
      </section>
    </div>
  );
}

function buildEvents(
  detail: AgentRunDetail | undefined,
  fetches: Array<{ id: number; started_at: string; status: string; article_count: number; detail: string }>,
) {
  const events: Array<{ id: string; at: string; text: string; color: string }> = [];
  for (const stage of detail?.stages ?? []) {
    const name = String(stage.role === "system" ? stage.name : stage.role ?? stage.name);
    if (stage.started_at) {
      events.push({ id: `s${stage.id}`, at: String(stage.started_at), text: `${name} started`, color: "#e0b84f" });
    }
    if (stage.finished_at) {
      events.push({
        id: `f${stage.id}`,
        at: String(stage.finished_at),
        text: `${name} finished (${stage.status}) in ${(Number(stage.latency_ms ?? 0) / 1000).toFixed(1)} s`,
        color: String(stage.status) === "failed" ? "#e07a6a" : "#e6cf8b",
      });
    }
  }
  for (const call of detail?.tool_calls ?? []) {
    events.push({
      id: `t${call.id}`,
      at: String(call.created_at),
      text: `${call.stage_name} used ${call.tool_name} → ${call.status} (${call.latency_ms} ms)`,
      color: "#9fb3c8",
    });
  }
  for (const item of fetches.slice(0, 5)) {
    events.push({
      id: `n${item.id}`,
      at: item.started_at,
      text: `News Scout fetched from the internet → ${item.status}, ${item.article_count} headlines`,
      color: item.status === "ok" ? "#e0b84f" : "#f09a4a",
    });
  }
  return events.sort((a, b) => b.at.localeCompare(a.at));
}

function ModeBadge({ mode, runId }: { mode: "live" | "replay" | "recorded" | "idle"; runId: number | null }) {
  if (mode === "live") {
    return (
      <Pill tone="gold" pulse>
        LIVE · run {runId} working now
      </Pill>
    );
  }
  if (mode === "replay") {
    return <Pill tone="warn">REPLAY · run {runId}</Pill>;
  }
  if (mode === "recorded") {
    return <Pill tone="muted">Showing recorded run {runId}</Pill>;
  }
  return <Pill tone="muted">IDLE</Pill>;
}

const STATUS_TEXT: Record<AgentStatusKey, string> = {
  idle: "Idle",
  queued: "Queued",
  working: "Working",
  done: "Done",
  flagged: "Flagged",
  failed: "Failed",
};

function statusTone(status: AgentStatusKey): "gold" | "ok" | "warn" | "err" | "muted" {
  return status === "working"
    ? "gold"
    : status === "done"
      ? "ok"
      : status === "flagged"
        ? "warn"
        : status === "failed"
          ? "err"
          : "muted";
}

function RailAvatar({ agent, view }: { agent: (typeof CREW)[number]; view: AgentView }) {
  const working = view.status === "working";
  return (
    <div className="flex w-[92px] shrink-0 flex-col items-center gap-2 text-center">
      <motion.div
        animate={working ? { scale: [1, 1.08, 1] } : { scale: 1 }}
        transition={working ? { duration: 1.4, repeat: Infinity } : { duration: 0.2 }}
        className={cn(
          "relative flex h-14 w-14 items-center justify-center rounded-2xl border",
          working
            ? "border-[var(--gold)] bg-[rgba(224,184,79,0.16)] text-[var(--gold-soft)] shadow-[0_0_24px_rgba(224,184,79,0.35)]"
            : view.status === "done"
              ? "border-[var(--line-strong)] bg-[rgba(224,184,79,0.06)] text-[var(--gold)]"
              : "border-[var(--line)] bg-[rgba(255,255,255,0.02)] text-[var(--muted)]",
        )}
      >
        <AnimatedIcon icon={agent.icon} active={working} size={26} />
      </motion.div>
      <p className="text-xs font-semibold">{agent.name}</p>
      <Pill tone={statusTone(view.status)} pulse={working}>
        {STATUS_TEXT[view.status]}
      </Pill>
    </div>
  );
}

function Connector({ active, dashed }: { active: boolean; dashed: boolean }) {
  return (
    <div className="relative mx-1 h-[2px] flex-1 overflow-hidden rounded-full bg-[var(--line)]">
      {dashed ? (
        <div className="absolute inset-0 bg-[repeating-linear-gradient(90deg,transparent_0_6px,rgba(5,5,5,1)_6px_12px)]" />
      ) : null}
      {active ? (
        <motion.div
          className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-[var(--gold)] to-transparent"
          initial={{ x: "-100%" }}
          animate={{ x: "300%" }}
          transition={{ duration: 1.1, repeat: Infinity, ease: "linear" }}
        />
      ) : null}
    </div>
  );
}

function AgentCard({ agent, view, index }: { agent: (typeof CREW)[number]; view: AgentView; index: number }) {
  const working = view.status === "working";
  return (
    <motion.article
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
      className={cn("panel flex flex-col gap-3 p-5", working && "working-sheen border-[var(--line-strong)]")}
    >
      <div className="flex items-start gap-3">
        <motion.div
          animate={working ? { rotate: [0, -4, 4, 0] } : { rotate: 0 }}
          transition={working ? { duration: 1.6, repeat: Infinity } : { duration: 0.2 }}
          className={cn(
            "flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border",
            working ? "border-[var(--gold)] bg-[rgba(224,184,79,0.16)] text-[var(--gold-soft)]" : "border-[var(--line)] text-[var(--gold)]",
          )}
        >
          <AnimatedIcon icon={agent.icon} active={working} size={24} />
        </motion.div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-lg font-semibold">{agent.name}</h3>
            <Pill tone={statusTone(view.status)} pulse={working}>
              {STATUS_TEXT[view.status]}
            </Pill>
          </div>
          <p className="text-sm text-[var(--muted)]">{agent.persona}</p>
        </div>
      </div>
      <div className="rounded-xl bg-[rgba(255,255,255,0.025)] px-3 py-2">
        <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Right now</p>
        <p className="text-sm">{view.now}</p>
      </div>
      <div>
        <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Tools</p>
        {view.tools.length ? (
          <ul className="mt-1 space-y-1">
            <AnimatePresence>
              {view.tools.map((tool, toolIndex) => (
                <motion.li
                  key={`${tool.tool}-${tool.at}-${toolIndex}`}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-center justify-between gap-2 rounded-lg border border-[var(--line)] px-2 py-1"
                >
                  <span className="truncate font-mono text-xs text-[var(--gold-soft)]">{tool.tool}</span>
                  <span className="shrink-0 font-mono text-xs text-[var(--muted)]">
                    {tool.status} · {tool.ms} ms
                  </span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        ) : (
          <p className="mt-1 text-xs text-[var(--muted)]">Can use: {agent.toolbox}</p>
        )}
      </div>
      {view.found ? (
        <p className="border-l-2 border-[var(--gold-deep)] pl-3 text-sm text-[var(--ink)]/90">{view.found}</p>
      ) : null}
      <p className="mt-auto text-xs text-[var(--muted)]">{agent.model ? "Uses the local AI model" : "Fixed rules, no AI model"}</p>
    </motion.article>
  );
}
