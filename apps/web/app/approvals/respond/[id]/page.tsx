import { Suspense } from "react";
import { ApprovalRespond } from "@/components/guided/ApprovalRespond";

export default async function ApprovalRespondPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense fallback={<p className="text-sm text-[var(--muted)]">Loading confirmation…</p>}>
      <ApprovalRespond requestId={id} />
    </Suspense>
  );
}
