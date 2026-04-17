import { PriorityTag } from "./PriorityTag";

function LinkedIssueRow({ issueKey, browseUrl, summary, headExtras }) {
  return (
    <li className="linked-jira-tests-line">
      <div className="linked-jira-tests-item">
        <div className="linked-jira-tests-head">
          <a className="linked-jira-tests-key" href={browseUrl} target="_blank" rel="noopener noreferrer">
            {issueKey}
          </a>
          {headExtras}
        </div>
        <p className="linked-jira-tests-summary">{summary}</p>
      </div>
    </li>
  );
}

export function LinkedJiraTestsBlock({ rows, heading }) {
  if (!rows?.length) return null;
  const scroll = rows.length > 3;
  const list = (
    <ul className="linked-jira-tests-list">
      {rows.map((row) => {
        const summary = String(row.summary || "").trim() || "—";
        const st = String(row.status_name || "").trim();
        const p = String(row.priority || "").trim();
        const pUrl = row.priority_icon_url ? String(row.priority_icon_url).trim() : "";
        return (
          <LinkedIssueRow
            key={row.issue_key}
            issueKey={row.issue_key}
            browseUrl={row.browse_url}
            summary={summary}
            headExtras={
              <>
                {p || pUrl ? <PriorityTag priority={p} iconUrl={pUrl || undefined} /> : null}
                {st ? <span className="linked-jira-tests-status">{st}</span> : null}
              </>
            }
          />
        );
      })}
    </ul>
  );
  const n = rows.length;
  return (
    <div className="linked-jira-tests" role="region" aria-label={`Linked JIRA test issues, ${n} items`}>
      <div className="linked-jira-tests-head-bar">
        <h3 className="linked-jira-tests-title">{heading}</h3>
        <span className="linked-jira-tests-count">Count: {n}</span>
      </div>
      {scroll ? <div className="linked-jira-tests-scroll">{list}</div> : list}
    </div>
  );
}

export function LinkedJiraWorkBlock({ rows, heading }) {
  if (!rows?.length) return null;
  const scroll = rows.length > 3;
  const list = (
    <ul className="linked-jira-tests-list">
      {rows.map((row) => {
        const summary = String(row.summary || "").trim() || "—";
        const it = String(row.issue_type_name || "").trim();
        const st = String(row.status_name || "").trim();
        return (
          <LinkedIssueRow
            key={row.issue_key}
            issueKey={row.issue_key}
            browseUrl={row.browse_url}
            summary={summary}
            headExtras={
              <>
                {it ? <span className="linked-jira-work-type">{it}</span> : null}
                {st ? <span className="linked-jira-tests-status">{st}</span> : null}
              </>
            }
          />
        );
      })}
    </ul>
  );
  const n = rows.length;
  return (
    <div className="linked-jira-tests" role="region" aria-label={`Linked JIRA work items, ${n} items`}>
      <div className="linked-jira-tests-head-bar">
        <h3 className="linked-jira-tests-title">{heading}</h3>
        <span className="linked-jira-tests-count">Count: {n}</span>
      </div>
      {scroll ? <div className="linked-jira-tests-scroll">{list}</div> : list}
    </div>
  );
}
