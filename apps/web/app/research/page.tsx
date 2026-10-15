import { Empty, PageIntro } from "@/components/ui";

export default function ResearchPage() {
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageIntro
        title="Research"
        note="Experiment records, hypotheses, and citations will live here."
      />
      <Empty title="Not implemented yet" note="There is no study to show." />
    </div>
  );
}
