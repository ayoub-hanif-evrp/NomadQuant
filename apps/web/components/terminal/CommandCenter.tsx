"use client";

import Link from "next/link";
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ActivityIcon } from "@/components/icons/animated/activity";
import { BotIcon } from "@/components/icons/animated/bot";
import { CircleCheckIcon } from "@/components/icons/animated/circle-check";
import { CloudDownloadIcon } from "@/components/icons/animated/cloud-download";
import { EarthIcon } from "@/components/icons/animated/earth";
import { HourglassIcon } from "@/components/icons/animated/hourglass";
import { TrendingUpIcon } from "@/components/icons/animated/trending-up";
import { WalletIcon } from "@/components/icons/animated/wallet";
import { SymbolChart } from "@/components/terminal/SymbolChart";
import {
  AnimatedIcon,
  formatDay,
  formatNewYork,
  formatUsd,
  Pill,
  timeAgo,
  type AnimatedIconComponent,
} from "@/components/terminal/kit";
import {
  loadAgentRuns,
  loadApprovals,
  loadLiveQuotes,
  loadNews,
  confirmPilotArm,
  loadHomeOverview,
  refreshNews,
  syncHistoricalBars,
  type HomeCheck,
} from "@/lib/api";

const rise = {
  hidden: { opacity: 0, y: 14 },
  show: (index: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: index * 0.07, duration: 0.45, ease: [0.22, 1, 0.36, 1] as const },
  }),
};

export function CommandCenter() {
  const queryClient = useQueryClient();
  const overview = useQuery({ queryKey: ["home-overview"], queryFn: loadHomeOverview, refetchInterval: 60_000 });
  const marketOpen = overview.data?.clock.state === "open";
  const live = useQuery({
    queryKey: ["live-quote"],
    queryFn: loadLiveQuotes,
    refetchInterval: marketOpen ? 20_000 : 300_000,
  });
  const runs = useQuery({ queryKey: ["agent-runs-home"], queryFn: () => loadAgentRuns("?limit=5") });
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: loadApprovals, refetchInterval: 30_000 });
  const news = useQuery({ queryKey: ["news"], queryFn: loadNews });
  const [syncState, setSyncState] = useState<"idle" | "confirm" | "running" | "done" | "error">("idle");
  const [syncNote, setSyncNote] = useState("");
  const [fetchingNews, setFetchingNews] = useState(false);
  const [armState, setArmState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [armNote, setArmNote] = useState("");

  const view = overview.data;
  const spy = live.data?.quotes.SPY;
  const running = (runs.data?.items ?? []).find((item) => item.status === "running");
  const pending = (approvals.data?.items ?? []).filter((item) => item.status === "pending").length;
  const fills = view?.trading.simulated_fills ?? 0;

  async function runSync() {
    setSyncState("running");
    setSyncNote("Downloading finished SIP daily bars from Alpaca…");
    try {
      const result = await syncHistoricalBars();
      setSyncState("done");
      setSyncNote(
        result.sync === "noop" ? "Nothing was missing. Your data is current." : "Market data updated.",
      );
      await queryClient.invalidateQueries();
    } catch (exc) {
      setSyncState("error");
      setSyncNote(exc instanceof Error ? exc.message : "The update failed.");
    }
  }

  async function armPilot() {
    setArmState("running");
    setArmNote("Arming the forward clock. No trade is created.");
    try {
      const result = await confirmPilotArm();
      setArmState("done");
      setArmNote(result.status === "PILOT_ARMED" ? "Pilot clock is set. No fill was simulated." : result.status);
      await queryClient.invalidateQueries({ queryKey: ["home-overview"] });
    } catch (exc) {
      setArmState("error");
      setArmNote(exc instanceof Error ? exc.message : "Arming failed.");
    }
  }

  async function fetchNews() {
    setFetchingNews(true);
    try {
      await refreshNews();
    } finally {
      setFetchingNews(false);
      await queryClient.invalidateQueries({ queryKey: ["news"] });
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <motion.header
        initial="hidden"
        animate="show"
        custom={0}
        variants={rise}
        className="flex flex-wrap items-end justify-between gap-4"
      >
        <div>
          <p className="kicker">{view ? `${view.clock.weekday}, ${formatDay(view.clock.today, false)}` : "Today"}</p>
          <h1 className="mt-1 text-4xl font-semibold tracking-tight">
            <span className="gold-text">Today at a glance</span>
          </h1>
          <p className="mt-2 text-base text-[var(--muted)]">
            {view ? formatNewYork(view.clock.now_new_york) : "Loading the market clock…"}
          </p>
        </div>
        {view ? (
          <div className="flex flex-col items-end gap-1">
            <Pill tone={marketOpen ? "gold" : "muted"} pulse={marketOpen}>
              {view.clock.label}
            </Pill>
            {!marketOpen ? (
              <span className="text-sm text-[var(--muted)]">Opens {formatNewYork(view.clock.next_open)}</span>
            ) : null}
          </div>
        ) : null}
      </motion.header>

      <AnimatePresence>
        {pending > 0 ? (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="panel flex items-center justify-between gap-3 border-[var(--line-strong)] p-4"
          >
            <p className="text-base">
              {pending} approval{pending === 1 ? "" : "s"} waiting for you.
            </p>
            <Link href="/approvals" className="gold-button px-4 py-1.5 text-sm">
              Review
            </Link>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile
          index={1}
          icon={TrendingUpIcon}
          label={marketOpen ? "SPY last IEX trade" : "Last IEX trade (market closed)"}
          value={spy ? formatUsd(spy.price) : live.isLoading ? "…" : "Unavailable"}
          accent={
            spy?.change_pct != null ? (
              <span className={spy.change_pct >= 0 ? "text-[var(--gold)]" : "text-[var(--err)]"}>
                {spy.change_pct >= 0 ? "▲" : "▼"} {Math.abs(spy.change_pct).toFixed(2)}%
              </span>
            ) : null
          }
          note={
            spy
              ? `${marketOpen ? "Last trade" : "Friday-or-last session trade"} ${formatNewYork(spy.trade_time)} · IEX display only`
              : (live.data?.detail ?? "Checking the real-time feed…")
          }
        />
        <Tile
          index={2}
          icon={ActivityIcon}
          label="Trading"
          value={fills > 0 ? `${fills} simulated` : "No trades yet"}
          accent={fills > 0 ? null : <span className="text-sm text-[var(--gold-soft)]">and that is expected</span>}
          note={
            view
              ? `Next possible trade: ${formatDay(view.trading.next_rebalance.fill_session)}`
              : "Loading…"
          }
          href="#why"
        />
        <Tile
          index={3}
          icon={WalletIcon}
          label="Your $100 book"
          value={formatUsd(view?.portfolio.equity_usd ?? null)}
          note={
            view
              ? `${Object.keys(view.portfolio.holdings).length ? "Invested" : "All cash"} · simulated money, not Alpaca`
              : "Loading…"
          }
          href="/portfolio"
        />
        <Tile
          index={4}
          icon={BotIcon}
          active={Boolean(running) || fetchingNews}
          label="AI agents"
          value={running ? "Working" : fetchingNews ? "Fetching news" : "Idle"}
          note={
            running
              ? `Review run ${running.id} is in progress`
              : fetchingNews
                ? "News Scout is on the internet now"
                : "Nothing is running. Start a review or fetch news."
          }
          href="/agents"
        />
      </section>

      <motion.section
        id="why"
        initial="hidden"
        animate="show"
        custom={5}
        variants={rise}
        className="panel p-5 md:p-6"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="kicker">Is the system working?</p>
            <h2 className="mt-1 text-2xl font-semibold">{view?.trading.headline ?? "Checking…"}</h2>
            <p className="mt-2 max-w-3xl text-base text-[var(--muted)]">{view?.trading.summary}</p>
          </div>
        </div>
        <ul className="mt-5 grid gap-3 lg:grid-cols-3">
          {(view?.trading.checks ?? []).map((check, index) => (
            <CheckRow
              key={check.key}
              check={check}
              index={index}
              syncState={syncState}
              onSync={() => setSyncState("confirm")}
              armState={armState}
              armable={Boolean(view?.trading.armable)}
              onArm={() => void armPilot()}
            />
          ))}
        </ul>
        <AnimatePresence>
          {syncState === "confirm" ? (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 overflow-hidden rounded-2xl border border-[var(--line-strong)] bg-[rgba(224,184,79,0.05)] p-4"
            >
              <p className="text-base">
                Download the missing finished trading days for SPY and QQQ from Alpaca? This only
                reads market data. It does not trade.
              </p>
              <div className="mt-3 flex gap-2">
                <button type="button" className="gold-button px-4 py-1.5 text-sm" onClick={() => void runSync()}>
                  Yes, update data
                </button>
                <button type="button" className="ghost-button px-4 py-1.5 text-sm" onClick={() => setSyncState("idle")}>
                  Cancel
                </button>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
        {syncNote ? (
          <p className={`mt-3 text-sm ${syncState === "error" ? "text-[var(--err)]" : "text-[var(--gold-soft)]"}`}>
            {syncNote}
          </p>
        ) : null}
        {armNote ? (
          <p className={`mt-3 text-sm ${armState === "error" ? "text-[var(--err)]" : "text-[var(--gold-soft)]"}`}>
            {armNote}
          </p>
        ) : null}
        {view?.trading.recent_decisions.length ? (
          <div className="mt-5 flex flex-wrap items-center gap-2 text-sm text-[var(--muted)]">
            <span>Recent daily checks:</span>
            {view.trading.recent_decisions.map((item) => (
              <Pill key={item.id} tone="muted">
                {formatDay(item.session)} · {item.result}
              </Pill>
            ))}
          </div>
        ) : null}
      </motion.section>

      <motion.div initial="hidden" animate="show" custom={6} variants={rise}>
        <SymbolChart />
      </motion.div>

      <motion.section initial="hidden" animate="show" custom={7} variants={rise} className="panel p-5 md:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--line-strong)] text-[var(--gold)]">
              <AnimatedIcon icon={EarthIcon} active={fetchingNews} size={24} />
            </span>
            <div>
              <p className="kicker">News</p>
              <h2 className="text-xl font-semibold">
                {fetchingNews
                  ? "News Scout is fetching headlines…"
                  : news.data?.items.length
                    ? "Latest SPY and QQQ headlines"
                    : "No headlines loaded yet"}
              </h2>
            </div>
          </div>
          <button
            type="button"
            className="gold-button px-4 py-2 text-sm"
            disabled={fetchingNews}
            onClick={() => void fetchNews()}
          >
            {fetchingNews ? "Fetching…" : "Fetch news"}
          </button>
        </div>
        <p className="mt-2 text-sm text-[var(--muted)]">
          {fetchingNews
            ? `Connecting to ${news.data?.source ?? "the Alpaca News API"} over the internet.`
            : news.data?.at
              ? `Last fetched ${timeAgo(news.data.at)} from ${news.data.source}. ${news.data.status === "ok" ? "" : (news.data.detail ?? "")}`
              : "Press Fetch news to download real headlines. Nothing is shown until you do."}
        </p>
        <ul className="mt-4 divide-y divide-[var(--line)]">
          {(news.data?.items ?? []).slice(0, 4).map((item) => (
            <li key={item.id} className="py-3">
              <a href={item.url} target="_blank" rel="noreferrer" className="text-base hover:text-[var(--gold-soft)]">
                {item.headline}
              </a>
              <p className="mt-1 text-sm text-[var(--muted)]">
                {item.source} · {timeAgo(item.published_at)}
              </p>
            </li>
          ))}
        </ul>
        {news.data?.items.length ? (
          <Link href="/agents" className="mt-2 inline-block text-sm text-[var(--gold)]">
            Ask the agents to analyze a headline →
          </Link>
        ) : null}
      </motion.section>
    </div>
  );
}

function Tile({
  index,
  icon,
  label,
  value,
  accent,
  note,
  href,
  active = false,
}: {
  index: number;
  icon: AnimatedIconComponent;
  label: string;
  value: string;
  accent?: React.ReactNode;
  note: string;
  href?: string;
  active?: boolean;
}) {
  const body = (
    <motion.article
      initial="hidden"
      animate="show"
      custom={index}
      variants={rise}
      whileHover={{ y: -3 }}
      className={`panel group h-full p-5 ${active ? "working-sheen border-[var(--line-strong)]" : ""}`}
    >
      <div className="flex items-center justify-between">
        <p className="kicker">{label}</p>
        <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-[var(--line)] bg-[rgba(224,184,79,0.06)] text-[var(--gold)]">
          <AnimatedIcon icon={icon} active={active} intro size={22} />
        </span>
      </div>
      <p className="mt-3 font-mono text-3xl font-semibold tracking-tight">{value}</p>
      {accent ? <p className="mt-1 text-base font-semibold">{accent}</p> : null}
      <p className="mt-2 text-sm text-[var(--muted)]">{note}</p>
    </motion.article>
  );
  return href ? (
    <Link href={href} className="block h-full">
      {body}
    </Link>
  ) : (
    body
  );
}

function CheckRow({
  check,
  index,
  syncState,
  onSync,
  armState,
  armable,
  onArm,
}: {
  check: HomeCheck;
  index: number;
  syncState: string;
  onSync: () => void;
  armState: string;
  armable: boolean;
  onArm: () => void;
}) {
  return (
    <motion.li
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.3 + index * 0.1 }}
      className="rounded-2xl border border-[var(--line)] bg-[rgba(255,255,255,0.02)] p-4"
    >
      <div className="flex items-center gap-3">
        <span className={check.ok ? "text-[var(--gold)]" : "text-[var(--warn)]"}>
          <AnimatedIcon icon={check.ok ? CircleCheckIcon : HourglassIcon} intro size={22} />
        </span>
        <p className="text-base font-semibold">{check.title}</p>
      </div>
      <p className="mt-2 text-sm text-[var(--muted)]">{check.detail}</p>
      {check.action === "sync" ? (
        <button
          type="button"
          onClick={onSync}
          disabled={syncState === "running"}
          className="gold-button mt-3 inline-flex items-center gap-2 px-4 py-1.5 text-sm"
        >
          <AnimatedIcon icon={CloudDownloadIcon} active={syncState === "running"} size={16} />
          {syncState === "running" ? "Updating…" : "Update data"}
        </button>
      ) : null}
      {check.action === "start_pilot" ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {armable ? (
            <button
              type="button"
              onClick={onArm}
              disabled={armState === "running"}
              className="gold-button px-4 py-1.5 text-sm"
            >
              {armState === "running" ? "Arming…" : "Arm the forward clock"}
            </button>
          ) : null}
          <Link href="/shadow" className="ghost-button inline-block px-4 py-1.5 text-sm">
            How the pilot works
          </Link>
        </div>
      ) : null}
    </motion.li>
  );
}
