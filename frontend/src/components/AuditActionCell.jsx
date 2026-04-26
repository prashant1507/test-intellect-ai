import { auditActionParts, jiraBrowseHref } from "../utils/audit";

function AuditIssueKeyLink({ issueKey, jiraBaseUrl }) {
  const href = jiraBrowseHref(jiraBaseUrl, issueKey);
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" className="audit-issue-link">
      {issueKey}
    </a>
  ) : (
    <code className="audit-issue-key">{issueKey}</code>
  );
}

export function AuditActionCell({ action, jiraBaseUrl }) {
  const parts = auditActionParts(action);
  if (parts.type === "test_create") {
    return (
      <span className="audit-action-cell">
        Created <AuditIssueKeyLink issueKey={parts.key} jiraBaseUrl={jiraBaseUrl} />
      </span>
    );
  }
  if (parts.type === "test_update") {
    return (
      <span className="audit-action-cell">
        Updated <AuditIssueKeyLink issueKey={parts.key} jiraBaseUrl={jiraBaseUrl} />
      </span>
    );
  }
  if (parts.type === "test_edit") {
    return (
      <span className="audit-action-cell">
        Edited <AuditIssueKeyLink issueKey={parts.key} jiraBaseUrl={jiraBaseUrl} />
      </span>
    );
  }
  if (parts.type === "automation_suite_id") {
    return (
      <span className="audit-action-cell">
        {parts.op} <AuditIssueKeyLink issueKey={parts.testId} jiraBaseUrl={jiraBaseUrl} />{" "}
        {parts.op === "Deleted" ? "from Auto Test suite" : "to Auto Test suite"}
      </span>
    );
  }
  return <>{parts.text}</>;
}
