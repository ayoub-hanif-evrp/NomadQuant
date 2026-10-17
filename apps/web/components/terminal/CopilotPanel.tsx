"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { CrewAvatar } from "@/components/avatars/CrewAvatar";
import { askCopilot, type CopilotAnswer } from "@/lib/api";

const STORAGE_KEY = "nq-copilot-thread";
const MAX_STORED = 30;

const STARTERS = [
  "Why are there no trades yet?",
  "Are my prices up to date?",
  "How much virtual money do I have?",
  "Explain the strategy simply.",
  "Is the market open right now?",
  "What are the agents doing?",
];

type Message =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; answer?: CopilotAnswer; error?: boolean };

function loadThread(): Message[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as Message[]) : [];
    return Array.isArray(parsed) ? parsed.slice(-MAX_STORED) : [];
  } catch {
    return [];
  }
}

export function CopilotPanel({ onClose }: { onClose: () => void }) {
  const [messages, setMessages] = useState<Message[]>(loadThread);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-MAX_STORED)));
    } catch {
      /* storage may be full or disabled */
    }
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) {
      return;
    }
    const history = messages
      .filter((item) => !(item.role === "assistant" && item.error))
      .slice(-6)
      .map((item) => ({ role: item.role, content: item.content }));
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    setQuestion("");
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const answer = await askCopilot(trimmed, history, controller.signal);
      setMessages((current) => [...current, { role: "assistant", content: answer.answer, answer }]);
    } catch (exc) {
      const stopped = exc instanceof DOMException && exc.name === "AbortError";
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: stopped
            ? "Stopped."
            : exc instanceof Error
              ? `I could not answer: ${exc.message}.`
              : "I could not answer.",
          error: true,
        },
      ]);
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  const lastUser = [...messages].reverse().find((item) => item.role === "user");

  return (
    <motion.aside
      initial={{ x: "100%", opacity: 0.6 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: "100%", opacity: 0.6 }}
      transition={{ type: "spring", stiffness: 260, damping: 30 }}
      className="fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-[var(--line-strong)] bg-[rgba(8,7,5,0.98)] shadow-[-20px_0_60px_rgba(0,0,0,0.6)] sm:max-w-[440px]"
    >
      <header className="flex items-center justify-between gap-3 border-b border-[var(--line)] px-5 py-4">
        <div className="flex items-center gap-3">
          <CrewAvatar id="copilot" mood={busy ? "working" : "idle"} size={44} />
          <div>
            <p className="kicker">Nomad Copilot</p>
            <h2 className="text-lg font-semibold">Ask me anything about your app</h2>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {messages.length ? (
            <button
              type="button"
              onClick={() => setMessages([])}
              className="whitespace-nowrap text-xs text-[var(--muted)] hover:text-[var(--ink)]"
            >
              Clear chat
            </button>
          ) : null}
          <button type="button" onClick={onClose} className="ghost-button px-3 py-1 text-sm" aria-label="Close assistant">
            Close
          </button>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {messages.length === 0 ? (
          <div className="space-y-4">
            <p className="text-base text-[var(--muted)]">
              I read your stored records, the market clock, and the live IEX price. I only state numbers I can show
              you a source for, and I cannot trade.
            </p>
            <div className="grid gap-2">
              {STARTERS.map((item, index) => (
                <motion.button
                  key={item}
                  type="button"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  onClick={() => void submit(item)}
                  className="rounded-2xl border border-[var(--line)] px-4 py-2.5 text-left text-sm hover:border-[var(--line-strong)] hover:bg-[rgba(224,184,79,0.05)]"
                >
                  {item}
                </motion.button>
              ))}
            </div>
          </div>
        ) : null}

        <AnimatePresence initial={false}>
          {messages.map((message, index) =>
            message.role === "user" ? (
              <motion.div
                key={`u${index}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-[linear-gradient(180deg,#f2d58a,#d4a73c)] px-4 py-2.5 text-sm font-medium text-[#140e02]"
              >
                {message.content}
              </motion.div>
            ) : (
              <motion.div
                key={`a${index}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="max-w-[92%] space-y-2"
              >
                <div
                  className={`rounded-2xl rounded-bl-md border px-4 py-3 text-[15px] leading-6 ${
                    message.error
                      ? "border-[rgba(224,122,106,0.4)] text-[var(--err)]"
                      : "border-[var(--line)] bg-[rgba(255,255,255,0.03)]"
                  }`}
                >
                  {message.content}
                </div>
                {message.answer ? <AnswerMeta answer={message.answer} onAsk={(text) => void submit(text)} /> : null}
                {message.error && lastUser && index === messages.length - 1 ? (
                  <button
                    type="button"
                    className="text-xs text-[var(--gold)]"
                    onClick={() => void submit(lastUser.content)}
                  >
                    Try again
                  </button>
                ) : null}
              </motion.div>
            ),
          )}
        </AnimatePresence>

        {busy ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-3 text-sm text-[var(--gold-soft)]"
          >
            <span className="flex gap-1">
              {[0, 1, 2].map((dot) => (
                <motion.span
                  key={dot}
                  className="h-2 w-2 rounded-full bg-[var(--gold)]"
                  animate={{ y: [0, -5, 0], opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 0.9, repeat: Infinity, delay: dot * 0.15 }}
                />
              ))}
            </span>
            Reading your records and asking the local model…
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="ml-auto text-xs text-[var(--muted)] hover:text-[var(--ink)]"
            >
              Stop
            </button>
          </motion.div>
        ) : null}
        <div ref={endRef} />
      </div>

      <form
        className="border-t border-[var(--line)] p-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--line-strong)] bg-[rgba(255,255,255,0.03)] px-3 py-1.5 focus-within:border-[var(--gold)]">
          <input
            aria-label="Question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about prices, trades, agents, news…"
            maxLength={500}
            className="flex-1 bg-transparent py-1.5 text-[15px] outline-none placeholder:text-[var(--muted)]"
          />
          <button type="submit" disabled={busy || !question.trim()} className="gold-button px-4 py-1.5 text-sm">
            Ask
          </button>
        </div>
        <p className="mt-2 text-[11px] text-[var(--muted)]">Chat history stays in this browser. Clear it any time.</p>
      </form>
    </motion.aside>
  );
}

function AnswerMeta({ answer, onAsk }: { answer: CopilotAnswer; onAsk: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
        <span>
          {answer.mode === "local_model"
            ? `Written by ${answer.model} from your records`
            : answer.ollama_available
              ? "From your records (model reply not used)"
              : "Local AI offline · from your records"}
        </span>
        {answer.evidence.length ? (
          <button type="button" onClick={() => setOpen((value) => !value)} className="text-[var(--gold)]">
            {open ? "Hide" : "Show"} {answer.evidence.length} source{answer.evidence.length === 1 ? "" : "s"}
          </button>
        ) : null}
      </div>
      <AnimatePresence>
        {open ? (
          <motion.ul
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="space-y-2 overflow-hidden"
          >
            {answer.evidence.map((item) => (
              <li key={item.id} className="rounded-xl border border-[var(--line)] p-3 text-xs">
                <p className="font-mono text-[var(--gold)]">
                  {item.id} · {item.source}
                </p>
                <p className="mt-1 text-[var(--muted)]">{item.text}</p>
              </li>
            ))}
          </motion.ul>
        ) : null}
      </AnimatePresence>
      {answer.follow_ups?.length ? (
        <div className="flex flex-wrap gap-2">
          {answer.follow_ups.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => onAsk(item)}
              className="rounded-full border border-[var(--line)] px-3 py-1 text-xs hover:border-[var(--line-strong)] hover:text-[var(--gold-soft)]"
            >
              {item}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
