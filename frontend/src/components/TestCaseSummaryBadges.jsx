import { FloatingTooltip } from "./common";
import { PriorityTag } from "./PriorityTag";
import { TestCaseScoreBadge } from "./TestCaseScoreBadge";
import { changeStatusLabel } from "../utils/format";

export function TestCaseSummaryBadges({ tc, statusSlug }) {
  return (
    <>
      <span className={`badge badge--tc-${statusSlug}`}>{changeStatusLabel(tc.change_status)}</span>
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
      <PriorityTag priority={tc.priority} iconUrl={tc.priority_icon_url} />
      <TestCaseScoreBadge score={tc.score} />
    </>
  );
}
