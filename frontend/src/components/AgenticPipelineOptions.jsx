import { useId } from "react";
import { FieldInfo } from "./common";
import { clampAgenticMaxRounds } from "../utils/testCase";

const AGENTIC_VALIDATION_INFO =
  "• 3: Good default—enough retries to fix JSON or validation issues without many extra calls.\n" +
  "• 4–5: Use for complex or messy requirements where failures are more likely; stop when gains level off.\n" +
  "• 6–10: Only if quality matters more than cost and latency; this is a tradeoff, not always better.";

export function AgenticPipelineOptions({ checked, onCheckedChange, maxRounds, onMaxRoundsChange, roundsInputId }) {
  const agenticCheckboxId = useId();
  return (
    <div className="row agentic-gen-row">
      <div className="agentic-gen-check">
        <input
          id={agenticCheckboxId}
          type="checkbox"
          checked={checked}
          onChange={(e) => onCheckedChange(e.target.checked)}
        />
        <span className="label-with-info">
          <label className="agentic-gen-check__label" htmlFor={agenticCheckboxId}>
            Agentic Validation and Scoring.
          </label>
          <FieldInfo text={AGENTIC_VALIDATION_INFO} />
        </span>
      </div>
      {checked ? (
        <label htmlFor={roundsInputId} className="agentic-rounds-label">
          Max Rounds
          <input
            id={roundsInputId}
            type="text"
            inputMode="numeric"
            className="agentic-rounds-input"
            value={maxRounds}
            onChange={(e) => onMaxRoundsChange(e.target.value)}
            onBlur={() => onMaxRoundsChange(String(clampAgenticMaxRounds(maxRounds)))}
            aria-label="Max validation rounds"
          />
        </label>
      ) : null}
    </div>
  );
}
