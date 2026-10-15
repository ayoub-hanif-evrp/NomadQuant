export type ConnectionState = "loading" | "ok" | "stale" | "error" | "disconnected";

export function connectionState(args: {
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  dataUpdatedAt: number;
  error: unknown;
  /** Soft stale threshold in ms after last successful fetch. */
  staleAfterMs?: number;
}): ConnectionState {
  const staleAfter = args.staleAfterMs ?? 90_000;
  if (args.isError) {
    if (args.error instanceof TypeError) {
      return "disconnected";
    }
    return "error";
  }
  if (args.isLoading && args.dataUpdatedAt === 0) {
    return "loading";
  }
  if (args.dataUpdatedAt === 0) {
    return "loading";
  }
  const age = Date.now() - args.dataUpdatedAt;
  if (age > staleAfter && !args.isFetching) {
    return "stale";
  }
  return "ok";
}

export function connectionLabel(state: ConnectionState): string {
  switch (state) {
    case "loading":
      return "checking";
    case "ok":
      return "ok";
    case "stale":
      return "stale";
    case "error":
      return "error";
    case "disconnected":
      return "down";
  }
}

export function connectionTone(state: ConnectionState): "ok" | "warn" | "err" | "info" {
  switch (state) {
    case "ok":
      return "ok";
    case "loading":
      return "info";
    case "stale":
      return "warn";
    case "error":
    case "disconnected":
      return "err";
  }
}
