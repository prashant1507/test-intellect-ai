import { useEffect, useState } from "react";
import { isUnifiedGherkin } from "../utils/testCase";

export function TestCaseEditModal({ tc, onSave, onClose }) {
  const [description, setDescription] = useState("");
  const [preconditions, setPreconditions] = useState("");
  const [stepsText, setStepsText] = useState("");
  const [expectedResult, setExpectedResult] = useState("");

  useEffect(() => {
    if (!tc) return;
    setDescription(String(tc.description || ""));
    setPreconditions(String(tc.preconditions || ""));
    setStepsText((tc.steps || []).map((s) => String(s)).join("\n"));
    setExpectedResult(String(tc.expected_result || ""));
  }, [tc]);

  if (!tc) return null;

  const gh = isUnifiedGherkin(tc);
  const steps = stepsText
    .split(/\r?\n/)
    .map((l) => l.trimEnd())
    .filter((l) => l.length > 0);
  const canSave = description.trim().length > 0 && steps.length > 0;

  const handleSave = () => {
    if (!canSave) return;
    const next = gh
      ? {
          ...tc,
          description: description.trim(),
          preconditions: "",
          steps,
          expected_result: "",
          change_status: "updated",
        }
      : {
          ...tc,
          description: description.trim(),
          preconditions: preconditions.trim(),
          steps,
          expected_result: expectedResult.trim(),
          change_status: "updated",
        };
    onSave(next);
  };

  return (
    <>
      <div className="modal-dialog-head">
        <h2 id="tc-edit-title" className="modal-dialog-title">
          Edit test case
        </h2>
        <button type="button" className="modal-dialog-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <div className="modal-dialog-tc-edit-body">
        <label className="tc-edit-label" htmlFor="tc-edit-desc">
          Scenario title
        </label>
        <input
          id="tc-edit-desc"
          className="tc-edit-input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          autoComplete="off"
        />
        {gh ? (
          <>
            <label className="tc-edit-label" htmlFor="tc-edit-steps">
              Steps (one per line)
            </label>
            <textarea
              id="tc-edit-steps"
              className="tc-edit-textarea"
              value={stepsText}
              onChange={(e) => setStepsText(e.target.value)}
              rows={12}
            />
          </>
        ) : (
          <>
            <label className="tc-edit-label" htmlFor="tc-edit-pre">
              Preconditions
            </label>
            <textarea
              id="tc-edit-pre"
              className="tc-edit-textarea"
              value={preconditions}
              onChange={(e) => setPreconditions(e.target.value)}
              rows={3}
            />
            <label className="tc-edit-label" htmlFor="tc-edit-steps2">
              Steps (one per line)
            </label>
            <textarea
              id="tc-edit-steps2"
              className="tc-edit-textarea"
              value={stepsText}
              onChange={(e) => setStepsText(e.target.value)}
              rows={10}
            />
            <label className="tc-edit-label" htmlFor="tc-edit-exp">
              Expected result
            </label>
            <textarea
              id="tc-edit-exp"
              className="tc-edit-textarea"
              value={expectedResult}
              onChange={(e) => setExpectedResult(e.target.value)}
              rows={3}
            />
          </>
        )}
      </div>
      <div className="modal-dialog-tc-edit-actions">
        <button type="button" className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="primary" disabled={!canSave} onClick={handleSave}>
          Save
        </button>
      </div>
    </>
  );
}
