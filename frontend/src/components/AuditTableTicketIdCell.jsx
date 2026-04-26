import { jiraBrowseHref } from "../utils/audit";
import { isLikelyJiraIssueKey } from "../utils/format";

export function AuditTableTicketIdCell({ ticketId, jiraUrl }) {
  if (ticketId === "AUTH") {
    return <span className="audit-context-muted">—</span>;
  }
  const tid = String(ticketId ?? "");
  const linkHref =
    jiraUrl?.trim() && isLikelyJiraIssueKey(tid) && jiraBrowseHref(jiraUrl, tid);
  if (linkHref) {
    return (
      <a
        href={linkHref}
        target="_blank"
        rel="noopener noreferrer"
        className="audit-issue-link"
      >
        <code className="audit-ticket">{tid}</code>
      </a>
    );
  }
  return <code className="audit-ticket">{tid}</code>;
}
