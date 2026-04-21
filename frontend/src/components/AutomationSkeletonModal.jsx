import { useCallback, useEffect, useMemo, useState } from "react";
import { jiraBrowseHref } from "../utils/audit";
import { Copy, FloatingTooltip, Spinner } from "./common";

const LANG_OPTIONS = [
  ["python", "Python"],
  ["java", "Java"],
  ["javascript", "JavaScript"],
  ["typescript", "TypeScript"],
  ["csharp", "C#"],
];

function frameworksFor(lang) {
  const base = [
    ["playwright", "Playwright"],
    ["selenium", "Selenium"],
  ];
  if (lang === "javascript" || lang === "typescript") {
    return [...base, ["cypress", "Cypress"]];
  }
  return base;
}

const SKEL_BTN = "Generate automation test skeleton";

export function AutomationSkeletonIconButton({ onClick, disabled }) {
  return (
    <FloatingTooltip text={SKEL_BTN}>
      <button
        type="button"
        className="tc-edit-icon-btn"
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        aria-label={SKEL_BTN}
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
          <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
          <polyline points="14 2 14 8 20 8" />
          <path d="m10 13-2 2 2 2" />
          <path d="m14 13 2 2-2 2" />
        </svg>
      </button>
    </FloatingTooltip>
  );
}

export function AutomationSkeletonModal({ tc, jiraBaseUrl, api, onClose, onAnnounce }) {
  const [language, setLanguage] = useState("python");
  const [framework, setFramework] = useState("playwright");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const fwOpts = useMemo(() => frameworksFor(language), [language]);
  useEffect(() => {
    const ids = new Set(fwOpts.map(([id]) => id));
    setFramework((f) => (ids.has(f) ? f : fwOpts[0][0]));
  }, [fwOpts]);

  const generate = useCallback(async () => {
    setErr("");
    setLoading(true);
    try {
      const d = await api("/generate-automation-skeleton", "POST", {
        test_case: tc,
        language,
        framework,
        ticket_id: String(tc?.jira_issue_key || "").trim(),
      });
      const c = typeof d?.code === "string" ? d.code : "";
      setCode(c);
      onAnnounce?.("Automation skeleton generated.");
    } catch (e) {
      setErr(e?.message || "Generation failed");
    } finally {
      setLoading(false);
    }
  }, [api, tc, language, framework, onAnnounce]);

  if (!tc) return null;

  const title = String(tc.description || "").trim() || "Test case";
  const testCaseIssueKey = String(tc.jira_issue_key || "").trim().toUpperCase();
  const issueHref = testCaseIssueKey ? jiraBrowseHref(jiraBaseUrl, testCaseIssueKey) : null;

  return (
    <>
      <div className="modal-dialog-head">
        <h2 id="automation-skel-title" className="modal-dialog-title">
          Automation Skeleton Generation
        </h2>
        <button type="button" className="modal-dialog-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <div className="modal-dialog-automation-skel-body">
        <p className="automation-skel-scenario">
          {testCaseIssueKey ? (
            <>
              {issueHref ? (
                <a
                  href={issueHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="audit-issue-link"
                >
                  {testCaseIssueKey}
                </a>
              ) : (
                <strong className="automation-skel-scenario-key">{testCaseIssueKey}</strong>
              )}{" "}
              <span className="automation-skel-scenario-title">{title}</span>
            </>
          ) : (
            <span className="automation-skel-scenario-title">{title}</span>
          )}
        </p>
        <div className="automation-skel-form" role="group" aria-label="Language and framework">
          <div className="automation-skel-field">
            <label className="tc-edit-label" htmlFor="automation-skel-lang">
              Language
            </label>
            <select
              id="automation-skel-lang"
              className="audit-filter-select automation-skel-select"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={loading}
            >
              {LANG_OPTIONS.map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="automation-skel-field">
            <label className="tc-edit-label" htmlFor="automation-skel-fw">
              Test Framework
            </label>
            <select
              id="automation-skel-fw"
              className="audit-filter-select automation-skel-select"
              value={framework}
              onChange={(e) => setFramework(e.target.value)}
              disabled={loading}
            >
              {fwOpts.map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="automation-skel-generate-btn"
            onClick={() => void generate()}
            disabled={loading}
          >
            {loading ? <Spinner /> : null}
            {loading ? " Generating…" : "Generate"}
          </button>
        </div>
        {err ? (
          <p className="err automation-skel-err" role="alert">
            {err}
          </p>
        ) : null}
        <div className="automation-skel-code-head">
          <span className="automation-skel-code-label">Generated code</span>
          <Copy text={code} label="Copy code" onAnnounce={onAnnounce} />
        </div>
        <div className="automation-skel-pre-wrap">
          <pre className="automation-skel-pre">
            <code>{code || (loading ? "…" : "Choose options and click generate.")}</code>
          </pre>
        </div>
      </div>
    </>
  );
}
