import { Empty, PageIntro } from "@/components/ui";

export default function StrategiesPage() {
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageIntro title="Strategies" note="Strategy definitions and evaluations will live here." />
      <Empty title="No strategy evaluations yet" note="Not implemented yet. This page cannot place a trade." />
    </div>
  );
}