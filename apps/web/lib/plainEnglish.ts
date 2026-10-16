export type PlainStatus = {
  title: string;
  means: string;
  why: string;
  next: string;
  tone: "ok" | "warn" | "info" | "err";
};

const PILOT: Record<string, PlainStatus> = {
  WAITING_FOR_SESSION: {
    title: "No action needed right now",
    means: "The market session needed for the next decision is not complete yet.",
    why: "The strategy only rebalances on a month-start session, and that bar is not due.",
    next: "Leave the pilot unstarted. Inspect again after the next completed NYSE session.",
    tone: "info",
  },
  WAITING_FOR_DATA: {
    title: "Waiting for market data",
    means: "A decision cannot be judged until the required SPY bar is stored.",
    why: "Missing prices would make the signal and the risk check unreliable.",
    next: "Sync historical bars if you want them, then inspect again. Do not approve yet.",
    tone: "warn",
  },
  READY_TO_START: {
    title: "A supervised start is available",
    means: "The checks that must pass before an internal shadow cycle are clear.",
    why: "Starting still changes the internal $100 ledger only after you confirm it.",
    next: "Read the decision story, then approve only if you intend that one shadow cycle.",
    tone: "ok",
  },
  BLOCKED: {
    title: "A check is blocking action",
    means: "The system can show the situation, but it will not take the action.",
    why: "Risk, data, or ledger checks failed closed.",
    next: "Open the blocker detail under Advanced. Nothing will be executed.",
    tone: "err",
  },
  RECOVERY_REQUIRED: {
    title: "Recovery is required",
    means: "A previous shadow cycle was interrupted.",
    why: "An open reservation should be released before any new action.",
    next: "Run recover from the operations manual. Do not approve a new cycle first.",
    tone: "err",
  },
  OBSERVING: {
    title: "The pilot clock is already set",
    means: "The internal shadow pilot has a start time. That does not mean a broker order exists.",
    why: "The clock separates prospective decisions from historical research.",
    next: "Review the latest decision and the portfolio. No order is sent from this screen.",
    tone: "info",
  },
};

export function explainPilot(state: string | undefined): PlainStatus {
  if (state && PILOT[state]) {
    return PILOT[state];
  }
  return {
    title: "Status is not a trade",
    means: state ? `The system reports ${state}.` : "The pilot status has not loaded.",
    why: "Raw status names are internal. They are not instructions to buy or sell.",
    next: "Refresh. If this persists, open Advanced → Shadow Operations.",
    tone: "info",
  };
}

export function explainIntent(intent: string | undefined): string {
  switch (intent) {
    case "buy":
      return "The strategy would add SPY inside the internal shadow ledger.";
    case "sell":
      return "The strategy would reduce SPY inside the internal shadow ledger.";
    case "hold":
      return "The strategy would keep the current shadow position.";
    case "no_trade":
      return "No shadow trade is proposed.";
    default:
      return "No executable action is proposed.";
  }
}
