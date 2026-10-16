import { Suspense } from "react";
import { ResearchLab } from "@/components/ResearchLab";

export default function ResearchPage() {
  return (
    <Suspense fallback={null}>
      <ResearchLab />
    </Suspense>
  );
}
