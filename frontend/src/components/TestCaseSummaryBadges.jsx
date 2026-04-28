import { FloatingTooltip } from "./common";
import { PriorityTag } from "./PriorityTag";
import { SeverityTag } from "./SeverityTag";
import { TestCaseScoreBadge } from "./TestCaseScoreBadge";
import {
  changeStatusLabel,
  changeStatusTooltip,
  prioritySourceTooltip,
  severitySourceTooltip,
} from "../utils/format";

export function TestCaseSummaryBadges({ tc, statusSlug }) {
  const priTip = prioritySourceTooltip(tc);
  const showPri = Boolean(String(tc.priority ?? "").trim());
  const sevTip = severitySourceTooltip(tc);
  const showSev = Boolean(String(tc.severity ?? "").trim());
  return (
    <>
      <FloatingTooltip text={changeStatusTooltip(statusSlug)}>
        <span className={`badge badge--tc-${statusSlug}`}>{changeStatusLabel(tc.change_status)}</span>
      </FloatingTooltip>
      {tc.jira_existing ? (
        <FloatingTooltip text="Already in JIRA">
          <span className="badge badge--jira-existing">EXISTING</span>
        </FloatingTooltip>
      ) : null}
      {tc.jira_status ? (
        <FloatingTooltip text="Workflow Status">
          <span className="tc-jira-status">{tc.jira_status}</span>
        </FloatingTooltip>
      ) : null}
      {showPri ? (
        <FloatingTooltip text={priTip}>
          <PriorityTag
            priority={tc.priority}
            iconUrl={tc.priority_icon_url}
            fromJiraIssue={!!tc.jira_existing}
          />
        </FloatingTooltip>
      ) : null}
      {showSev ? (
        <FloatingTooltip text={sevTip}>
          <SeverityTag
            severity={tc.severity}
            iconUrl={tc.severity_icon_url}
            fromJiraIssue={!!tc.jira_existing}
          />
        </FloatingTooltip>
      ) : null}
      <TestCaseScoreBadge score={tc.score} />
    </>
  );
}
