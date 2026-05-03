import { FieldInfo } from "./common";

export function MinMaxTestCaseFields({
  idPrefix,
  layout,
  minTestCases,
  maxTestCases,
  onMinChange,
  onMaxChange,
  parseMinTc,
  parseMaxTc,
}) {
  const minId = `${idPrefix}-minTc`;
  const maxId = `${idPrefix}-maxTc`;
  const hintMaxId = `${idPrefix}-hint-max-tc`;
  const inner = (
    <>
      <div>
        <label htmlFor={minId} className="label-with-info">
          <span>Minimum Test Cases</span>
          <FieldInfo text="Minimum number of test cases to generate." />
        </label>
        <input
          id={minId}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={minTestCases}
          onChange={(e) => onMinChange(e.target.value)}
          onBlur={() => onMinChange(String(parseMinTc(minTestCases)))}
        />
      </div>
      <div>
        <label htmlFor={maxId} className="label-with-info">
          <span>Maximum Test Cases</span>
          <FieldInfo text="Maximum number of test cases to generate (whole number ≥ 1). Must be greater than or equal to minimum." />
        </label>
        <input
          id={maxId}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={maxTestCases}
          onChange={(e) => onMaxChange(e.target.value)}
          onBlur={() => {
            const n = parseMaxTc(maxTestCases);
            if (Number.isFinite(n)) onMaxChange(String(n));
          }}
          aria-describedby={hintMaxId}
        />
        <span id={hintMaxId} className="sr-only">
          Maximum number of test cases to generate
        </span>
      </div>
    </>
  );
  if (layout === "sideBySide") {
    return <div className="row cols-2">{inner}</div>;
  }
  if (layout === "jiraCols3") {
    return <div className="row cols-3 jira-credentials-row-equal">{inner}</div>;
  }
  return inner;
}
