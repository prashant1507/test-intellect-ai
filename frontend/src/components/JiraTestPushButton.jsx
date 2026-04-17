import { jiraBrowseHref } from "../utils/audit";
import { FloatingTooltip, Spinner } from "./common";

export function JiraTestPushButton({
  disabled,
  isPushing,
  isUpdating = false,
  pushedKey,
  onClick,
  onUpdate,
  title,
  ariaLabel,
  updateTitle,
  updateAriaLabel,
  updateSucceeded = false,
  showUpdateButton = false,
  jiraBaseUrl,
  displayMode = "default",
}) {
  const done = Boolean(pushedKey);
  const showUpdate = Boolean(
    showUpdateButton && done && pushedKey && typeof onUpdate === "function",
  );
  const issueHref = done && pushedKey ? jiraBrowseHref(jiraBaseUrl, pushedKey) : null;

  if (displayMode === "linkOnly") {
    if (isPushing) {
      return (
        <div className="tc-jira-push-column tc-jira-push-column--link-only" aria-busy="true">
          <Spinner />
        </div>
      );
    }
    if (!done || !pushedKey) return null;
    return (
      <div className="tc-jira-push-column tc-jira-push-column--link-only">
        {issueHref ? (
          <a
            href={issueHref}
            className="tc-jira-issue-link"
            target="_blank"
            rel="noopener noreferrer"
            title={`Open ${pushedKey} in JIRA`}
            onClick={(e) => e.stopPropagation()}
          >
            {pushedKey}
          </a>
        ) : (
          <span className="tc-jira-issue-id" title="Set JIRA URL to enable link">
            {pushedKey}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className={`tc-jira-push-column${showUpdate ? " tc-jira-push-column--with-update" : ""}`}>
      <FloatingTooltip text={title} wrapClassName="field-info-wrap--jira-push">
        <button
          type="button"
          className={`tc-jira-push${isPushing && !isUpdating ? " tc-jira-push--loading" : ""}${done ? " tc-jira-push--done" : ""}`}
          disabled={disabled || done}
          aria-label={ariaLabel}
          aria-busy={isPushing && !isUpdating}
          onClick={onClick}
        >
          {isPushing && !isUpdating ? (
            <Spinner />
          ) : done ? (
            <svg
              className="tc-jira-check"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M20 6L9 17l-5-5" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M12 5v14M5 12h14" />
            </svg>
          )}
        </button>
      </FloatingTooltip>
      {done && pushedKey ? (
        issueHref ? (
          <a
            href={issueHref}
            className="tc-jira-issue-link"
            target="_blank"
            rel="noopener noreferrer"
            title={`Open ${pushedKey} in JIRA`}
            onClick={(e) => e.stopPropagation()}
          >
            {pushedKey}
          </a>
        ) : (
          <span className="tc-jira-issue-id" title="Set JIRA URL to enable link">
            {pushedKey}
          </span>
        )
      ) : null}
      {showUpdate ? (
        <FloatingTooltip
          text={updateTitle || "Update the existing JIRA issue"}
          wrapClassName="field-info-wrap--jira-push"
        >
          <button
            type="button"
            className={`tc-jira-update${isUpdating ? " tc-jira-update--loading" : ""}${updateSucceeded && !isUpdating ? " tc-jira-update--done" : ""}`}
            disabled={disabled || isPushing}
            aria-label={updateAriaLabel || "Update test case in JIRA"}
            aria-busy={isUpdating}
            onClick={(e) => {
              e.stopPropagation();
              onUpdate(e);
            }}
          >
            {isUpdating ? (
              <Spinner />
            ) : (
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
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            )}
          </button>
        </FloatingTooltip>
      ) : null}
    </div>
  );
}
