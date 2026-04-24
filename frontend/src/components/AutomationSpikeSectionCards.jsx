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
import { FieldInfo, FloatingTooltip, Spinner } from "./common";
import { ResizableScrollClip, useScrollClipHeightPx } from "./LinkedJiraLists";

const SAVED_LINKED_LIST_VISIBLE_ROWS = 4;
const SAVED_SELECTORS_VISIBLE_ROWS = 2;

function buildEnvOptionsBody(envObj, patch) {
  return {
    automation_headless: patch.automation_headless ?? !!envObj.automation_headless,
    automation_screenshot_on_pass:
      patch.automation_screenshot_on_pass ?? !!envObj.automation_screenshot_on_pass,
    automation_trace_file_generation:
      patch.automation_trace_file_generation ??
      !!envObj.automation_trace_file_generation,
  };
}

function formatSuiteAnalysisAt(iso) {
  if (iso == null || !String(iso).trim()) return "";
  const d = new Date(String(iso));
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function formatHistoryDate(iso) {
  if (iso == null || !String(iso).trim()) return "—";
  const d = new Date(String(iso));
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

function formatHistoryTime(iso) {
  if (iso == null || !String(iso).trim()) return "—";
  const d = new Date(String(iso));
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString(undefined, { timeStyle: "short" });
}

const BDD_ANALYSIS_STEP = /^(Given|When|Then|And)\b/i;
const BDD_ANALYSIS_SKIP_HDR = /^(Feature|Scenario|Background)\b/i;

function parseBddStepLinesForAnalysis(bdd) {
  const out = [];
  for (const line of String(bdd || "").split(/\r?\n/)) {
    const s = line.trim();
    if (!s || BDD_ANALYSIS_SKIP_HDR.test(s)) continue;
    if (BDD_ANALYSIS_STEP.test(s)) out.push(s);
  }
  return out;
}

function stepIsPass(step) {
  const p = step?.pass;
  if (p === true || p === 1) return true;
  if (p === false || p === 0) return false;
  return Boolean(p);
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

function SuiteAnalysisStepsView({ bdd, runDetail }) {
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
  const rows = [];
  for (let i = 0; i < steps.length; i += 1) {
    const s = steps[i];
    const line = lineTexts[i] != null ? lineTexts[i] : String(s?.step_text || "").trim() || "—";
    const showReason = s?.err != null && String(s.err).trim() !== "" && !stepIsPass(s);
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
      </div>,
    );
  }
  for (let j = steps.length; j < lineTexts.length; j += 1) {
    rows.push(
      <div
        key={`un-${j}`}
        className="automation-spike-analysis-step automation-spike-analysis-step--skipped"
        role="listitem"
      >
        <div className="automation-spike-analysis-step-line">{lineTexts[j]}</div>
        <div className="automation-spike-analysis-step-reason">
          {runErr || "Not executed (run did not reach this step)."}
        </div>
      </div>,
    );
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

function SuiteCaseJiraScenarioLine({ c }) {
  const scenario = (c.title || "Untitled").trim() || "Untitled";
  const j = (c.jira_id || "").trim();
  if (j) {
    return (
      <>
        <span className="automation-spike-suite-jira">{j}</span>
        <span className="automation-spike-suite-sep" aria-hidden="true">
          {" "}
          ·{" "}
        </span>
        {scenario}
      </>
    );
  }
  return scenario;
}

function SuiteCaseRow({ c, runDisabled, onView, onRun, onAnalysis, onHistory, onDelete, isRunningInSuite }) {
  const hasSuiteAnalysis = Boolean(String(c.last_suite_analysis ?? "").trim());
  return (
    <li>
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
            disabled={runDisabled}
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
          <button
            type="button"
            className="tc-edit-icon-btn"
            onClick={() => onRun(c)}
            disabled={runDisabled}
            aria-label="Run this saved case"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="currentColor"
              stroke="none"
              aria-hidden
            >
              <polygon points="7 4 7 20 20 12 7 4" />
            </svg>
          </button>
        </FloatingTooltip>
        <FloatingTooltip text="View run analysis">
          <button
            type="button"
            className="tc-edit-icon-btn"
            onClick={() => onAnalysis(c)}
            disabled={runDisabled || !hasSuiteAnalysis}
            aria-label="View run analysis"
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
            onClick={() => onDelete(c.id)}
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

const BROWSER_RADIO_VALUES = ["chromium", "firefox", "msedge"];

export function AutomationSpikeSectionCards({
  api,
  env,
  onAutomationEnv,
  listRefreshKey = 0,
  spikeRunBusy = false,
  onSuiteRunBusyChange,
}) {
  const [suiteCases, setSuiteCases] = useState([]);
  const [selectors, setSelectors] = useState([]);
  const [suiteBusy, setSuiteBusy] = useState(false);
  const [suiteErr, setSuiteErr] = useState("");
  const [lastSuiteReport, setLastSuiteReport] = useState(null);
  const [suiteRunDialogOpen, setSuiteRunDialogOpen] = useState(false);
  const [suiteRunUrlDraft, setSuiteRunUrlDraft] = useState("");
  const [suiteRunUrlInvalid, setSuiteRunUrlInvalid] = useState(false);
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
  const [suiteRunningCaseId, setSuiteRunningCaseId] = useState(null);
  const [browserSaving, setBrowserSaving] = useState(false);
  const [browserErr, setBrowserErr] = useState("");
  const [envOptionsSaving, setEnvOptionsSaving] = useState(false);
  const [envOptionsErr, setEnvOptionsErr] = useState("");
  const suiteRunUrlInputRef = useRef(null);
  const suiteRunOneUrlInputRef = useRef(null);

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
    onSuiteRunBusyChange?.(suiteBusy);
  }, [suiteBusy, onSuiteRunBusyChange]);

  useEffect(() => {
    if (!suiteBusy) {
      setSuiteRunningCaseId(null);
      return undefined;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const d = await api("/automation/suite-run-status");
        if (cancelled) return;
        const id = d?.current_case_id;
        setSuiteRunningCaseId(id != null && String(id).trim() ? String(id).trim() : null);
      } catch {
        if (!cancelled) setSuiteRunningCaseId(null);
      }
    };
    void tick();
    const interval = window.setInterval(tick, 400);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      setSuiteRunningCaseId(null);
    };
  }, [suiteBusy, api]);

  useEffect(() => {
    return () => {
      onSuiteRunBusyChange?.(false);
    };
  }, [onSuiteRunBusyChange]);

  const deleteCase = async (id) => {
    if (!id) return;
    setSuiteBusy(true);
    setSuiteErr("");
    try {
      await api(`/automation/suite/${encodeURIComponent(id)}`, "DELETE");
      await refreshLists();
    } catch (e) {
      setSuiteErr(e?.message || String(e));
    } finally {
      setSuiteBusy(false);
    }
  };

  const openRunAllDialog = useCallback(() => {
    setSuiteErr("");
    setSuiteRunUrlInvalid(false);
    setSuiteRunUrlDraft("");
    setSuiteRunDialogOpen(true);
  }, []);

  const openRunOneCase = useCallback((c) => {
    if (!c?.id) return;
    setSuiteErr("");
    setSuiteRunOneUrlInvalid(false);
    setSuiteRunOneUrlDraft(String(c.url || "").trim());
    setSuiteRunOneCase(c);
    setSuiteRunOneDialogOpen(true);
  }, []);

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
  const openSuiteHistory = useCallback((c) => {
    if (!c?.id) return;
    setSuiteHistoryViewCase(c);
    setSuiteHistoryRows(null);
    setSuiteHistoryErr("");
  }, []);

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
              <FieldInfo text="Saved in the automation database. Defaults come from environment variables until you change a value here." />
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
                      { value: "chromium", label: "Chrome" },
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
                {browserErr ? (
                  <p
                    className="automation-spike-err automation-spike-env-grid-alert"
                    role="alert"
                  >
                    {browserErr}
                  </p>
                ) : null}
                {envOptionsSaving ? (
                  <div className="automation-spike-env-grid-foot automation-spike-env-options-saving">
                    <Spinner /> <span className="automation-spike-muted">Saving…</span>
                  </div>
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
        {suiteErr ? <p className="automation-spike-err">{suiteErr}</p> : null}
        <div className="automation-spike-suite-actions">
          {lastSuiteReport?.report_url ? (
            <a
              href={lastSuiteReport.report_url}
              className="automation-spike-link automation-spike-suite-report-link"
              target="_blank"
              rel="noreferrer"
            >
              Auto Test Report
            </a>
          ) : null}
          <div className="automation-spike-suite-actions-lead">
            <button
              type="button"
              className="primary"
              onClick={openRunAllDialog}
              disabled={suiteBusy || suiteCases.length === 0 || spikeRunBusy}
            >
              {suiteBusy ? "Running Suite…" : "Run All"}
            </button>
            {suiteBusy ? (
              <>
                <button
                  type="button"
                  className="secondary has-icon"
                  onClick={() => void requestStopCurrentTest()}
                  disabled={suiteStopKind !== null}
                  aria-busy={suiteStopKind === "current"}
                >
                  {suiteStopKind === "current" ? <Spinner /> : null}
                  {suiteStopKind === "current" ? "In progress…" : "Stop Current Test"}
                </button>
                <button
                  type="button"
                  className="secondary has-icon"
                  onClick={() => void requestStopAllSuite()}
                  disabled={suiteStopKind !== null}
                  aria-busy={suiteStopKind === "all"}
                >
                  {suiteStopKind === "all" ? <Spinner /> : null}
                  {suiteStopKind === "all" ? "In progress…" : "Stop all Tests"}
                </button>
              </>
            ) : null}
          </div>
        </div>
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
                      suiteRunningCaseId && String(c.id) === String(suiteRunningCaseId),
                    )}
                    runDisabled={suiteBusy || spikeRunBusy}
                    onView={setSuiteBddViewCase}
                    onRun={openRunOneCase}
                    onAnalysis={setSuiteAnalysisViewCase}
                    onHistory={openSuiteHistory}
                    onDelete={deleteCase}
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
                    <FloatingTooltip text="Remove cached selector">
                      <button
                        type="button"
                        className="tc-delete-icon-btn"
                        onClick={() => deleteSel(r.rowid)}
                        aria-label="Remove cached selector"
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
