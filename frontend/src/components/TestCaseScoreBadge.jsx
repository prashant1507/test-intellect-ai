import { FloatingTooltip } from "./common";

export function TestCaseScoreBadge({ score }) {
  if (typeof score !== "number") return null;
  return (
    <FloatingTooltip text="LLM Quality Score">
      <span className="tc-score" aria-label={`Score ${score} out of 10`}>
        {score}/10
      </span>
    </FloatingTooltip>
  );
}
