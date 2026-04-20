import { clampAgenticMaxRounds } from "../utils/testCase";

export function AgenticPipelineOptions({ checked, onCheckedChange, maxRounds, onMaxRoundsChange, roundsInputId }) {
  return (
    <div className="row agentic-gen-row">
      <label className="agentic-gen-check">
        <input type="checkbox" checked={checked} onChange={(e) => onCheckedChange(e.target.checked)} />
        <span>Agentic Validation and Scoring.</span>
      </label>
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
