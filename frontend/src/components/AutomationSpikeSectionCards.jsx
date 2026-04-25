import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import {
  AutoTestRunIconButton,
  FieldInfo,
  FloatingTooltip,
  InlineDownloadIconButton,
  Spinner,
  downloadUrlAsFile,
  suggestedFilenameFromUrl,
} from "./common";
import {
  AutomationRunStepScreenshot,
  stepShotAccordionId,
} from "./AutomationRunStepScreenshot";
import { ResizableScrollClip, useScrollClipHeightPx } from "./LinkedJiraLists";
import { normalizeJiraKeyCsv, normalizeTagCsv, parseTagCsv } from "../utils/tagCsv";
import {
  formatHistoryDate,
  formatHistoryTime,
  formatReportListAt,
  formatSuiteAnalysisAt,
} from "../utils/format";
import { parseBddStepLines as parseBddStepLinesForAnalysis } from "../utils/bddStepLines";

const SAVED_LINKED_LIST_VISIBLE_ROWS = 4;
const SAVED_SELECTORS_VISIBLE_ROWS = 2;
const SUITE_REPORTS_RECENT_LS_KEY = "automation-suite-reports-recent-open";

function buildEnvOptionsBody(envObj, patch) {
  const defTo =
    typeof envObj.automation_default_timeout_ms === "number" &&
    !Number.isNaN(envObj.automation_default_timeout_ms)
      ? envObj.automation_default_timeout_ms
      : 30_000;
  const defPar = (() => {
    const p = envObj.automation_parallel_execution;
    if (typeof p === "number" && p >= 1 && p <= 4) return p;
    return 1;
  })();
  return {
    automation_headless: patch.automation_headless ?? !!envObj.automation_headless,
    automation_screenshot_on_pass:
      patch.automation_screenshot_on_pass ?? !!envObj.automation_screenshot_on_pass,
    automation_trace_file_generation:
      patch.automation_trace_file_generation ??
      !!envObj.automation_trace_file_generation,
    automation_default_timeout_ms: patch.automation_default_timeout_ms ?? defTo,
    automation_parallel_execution:
      typeof patch.automation_parallel_execution === "number" &&
      patch.automation_parallel_execution >= 1 &&
      patch.automation_parallel_execution <= 4
        ? patch.automation_parallel_execution
        : defPar,
  };
}

const SKIP_PREV_FAIL_ERR = /^skipped \(previous step failed\)$/i;

function stepIsPass(step) {
  const p = step?.pass;
  if (p === true || p === 1) return true;
  if (p === false || p === 0) return false;
  return Boolean(p);
}

function shouldShowErrInStepAnalysis(err) {
  if (err == null) return false;
  const t = String(err).trim();
  if (!t) return false;
  return !SKIP_PREV_FAIL_ERR.test(t);
}

function analysisStepClass(step) {
  if (stepIsPass(step)) {
    return "automation-spike-analysis-step automation-spike-analysis-step--pass";
  }
  const e = String(step?.err || "").toLowerCase();
  if (e && /skip/.test(e)) {
    return "automation-spike-analysis-step automation-spike-analysis-step--skipped";
  }
  return "automation-spike-analysis-step automation-spike-analysis-step--fail";
}

function buildStepIndexMap(stepList) {
  const m = new Map();
  if (!Array.isArray(stepList)) return { map: m, hasIndex: false };
  for (const s of stepList) {
    if (!s || typeof s !== "object") continue;
    const k = Number(s.step_index);
    if (Number.isFinite(k) && k >= 0) m.set(k, s);
  }
  return { map: m, hasIndex: m.size > 0 };
}

function stepForBddLineIndex(steps, byIdx, hasIndex, i) {
  if (hasIndex) return byIdx.get(i) ?? null;
  if (i < steps.length) return steps[i];
  return null;
}

function SuiteAnalysisStepsView({ bdd, runDetail }) {
  const [expandedShotId, setExpandedShotId] = useState(null);
  useEffect(() => {
    setExpandedShotId(null);
  }, [runDetail?.run_id]);

  if (runDetail?.noRunId) {
    return (
      <p className="automation-spike-muted">
        Step-level results are not linked for this case yet. Re-run the case from the saved suite to capture them.
      </p>
    );
  }
  if (runDetail?.fetchError) {
    return (
      <p className="automation-spike-err" role="alert">
        {runDetail.fetchError} Step data may be unavailable if it was removed by retention.
      </p>
    );
  }
  if (runDetail?.loading) {
    return <p className="automation-spike-muted">Loading step results…</p>;
  }
  const runId = runDetail?.run_id;
  const lineTexts = parseBddStepLinesForAnalysis(bdd);
  const rawSteps = Array.isArray(runDetail?.steps) ? runDetail.steps : [];
  const runErr = runDetail?.error != null ? String(runDetail.error).trim() : "";
  const st = String(runDetail?.status || "").toLowerCase();
  let steps = rawSteps;
  if (lineTexts.length > 0 && rawSteps.length === 0) {
    if (st === "completed" && !runErr) {
      steps = lineTexts.map((t) => ({ step_text: t, pass: true, err: null }));
    }
  }
  const { map: byStepIndex, hasIndex: stepsHaveIndex } = buildStepIndexMap(steps);
  const rows = [];
  if (lineTexts.length === 0 && steps.length > 0) {
    const ordered = [...steps].sort(
      (a, b) => Number(a?.step_index ?? 0) - Number(b?.step_index ?? 0),
    );
    ordered.forEach((s, i) => {
      const line = String(s?.step_text || "").trim() || "—";
      const showReason =
        shouldShowErrInStepAnalysis(s?.err) && !stepIsPass(s);
      rows.push(
        <div
          key={`st-orphan-${i}`}
          className={analysisStepClass(s)}
          role="listitem"
        >
          <div className="automation-spike-analysis-step-line">{line}</div>
          {showReason ? (
            <div className="automation-spike-analysis-step-reason">{String(s.err)}</div>
          ) : null}
          <AutomationRunStepScreenshot
            runId={runId}
            step={s}
            defaultExpanded={false}
            accordionId={stepShotAccordionId(runId, s, i)}
            expandedAccordionId={expandedShotId}
            onExpandedAccordionChange={setExpandedShotId}
          />
        </div>,
      );
    });
  } else {
    for (let i = 0; i < lineTexts.length; i += 1) {
      const s = stepForBddLineIndex(steps, byStepIndex, stepsHaveIndex, i);
      if (s == null) {
        rows.push(
          <div
            key={`un-${i}`}
            className="automation-spike-analysis-step automation-spike-analysis-step--skipped"
            role="listitem"
          >
            <div className="automation-spike-analysis-step-line">{lineTexts[i]}</div>
            <div className="automation-spike-analysis-step-reason">
              {runErr || "Not executed (run did not reach this step)."}
            </div>
          </div>,
        );
        continue;
      }
      const line = (lineTexts[i] ?? String(s?.step_text || "").trim()) || "—";
      const showReason =
        shouldShowErrInStepAnalysis(s?.err) && !stepIsPass(s);
        rows.push(
        <div
          key={`st-${i}`}
          className={analysisStepClass(s)}
          role="listitem"
        >
          <div className="automation-spike-analysis-step-line">{line}</div>
          {showReason ? (
            <div className="automation-spike-analysis-step-reason">{String(s.err)}</div>
          ) : null}
          <AutomationRunStepScreenshot
            runId={runId}
            step={s}
            defaultExpanded={false}
            accordionId={stepShotAccordionId(runId, s, i)}
            expandedAccordionId={expandedShotId}
            onExpandedAccordionChange={setExpandedShotId}
          />
        </div>,
      );
    }
    if (stepsHaveIndex && lineTexts.length > 0) {
      const extraKs = [...byStepIndex.keys()]
        .filter((k) => k >= lineTexts.length)
        .sort((a, b) => a - b);
      for (const k of extraKs) {
        const s = byStepIndex.get(k);
        if (!s) continue;
        const line = String(s?.step_text || "").trim() || `Step ${k}`;
        const showReason =
          shouldShowErrInStepAnalysis(s?.err) && !stepIsPass(s);
        rows.push(
          <div
            key={`st-extra-${k}`}
            className={analysisStepClass(s)}
            role="listitem"
          >
            <div className="automation-spike-analysis-step-line">{line}</div>
            {showReason ? (
              <div className="automation-spike-analysis-step-reason">{String(s.err)}</div>
            ) : null}
            <AutomationRunStepScreenshot
              runId={runId}
              step={s}
              defaultExpanded={false}
              accordionId={stepShotAccordionId(runId, s, k)}
              expandedAccordionId={expandedShotId}
              onExpandedAccordionChange={setExpandedShotId}
            />
          </div>,
        );
      }
    }
  }
  if (rows.length === 0) {
    return <p className="automation-spike-muted">No step data for this run.</p>;
  }
  return (
    <div className="automation-spike-analysis-steps" role="list" aria-label="Test Steps Results">
      {rows}
    </div>
  );
}

const BDD_HEADER_RE =
  /^(Feature|Rule|Background|Scenario(?:\s+Outline)?|Examples?)\s*:\s*(.*)$/i;
const BDD_STEP_RE = /^(Given|When|Then|And|But)\b\s+(.+)$/i;
const BDD_STAR_RE = /^\*\s+(.+)$/;

function stepKeywordClass(k) {
  const n = k.toLowerCase();
  if (n === "given") return "automation-bdd-kw automation-bdd-kw--given";
  if (n === "when") return "automation-bdd-kw automation-bdd-kw--when";
  if (n === "then") return "automation-bdd-kw automation-bdd-kw--then";
  return "automation-bdd-kw automation-bdd-kw--and";
}

function BddStepsView({ bdd }) {
  const s = String(bdd ?? "");
  if (!s.trim()) {
    return (
      <div className="automation-spike-bdd-view-body">
        <p className="automation-bdd-empty">—</p>
      </div>
    );
  }
  const lines = s.replace(/\r\n/g, "\n").split("\n");
  return (
    <div
      className="automation-spike-bdd-view-body"
      role="region"
      aria-label="BDD test steps"
    >
      <div className="automation-bdd-lines">
      {lines.map((line, i) => {
        const t = line.replace(/\r$/, "");
        const tr = t.trim();
        if (!tr) {
          return <div key={i} className="automation-bdd-line automation-bdd-line--spacer" aria-hidden="true" />;
        }
        if (tr.startsWith("#")) {
          return (
            <div key={i} className="automation-bdd-line automation-bdd-line--comment">
              {t}
            </div>
          );
        }
        if (tr.startsWith("|") && tr.includes("|")) {
          return (
            <div key={i} className="automation-bdd-line automation-bdd-line--table">
              {t}
            </div>
          );
        }
        const h = tr.match(BDD_HEADER_RE);
        if (h) {
          return (
            <div key={i} className="automation-bdd-line automation-bdd-line--header">
              <span className="automation-bdd-hdr-label">{h[1]}:</span>
              {h[2] ? <span className="automation-bdd-hdr-title"> {h[2]}</span> : null}
            </div>
          );
        }
        const step = tr.match(BDD_STEP_RE);
        if (step) {
          return (
            <div key={i} className="automation-bdd-line automation-bdd-line--step">
              <span className={stepKeywordClass(step[1])}>{step[1]}</span>{" "}
              <span className="automation-bdd-line-body">{step[2]}</span>
            </div>
          );
        }
        const st = tr.match(BDD_STAR_RE);
        if (st) {
          return (
            <div key={i} className="automation-bdd-line automation-bdd-line--step">
              <span className="automation-bdd-kw automation-bdd-kw--star">*</span>{" "}
              <span className="automation-bdd-line-body">{st[1]}</span>
            </div>
          );
        }
        if (/^@/.test(tr) && tr.split(/\s+/).every((p) => !p || p.startsWith("@"))) {
          return (
            <div key={i} className="automation-bdd-line automation-bdd-line--tags">
              {tr}
            </div>
          );
        }
        return (
          <div key={i} className="automation-bdd-line automation-bdd-line--plain">
            {t}
          </div>
        );
      })}
      </div>
    </div>
  );
}

const SUITE_TAG_TEST_TYPE_RE = /^(ui|api)$/i;

function suiteCaseSavedLineParts(c) {
  const raw = parseTagCsv(c?.tag);
  let testType = "";
  let restTags;
  if (raw.length && SUITE_TAG_TEST_TYPE_RE.test(String(raw[0]).trim())) {
    testType = String(raw[0]).trim().toUpperCase() === "API" ? "API" : "UI";
    restTags = raw.slice(1);
  } else {
    restTags = raw;
  }
  const tagsStr = restTags.length ? restTags.map((t) => String(t).trim()).filter(Boolean).join(", ") : "";
  const req = String(c?.requirement_ticket_id || "").trim();
  const testId = String(c?.jira_id || "").trim();
  const scenario = String(c?.title || "Untitled").trim() || "Untitled";
  return { testType, tagsStr, req, testId, scenario };
}

function suiteCaseSavedLinePlainText(c) {
  const p = suiteCaseSavedLineParts(c);
  return [p.testType || "—", p.tagsStr || "—", p.req || "—", p.testId || "—", p.scenario].join(" · ");
}

function SuiteCaseJiraScenarioLine({ c }) {
  const p = suiteCaseSavedLineParts(c);
  const segments = [p.testType || "—", p.tagsStr || "—", p.req || "—", p.testId || "—", p.scenario];
  return (
    <>
      {segments.map((text, i) => (
        <span key={i}>
          {i > 0 ? (
            <span className="automation-spike-suite-sep" aria-hidden="true">
              {" "}
              ·{" "}
            </span>
          ) : null}
          {i < 4 ? (
            <span className="automation-spike-suite-jira">{text}</span>
          ) : (
            <span>{text}</span>
          )}
        </span>
      ))}
    </>
  );
}

function suiteCaseDeletePreviewPlainText(c) {
  const s = suiteCaseSavedLinePlainText(c);
  return s.length > 120 ? `${s.slice(0, 120)}…` : s;
}

function lastRunStatusToClassSuffix(status) {
  const s = String(status || "").toLowerCase();
  if (s === "completed") return "pass";
  if (s === "aborted") return "aborted";
  if (!s || s === "running") return null;
  return "fail";
}

function SuiteCaseRow({ c, runDisabled, onView, onRun, onAnalysis, onHistory, onDelete, isRunningInSuite }) {
  const hasSuiteAnalysis = Boolean(String(c.last_suite_analysis ?? "").trim());
  const runColor = lastRunStatusToClassSuffix(c.last_suite_run_status);
  return (
    <li data-suite-case-id={c.id != null && String(c.id).trim() ? String(c.id) : undefined}>
      <span className="automation-spike-suite-title">
        {isRunningInSuite ? (
          <span
            className="automation-spike-suite-running-dot"
            title="Running now"
            aria-label="Running now"
            role="img"
          />
        ) : null}
        <SuiteCaseJiraScenarioLine c={c} />
      </span>
      <div className="automation-spike-suite-item-actions">
        <FloatingTooltip text="View test steps">
          <button
            type="button"
            className="tc-edit-icon-btn"
            onClick={() => onView(c)}
            aria-label="View test steps"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </FloatingTooltip>
        <FloatingTooltip text="Run this saved case">
          <AutoTestRunIconButton
            className={runColor ? `automation-spike-run-by-status--${runColor}` : ""}
            onClick={() => onRun(c)}
            disabled={runDisabled}
            ariaLabel="Run this saved case"
          />
        </FloatingTooltip>
        <FloatingTooltip text="View run analysis. This shows analysis for the last run only.">
          <button
            type="button"
            className="tc-edit-icon-btn"
            onClick={() => onAnalysis(c)}
            disabled={runDisabled || !hasSuiteAnalysis}
            aria-label="View run analysis. This shows analysis for the last run only."
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <line x1="18" y1="20" x2="18" y2="10" />
              <line x1="12" y1="20" x2="12" y2="4" />
              <line x1="6" y1="20" x2="6" y2="14" />
            </svg>
          </button>
        </FloatingTooltip>
        <FloatingTooltip text="View execution history">
          <button
            type="button"
            className="tc-edit-icon-btn"
            onClick={() => onHistory(c)}
            disabled={runDisabled}
            aria-label="View execution history"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
            </svg>
          </button>
        </FloatingTooltip>
        <FloatingTooltip text="Remove from saved suite">
          <button
            type="button"
            className="tc-delete-icon-btn"
            onClick={() => onDelete(c)}
            disabled={runDisabled}
            aria-label="Remove from saved suite"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              <line x1="10" y1="11" x2="10" y2="17" />
              <line x1="14" y1="11" x2="14" y2="17" />
            </svg>
          </button>
        </FloatingTooltip>
      </div>
    </li>
  );
}

const BROWSER_RADIO_VALUES = ["chromium", "chrome", "firefox", "msedge"];

export function AutomationSpikeSectionCards({
  api,
  env,
  onAutomationEnv,
  listRefreshKey = 0,
  spikeRunBusy = false,
  onSuiteRunBusyChange,
  automationRetentionDays = null,
  auditModalOpen = false,
  onDismissAudit,
}) {
  const [suiteCases, setSuiteCases] = useState([]);
  const [selectors, setSelectors] = useState([]);
  const [suiteBusy, setSuiteBusy] = useState(false);
  const [suiteErr, setSuiteErr] = useState("");
  const [lastSuiteReport, setLastSuiteReport] = useState(null);
  const [suiteRunDialogOpen, setSuiteRunDialogOpen] = useState(false);
  const [suiteRunUrlDraft, setSuiteRunUrlDraft] = useState("");
  const [suiteRunUrlInvalid, setSuiteRunUrlInvalid] = useState(false);
  const [suiteRunFilterSelectedTags, setSuiteRunFilterSelectedTags] = useState([]);
  const [suiteRunFilterTagInput, setSuiteRunFilterTagInput] = useState("");
  const [suiteRunFilterTagSuggestOpen, setSuiteRunFilterTagSuggestOpen] = useState(false);
  const [suiteRunFilterSelectedJiras, setSuiteRunFilterSelectedJiras] = useState([]);
  const [suiteRunFilterJiraInput, setSuiteRunFilterJiraInput] = useState("");
  const [suiteRunFilterJiraSuggestOpen, setSuiteRunFilterJiraSuggestOpen] = useState(false);
  const [suiteBddViewCase, setSuiteBddViewCase] = useState(null);
  const [suiteAnalysisViewCase, setSuiteAnalysisViewCase] = useState(null);
  const [suiteAnalysisRunDetail, setSuiteAnalysisRunDetail] = useState(null);
  const [suiteHistoryViewCase, setSuiteHistoryViewCase] = useState(null);
  const [suiteHistoryRows, setSuiteHistoryRows] = useState(null);
  const [suiteHistoryErr, setSuiteHistoryErr] = useState("");
  const [suiteStopKind, setSuiteStopKind] = useState(null);
  const [suiteRunOneDialogOpen, setSuiteRunOneDialogOpen] = useState(false);
  const [suiteRunOneCase, setSuiteRunOneCase] = useState(null);
  const [suiteRunOneUrlDraft, setSuiteRunOneUrlDraft] = useState("");
  const [suiteRunOneUrlInvalid, setSuiteRunOneUrlInvalid] = useState(false);
  const [suiteRunningCaseIds, setSuiteRunningCaseIds] = useState([]);
  const [suiteDeleteCase, setSuiteDeleteCase] = useState(null);
  const [suiteReportsRecentOpen, setSuiteReportsRecentOpen] = useState(() => {
    try {
      return typeof localStorage !== "undefined" && localStorage.getItem(SUITE_REPORTS_RECENT_LS_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [suiteReportsRecentList, setSuiteReportsRecentList] = useState([]);
  const [suiteReportsRecentErr, setSuiteReportsRecentErr] = useState("");
  const [suiteReportsRecentLoading, setSuiteReportsRecentLoading] = useState(false);
  const [browserSaving, setBrowserSaving] = useState(false);
  const [browserErr, setBrowserErr] = useState("");
  const [envOptionsSaving, setEnvOptionsSaving] = useState(false);
  const [automationTimeoutDraft, setAutomationTimeoutDraft] = useState(null);
  const [envOptionsErr, setEnvOptionsErr] = useState("");

  const suiteTagFilterOptions = useMemo(() => {
    const s = new Set();
    for (const c of suiteCases) {
      parseTagCsv(c?.tag).forEach((t) => s.add(t));
    }
    return Array.from(s).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  }, [suiteCases]);

  const suiteJiraFilterOptions = useMemo(() => {
    const s = new Set();
    for (const c of suiteCases) {
      const j = String(c?.jira_id || "").trim();
      if (j) s.add(j);
    }
    return Array.from(s).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  }, [suiteCases]);

  const suiteTagRunFilterSuggestions = useMemo(() => {
    const picked = new Set(suiteRunFilterSelectedTags);
    const q = suiteRunFilterTagInput.trim().toLowerCase();
    return suiteTagFilterOptions.filter(
      (t) => !picked.has(t) && (q === "" || t.toLowerCase().includes(q)),
    );
  }, [suiteTagFilterOptions, suiteRunFilterSelectedTags, suiteRunFilterTagInput]);

  const suiteJiraRunFilterSuggestions = useMemo(() => {
    const picked = new Set(suiteRunFilterSelectedJiras);
    const q = suiteRunFilterJiraInput.trim().toLowerCase();
    return suiteJiraFilterOptions.filter(
      (k) => !picked.has(k) && (q === "" || k.toLowerCase().includes(q)),
    );
  }, [suiteJiraFilterOptions, suiteRunFilterSelectedJiras, suiteRunFilterJiraInput]);

  useEffect(() => {
    const ts = new Set(suiteTagFilterOptions);
    setSuiteRunFilterSelectedTags((p) => p.filter((x) => ts.has(x)));
  }, [suiteTagFilterOptions]);

  useEffect(() => {
    const js = new Set(suiteJiraFilterOptions);
    setSuiteRunFilterSelectedJiras((p) => p.filter((x) => js.has(x)));
  }, [suiteJiraFilterOptions]);

  const addSuiteRunFilterTag = useCallback(
    (t) => {
      if (!t) return;
      setSuiteRunFilterSelectedTags((prev) => {
        if (prev.includes(t)) return prev;
        if (!suiteTagFilterOptions.includes(t)) return prev;
        return [...prev, t].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
      });
      setSuiteRunFilterTagInput("");
    },
    [suiteTagFilterOptions],
  );

  const removeSuiteRunFilterTag = useCallback((t) => {
    setSuiteRunFilterSelectedTags((prev) => prev.filter((x) => x !== t));
  }, []);

  const addSuiteRunFilterJira = useCallback(
    (k) => {
      if (!k) return;
      setSuiteRunFilterSelectedJiras((prev) => {
        if (prev.includes(k)) return prev;
        if (!suiteJiraFilterOptions.includes(k)) return prev;
        return [...prev, k].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
      });
      setSuiteRunFilterJiraInput("");
    },
    [suiteJiraFilterOptions],
  );

  const removeSuiteRunFilterJira = useCallback((k) => {
    setSuiteRunFilterSelectedJiras((prev) => prev.filter((x) => x !== k));
  }, []);

  useEffect(() => {
    try {
      if (suiteReportsRecentOpen) localStorage.setItem(SUITE_REPORTS_RECENT_LS_KEY, "1");
      else localStorage.removeItem(SUITE_REPORTS_RECENT_LS_KEY);
    } catch {}
  }, [suiteReportsRecentOpen]);
  const suiteRunUrlInputRef = useRef(null);
  const suiteRunFilterTagComboRef = useRef(null);
  const suiteRunFilterJiraComboRef = useRef(null);
  const suiteRunOneUrlInputRef = useRef(null);
  const suiteReportsRecentDialogRef = useRef(null);
  const suiteDeleteCaseDialogRef = useRef(null);

  useEffect(() => {
    const onDoc = (e) => {
      if (!suiteRunFilterTagComboRef.current || !suiteRunFilterTagComboRef.current.contains(e.target)) {
        setSuiteRunFilterTagSuggestOpen(false);
      }
      if (!suiteRunFilterJiraComboRef.current || !suiteRunFilterJiraComboRef.current.contains(e.target)) {
        setSuiteRunFilterJiraSuggestOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const suiteListRef = useRef(null);
  const suiteKeyForClip = useMemo(
    () => suiteCases.map((c) => String(c.id ?? "")).join("\0"),
    [suiteCases],
  );
  const suiteScrollEnabled = suiteCases.length > SAVED_LINKED_LIST_VISIBLE_ROWS;
  const suiteClipPx = useScrollClipHeightPx(
    suiteScrollEnabled,
    suiteListRef,
    suiteKeyForClip,
    SAVED_LINKED_LIST_VISIBLE_ROWS,
  );

  const cacheListRef = useRef(null);
  const cacheKeyForClip = useMemo(
    () =>
      selectors
        .map((r) => `${String(r.rowid)}:${String(r.fingerprint ?? "")}:${String(r.step_index ?? "")}`)
        .join("\0"),
    [selectors],
  );
  const cacheScrollEnabled = selectors.length > SAVED_SELECTORS_VISIBLE_ROWS;
  const cacheClipPx = useScrollClipHeightPx(
    cacheScrollEnabled,
    cacheListRef,
    cacheKeyForClip,
    SAVED_SELECTORS_VISIBLE_ROWS,
  );

  const anyCaseMissingUrl = useMemo(
    () => suiteCases.some((c) => !String(c.url || "").trim()),
    [suiteCases],
  );

  const effectiveBrowser = useMemo(() => {
    const b = String(env?.automation_browser || "chromium").toLowerCase();
    if (BROWSER_RADIO_VALUES.includes(b)) return b;
    return "chromium";
  }, [env?.automation_browser]);

  const onBrowserRadioChange = useCallback(
    async (e) => {
      const browser = e.target.value;
      if (!BROWSER_RADIO_VALUES.includes(browser)) return;
      setBrowserErr("");
      setBrowserSaving(true);
      try {
        const d = await api("/automation/browser", "POST", { browser });
        onAutomationEnv?.(d);
      } catch (err) {
        setBrowserErr(err?.message || String(err));
      } finally {
        setBrowserSaving(false);
      }
    },
    [api, onAutomationEnv],
  );

  const onEnvOptionsChange = useCallback(
    async (patch) => {
      if (!env || typeof env !== "object") return;
      setEnvOptionsErr("");
      setEnvOptionsSaving(true);
      try {
        const body = buildEnvOptionsBody(env, patch);
        const d = await api("/automation/env-options", "POST", body);
        onAutomationEnv?.(d);
      } catch (err) {
        setEnvOptionsErr(err?.message || String(err));
      } finally {
        setEnvOptionsSaving(false);
      }
    },
    [api, env, onAutomationEnv],
  );

  const refreshLists = useCallback(async () => {
    try {
      const d = await api("/automation/suite");
      if (Array.isArray(d.cases)) setSuiteCases(d.cases);
    } catch (_) {}
    try {
      const d = await api("/automation/selectors?limit=80");
      if (Array.isArray(d.rows)) setSelectors(d.rows);
    } catch (_) {}
  }, [api]);

  useEffect(() => {
    void refreshLists();
  }, [refreshLists, listRefreshKey]);

  useEffect(() => {
    setAutomationTimeoutDraft(null);
  }, [env?.automation_default_timeout_ms]);

  useEffect(() => {
    onSuiteRunBusyChange?.(suiteBusy);
  }, [suiteBusy, onSuiteRunBusyChange]);

  useEffect(() => {
    if (!suiteBusy) {
      setSuiteRunningCaseIds([]);
      return undefined;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const d = await api("/automation/suite-run-status");
        if (cancelled) return;
        const raw = d?.current_case_ids;
        let ids = [];
        if (Array.isArray(raw) && raw.length) {
          ids = raw.map((x) => String(x).trim()).filter(Boolean);
        } else {
          const one = d?.current_case_id;
          if (one != null && String(one).trim()) ids = [String(one).trim()];
        }
        setSuiteRunningCaseIds(ids);
      } catch {
        if (!cancelled) setSuiteRunningCaseIds([]);
      }
    };
    void tick();
    const interval = window.setInterval(tick, 400);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      setSuiteRunningCaseIds([]);
    };
  }, [suiteBusy, api]);

  const suiteScrollRunningCaseId = useMemo(() => {
    if (!suiteRunningCaseIds.length || !suiteCases.length) return null;
    const want = new Set(suiteRunningCaseIds.map(String));
    const first = suiteCases.find((c) => want.has(String(c.id)));
    return first != null && String(first.id).trim() ? String(first.id) : suiteRunningCaseIds[0] ?? null;
  }, [suiteRunningCaseIds, suiteCases]);

  useEffect(() => {
    if (!suiteScrollRunningCaseId || !suiteListRef.current) return undefined;
    const want = String(suiteScrollRunningCaseId);
    const id = requestAnimationFrame(() => {
      const root = suiteListRef.current;
      if (!root) return;
      for (const li of root.querySelectorAll("li[data-suite-case-id]")) {
        if (li.getAttribute("data-suite-case-id") === want) {
          const smooth =
            typeof window !== "undefined" &&
            !window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
          li.scrollIntoView({ block: "nearest", behavior: smooth ? "smooth" : "auto" });
          break;
        }
      }
    });
    return () => cancelAnimationFrame(id);
  }, [suiteScrollRunningCaseId]);

  useEffect(() => {
    return () => {
      onSuiteRunBusyChange?.(false);
    };
  }, [onSuiteRunBusyChange]);

  const closeRunOneCaseDialog = useCallback(() => {
    setSuiteRunOneDialogOpen(false);
    setSuiteRunOneCase(null);
    setSuiteRunOneUrlInvalid(false);
  }, []);

  const closeRunAllDialog = useCallback(() => {
    setSuiteRunDialogOpen(false);
    setSuiteRunUrlInvalid(false);
  }, []);

  const closeSuiteBddView = useCallback(() => setSuiteBddViewCase(null), []);
  const closeSuiteAnalysisView = useCallback(() => {
    setSuiteAnalysisViewCase(null);
    setSuiteAnalysisRunDetail(null);
  }, []);
  const closeSuiteHistoryView = useCallback(() => {
    setSuiteHistoryViewCase(null);
    setSuiteHistoryRows(null);
    setSuiteHistoryErr("");
  }, []);

  const closeSuiteReportsRecent = useCallback(() => {
    setSuiteReportsRecentOpen(false);
  }, []);

  const closeAllSuiteOverlays = useCallback(() => {
    setSuiteBddViewCase(null);
    setSuiteAnalysisViewCase(null);
    setSuiteAnalysisRunDetail(null);
    setSuiteHistoryViewCase(null);
    setSuiteHistoryRows(null);
    setSuiteHistoryErr("");
    setSuiteRunDialogOpen(false);
    setSuiteRunUrlInvalid(false);
    setSuiteRunOneDialogOpen(false);
    setSuiteRunOneCase(null);
    setSuiteRunOneUrlInvalid(false);
    setSuiteDeleteCase(null);
    setSuiteReportsRecentOpen(false);
  }, []);

  const requestDeleteSuiteCase = useCallback(
    (c) => {
      if (!c?.id) return;
      onDismissAudit?.();
      closeAllSuiteOverlays();
      setSuiteDeleteCase(c);
    },
    [onDismissAudit, closeAllSuiteOverlays],
  );

  const cancelDeleteSuiteCase = useCallback(() => {
    setSuiteDeleteCase(null);
  }, []);

  const confirmDeleteSuiteCase = async () => {
    const c = suiteDeleteCase;
    if (!c?.id) return;
    setSuiteDeleteCase(null);
    setSuiteBusy(true);
    setSuiteErr("");
    try {
      await api(`/automation/suite/${encodeURIComponent(c.id)}`, "DELETE");
      await refreshLists();
    } catch (e) {
      setSuiteErr(e?.message || String(e));
    } finally {
      setSuiteBusy(false);
    }
  };

  const openSuiteBddView = useCallback(
    (c) => {
      onDismissAudit?.();
      closeAllSuiteOverlays();
      setSuiteBddViewCase(c);
    },
    [onDismissAudit, closeAllSuiteOverlays],
  );
  const openSuiteAnalysis = useCallback(
    (c) => {
      onDismissAudit?.();
      closeAllSuiteOverlays();
      setSuiteAnalysisViewCase(c);
    },
    [onDismissAudit, closeAllSuiteOverlays],
  );
  const openSuiteHistory = useCallback(
    (c) => {
      if (!c?.id) return;
      onDismissAudit?.();
      closeAllSuiteOverlays();
      setSuiteHistoryViewCase(c);
      setSuiteHistoryRows(null);
      setSuiteHistoryErr("");
    },
    [onDismissAudit, closeAllSuiteOverlays],
  );

  useLayoutEffect(() => {
    if (auditModalOpen) closeAllSuiteOverlays();
  }, [auditModalOpen, closeAllSuiteOverlays]);

  useEffect(() => {
    if (!suiteReportsRecentOpen) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeSuiteReportsRecent();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [suiteReportsRecentOpen, closeSuiteReportsRecent]);

  useLayoutEffect(() => {
    if (!suiteReportsRecentOpen) return;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
      suiteReportsRecentDialogRef.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(id);
  }, [suiteReportsRecentOpen]);

  useLayoutEffect(() => {
    if (!suiteDeleteCase) return;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
      suiteDeleteCaseDialogRef.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(id);
  }, [suiteDeleteCase]);

  useEffect(() => {
    const hasSuiteModal =
      Boolean(suiteBddViewCase) ||
      Boolean(suiteAnalysisViewCase) ||
      Boolean(suiteHistoryViewCase) ||
      suiteRunDialogOpen ||
      (suiteRunOneDialogOpen && suiteRunOneCase) ||
      Boolean(suiteDeleteCase) ||
      suiteReportsRecentOpen;
    if (!hasSuiteModal) return undefined;

    const onDocPointerDown = (e) => {
      if (!(e.target instanceof Node)) return;
      const t = e.target;
      if (suiteRunOneDialogOpen && suiteRunOneCase) {
        const d = document.getElementById("automation-suite-run-one-url-dialog");
        if (d?.contains(t)) return;
        closeRunOneCaseDialog();
        return;
      }
      if (suiteRunDialogOpen) {
        const d = document.getElementById("automation-suite-run-url-dialog");
        if (d?.contains(t)) return;
        closeRunAllDialog();
        return;
      }
      if (suiteReportsRecentOpen) {
        const d = document.getElementById("automation-suite-reports-recent-dialog");
        if (d?.contains(t)) return;
        closeSuiteReportsRecent();
        return;
      }
      if (suiteDeleteCase) {
        const d = document.getElementById("automation-suite-delete-case-dialog");
        if (d?.contains(t)) return;
        cancelDeleteSuiteCase();
        return;
      }
      if (suiteHistoryViewCase) {
        const d = document.getElementById("automation-suite-run-history-dialog");
        if (d?.contains(t)) return;
        closeSuiteHistoryView();
        return;
      }
      if (suiteAnalysisViewCase) {
        const d = document.getElementById("automation-suite-analysis-dialog");
        if (d?.contains(t)) return;
        closeSuiteAnalysisView();
        return;
      }
      if (suiteBddViewCase) {
        const d = document.getElementById("automation-suite-bdd-view-dialog");
        if (d?.contains(t)) return;
        closeSuiteBddView();
        return;
      }
    };

    const t = window.setTimeout(() => {
      document.addEventListener("pointerdown", onDocPointerDown, true);
    }, 0);

    return () => {
      window.clearTimeout(t);
      document.removeEventListener("pointerdown", onDocPointerDown, true);
    };
  }, [
    suiteBddViewCase,
    suiteAnalysisViewCase,
    suiteHistoryViewCase,
    suiteRunDialogOpen,
    suiteRunOneDialogOpen,
    suiteRunOneCase,
    suiteDeleteCase,
    suiteReportsRecentOpen,
    closeSuiteBddView,
    closeSuiteAnalysisView,
    closeSuiteHistoryView,
    closeRunAllDialog,
    closeRunOneCaseDialog,
    cancelDeleteSuiteCase,
    closeSuiteReportsRecent,
  ]);

  useEffect(() => {
    if (!suiteDeleteCase) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setSuiteDeleteCase(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [suiteDeleteCase]);

  const openRunAllDialog = useCallback(() => {
    onDismissAudit?.();
    closeAllSuiteOverlays();
    setSuiteErr("");
    setSuiteRunUrlInvalid(false);
    setSuiteRunUrlDraft("");
    setSuiteRunDialogOpen(true);
  }, [onDismissAudit, closeAllSuiteOverlays]);

  const openSuiteReportsRecent = useCallback(() => {
    onDismissAudit?.();
    closeAllSuiteOverlays();
    setSuiteErr("");
    setSuiteReportsRecentOpen(true);
  }, [onDismissAudit, closeAllSuiteOverlays]);

  useEffect(() => {
    if (!suiteReportsRecentOpen) return undefined;
    let cancelled = false;
    setSuiteReportsRecentErr("");
    setSuiteReportsRecentLoading(true);
    (async () => {
      try {
        const d = await api("/automation/suite-reports-recent", "GET");
        if (cancelled) return;
        setSuiteReportsRecentList(Array.isArray(d.reports) ? d.reports : []);
      } catch (e) {
        if (!cancelled) {
          setSuiteReportsRecentList([]);
          setSuiteReportsRecentErr(e?.message || String(e));
        }
      } finally {
        if (!cancelled) setSuiteReportsRecentLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [suiteReportsRecentOpen, api]);

  const openRunOneCase = useCallback(
    (c) => {
      if (!c?.id) return;
      onDismissAudit?.();
      closeAllSuiteOverlays();
      setSuiteErr("");
      setSuiteRunOneUrlInvalid(false);
      setSuiteRunOneUrlDraft(String(c.url || "").trim());
      setSuiteRunOneCase(c);
      setSuiteRunOneDialogOpen(true);
    },
    [onDismissAudit, closeAllSuiteOverlays],
  );

  useLayoutEffect(() => {
    if (!suiteRunDialogOpen) return;
    const id = requestAnimationFrame(() => suiteRunUrlInputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [suiteRunDialogOpen]);

  useLayoutEffect(() => {
    if (!suiteRunOneDialogOpen) return;
    const id = requestAnimationFrame(() => suiteRunOneUrlInputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [suiteRunOneDialogOpen]);

  useEffect(() => {
    if (!suiteRunDialogOpen) return undefined;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [suiteRunDialogOpen]);

  useEffect(() => {
    if (!suiteRunOneDialogOpen) return undefined;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [suiteRunOneDialogOpen]);

  useEffect(() => {
    if (!suiteRunDialogOpen) return;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeRunAllDialog();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [suiteRunDialogOpen, closeRunAllDialog]);

  useEffect(() => {
    if (!suiteRunOneDialogOpen) return;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeRunOneCaseDialog();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [suiteRunOneDialogOpen, closeRunOneCaseDialog]);

  useEffect(() => {
    if (!suiteBddViewCase) return undefined;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [suiteBddViewCase]);

  useEffect(() => {
    if (!suiteAnalysisViewCase) return undefined;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [suiteAnalysisViewCase]);

  useEffect(() => {
    if (!suiteAnalysisViewCase) {
      setSuiteAnalysisRunDetail(null);
      return undefined;
    }
    if (!suiteAnalysisViewCase.id) {
      setSuiteAnalysisRunDetail(null);
      return undefined;
    }
    const rid = String(suiteAnalysisViewCase.last_suite_run_id || "").trim();
    if (!rid) {
      setSuiteAnalysisRunDetail({ noRunId: true });
      return undefined;
    }
    let cancelled = false;
    setSuiteAnalysisRunDetail({ loading: true });
    (async () => {
      try {
        const d = await api(`/automation/runs/${encodeURIComponent(rid)}`);
        if (cancelled) return;
        setSuiteAnalysisRunDetail(d);
      } catch (e) {
        if (cancelled) return;
        setSuiteAnalysisRunDetail({ fetchError: e?.message || String(e) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [suiteAnalysisViewCase, api]);

  useEffect(() => {
    if (!suiteBddViewCase) return;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeSuiteBddView();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [suiteBddViewCase, closeSuiteBddView]);

  useEffect(() => {
    if (!suiteAnalysisViewCase) return;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeSuiteAnalysisView();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [suiteAnalysisViewCase, closeSuiteAnalysisView]);

  useEffect(() => {
    if (!suiteHistoryViewCase?.id) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const d = await api(
          `/automation/suite/${encodeURIComponent(suiteHistoryViewCase.id)}/run-history`,
        );
        if (cancelled) return;
        setSuiteHistoryRows(Array.isArray(d.rows) ? d.rows : []);
        setSuiteHistoryErr("");
      } catch (e) {
        if (cancelled) return;
        setSuiteHistoryErr(e?.message || String(e));
        setSuiteHistoryRows([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [suiteHistoryViewCase, api]);

  useEffect(() => {
    if (!suiteHistoryViewCase) return undefined;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [suiteHistoryViewCase]);

  useEffect(() => {
    if (!suiteHistoryViewCase) return;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeSuiteHistoryView();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [suiteHistoryViewCase, closeSuiteHistoryView]);

  const confirmRunAllSuite = async () => {
    setSuiteRunUrlInvalid(false);
    const defaultUrl = suiteRunUrlDraft.trim();
    if (anyCaseMissingUrl && !defaultUrl) {
      setSuiteRunUrlInvalid(true);
      requestAnimationFrame(() => suiteRunUrlInputRef.current?.focus());
      return;
    }
    setSuiteRunDialogOpen(false);
    setSuiteErr("");
    setSuiteBusy(true);
    setLastSuiteReport(null);
    try {
      const out = await api("/automation/suite-run", "POST", {
        case_ids: null,
        default_url: defaultUrl,
        use_tag_filter: suiteRunFilterSelectedTags.length > 0,
        filter_tags: normalizeTagCsv(suiteRunFilterSelectedTags.join(",")),
        use_jira_filter: suiteRunFilterSelectedJiras.length > 0,
        filter_jira_ids: normalizeJiraKeyCsv(suiteRunFilterSelectedJiras.join(",")),
      });
      setLastSuiteReport(out);
      await refreshLists();
    } catch (e) {
      setSuiteErr(e?.message || String(e));
    } finally {
      setSuiteBusy(false);
    }
  };

  const confirmRunOneCase = async () => {
    if (!suiteRunOneCase?.id) return;
    setSuiteRunOneUrlInvalid(false);
    const defaultUrl = suiteRunOneUrlDraft.trim();
    const hasCaseUrl = String(suiteRunOneCase.url || "").trim();
    if (!hasCaseUrl && !defaultUrl) {
      setSuiteRunOneUrlInvalid(true);
      requestAnimationFrame(() => suiteRunOneUrlInputRef.current?.focus());
      return;
    }
    const cid = suiteRunOneCase.id;
    setSuiteRunOneDialogOpen(false);
    setSuiteRunOneCase(null);
    setSuiteErr("");
    setSuiteBusy(true);
    setLastSuiteReport(null);
    try {
      const out = await api("/automation/suite-run", "POST", {
        case_ids: [cid],
        default_url: defaultUrl,
      });
      setLastSuiteReport(out);
      await refreshLists();
    } catch (e) {
      setSuiteErr(e?.message || String(e));
    } finally {
      setSuiteBusy(false);
    }
  };

  const deleteSel = async (rowid) => {
    setSuiteErr("");
    try {
      await api(`/automation/selectors/${rowid}`, "DELETE");
      await refreshLists();
    } catch (e) {
      setSuiteErr(e?.message || String(e));
    }
  };

  const yieldToPaint = () =>
    new Promise((resolve) => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          resolve();
        });
      });
    });

  const requestStopCurrentTest = async () => {
    if (suiteStopKind) return;
    flushSync(() => {
      setSuiteStopKind("current");
    });
    await yieldToPaint();
    try {
      await api("/automation/cancel", "POST", { all_in_suite: false });
    } catch (_) {
    } finally {
      setSuiteStopKind(null);
    }
  };

  const requestStopAllSuite = async () => {
    if (suiteStopKind) return;
    flushSync(() => {
      setSuiteStopKind("all");
    });
    await yieldToPaint();
    try {
      await api("/automation/cancel", "POST", { all_in_suite: true });
    } catch (_) {
    } finally {
      setSuiteStopKind(null);
    }
  };

  return (
    <>
      <div className="card section-card">
        <div className="head automation-spike-metric-head">
          <h2>
            <span className="label-with-info">
              <span>Environment</span>
              <FieldInfo text="Saved in the automation database." />
            </span>
          </h2>
        </div>
        {env && typeof env === "object" ? (
          <div className="automation-spike-env-inset">
            <div className="automation-spike-env-text" role="status">
              <div
                className="automation-spike-env-grid"
                aria-label="Automation environment"
              >
                    <span
                      className="automation-spike-env-grid-label"
                      id="automation-env-browser-label"
                    >
                      Browser
                    </span>
                <div className="automation-spike-env-grid-control">
                  <div
                    className="automation-spike-browser-radios"
                    role="radiogroup"
                    aria-labelledby="automation-env-browser-label"
                  >
                    {[
                      { value: "chromium", label: "Chromium" },
                      { value: "chrome", label: "Chrome" },
                      { value: "firefox", label: "Firefox" },
                      { value: "msedge", label: "Edge" },
                    ].map(({ value, label }) => (
                      <label key={value} className="automation-spike-browser-radio">
                        <input
                          type="radio"
                          name="automation-spike-browser"
                          value={value}
                          checked={effectiveBrowser === value}
                          onChange={onBrowserRadioChange}
                          disabled={
                            browserSaving ||
                            envOptionsSaving ||
                            suiteBusy ||
                            spikeRunBusy
                          }
                        />
                        <span>{label}</span>
                      </label>
                    ))}
                  </div>
                  {browserSaving ? <Spinner /> : null}
                </div>
                {[
                  {
                    name: "automation-opt-headless",
                    label: "Headless",
                    labelledBy: "automation-env-opt-headless",
                    on: !!env.automation_headless,
                    patchOn: { automation_headless: true },
                    patchOff: { automation_headless: false },
                  },
                  {
                    name: "automation-opt-screenshot",
                    label: "Screenshots on Pass",
                    labelledBy: "automation-env-opt-screenshot",
                    on: !!env.automation_screenshot_on_pass,
                    patchOn: { automation_screenshot_on_pass: true },
                    patchOff: { automation_screenshot_on_pass: false },
                  },
                  {
                    name: "automation-opt-trace",
                    label: "Generate Trace File",
                    labelledBy: "automation-env-opt-trace",
                    on: !!env.automation_trace_file_generation,
                    patchOn: { automation_trace_file_generation: true },
                    patchOff: { automation_trace_file_generation: false },
                  },
                ].map(({ name, label, labelledBy, on, patchOn, patchOff }) => (
                  <Fragment key={name}>
                    <span className="automation-spike-env-grid-label" id={labelledBy}>
                      {label}
                    </span>
                    <div className="automation-spike-env-grid-control">
                      <div
                        className="automation-spike-env-bool-radios"
                        role="radiogroup"
                        aria-labelledby={labelledBy}
                      >
                        <label className="automation-spike-env-bool-radio">
                          <input
                            type="radio"
                            name={name}
                            value="0"
                            checked={!on}
                            onChange={() => onEnvOptionsChange(patchOff)}
                            disabled={
                              browserSaving ||
                              envOptionsSaving ||
                              suiteBusy ||
                              spikeRunBusy
                            }
                          />
                          <span>Off</span>
                        </label>
                        <label className="automation-spike-env-bool-radio">
                          <input
                            type="radio"
                            name={name}
                            value="1"
                            checked={on}
                            onChange={() => onEnvOptionsChange(patchOn)}
                            disabled={
                              browserSaving ||
                              envOptionsSaving ||
                              suiteBusy ||
                              spikeRunBusy
                            }
                          />
                          <span>On</span>
                        </label>
                      </div>
                    </div>
                  </Fragment>
                ))}
                <span
                  className="automation-spike-env-grid-label"
                  id="automation-env-opt-parallel"
                >
                  <span className="label-with-info">
                    <span>Parallel Execution</span>
                    <FieldInfo text="Number of parallel tests to be executed in the saved suite (Run all). 1 = one at a time." />
                  </span>
                </span>
                <div className="automation-spike-env-grid-control">
                  <div
                    className="automation-spike-browser-radios automation-spike-parallel-radios"
                    role="radiogroup"
                    aria-labelledby="automation-env-opt-parallel"
                  >
                    {[1, 2, 3, 4].map((n) => {
                      const cur =
                        typeof env.automation_parallel_execution === "number" &&
                        env.automation_parallel_execution >= 1 &&
                        env.automation_parallel_execution <= 4
                          ? env.automation_parallel_execution
                          : 1;
                      return (
                        <label key={n} className="automation-spike-browser-radio">
                          <input
                            type="radio"
                            name="automation-spike-parallel"
                            value={String(n)}
                            checked={cur === n}
                            onChange={() =>
                              void onEnvOptionsChange({ automation_parallel_execution: n })
                            }
                            disabled={
                              browserSaving ||
                              envOptionsSaving ||
                              suiteBusy ||
                              spikeRunBusy
                            }
                          />
                          <span>{n}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
                <span
                  className="automation-spike-env-grid-label"
                  id="automation-env-opt-timeout"
                >
                  <span className="label-with-info">
                    <span>Default Timeout (ms)</span>
                    <FieldInfo text="Playwright default action timeout. Range 1000–600000." />
                  </span>
                </span>
                <div className="automation-spike-env-grid-control">
                  <input
                    type="number"
                    min={1000}
                    max={600000}
                    step={1000}
                    className="automation-spike-env-timeout-input"
                    id="automation-env-default-timeout-ms"
                    aria-labelledby="automation-env-opt-timeout"
                    value={
                      automationTimeoutDraft !== null
                        ? automationTimeoutDraft
                        : String(
                            typeof env.automation_default_timeout_ms === "number"
                              ? env.automation_default_timeout_ms
                              : 30000,
                          )
                    }
                    onChange={(e) => setAutomationTimeoutDraft(e.target.value)}
                    onBlur={() => {
                      const cur =
                        typeof env.automation_default_timeout_ms === "number"
                          ? env.automation_default_timeout_ms
                          : 30000;
                      const raw =
                        automationTimeoutDraft !== null
                          ? automationTimeoutDraft
                          : String(cur);
                      setAutomationTimeoutDraft(null);
                      const v = parseInt(String(raw).trim(), 10);
                      if (Number.isNaN(v)) return;
                      const clamped = Math.min(600000, Math.max(1000, v));
                      if (clamped !== cur) {
                        void onEnvOptionsChange({
                          automation_default_timeout_ms: clamped,
                        });
                      }
                    }}
                    disabled={
                      browserSaving || envOptionsSaving || suiteBusy || spikeRunBusy
                    }
                  />
                </div>
                {browserErr ? (
                  <p
                    className="automation-spike-err automation-spike-env-grid-alert"
                    role="alert"
                  >
                    {browserErr}
                  </p>
                ) : null}
                {envOptionsErr ? (
                  <p
                    className="automation-spike-err automation-spike-env-grid-alert automation-spike-env-options-err"
                    role="alert"
                  >
                    {envOptionsErr}
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        ) : (
          <div className="automation-spike-env-inset">
            <p className="automation-spike-muted">No environment data.</p>
          </div>
        )}
      </div>

      <div className="card section-card">
        <div className="head automation-spike-metric-head">
          <h2>
            <span className="label-with-info">
              <span>Saved Suite</span>
              <FieldInfo text="Saves test scenarios. 'Run All' runs every case in order." />
            </span>
          </h2>
          <span className="linked-jira-tests-count">Count: {suiteCases.length}</span>
        </div>
        {typeof automationRetentionDays === "number" ? (
          <p className="automation-spike-saved-suite-retention" role="status">
            {automationRetentionDays > 0 ? (
              <>
                Reports, Traces, Screenshots and History over{" "}
                {automationRetentionDays}{" "}
                {automationRetentionDays === 1 ? "day" : "days"} will be automatically deleted.
              </>
            ) : (
              <>Retention: automatic removal of old run data is off.</>
            )}
          </p>
        ) : null}
        <div className="automation-spike-saved-suite-toolbar">
          {suiteCases.length > 0 ? (
          <details className="automation-saved-suite-run-filters">
            <summary className="automation-saved-suite-run-filters-summary">
              <span className="automation-saved-suite-run-filters-chevron" aria-hidden>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 18l6-6-6-6" />
                </svg>
              </span>
              <span className="automation-saved-suite-run-filters-title">
                Run Filter
                <span className="automation-saved-suite-run-filters-hint">(Optional)</span>
              </span>
            </summary>
            <div className="automation-saved-suite-run-filters-body">
            <div className="automation-saved-suite-run-filters-field">
              <div className="automation-saved-suite-run-filters-field-head">
                <span className="automation-saved-suite-run-filters-k">
                  Tag <span className="automation-saved-suite-run-filters-hint">(Optional)</span>
                </span>
                <span className="label-with-info automation-saved-suite-run-filters-or-with-info">
                  <span className="automation-saved-suite-run-filters-pill">OR match</span>
                  <FieldInfo text="A test runs if it has at least one of these tags (OR)." />
                </span>
              </div>
              {suiteTagFilterOptions.length === 0 ? (
                <p className="automation-saved-suite-run-filters-empty automation-spike-muted">
                  No tags in saved suite yet. Add tags on saved cases in Auto Tests, then return here.
                </p>
              ) : (
                <div className="automation-saved-suite-run-filters-tag-combo" ref={suiteRunFilterTagComboRef}>
                  <div className="automation-saved-suite-run-filters-tag-box" role="group" aria-label="Choose tags from saved suite">
                    {suiteRunFilterSelectedTags.map((t) => (
                      <span key={t} className="automation-saved-suite-run-filters-tag-chip" title={t}>
                        <span className="automation-saved-suite-run-filters-tag-chip-text">{t}</span>
                        <button
                          type="button"
                          className="automation-saved-suite-run-filters-tag-chip-x"
                          aria-label={`Remove tag ${t}`}
                          onClick={() => removeSuiteRunFilterTag(t)}
                        >
                          <svg
                            width="10"
                            height="10"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden
                          >
                            <path d="M18 6L6 18M6 6l12 12" />
                          </svg>
                        </button>
                      </span>
                    ))}
                    <input
                      id="automation-suite-run-filter-tag-input"
                      type="text"
                      className="automation-saved-suite-run-filters-tag-typeahead"
                      value={suiteRunFilterTagInput}
                      onChange={(e) => {
                        setSuiteRunFilterTagInput(e.target.value);
                        setSuiteRunFilterTagSuggestOpen(true);
                      }}
                      onFocus={() => setSuiteRunFilterTagSuggestOpen(true)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") {
                          setSuiteRunFilterTagSuggestOpen(false);
                          e.stopPropagation();
                        } else if (e.key === "Enter" && suiteTagRunFilterSuggestions.length > 0) {
                          e.preventDefault();
                          addSuiteRunFilterTag(suiteTagRunFilterSuggestions[0]);
                        } else if (
                          e.key === "Backspace" &&
                          !suiteRunFilterTagInput &&
                          suiteRunFilterSelectedTags.length > 0
                        ) {
                          removeSuiteRunFilterTag(
                            suiteRunFilterSelectedTags[suiteRunFilterSelectedTags.length - 1],
                          );
                        }
                      }}
                      placeholder="Type to find tags…"
                      autoComplete="off"
                      autoCorrect="off"
                      spellCheck={false}
                      aria-label="Search and add tags"
                      aria-expanded={suiteRunFilterTagSuggestOpen && suiteRunFilterTagInput.trim() !== ""}
                      aria-controls="automation-suite-run-tag-suggest"
                      aria-autocomplete="list"
                    />
                  </div>
                  {suiteRunFilterTagSuggestOpen && suiteRunFilterTagInput.trim() !== "" ? (
                    <div
                      id="automation-suite-run-tag-suggest"
                      className="automation-saved-suite-run-filters-tag-suggest"
                      role="listbox"
                      aria-label="Tag suggestions"
                    >
                      {suiteTagRunFilterSuggestions.length > 0 ? (
                        suiteTagRunFilterSuggestions.map((t) => (
                          <button
                            key={t}
                            type="button"
                            role="option"
                            className="automation-saved-suite-run-filters-tag-suggest-item"
                            onMouseDown={(e) => {
                              e.preventDefault();
                              addSuiteRunFilterTag(t);
                            }}
                          >
                            {t}
                          </button>
                        ))
                      ) : (
                        <div className="automation-saved-suite-run-filters-tag-suggest-empty" role="status">
                          No matching tags.
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              )}
            </div>
            <div className="automation-saved-suite-run-filters-field">
              <div className="automation-saved-suite-run-filters-field-head">
                <span className="automation-saved-suite-run-filters-k">
                  JIRA ID <span className="automation-saved-suite-run-filters-hint">(Optional)</span>
                </span>
                <span className="label-with-info automation-saved-suite-run-filters-or-with-info">
                  <span className="automation-saved-suite-run-filters-pill">OR match</span>
                  <FieldInfo text="A test runs if its JIRA key matches one of these (OR)." />
                </span>
              </div>
              {suiteJiraFilterOptions.length === 0 ? (
                <p className="automation-saved-suite-run-filters-empty automation-spike-muted">
                  No JIRA IDs in saved suite yet. Add a JIRA ID on saved cases, then return here.
                </p>
              ) : (
                <div className="automation-saved-suite-run-filters-tag-combo" ref={suiteRunFilterJiraComboRef}>
                  <div className="automation-saved-suite-run-filters-tag-box" role="group" aria-label="Choose JIRA issue keys from saved suite">
                    {suiteRunFilterSelectedJiras.map((k) => (
                      <span key={k} className="automation-saved-suite-run-filters-tag-chip" title={k}>
                        <span className="automation-saved-suite-run-filters-tag-chip-text">{k}</span>
                        <button
                          type="button"
                          className="automation-saved-suite-run-filters-tag-chip-x"
                          aria-label={`Remove JIRA key ${k}`}
                          onClick={() => removeSuiteRunFilterJira(k)}
                        >
                          <svg
                            width="10"
                            height="10"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden
                          >
                            <path d="M18 6L6 18M6 6l12 12" />
                          </svg>
                        </button>
                      </span>
                    ))}
                    <input
                      id="automation-suite-run-filter-jira-input"
                      type="text"
                      className="automation-saved-suite-run-filters-tag-typeahead"
                      value={suiteRunFilterJiraInput}
                      onChange={(e) => {
                        setSuiteRunFilterJiraInput(e.target.value);
                        setSuiteRunFilterJiraSuggestOpen(true);
                      }}
                      onFocus={() => setSuiteRunFilterJiraSuggestOpen(true)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") {
                          setSuiteRunFilterJiraSuggestOpen(false);
                          e.stopPropagation();
                        } else if (e.key === "Enter" && suiteJiraRunFilterSuggestions.length > 0) {
                          e.preventDefault();
                          addSuiteRunFilterJira(suiteJiraRunFilterSuggestions[0]);
                        } else if (
                          e.key === "Backspace" &&
                          !suiteRunFilterJiraInput &&
                          suiteRunFilterSelectedJiras.length > 0
                        ) {
                          removeSuiteRunFilterJira(
                            suiteRunFilterSelectedJiras[suiteRunFilterSelectedJiras.length - 1],
                          );
                        }
                      }}
                      placeholder="Type to find JIRA keys…"
                      autoComplete="off"
                      autoCorrect="off"
                      spellCheck={false}
                      aria-label="Search and add JIRA issue keys"
                      aria-expanded={suiteRunFilterJiraSuggestOpen && suiteRunFilterJiraInput.trim() !== ""}
                      aria-controls="automation-suite-run-jira-suggest"
                      aria-autocomplete="list"
                    />
                  </div>
                  {suiteRunFilterJiraSuggestOpen && suiteRunFilterJiraInput.trim() !== "" ? (
                    <div
                      id="automation-suite-run-jira-suggest"
                      className="automation-saved-suite-run-filters-tag-suggest"
                      role="listbox"
                      aria-label="JIRA key suggestions"
                    >
                      {suiteJiraRunFilterSuggestions.length > 0 ? (
                        suiteJiraRunFilterSuggestions.map((j) => (
                          <button
                            key={j}
                            type="button"
                            role="option"
                            className="automation-saved-suite-run-filters-tag-suggest-item"
                            onMouseDown={(e) => {
                              e.preventDefault();
                              addSuiteRunFilterJira(j);
                            }}
                          >
                            {j}
                          </button>
                        ))
                      ) : (
                        <div className="automation-saved-suite-run-filters-tag-suggest-empty" role="status">
                          No matching JIRA keys.
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              )}
            </div>
            </div>
          </details>
          ) : null}
          <div className="automation-spike-suite-actions">
            <div className="automation-spike-suite-actions-lead">
            {suiteCases.length > 0 ? (
              <>
                {lastSuiteReport?.report_url ? (
                  <>
                    <FloatingTooltip text="Open report">
                      <a
                        href={lastSuiteReport.report_url}
                        className="automation-spike-suite-report-icon-link"
                        target="_blank"
                        rel="noreferrer"
                        aria-label="Open auto test report"
                      >
                        <svg
                          width="20"
                          height="20"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden
                        >
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <path d="M14 2v6h6" />
                          <path d="M16 13H8" />
                          <path d="M16 17H8" />
                          <path d="M10 9H8" />
                        </svg>
                      </a>
                    </FloatingTooltip>
                    <FloatingTooltip text="Download report">
                      <span className="automation-spike-suite-report-dl-wrap">
                        <InlineDownloadIconButton
                          className="automation-spike-suite-report-dl"
                          ariaLabel="Download report"
                          onClick={(e) => {
                            e.preventDefault();
                            void downloadUrlAsFile(
                              lastSuiteReport.report_url,
                              suggestedFilenameFromUrl(lastSuiteReport.report_url, "report.html"),
                            );
                          }}
                        />
                      </span>
                    </FloatingTooltip>
                  </>
                ) : null}
                <FloatingTooltip text="View saved test reports">
                  <button
                    type="button"
                    className="automation-spike-suite-recent-reports-icon-btn"
                    onClick={() => void openSuiteReportsRecent()}
                    aria-label="View recent suite run reports"
                  >
                    <svg
                      width="20"
                      height="20"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <rect x="3" y="3" width="18" height="18" rx="2" />
                      <line x1="7" y1="8" x2="16" y2="8" />
                      <line x1="7" y1="12" x2="16" y2="12" />
                      <line x1="7" y1="16" x2="13" y2="16" />
                    </svg>
                  </button>
                </FloatingTooltip>
                <FloatingTooltip
                  text={
                    suiteBusy
                      ? "Running suite…"
                      : "Run all tests in the saved suite, in order"
                  }
                >
                  <button
                    type="button"
                    className="primary automation-spike-suite-run-all-icon"
                    onClick={openRunAllDialog}
                    disabled={suiteBusy || suiteCases.length === 0 || spikeRunBusy}
                    aria-busy={suiteBusy || undefined}
                    aria-label={suiteBusy ? "Running suite…" : "Run all tests in the saved suite"}
                  >
                    {suiteBusy ? (
                      <Spinner />
                    ) : (
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        aria-hidden
                      >
                        <path d="M3 5.5h7v2.25H3V5.5zm0 5.25h5.25V13H3v-2.25zm0 5.25H11v2.25H3V16z" />
                        <path d="M14.5 4.5v15L24 12l-9.5-7.5z" />
                      </svg>
                    )}
                  </button>
                </FloatingTooltip>
              </>
            ) : null}
            {suiteBusy ? (
              <>
                <FloatingTooltip text="Stop the current test now. The suite will continue with the next case.">
                  <button
                    type="button"
                    className="automation-spike-suite-stop-icon-btn"
                    onClick={() => void requestStopCurrentTest()}
                    disabled={suiteStopKind !== null}
                    aria-busy={suiteStopKind === "current"}
                    aria-label={
                      suiteStopKind === "current"
                        ? "Stopping current test…"
                        : "Stop the currently running test"
                    }
                  >
                    {suiteStopKind === "current" ? (
                      <Spinner />
                    ) : (
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        aria-hidden
                      >
                        <rect x="5" y="5" width="14" height="14" rx="1.5" />
                      </svg>
                    )}
                  </button>
                </FloatingTooltip>
                <FloatingTooltip text="Stop the whole suite run.">
                  <button
                    type="button"
                    className="automation-spike-suite-stop-icon-btn"
                    onClick={() => void requestStopAllSuite()}
                    disabled={suiteStopKind !== null}
                    aria-busy={suiteStopKind === "all"}
                    aria-label={
                      suiteStopKind === "all"
                        ? "Stopping entire suite…"
                        : "Stop the entire suite run"
                    }
                  >
                    {suiteStopKind === "all" ? (
                      <Spinner />
                    ) : (
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        aria-hidden
                      >
                        <rect x="3" y="3" width="7" height="7" rx="1.25" />
                        <rect x="14" y="3" width="7" height="7" rx="1.25" />
                        <rect x="3" y="14" width="7" height="7" rx="1.25" />
                        <rect x="14" y="14" width="7" height="7" rx="1.25" />
                      </svg>
                    )}
                  </button>
                </FloatingTooltip>
              </>
            ) : null}
            </div>
          </div>
        </div>
        {suiteErr ? <p className="automation-spike-err">{suiteErr}</p> : null}
        {suiteCases.length === 0 ? (
          <p className="automation-spike-muted">No saved cases yet. Use &quot;Save to Suite&quot; in the form above to add a new test.</p>
        ) : (
          <div
            className="automation-spike-suite-linked-wrap"
            role="region"
            aria-label={`Saved suite, ${suiteCases.length} test cases. Scroll when more than ${SAVED_LINKED_LIST_VISIBLE_ROWS}.`}
          >
            <ResizableScrollClip
              scroll={suiteScrollEnabled}
              clipPx={suiteClipPx}
              className="linked-jira-tests-scroll"
              storageKey="automationSuiteListScrollExtra"
            >
              <ul ref={suiteListRef} className="automation-spike-suite-list">
                {suiteCases.map((c, i) => (
                  <SuiteCaseRow
                    key={`suite-${i}-${String(c.id)}`}
                    c={c}
                    isRunningInSuite={Boolean(
                      suiteRunningCaseIds.length > 0 &&
                        suiteRunningCaseIds.some((id) => String(c.id) === String(id)),
                    )}
                    runDisabled={suiteBusy || spikeRunBusy}
                    onView={openSuiteBddView}
                    onRun={openRunOneCase}
                    onAnalysis={openSuiteAnalysis}
                    onHistory={openSuiteHistory}
                    onDelete={requestDeleteSuiteCase}
                  />
                ))}
              </ul>
            </ResizableScrollClip>
          </div>
        )}
      </div>

      <div className="card section-card">
        <div className="head automation-spike-metric-head">
          <h2>
            <span className="label-with-info">
              <span>Saved Selectors</span>
              <FieldInfo text="Cached selectors from successful runs, so later runs can resolve steps more quickly when the app matches a known state." />
            </span>
          </h2>
          <span className="linked-jira-tests-count">Count: {selectors.length}</span>
        </div>
        {selectors.length === 0 ? (
          <p className="automation-spike-muted">No cached rows yet. They appear after successful runs with new fingerprints.</p>
        ) : (
          <div
            className="automation-spike-cache-linked-wrap"
            role="region"
            aria-label={`Cached selectors, ${selectors.length} rows. Scroll when more than ${SAVED_SELECTORS_VISIBLE_ROWS}.`}
          >
            <ResizableScrollClip
              scroll={cacheScrollEnabled}
              clipPx={cacheClipPx}
              className="linked-jira-tests-scroll"
              storageKey="automationCacheListScrollExtra"
            >
              <ul ref={cacheListRef} className="automation-spike-sel-list">
                {selectors.map((r, i) => (
                  <li key={`sel-${i}-${r.rowid}-${r.fingerprint}-${r.step_index}`}>
                    <code className="automation-spike-sel-code">{r.selector}</code>
                    <FloatingTooltip text="Remove saved selector">
                      <button
                        type="button"
                        className="tc-delete-icon-btn"
                        onClick={() => deleteSel(r.rowid)}
                        aria-label="Remove saved selector"
                      >
                        <svg
                          width="18"
                          height="18"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden
                        >
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          <line x1="10" y1="11" x2="10" y2="17" />
                          <line x1="14" y1="11" x2="14" y2="17" />
                        </svg>
                      </button>
                    </FloatingTooltip>
                  </li>
                ))}
              </ul>
            </ResizableScrollClip>
          </div>
        )}
      </div>

      {suiteBddViewCase ? (
        <div
          className="modal-backdrop modal-backdrop--main-area"
          role="presentation"
          onClick={closeSuiteBddView}
        >
          <div
            id="automation-suite-bdd-view-dialog"
            className="modal-dialog modal-dialog-tc-edit automation-spike-bdd-view-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="automation-suite-bdd-view-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-dialog-head">
              <h2 id="automation-suite-bdd-view-title" className="modal-dialog-title">
                Test Steps
              </h2>
              <button type="button" className="modal-dialog-close" onClick={closeSuiteBddView} aria-label="Close">
                ×
              </button>
            </div>
            <div className="modal-dialog-tc-edit-body">
              <p className="automation-spike-bdd-view-scenario">
                <SuiteCaseJiraScenarioLine c={suiteBddViewCase} />
              </p>
              <BddStepsView bdd={suiteBddViewCase.bdd} />
            </div>
            <div className="modal-dialog-tc-edit-actions">
              <button type="button" className="primary" onClick={closeSuiteBddView}>
                Close
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {suiteAnalysisViewCase ? (
        <div
          className="modal-backdrop modal-backdrop--main-area"
          role="presentation"
          onClick={closeSuiteAnalysisView}
        >
          <div
            id="automation-suite-analysis-dialog"
            className="modal-dialog modal-dialog-tc-edit automation-spike-bdd-view-modal automation-spike-suite-analysis-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="automation-suite-analysis-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-dialog-head">
              <h2 id="automation-suite-analysis-title" className="modal-dialog-title">
                Analysis
              </h2>
              <button type="button" className="modal-dialog-close" onClick={closeSuiteAnalysisView} aria-label="Close">
                ×
              </button>
            </div>
            <div className="modal-dialog-tc-edit-body automation-spike-suite-analysis-body">
              {formatSuiteAnalysisAt(suiteAnalysisViewCase.last_suite_analysis_at) ? (
                <time
                  className="automation-spike-suite-analysis-saved-at"
                  dateTime={String(suiteAnalysisViewCase.last_suite_analysis_at || "")}
                >
                  {formatSuiteAnalysisAt(suiteAnalysisViewCase.last_suite_analysis_at)}
                </time>
              ) : null}
              <div className="automation-spike-suite-analysis-scenario-block">
                <div className="automation-spike-suite-analysis-section-label">Test Case</div>
                <p className="automation-spike-suite-analysis-scenario-text">
                  <SuiteCaseJiraScenarioLine c={suiteAnalysisViewCase} />
                </p>
              </div>
              <div className="automation-spike-suite-analysis-bdd-block">
                <div className="automation-spike-suite-analysis-section-label">Test Steps Results</div>
                <SuiteAnalysisStepsView
                  bdd={suiteAnalysisViewCase.bdd}
                  runDetail={suiteAnalysisRunDetail}
                />
              </div>
              {suiteAnalysisRunDetail &&
              !suiteAnalysisRunDetail.loading &&
              !suiteAnalysisRunDetail.fetchError &&
              !suiteAnalysisRunDetail.noRunId &&
              suiteAnalysisRunDetail.trace_url ? (
                <div className="automation-spike-suite-analysis-trace-block">
                  <div className="automation-spike-suite-analysis-section-label">Playwright Trace File</div>
                  <div className="automation-spike-suite-analysis-trace-row">
                    <p
                      className="automation-spike-trace-hint automation-spike-suite-analysis-trace-hint"
                      role="note"
                    >
                      Open with: <kbd className="automation-spike-kbd">npx playwright show-trace</kbd>{" "}
                      &lt;file&gt;
                    </p>
                    <span
                      className="automation-spike-step-shot-dl-wrap"
                      onClick={(e) => e.stopPropagation()}
                      onPointerDown={(e) => e.stopPropagation()}
                      role="presentation"
                    >
                      <FloatingTooltip text="Download trace file (.zip)">
                        <InlineDownloadIconButton
                          className="automation-spike-step-shot-dl"
                          ariaLabel="Download Playwright trace file"
                          onClick={() =>
                            void downloadUrlAsFile(
                              suiteAnalysisRunDetail.trace_url,
                              suggestedFilenameFromUrl(
                                suiteAnalysisRunDetail.trace_url,
                                "trace.zip",
                              ),
                            )
                          }
                        />
                      </FloatingTooltip>
                    </span>
                  </div>
                </div>
              ) : null}
              <div className="automation-spike-suite-analysis-panel">
                <div className="automation-spike-suite-analysis-panel-head">
                  <div className="automation-spike-suite-analysis-section-label">Post-Run Summary</div>
                </div>
                <div
                  className="automation-spike-suite-analysis-text"
                  role="region"
                  aria-label="Run analysis"
                >
                  {String(suiteAnalysisViewCase.last_suite_analysis || "").trim() || "—"}
                </div>
              </div>
            </div>
            <div className="modal-dialog-tc-edit-actions">
              <button type="button" className="secondary" onClick={closeSuiteAnalysisView}>
                Close
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {suiteHistoryViewCase ? (
        <div
          className="modal-backdrop modal-backdrop--main-area"
          role="presentation"
          onClick={closeSuiteHistoryView}
        >
          <div
            id="automation-suite-run-history-dialog"
            className="modal-dialog modal-dialog-tc-edit automation-spike-bdd-view-modal automation-spike-suite-run-history-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="automation-suite-run-history-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-dialog-head">
              <h2 id="automation-suite-run-history-title" className="modal-dialog-title">
                Execution History
              </h2>
              <button type="button" className="modal-dialog-close" onClick={closeSuiteHistoryView} aria-label="Close">
                ×
              </button>
            </div>
            <div className="modal-dialog-tc-edit-body automation-spike-suite-run-history-body">
              <p className="automation-spike-bdd-view-scenario">
                <SuiteCaseJiraScenarioLine c={suiteHistoryViewCase} />
              </p>
              {suiteHistoryErr ? (
                <p className="automation-spike-err" role="alert">
                  {suiteHistoryErr}
                </p>
              ) : null}
              {suiteHistoryRows == null ? (
                <p className="automation-spike-muted">Loading…</p>
              ) : suiteHistoryRows.length === 0 && !suiteHistoryErr ? (
                <p className="automation-spike-muted">No saved-suite runs yet. History is recorded when you use Run or Run All.</p>
              ) : (
                <div className="automation-spike-run-history-table-wrap" role="region" aria-label="Run history">
                  <table className="automation-spike-run-history-table">
                    <thead>
                      <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Time</th>
                        <th scope="col">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {suiteHistoryRows.map((row, hi) => {
                        const t = String(row.finished_at ?? "");
                        const st = String(row.status ?? "—");
                        const u = st.toUpperCase();
                        let statusMod = "automation-spike-run-history-status--fail";
                        if (u === "PASS") statusMod = "automation-spike-run-history-status--pass";
                        else if (u === "ABORTED") statusMod = "automation-spike-run-history-status--aborted";
                        return (
                          <tr key={`${String(row.run_id ?? "")}-${t}-${hi}`}>
                            <td>{formatHistoryDate(t)}</td>
                            <td>
                              <time dateTime={t}>{formatHistoryTime(t)}</time>
                            </td>
                            <td>
                              <span
                                className={`automation-spike-run-history-status ${statusMod}`}
                              >
                                {st}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div className="modal-dialog-tc-edit-actions">
              <button type="button" className="secondary" onClick={closeSuiteHistoryView}>
                Close
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {suiteDeleteCase ? (
        <div
          className="modal-backdrop modal-backdrop--main-area"
          role="presentation"
          onClick={cancelDeleteSuiteCase}
        >
          <div
            id="automation-suite-delete-case-dialog"
            ref={suiteDeleteCaseDialogRef}
            className="modal-dialog modal-dialog-tc-edit"
            role="dialog"
            tabIndex={-1}
            aria-modal="true"
            aria-labelledby="automation-suite-delete-case-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-dialog-head">
              <h2 id="automation-suite-delete-case-title" className="modal-dialog-title">
                Remove from saved suite?
              </h2>
              <button
                type="button"
                className="modal-dialog-close"
                onClick={cancelDeleteSuiteCase}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <div className="modal-dialog-tc-edit-body">
              <p className="modal-dialog-sub">
                This removes &quot;{suiteCaseDeletePreviewPlainText(suiteDeleteCase)}&quot; from the saved suite. This
                cannot be undone.
              </p>
              <div className="modal-dialog-tc-edit-actions">
                <button
                  type="button"
                  className="primary danger-btn"
                  onClick={() => void confirmDeleteSuiteCase()}
                  disabled={suiteBusy}
                >
                  Remove
                </button>
                <button type="button" onClick={cancelDeleteSuiteCase} disabled={suiteBusy}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {suiteReportsRecentOpen ? (
        <div
          className="modal-backdrop modal-backdrop--main-area"
          role="presentation"
          onClick={closeSuiteReportsRecent}
        >
          <div
            id="automation-suite-reports-recent-dialog"
            ref={suiteReportsRecentDialogRef}
            className="modal-dialog modal-dialog-tc-edit automation-spike-bdd-view-modal automation-spike-suite-reports-recent-modal"
            role="dialog"
            tabIndex={-1}
            aria-modal="true"
            aria-labelledby="automation-suite-reports-recent-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-dialog-head">
              <h2 id="automation-suite-reports-recent-title" className="modal-dialog-title">
                Auto Test Reports
              </h2>
              <button
                type="button"
                className="modal-dialog-close"
                onClick={closeSuiteReportsRecent}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <div className="modal-dialog-tc-edit-body">
              {suiteReportsRecentErr ? (
                <p className="automation-spike-err" role="alert">
                  {suiteReportsRecentErr}
                </p>
              ) : null}
              {suiteReportsRecentLoading ? (
                <p className="automation-spike-muted">
                  <Spinner /> <span>Loading…</span>
                </p>
              ) : suiteReportsRecentList.length === 0 && !suiteReportsRecentErr ? (
                <p className="automation-spike-muted">No reports yet.</p>
              ) : (
                <div
                  className="automation-spike-run-history-table-wrap automation-spike-suite-reports-table-wrap"
                  role="region"
                  aria-label="Recent suite run reports"
                >
                  <table className="automation-spike-run-history-table">
                    <tbody>
                      {suiteReportsRecentList.map((row) => (
                        <tr key={row.name}>
                          <td>{formatReportListAt(row.modified_at)}</td>
                          <td>
                            <code className="automation-spike-suite-reports-filename">{row.name}</code>
                          </td>
                          <td className="automation-spike-suite-reports-actions-col">
                            <span className="automation-spike-suite-reports-actions">
                              <FloatingTooltip text="Open report">
                                <a
                                  href={row.report_url}
                                  className="automation-spike-suite-report-icon-link"
                                  target="_blank"
                                  rel="noreferrer"
                                  aria-label={`Open report ${row.name}`}
                                >
                                  <svg
                                    width="20"
                                    height="20"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    aria-hidden
                                  >
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                                    <path d="M14 2v6h6" />
                                    <path d="M16 13H8" />
                                    <path d="M16 17H8" />
                                    <path d="M10 9H8" />
                                  </svg>
                                </a>
                              </FloatingTooltip>
                              <FloatingTooltip text="Download report">
                                <span className="automation-spike-suite-report-dl-wrap">
                                  <InlineDownloadIconButton
                                    className="automation-spike-suite-report-dl"
                                    ariaLabel={`Download report ${row.name}`}
                                    onClick={() =>
                                      void downloadUrlAsFile(
                                        row.report_url,
                                        suggestedFilenameFromUrl(row.report_url, row.name),
                                      )
                                    }
                                  />
                                </span>
                              </FloatingTooltip>
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div className="modal-dialog-tc-edit-actions">
              <button type="button" onClick={closeSuiteReportsRecent}>
                Close
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {suiteRunDialogOpen ? (
        <div
          className="modal-backdrop modal-backdrop--main-area"
          role="presentation"
          onClick={closeRunAllDialog}
        >
          <div
            id="automation-suite-run-url-dialog"
            className="modal-dialog modal-dialog-tc-edit"
            role="dialog"
            aria-modal="true"
            aria-labelledby="automation-suite-run-url-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-dialog-head">
              <h2 id="automation-suite-run-url-title" className="modal-dialog-title">
                Run All Tests
              </h2>
              <button type="button" className="modal-dialog-close" onClick={closeRunAllDialog} aria-label="Close">
                ×
              </button>
            </div>
            <div className="modal-dialog-tc-edit-body">
              <div className="automation-suite-run-url-field">
                <label htmlFor="automation-suite-run-default-url" className="label-with-info">
                  <span>URL for this run</span>
                  <FieldInfo text="Application URL. Use a full URL (e.g. https://example.com)." />
                </label>
                <input
                  id="automation-suite-run-default-url"
                  ref={suiteRunUrlInputRef}
                  type="url"
                  className={
                    suiteRunUrlInvalid ? "tc-edit-input tc-edit-input--invalid" : "tc-edit-input"
                  }
                  value={suiteRunUrlDraft}
                  aria-invalid={suiteRunUrlInvalid ? true : undefined}
                  onChange={(e) => {
                    setSuiteRunUrlDraft(e.target.value);
                    if (suiteRunUrlInvalid) setSuiteRunUrlInvalid(false);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void confirmRunAllSuite();
                    }
                  }}
                  autoComplete="off"
                />
              </div>
            </div>
            <div className="modal-dialog-tc-edit-actions">
              <button type="button" onClick={closeRunAllDialog}>
                Cancel
              </button>
              <button type="button" className="primary" onClick={() => void confirmRunAllSuite()}>
                Run Suite
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {suiteRunOneDialogOpen && suiteRunOneCase ? (
        <div
          className="modal-backdrop modal-backdrop--main-area"
          role="presentation"
          onClick={closeRunOneCaseDialog}
        >
          <div
            id="automation-suite-run-one-url-dialog"
            className="modal-dialog modal-dialog-tc-edit"
            role="dialog"
            aria-modal="true"
            aria-labelledby="automation-suite-run-one-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-dialog-head">
              <h2 id="automation-suite-run-one-title" className="modal-dialog-title">
                Run this Test
              </h2>
              <button
                type="button"
                className="modal-dialog-close"
                onClick={closeRunOneCaseDialog}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <div className="modal-dialog-tc-edit-body">
              <p className="automation-spike-run-one-dialog-scenario">
                <SuiteCaseJiraScenarioLine c={suiteRunOneCase} />
              </p>
              <div className="automation-suite-run-url-field">
                <label htmlFor="automation-suite-run-one-url" className="label-with-info">
                  <span>URL for this run</span>
                  <FieldInfo
                    text={
                      String(suiteRunOneCase.url || "").trim()
                        ? "Override the URL stored on the case, or leave as-is. Full URL (e.g. https://example.com)."
                        : "Required when this case has no saved URL. Full URL (e.g. https://example.com)."
                    }
                  />
                </label>
                <input
                  id="automation-suite-run-one-url"
                  ref={suiteRunOneUrlInputRef}
                  type="url"
                  className={
                    suiteRunOneUrlInvalid ? "tc-edit-input tc-edit-input--invalid" : "tc-edit-input"
                  }
                  value={suiteRunOneUrlDraft}
                  aria-invalid={suiteRunOneUrlInvalid ? true : undefined}
                  onChange={(e) => {
                    setSuiteRunOneUrlDraft(e.target.value);
                    if (suiteRunOneUrlInvalid) setSuiteRunOneUrlInvalid(false);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void confirmRunOneCase();
                    }
                  }}
                  autoComplete="off"
                />
              </div>
            </div>
            <div className="modal-dialog-tc-edit-actions">
              <button type="button" onClick={closeRunOneCaseDialog}>
                Cancel
              </button>
              <button type="button" className="primary" onClick={() => void confirmRunOneCase()}>
                Run
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
