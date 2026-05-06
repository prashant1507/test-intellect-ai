import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { FieldInfo } from "./common";
import { isGeneratedCaseAlreadyInSuite } from "../utils/automationSuitePayload";
import { testCaseToSpikeBdd } from "../utils/testCase";

export function SaveToSuiteBulkModal({
  open,
  tests,
  suiteCases,
  requirementTicketId,
  busy,
  onClose,
  onConfirm,
}) {
  const dialogRef = useRef(null);
  const [testType, setTestType] = useState("UI");
  const [selected, setSelected] = useState(() => new Set());

  const rows = useMemo(() => (Array.isArray(tests) ? tests : []), [tests]);
  const suiteList = useMemo(() => (Array.isArray(suiteCases) ? suiteCases : []), [suiteCases]);

  const bddMask = useMemo(
    () =>
      rows.map((tc) => Boolean(tc && typeof tc === "object" && String(testCaseToSpikeBdd(tc)).trim())),
    [rows],
  );

  const inSuiteMask = useMemo(
    () => rows.map((tc) => isGeneratedCaseAlreadyInSuite(tc, suiteList)),
    [rows, suiteList],
  );

  const selectableMask = useMemo(
    () => bddMask.map((bddOk, i) => bddOk && !inSuiteMask[i]),
    [bddMask, inSuiteMask],
  );

  useEffect(() => {
    if (!open) return;
    const next = new Set();
    selectableMask.forEach((ok, i) => {
      if (ok) next.add(i);
    });
    setSelected(next);
    setTestType("UI");
  }, [open, selectableMask]);

  useLayoutEffect(() => {
    if (!open) return;
    const id = requestAnimationFrame(() => {
      const root = dialogRef.current;
      if (!root) return;
      const focusable = root.querySelector(
        'button:not([disabled]), [href]:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
      );
      (focusable ?? root).focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(id);
  }, [open]);

  if (!open) return null;

  const selectableCount = selectableMask.filter(Boolean).length;
  const selectedSelectable = [...selected].filter((i) => selectableMask[i]).length;

  const toggle = (i) => {
    if (!selectableMask[i]) return;
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });
  };

  const selectAllSelectable = () => {
    const n = new Set();
    selectableMask.forEach((ok, i) => {
      if (ok) n.add(i);
    });
    setSelected(n);
  };

  const clearAll = () => setSelected(new Set());

  const submit = () => {
    const picked = rows.filter((_, i) => selected.has(i) && selectableMask[i]);
    if (!picked.length || busy) return;
    onConfirm(testType, picked, requirementTicketId);
  };

  return (
    <div
      className="modal-backdrop modal-backdrop--main-area modal-backdrop--stack-above"
      role="presentation"
      onClick={() => !busy && onClose()}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        id="save-to-suite-bulk-dialog"
        className="modal-dialog modal-dialog-tc-edit save-to-suite-bulk-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="save-to-suite-bulk-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-dialog-head">
          <h2 id="save-to-suite-bulk-title" className="modal-dialog-title">
            Save to Saved Suite
          </h2>
          <button type="button" className="modal-dialog-close" onClick={() => !busy && onClose()} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-dialog-tc-edit-body save-to-suite-bulk-body">
          <p className="save-to-suite-bulk-meta">
            Requirement ticket:{" "}
            <strong translate="no">{String(requirementTicketId || "").trim() || "—"}</strong>
          </p>
          <div className="save-to-suite-bulk-type-row">
            <span className="label-with-info" id="save-to-suite-bulk-type-label">
              <span>Test Type</span>
              <FieldInfo text="UI uses browser automation; API uses HTTP-only runs. Saved as the first tag on each suite case" />
            </span>
            <div
              className="save-to-suite-bulk-type-radios"
              role="radiogroup"
              aria-labelledby="save-to-suite-bulk-type-label"
            >
              <label className="save-to-suite-bulk-radio">
                <input
                  type="radio"
                  name="save-to-suite-type"
                  checked={testType === "UI"}
                  disabled={busy}
                  onChange={() => setTestType("UI")}
                />{" "}
                UI
              </label>
              <label className="save-to-suite-bulk-radio">
                <input
                  type="radio"
                  name="save-to-suite-type"
                  checked={testType === "API"}
                  disabled={busy}
                  onChange={() => setTestType("API")}
                />{" "}
                API
              </label>
            </div>
          </div>
          <div className="save-to-suite-bulk-list-head">
            <span className="save-to-suite-bulk-list-title">
              Test Cases ({selectedSelectable}/{selectableCount} Selected)
            </span>
            <span className="save-to-suite-bulk-list-actions">
              <button type="button" className="linkish" disabled={busy} onClick={selectAllSelectable}>
                Select all
              </button>
              <button type="button" className="linkish" disabled={busy} onClick={clearAll}>
                Clear
              </button>
            </span>
          </div>
          <ul className="save-to-suite-bulk-list" role="list">
            {rows.map((tc, i) => {
              const bddOk = bddMask[i];
              const inSuite = inSuiteMask[i];
              const selectable = selectableMask[i];
              const scenario = String(tc?.description ?? "").trim() || "Untitled";
              const jira = String(tc?.jira_issue_key ?? "").trim();
              const liClass = [
                "save-to-suite-bulk-li",
                !selectable ? "save-to-suite-bulk-li--disabled" : "",
                inSuite && bddOk ? "save-to-suite-bulk-li--in-suite" : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <li key={i} className={liClass}>
                  <label className="save-to-suite-bulk-cb-label">
                    <input
                      type="checkbox"
                      checked={Boolean(selectable && selected.has(i))}
                      disabled={busy || !selectable}
                      onChange={() => toggle(i)}
                    />
                    <span className="save-to-suite-bulk-cb-text" translate="no">
                      {jira ? (
                        <>
                          <span className="automation-spike-suite-jira">{jira}</span>
                          <span className="automation-spike-suite-sep" aria-hidden="true">
                            {" "}
                            ·{" "}
                          </span>
                        </>
                      ) : null}
                      {scenario}
                    </span>
                  </label>
                  {inSuite && bddOk ? (
                    <span className="save-to-suite-bulk-in-suite">Already in Saved Suite</span>
                  ) : null}
                  {!bddOk ? <span className="save-to-suite-bulk-no-bdd">No steps to save</span> : null}
                </li>
              );
            })}
          </ul>
        </div>
        <div className="modal-dialog-tc-edit-actions save-to-suite-bulk-actions">
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={busy || selectedSelectable === 0} onClick={submit}>
            {busy ? "Saving…" : "Save to Suite"}
          </button>
        </div>
      </div>
    </div>
  );
}
