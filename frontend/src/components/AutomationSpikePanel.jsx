import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  FieldInfo,
  FloatingTooltip,
  InlineDownloadIconButton,
  Spinner,
  downloadUrlAsFile,
  suggestedFilenameFromUrl,
} from "./common";
import {
  AutomationRunStepScreenshot,
  getFirstFailingStepShotAccordionId,
  stepShotAccordionId,
} from "./AutomationRunStepScreenshot";

function spikeRunStatusDisplay(status) {
  const s = String(status || "").toLowerCase();
  if (s === "completed") return { label: "Pass", mod: "pass" };
  if (s === "aborted") return { label: "Stopped", mod: "aborted" };
  return { label: "Fail", mod: "fail" };
}

function RunStatusPill({ status }) {
  const { label, mod } = spikeRunStatusDisplay(status);
  return (
    <span className={`automation-spike-status automation-spike-status--${mod}`} role="status">
      {label}
    </span>
  );
}

export function AutomationSpikePanel({
  api,
  onListsChanged,
  suiteRunBusy = false,
  onSpikeRunBusyChange,
  traceFileGeneration = true,
}) {
  const [title, setTitle] = useState("");
  const [bdd, setBdd] = useState("");
  const [url, setUrl] = useState("");
  const [jiraId, setJiraId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [saveSuiteErr, setSaveSuiteErr] = useState("");
  const [saveSuiteInfo, setSaveSuiteInfo] = useState("");
  const [result, setResult] = useState(null);
  const [saveScenarioInvalid, setSaveScenarioInvalid] = useState(false);
  const [saveBddInvalid, setSaveBddInvalid] = useState(false);
  const [startUrlInvalid, setStartUrlInvalid] = useState(false);
  const [startBddInvalid, setStartBddInvalid] = useState(false);
  const [stopInProgress, setStopInProgress] = useState(false);
  const [analysisExpandedShotId, setAnalysisExpandedShotId] = useState(null);
  const analysisShotRunInited = useRef(null);
  const scenarioInputRef = useRef(null);
  const urlInputRef = useRef(null);
  const bddTextareaRef = useRef(null);

  const bumpLists = () => {
    onListsChanged?.();
  };

  const yieldToPaint = () =>
    new Promise((resolve) => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          resolve();
        });
      });
    });

  useEffect(() => {
    onSpikeRunBusyChange?.(busy);
  }, [busy, onSpikeRunBusyChange]);

  useEffect(() => {
    return () => {
      onSpikeRunBusyChange?.(false);
    };
  }, [onSpikeRunBusyChange]);

  useEffect(() => {
    const rid = result?.run_id;
    if (rid == null) {
      setAnalysisExpandedShotId(null);
      analysisShotRunInited.current = null;
      return;
    }
    const ridS = String(rid);
    if (analysisShotRunInited.current !== ridS) {
      analysisShotRunInited.current = ridS;
      setAnalysisExpandedShotId(
        getFirstFailingStepShotAccordionId(rid, result?.steps) ?? null,
      );
      return;
    }
    setAnalysisExpandedShotId((prev) => {
      if (prev != null) return prev;
      return getFirstFailingStepShotAccordionId(rid, result?.steps) ?? null;
    });
  }, [result?.run_id, result?.steps]);

  const formLocked = busy || suiteRunBusy;

  const run = async () => {
    setErr("");
    setSaveSuiteInfo("");
    setResult(null);
    setStartUrlInvalid(false);
    setStartBddInvalid(false);
    const u = url.trim();
    const okUrl = Boolean(u);
    const okBdd = Boolean(bdd.trim());
    if (!okUrl || !okBdd) {
      if (!okUrl) setStartUrlInvalid(true);
      if (!okBdd) setStartBddInvalid(true);
      requestAnimationFrame(() => {
        if (!okUrl) urlInputRef.current?.focus();
        else bddTextareaRef.current?.focus();
      });
      return;
    }
    setBusy(true);
    const body = {
      title: title.trim(),
      bdd,
      url: u,
      jira_id: jiraId.trim(),
    };
    try {
      const out = await api("/automation/spike-run", "POST", body);
      setResult(out);
      bumpLists();
    } catch (e) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveToSuite = async () => {
    setSaveSuiteErr("");
    setSaveSuiteInfo("");
    setSaveScenarioInvalid(false);
    setSaveBddInvalid(false);
    const titleT = title.trim();
    const jiraT = jiraId.trim();
    const okTitle = Boolean(titleT);
    const okBdd = Boolean(bdd.trim());
    if (!okTitle || !okBdd) {
      if (!okTitle) setSaveScenarioInvalid(true);
      if (!okBdd) setSaveBddInvalid(true);
      requestAnimationFrame(() => {
        if (!okTitle) scenarioInputRef.current?.focus();
        else bddTextareaRef.current?.focus();
      });
      return;
    }
    try {
      const { cases } = await api("/automation/suite");
      const list = cases || [];
      if (jiraT) {
        const jl = jiraT.toLowerCase();
        if (
          list.some(
            (c) =>
              String(c.jira_id || "")
                .trim()
                .toLowerCase() === jl,
          )
        ) {
          setSaveSuiteInfo(
            "A saved suite case with this JIRA ID already exists.",
          );
          return;
        }
      } else if (
        list.some((c) => {
          if (String(c.jira_id || "").trim()) return false;
          return (c.title || "").trim() === titleT;
        })
      ) {
        setSaveSuiteInfo(
          "A saved suite case with this scenario name already exists.",
        );
        return;
      }
      await api("/automation/suite", "POST", {
        title: titleT,
        bdd,
        url: "",
        jira_id: jiraT,
      });
      bumpLists();
    } catch (e) {
      const m = e?.message || String(e);
      if (m.includes("already exists")) setSaveSuiteInfo(m);
      else setSaveSuiteErr(m);
    }
  };

  const requestStopCurrentTest = async () => {
    if (stopInProgress) return;
    flushSync(() => {
      setStopInProgress(true);
    });
    await yieldToPaint();
    try {
      await api("/automation/cancel", "POST", { all_in_suite: false });
    } catch (_) {
    } finally {
      setStopInProgress(false);
    }
  };

  return (
    <div className="automation-spike-stack" aria-label="Auto Tests (BDD + Playwright)">
      <div className="row cols-2">
        <div>
          <label htmlFor="automation-spike-jira-id" className="label-with-info">
            <span>JIRA ID (Optional)</span>
            <FieldInfo text="Issue key from JIRA." />
          </label>
          <input
            id="automation-spike-jira-id"
            value={jiraId}
            onChange={(e) => setJiraId(e.target.value)}
            disabled={formLocked}
            autoComplete="off"
            aria-describedby="automation-spike-jira-id-hint"
          />
          <span id="automation-spike-jira-id-hint" className="sr-only">
            Issue key from JIRA.
          </span>
        </div>
        <div>
          <label htmlFor="automation-spike-scenario" className="label-with-info">
            <span>Scenario</span>
            <FieldInfo text="Scenario Name." />
          </label>
          <input
            id="automation-spike-scenario"
            ref={scenarioInputRef}
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
              if (saveScenarioInvalid) setSaveScenarioInvalid(false);
            }}
            className={saveScenarioInvalid ? "form-field--invalid" : undefined}
            aria-invalid={saveScenarioInvalid ? true : undefined}
            disabled={formLocked}
            aria-describedby="automation-spike-scenario-hint"
          />
          <span id="automation-spike-scenario-hint" className="sr-only">
            Scenario Name
          </span>
        </div>
      </div>
      <div className="row">
        <label htmlFor="automation-spike-url" className="label-with-info">
          <span>URL</span>
          <FieldInfo text="Application URL. Use a full URL (e.g. https://example.com)." />
        </label>
        <input
          id="automation-spike-url"
          ref={urlInputRef}
          type="url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            if (startUrlInvalid) setStartUrlInvalid(false);
          }}
          className={startUrlInvalid ? "form-field--invalid" : undefined}
          aria-invalid={startUrlInvalid ? true : undefined}
          disabled={formLocked}
          aria-describedby="automation-spike-url-hint"
        />
        <span id="automation-spike-url-hint" className="sr-only">
          Application URL. Use a full URL (e.g. https://example.com).
        </span>
      </div>
      <div className="row">
        <label htmlFor="automation-spike-test-steps" className="label-with-info">
          <span>Test Steps</span>
          <FieldInfo text="BDD-style steps (Given / When / Then) that describe what the automation should do on the page." />
        </label>
        <textarea
          id="automation-spike-test-steps"
          ref={bddTextareaRef}
          className={
            saveBddInvalid || startBddInvalid
              ? "paste-requirements-textarea form-field--invalid"
              : "paste-requirements-textarea"
          }
          value={bdd}
          onChange={(e) => {
            setBdd(e.target.value);
            if (saveBddInvalid) setSaveBddInvalid(false);
            if (startBddInvalid) setStartBddInvalid(false);
          }}
          rows={5}
          aria-invalid={saveBddInvalid || startBddInvalid ? true : undefined}
          disabled={formLocked}
          aria-describedby="automation-spike-test-steps-hint"
        />
        <span id="automation-spike-test-steps-hint" className="sr-only">
          BDD-style steps (Given / When / Then) that describe what the automation should do on the page.
        </span>
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary has-icon"
          onClick={run}
          disabled={formLocked}
        >
          {busy ? <Spinner /> : null}
          {busy ? "Running…" : "Start Test"}
        </button>
        {busy ? (
          <button
            type="button"
            className="secondary has-icon"
            onClick={() => void requestStopCurrentTest()}
            disabled={stopInProgress}
            aria-busy={stopInProgress}
          >
            {stopInProgress ? <Spinner /> : null}
            {stopInProgress ? "In progress…" : "Stop Test"}
          </button>
        ) : null}
        <button type="button" className="secondary" onClick={saveToSuite} disabled={formLocked}>
          Save to Suite
        </button>
      </div>
      {saveSuiteInfo ? (
        <p
          className={
            saveSuiteInfo.includes("JIRA ID")
              ? "automation-spike-err"
              : "automation-spike-muted"
          }
          role="status"
        >
          {saveSuiteInfo}
        </p>
      ) : null}
      {saveSuiteErr ? (
        <p className="automation-spike-err" role="status">
          {saveSuiteErr}
        </p>
      ) : null}
      {err ? (
        <div className="err" role="alert">
          <strong>Error.</strong> {err}
        </div>
      ) : null}
      {result ? (
        <div className="automation-spike-result">
          <div className="automation-spike-run-head">
            <h3 className="automation-spike-run-title">Execution Status</h3>
            <RunStatusPill status={result.status} />
          </div>
          {result.used_cache != null || result.fingerprint ? (
            <div className="automation-spike-run-meta">
              <ul className="automation-spike-run-kv" aria-label="Run metadata">
                {result.used_cache != null ? (
                  <li>
                    <span className="automation-spike-run-k">Cache</span>
                    <span className="automation-spike-run-v">
                      {typeof result.used_cache === "boolean"
                        ? result.used_cache
                          ? "On"
                          : "Off"
                        : String(result.used_cache)}
                    </span>
                  </li>
                ) : null}
                {result.fingerprint ? (
                  <li>
                    <span className="automation-spike-run-k">Fingerprint</span>
                    <span
                      className="automation-spike-run-fp"
                      translate="no"
                    >
                      {result.fingerprint}
                    </span>
                  </li>
                ) : null}
              </ul>
            </div>
          ) : null}
          {(traceFileGeneration && result.trace_url) || result.report_url ? (
            <div className="automation-spike-run-artifacts" role="group" aria-label="Run artifacts">
              {traceFileGeneration && result.trace_url ? (
                <div className="automation-spike-run-artifact">
                  <span className="automation-spike-run-artifact-label">Trace</span>
                  <div className="automation-spike-run-artifact-body">
                    <div className="automation-spike-run-artifact-trace-line">
                      <FloatingTooltip
                        text="Download trace file (.zip)"
                        wrapClassName="automation-spike-trace-dl-tooltip-wrap"
                      >
                        <InlineDownloadIconButton
                          className="automation-spike-run-artifact-dl"
                          ariaLabel="Download Playwright trace file"
                          onClick={() =>
                            void downloadUrlAsFile(
                              result.trace_url,
                              suggestedFilenameFromUrl(result.trace_url, "trace.zip"),
                            )
                          }
                        />
                      </FloatingTooltip>
                      <p
                        className="automation-spike-trace-hint automation-spike-trace-hint--inline"
                        role="note"
                      >
                        Open with: <kbd className="automation-spike-kbd">npx playwright show-trace</kbd>{" "}
                        &lt;file&gt;
                      </p>
                    </div>
                  </div>
                </div>
              ) : null}
              {result.report_url ? (
                <div className="automation-spike-run-artifact">
                  <span className="automation-spike-run-artifact-label">Report</span>
                  <div className="automation-spike-run-artifact-body automation-spike-run-artifact-body--with-dl">
                    <FloatingTooltip text="Download report">
                      <InlineDownloadIconButton
                        className="automation-spike-run-artifact-dl"
                        ariaLabel="Download report"
                        onClick={(e) => {
                          e.preventDefault();
                          void downloadUrlAsFile(
                            result.report_url,
                            suggestedFilenameFromUrl(result.report_url, "report.html"),
                          );
                        }}
                      />
                    </FloatingTooltip>
                    <a
                      href={result.report_url}
                      className="automation-spike-link automation-spike-link--external"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Report
                    </a>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          {result.error ? <p className="automation-spike-err">Error: {result.error}</p> : null}
          {result.analysis || (Array.isArray(result.steps) && result.steps.length > 0) ? (
            <details className="automation-spike-analysis">
              <summary className="automation-spike-analysis-summary">
                <svg
                  className="automation-spike-analysis-chevron"
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden
                >
                  <path
                    d="M9 6l6 6-6 6"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <span className="automation-spike-analysis-summary-title">Analysis</span>
                <span className="automation-spike-analysis-summary-hint">Summary &amp; Selectors</span>
              </summary>
              <div className="automation-spike-analysis-panel">
                {result.analysis ? (
                  <p className="automation-spike-analysis-text">{result.analysis}</p>
                ) : null}
                {Array.isArray(result.steps) && result.steps.length > 0 ? (
                  <div className="automation-spike-analysis-steps">
                    <p className="automation-spike-analysis-steps-label">Displayed Selectors</p>
                    <ol className="automation-spike-steps">
                      {[...result.steps]
                        .sort(
                          (a, b) =>
                            Number(a?.step_index ?? 0) - Number(b?.step_index ?? 0),
                        )
                        .map((s) => (
                        <li key={s.step_index} className={s.pass ? "is-pass" : "is-fail"}>
                          <code>{s.selector}</code> — {s.action}
                          {s.actual_text != null && s.actual_text !== "" ? (
                            <span className="automation-spike-actual">
                              {" "}
                              — text: {s.actual_text.length > 200 ? `${s.actual_text.slice(0, 200)}…` : s.actual_text}
                            </span>
                          ) : null}
                          {s.err && !/^skipped \(previous step failed\)$/i.test(String(s.err).trim()) ? (
                            <span className="automation-spike-err"> — {s.err}</span>
                          ) : null}
                          <div className="automation-spike-step-shot-wrap">
                            <AutomationRunStepScreenshot
                              runId={result?.run_id}
                              step={s}
                              accordionId={stepShotAccordionId(result?.run_id, s, 0)}
                              expandedAccordionId={analysisExpandedShotId}
                              onExpandedAccordionChange={setAnalysisExpandedShotId}
                            />
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
