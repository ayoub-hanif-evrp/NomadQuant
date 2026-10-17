"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ReactFlow, Background, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { loadAgentRun, loadAgentRuns, loadAgentStatus, loadResearchRuns, startResearchReview } from "@/lib/api";

const ORDER = ["researcher", "skeptic", "reviewer", "verification"] as const;

function stageState(name: string, stages: Array<{ name?: string; role?: string; status?: string }>, running: boolean) {
  const match = stages.find((stage) => `${stage.role} ${stage.name}`.toLowerCase().includes(name));
  if (!match) {
    return running ? "queued" : "idle";
  }
  return String(match.status || "completed");
}

export function AgentWorkspace() {
  const status = useQuery({ queryKey: ["agent-flow"], queryFn: loadAgentStatus });
  const runs = useQuery({ queryKey: ["agent-runs"], queryFn: () => loadAgentRuns("?limit=8") });
  const research = useQuery({ queryKey: ["research-runs-picker"], queryFn: () => loadResearchRuns() });
  const [runId, setRunId] = useState<number | null>(null);
  const [replay, setReplay] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [researchRunId, setResearchRunId] = useState("");
  const [model, setModel] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const detail = useQuery({
    queryKey: ["agent-run", runId],
    queryFn: () => loadAgentRun(runId as number),
    enabled: runId !== null,
  });
  const detailStages = detail.data?.stages as
    | Array<{ name?: string; role?: string; status?: string; latency_ms?: number }>
    | undefined;
  const active = (runs.data?.items ?? []).find((item) => item.status === "running");

  useEffect(() => {
    if (!playing || replay >= ORDER.length) {
      return;
    }
    const timer = window.setTimeout(() => setReplay((value) => value + 1), 700);
    return () => window.clearTimeout(timer);
  }, [playing, replay]);

  const nodes: Node[] = useMemo(() => {
    const stages = detailStages ?? [];
    return ORDER.map((name, index) => {
      const recorded = stageState(name, stages, Boolean(active));
      const shown = playing ? (index < replay ? recorded : "idle") : recorded;
      const live = shown === "running" || shown === "queued";
      return {
        id: name,
        position: { x: 40, y: index * 110 },
        data: { label: `${name} · ${shown}` },
        style: {
          width: 260,
          color: "#e2eaee",
          background: live ? "rgba(92,228,212,0.16)" : "rgba(14,20,30,0.95)",
          border: "1px solid rgba(92,228,212,0.28)",
          borderRadius: 16,
          fontSize: 14,
        },
      };
    });
  }, [active, detailStages, playing, replay]);

  const edges: Edge[] = ORDER.slice(0, -1).map((name, index) => ({
    id: `${name}-next`,
    source: name,
    target: ORDER[index + 1],
    animated: playing && replay === index + 1,
  }));

  return (
    <div className="mb-6 space-y-4">
      <header>
        <p className="kicker">Agents</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Research review</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          {status.data?.ollama.available
            ? "Ollama is installed. Nodes stay idle until a stored or running review says otherwise."
            : "Local model runtime is offline. Stored reviews can still be replayed."}
        </p>
      </header>
      <div className="flex flex-wrap gap-2">
        {(runs.data?.items ?? []).map((run) => (
          <button
            key={run.id}
            type="button"
            onClick={() => {
              setRunId(run.id);
              setPlaying(false);
              setReplay(0);
            }}
            className="rounded-full border border-[var(--line)] px-3 py-1 text-sm"
          >
            Run {run.id} · {run.label} · {run.status}
          </button>
        ))}
        <button
          type="button"
          disabled={runId === null}
          onClick={() => {
            setReplay(0);
            setPlaying(true);
          }}
          className="rounded-full bg-[var(--cyan)] px-3 py-1 text-sm font-semibold text-[#04120f] disabled:opacity-40"
        >
          Replay recorded activity
        </button>
        <button
          type="button"
          onClick={() => {
            const installed = status.data?.ollama.models ?? [];
            const preferred = ["qwen3.5:9b", "gemma4:12b"].find((name) => installed.includes(name)) ?? installed[0] ?? "";
            setModel(preferred);
            setReviewOpen(true);
          }}
          className="rounded-full border border-[var(--line)] px-3 py-1 text-sm"
        >
          Run research review
        </button>
      </div>
      {reviewOpen ? (
        <form
          className="panel space-y-3 p-4"
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
                setReviewNote("Review started. The graph shows running only after the stored status says so.");
                setReviewOpen(false);
                void runs.refetch();
              })
              .catch((exc: unknown) => {
                setReviewNote(exc instanceof Error ? exc.message : "The review did not start.");
              });
          }}
        >
          <p className="text-sm">
            This loads one installed local model and reviews a stored backtest. It does not download a model and cannot place an order.
          </p>
          <label className="block text-sm">
            Research run
            <select
              className="mt-1 w-full rounded-lg border border-[var(--line)] bg-transparent px-2 py-2"
              value={researchRunId}
              onChange={(event) => setResearchRunId(event.target.value)}
            >
              <option value="">Select a stored run</option>
              {(research.data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id} · {item.label} · {item.created_at}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            Installed model
            <select
              className="mt-1 w-full rounded-lg border border-[var(--line)] bg-transparent px-2 py-2"
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
          <div className="flex gap-2">
            <button type="submit" className="rounded-full bg-[var(--cyan)] px-3 py-1.5 text-sm font-semibold text-[#04120f]">
              Start local review
            </button>
            <button type="button" className="text-sm text-[var(--muted)]" onClick={() => setReviewOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      {reviewNote ? <p className="text-sm text-[var(--muted)]">{reviewNote}</p> : null}
      {playing && replay < ORDER.length ? (
        <p className="text-sm text-[var(--warn)]">REPLAY of a stored run. This is not a live model call.</p>
      ) : null}
      {active ? <p className="text-sm">Run {active.id} is actually running.</p> : <p className="text-sm text-[var(--muted)]">No review is running. The graph is idle unless you open a stored run.</p>}
      <div className="panel h-[460px]">
        <ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} nodesConnectable={false} colorMode="dark">
          <Background />
        </ReactFlow>
      </div>
      {detail.data ? (
        <p className="text-sm text-[var(--muted)]">
          Verdict {detail.data.verdict}. Model {detail.data.model}. This review is labeled {detail.data.label}.
        </p>
      ) : null}
    </div>
  );
}
