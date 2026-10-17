"use client";

import { useState } from "react";
import { askCopilot, type CopilotAnswer } from "@/lib/api";

const SUGGESTIONS = [
  "Are my market prices up to date?",
  "How much virtual money do I currently have?",
  "Why didn't the system buy SPY today?",
  "What is the difference between this backtest and real trading?",
];

export function CopilotPanel({ onClose }: { onClose: () => void }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState<CopilotAnswer | null>(null);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      setAnswer(await askCopilot(trimmed));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The assistant could not answer.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-[var(--line)] bg-[rgba(6,10,16,0.98)] shadow-2xl">
      <header className="flex items-center justify-between border-b border-[var(--line)] px-4 py-3">
        <div>
          <p className="kicker">Nomad Copilot</p>
          <h2 className="text-lg font-semibold">Ask about what is stored</h2>
        </div>
        <button type="button" onClick={onClose} className="text-sm text-[var(--muted)]" aria-label="Close assistant">
          Close
        </button>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        <p className="text-sm text-[var(--muted)]">
          Answers come from local records. A model is used only when it stays inside that evidence. It cannot trade.
        </p>
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((item) => (
            <button key={item} type="button" className="rounded-full border border-[var(--line)] px-3 py-1 text-left text-xs" onClick={() => void submit(item)}>
              {item}
            </button>
          ))}
        </div>
        {busy ? <p className="text-sm">Reading stored evidence…</p> : null}
        {error ? <p className="text-sm text-[var(--err)]">{error}</p> : null}
        {answer ? (
          <article className="space-y-3">
            <p className="text-sm leading-6">{answer.answer}</p>
            <p className="text-xs text-[var(--muted)]">
              {answer.ollama_available ? answer.note : "Local AI assistant offline. This answer uses stored records only."}{" "}
              {answer.model ? `Model ${answer.model}.` : ""}
            </p>
            <ul className="space-y-2">
              {answer.evidence.map((item) => (
                <li key={item.id} className="rounded-xl border border-[var(--line)] p-3 text-xs">
                  <p className="font-mono text-[var(--cyan)]">{item.id}</p>
                  <p className="mt-1">{item.text}</p>
                </li>
              ))}
            </ul>
          </article>
        ) : null}
      </div>
      <form
        className="border-t border-[var(--line)] p-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <label className="block text-sm">
          Question
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            className="mt-1 w-full rounded-xl border border-[var(--line)] bg-transparent px-3 py-2"
          />
        </label>
        <button type="submit" disabled={busy} className="mt-2 rounded-full bg-[var(--cyan)] px-3 py-1.5 text-sm font-semibold text-[#04120f]">
          Ask
        </button>
      </form>
    </aside>
  );
}
