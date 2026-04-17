import { isUnifiedGherkin } from "../utils/testCase";

export function TestCaseBody({ tc }) {
  if (!tc) return null;
  if (isUnifiedGherkin(tc)) {
    return (
      <ol className="tc-gherkin" aria-label="Gherkin scenario">
        {(tc.steps || []).map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
    );
  }
  return (
    <>
      {tc.preconditions ? (
        <p className="meta">
          <strong>Preconditions:</strong> {tc.preconditions}
        </p>
      ) : null}
      <ol>
        {(tc.steps || []).map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
      {tc.expected_result ? (
        <p className="tc-exp">
          <strong>Expected:</strong> {tc.expected_result}
        </p>
      ) : null}
    </>
  );
}
