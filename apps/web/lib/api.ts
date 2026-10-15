export const API_URL = "http://127.0.0.1:8000";

export type BrokerStatus = "connected" | "disconnected" | "error" | "rate_limited";

export type SystemStatus = {
  trading_mode: "paper";
  paper_only: true;
  allow_order_submission: false;
  initial_virtual_capital_usd: number;
  credentials_configured: boolean;
  broker_status: BrokerStatus;
  broker_message: string | null;
  database_ok: boolean;
};

export type AccountSnapshot = {
  equity: string;
  buying_power: string;
  cash: string;
  currency: string;
  status: string;
};

export type BrokerAccount = {
  status: BrokerStatus;
  message: string | null;
  virtual_capital_usd: number;
  broker_equity_note: string;
  account: AccountSnapshot | null;
};

export type PositionSnapshot = {
  symbol: string;
  qty: string;
  side: string;
  market_value: string;
  avg_entry_price: string;
  unrealized_pl: string;
};

export type BrokerPositions = {
  status: BrokerStatus;
  message: string | null;
  positions: PositionSnapshot[];
};

const BROKER_STATUSES: readonly BrokerStatus[] = [
  "connected",
  "disconnected",
  "error",
  "rate_limited",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readStatus(value: unknown): BrokerStatus {
  if (typeof value === "string" && BROKER_STATUSES.includes(value as BrokerStatus)) {
    return value as BrokerStatus;
  }
  throw new Error("Unexpected broker status");
}

function readMessage(value: unknown): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "string") {
    return value;
  }
  throw new Error("Unexpected message");
}

function readAccountSnapshot(value: unknown): AccountSnapshot | null {
  if (value === null) {
    return null;
  }
  if (!isRecord(value)) {
    throw new Error("Unexpected account");
  }
  const fields = ["equity", "buying_power", "cash", "currency", "status"] as const;
  const snapshot = {} as AccountSnapshot;
  for (const field of fields) {
    if (typeof value[field] !== "string") {
      throw new Error("Unexpected account field");
    }
    snapshot[field] = value[field];
  }
  return snapshot;
}

export function parseSystemStatus(value: unknown): SystemStatus {
  if (!isRecord(value)) {
    throw new Error("Unexpected status payload");
  }
  if (value.trading_mode !== "paper" || value.paper_only !== true) {
    throw new Error("API is not reporting paper-only mode");
  }
  if (value.allow_order_submission !== false) {
    throw new Error("API is reporting order submission as enabled");
  }
  if (typeof value.initial_virtual_capital_usd !== "number") {
    throw new Error("Unexpected virtual capital");
  }
  if (typeof value.credentials_configured !== "boolean" || typeof value.database_ok !== "boolean") {
    throw new Error("Unexpected system flags");
  }
  return {
    trading_mode: "paper",
    paper_only: true,
    allow_order_submission: false,
    initial_virtual_capital_usd: value.initial_virtual_capital_usd,
    credentials_configured: value.credentials_configured,
    broker_status: readStatus(value.broker_status),
    broker_message: readMessage(value.broker_message),
    database_ok: value.database_ok,
  };
}

export function parseBrokerAccount(value: unknown): BrokerAccount {
  if (!isRecord(value)) {
    throw new Error("Unexpected account payload");
  }
  if (typeof value.virtual_capital_usd !== "number" || typeof value.broker_equity_note !== "string") {
    throw new Error("Unexpected account envelope");
  }
  return {
    status: readStatus(value.status),
    message: readMessage(value.message),
    virtual_capital_usd: value.virtual_capital_usd,
    broker_equity_note: value.broker_equity_note,
    account: readAccountSnapshot(value.account),
  };
}

export function parsePositions(value: unknown): BrokerPositions {
  if (!isRecord(value) || !Array.isArray(value.positions)) {
    throw new Error("Unexpected positions payload");
  }
  const positions = value.positions.map((item) => {
    if (!isRecord(item)) {
      throw new Error("Unexpected position");
    }
    const fields = ["symbol", "qty", "side", "market_value", "avg_entry_price", "unrealized_pl"] as const;
    const position = {} as PositionSnapshot;
    for (const field of fields) {
      if (typeof item[field] !== "string") {
        throw new Error("Unexpected position field");
      }
      position[field] = item[field];
    }
    return position;
  });
  return {
    status: readStatus(value.status),
    message: readMessage(value.message),
    positions,
  };
}

async function readJson(path: string): Promise<unknown> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`API request failed (${response.status})`);
  }
  return response.json() as Promise<unknown>;
}

export async function loadOverview(): Promise<{
  status: SystemStatus;
  account: BrokerAccount;
  positions: BrokerPositions;
}> {
  const [status, account, positions] = await Promise.all([
    readJson("/api/system/status"),
    readJson("/api/broker/account"),
    readJson("/api/broker/positions"),
  ]);
  return {
    status: parseSystemStatus(status),
    account: parseBrokerAccount(account),
    positions: parsePositions(positions),
  };
}

export function formatUsd(value: number | string): string {
  const amount = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(amount)) {
    return String(value);
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}
