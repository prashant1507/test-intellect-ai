import { auditActionParts, jiraBrowseHref } from "../utils/audit";

export function AuditActionCell({ action, jiraBaseUrl }) {
  const parts = auditActionParts(action);
  if (parts.type === "test_create") {
    const href = jiraBrowseHref(jiraBaseUrl, parts.key);
    return (
      <span className="audit-action-cell">
        Created{" "}
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className="audit-issue-link">
            {parts.key}
          </a>
        ) : (
          <code className="audit-issue-key">{parts.key}</code>
        )}
      </span>
    );
  }
  if (parts.type === "test_update") {
    const href = jiraBrowseHref(jiraBaseUrl, parts.key);
    return (
      <span className="audit-action-cell">
        Updated{" "}
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className="audit-issue-link">
            {parts.key}
          </a>
        ) : (
          <code className="audit-issue-key">{parts.key}</code>
        )}
      </span>
    );
  }
  if (parts.type === "test_edit") {
    const href = jiraBrowseHref(jiraBaseUrl, parts.key);
    return (
      <span className="audit-action-cell">
        Edited{" "}
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className="audit-issue-link">
            {parts.key}
          </a>
        ) : (
          <code className="audit-issue-key">{parts.key}</code>
        )}
      </span>
    );
  }
  return <>{parts.text}</>;
}
