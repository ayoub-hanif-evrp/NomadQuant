import { Suspense } from "react";
import { Activity } from "@/components/Activity";

export default function ActivityPage() {
  return (
    <Suspense fallback={<p className="text-sm text-[var(--muted)]">Loading activity…</p>}>
      <Activity />
    </Suspense>
  );
}
