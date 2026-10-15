export function toneFor(status: string): string {
  if (status === "succeeded" || status === "connected" || status === "info") {
    return "ok";
  }
  if (status === "failed" || status === "error") {
    return "err";
  }
  if (status === "warning" || status === "skipped" || status === "rate_limited") {
    return "warn";
  }
  return "info";
}

export type UiTone = "ok" | "warn" | "err" | "info";

export function toneClasses(tone: string): string {
  switch (tone) {
    case "ok":
      return "text-[var(--ok)] border-[rgba(107,201,146,0.35)]";
    case "warn":
      return "text-[var(--warn)] border-[rgba(221,181,106,0.35)]";
    case "err":
      return "text-[var(--err)] border-[rgba(220,148,148,0.4)]";
    default:
      return "text-[var(--cyan)] border-[rgba(92,228,212,0.28)]";
  }
}

export function verificationTone(result: string): UiTone {
  if (result === "PASS") {
    return "ok";
  }
  if (result === "FAIL") {
    return "err";
  }
  if (result === "NOT_EVALUABLE" || result === "INVALID_ARTIFACT") {
    return "warn";
  }
  return "info";
}
