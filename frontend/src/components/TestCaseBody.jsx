import { isUnifiedGherkin } from "../utils/testCase";
import {
  hasRenderableUpdatedDiff,
  lineDiff,
  linesFromText,
  normStepsArr,
} from "../utils/testCaseDiff";

function lineClass(t) {
  if (t === "remove") return "tc-diff-line tc-diff-line--remove";
  if (t === "add") return "tc-diff-line tc-diff-line--add";
  return "tc-diff-line tc-diff-line--same";
}

function textFieldRows(tc, pk, ck) {
  if (!(pk in tc)) return null;
  const o = linesFromText(tc[pk]);
  const n = linesFromText(tc[ck]);
  if (o.join("\n") === n.join("\n")) return null;
  return lineDiff(o, n);
}

function stepRows(tc) {
  if (!("previous_steps" in tc)) return null;
  const o = normStepsArr(tc.previous_steps);
  const n = normStepsArr(tc.steps);
  if (o.length === n.length && o.every((x, i) => x === n[i])) return null;
  return lineDiff(o, n);
}

function TextLinesDiff({ rows }) {
  return (
    <div className="tc-diff-body">
      {rows.map((r, i) => (
        <div key={i} className={lineClass(r.t)}>
          {r.text || "\u00a0"}
        </div>
      ))}
    </div>
  );
}

function TcDiffView({ tc }) {
  const gh = isUnifiedGherkin(tc);
  const descRows = textFieldRows(tc, "previous_description", "description");
  const preRows = textFieldRows(tc, "previous_preconditions", "preconditions");
  const stRows = stepRows(tc);
  const expRows = textFieldRows(tc, "previous_expected_result", "expected_result");
  const stepsOnly = normStepsArr(tc.steps);

  return (
    <>
      {descRows ? (
        <div className="tc-diff-block">
          <p className="tc-diff-block-title">Description</p>
          <TextLinesDiff rows={descRows} />
        </div>
      ) : null}
      {preRows ? (
        <div className="tc-diff-block">
          <p className="tc-diff-block-title">Preconditions</p>
          <TextLinesDiff rows={preRows} />
        </div>
      ) : tc.preconditions ? (
        <p className="meta">
          <strong>Preconditions:</strong> {tc.preconditions}
        </p>
      ) : null}
      {stRows ? (
        <ol
          className={gh ? "tc-gherkin tc-diff-steps" : "tc-diff-steps"}
          aria-label={gh ? "Gherkin scenario" : undefined}
        >
          {stRows.map((r, i) => (
            <li key={i} className={lineClass(r.t)}>
              {r.text}
            </li>
          ))}
        </ol>
      ) : stepsOnly.length ? (
        <ol className={gh ? "tc-gherkin" : undefined} aria-label={gh ? "Gherkin scenario" : undefined}>
          {stepsOnly.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      ) : null}
      {expRows ? (
        <div className="tc-diff-block">
          <p className="tc-diff-block-title">Expected</p>
          <TextLinesDiff rows={expRows} />
        </div>
      ) : tc.expected_result ? (
        <p className="tc-exp">
          <strong>Expected:</strong> {tc.expected_result}
        </p>
      ) : null}
    </>
  );
}

export function TestCaseBody({ tc }) {
  if (!tc) return null;
  if (String(tc.change_status || "").toLowerCase() === "updated" && hasRenderableUpdatedDiff(tc)) {
    return <TcDiffView tc={tc} />;
  }
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
