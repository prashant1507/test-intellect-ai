import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { PriorityTag } from "./PriorityTag";

const VISIBLE_ROWS = 2;

function useScrollClipHeightPx(enabled, listRef, depsKey, visibleCount) {
  const [px, setPx] = useState(null);
  useLayoutEffect(() => {
    if (!enabled) {
      setPx(null);
      return;
    }
    const root = listRef.current;
    if (!root) return;
    const measure = () => {
      const items = root.querySelectorAll(":scope > li");
      if (!items.length) {
        setPx(null);
        return;
      }
      const n = Math.min(visibleCount, items.length);
      const first = items[0];
      const last = items[n - 1];
      const h = last.getBoundingClientRect().bottom - first.getBoundingClientRect().top;
      if (h > 0) setPx(Math.ceil(h));
    };
    measure();
    const items = root.querySelectorAll(":scope > li");
    const ro = new ResizeObserver(measure);
    const limit = Math.min(visibleCount, items.length);
    for (let i = 0; i < limit; i++) ro.observe(items[i]);
    return () => ro.disconnect();
  }, [enabled, depsKey, visibleCount]);
  return px;
}

function ScrollClip({ scroll, clipPx, className, children }) {
  if (!scroll) return children;
  return (
    <div className={className} style={clipPx != null ? { maxHeight: clipPx } : undefined}>
      {children}
    </div>
  );
}

function LinkedIssueRow({ issueKey, browseUrl, summary, headExtras }) {
  return (
    <li className="linked-jira-tests-line">
      <div className="linked-jira-tests-item">
        <div className="linked-jira-tests-head">
          <a className="linked-jira-tests-key" href={browseUrl} target="_blank" rel="noopener noreferrer">
            {issueKey}
          </a>
          {headExtras}
          <span className="linked-jira-tests-summary">{summary}</span>
        </div>
      </div>
    </li>
  );
}

export function LinkedJiraTestsBlock({ rows, heading }) {
  const listRef = useRef(null);
  const safeRows = Array.isArray(rows) ? rows : [];
  const scroll = safeRows.length > VISIBLE_ROWS;
  const rowKey = safeRows.map((r) => String(r.issue_key ?? "")).join("\0");
  const clipPx = useScrollClipHeightPx(scroll, listRef, rowKey, VISIBLE_ROWS);
  if (!safeRows.length) return null;
  const list = (
    <ul ref={listRef} className="linked-jira-tests-list">
      {safeRows.map((row) => {
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
  const n = safeRows.length;
  return (
    <div className="linked-jira-tests" role="region" aria-label={`Linked JIRA test issues, ${n} items`}>
      <div className="linked-jira-tests-head-bar">
        <h3 className="linked-jira-tests-title">{heading}</h3>
        <span className="linked-jira-tests-count">Count: {n}</span>
      </div>
      <ScrollClip scroll={scroll} clipPx={clipPx} className="linked-jira-tests-scroll">
        {list}
      </ScrollClip>
    </div>
  );
}

export function LinkedJiraWorkBlock({ rows, heading }) {
  const listRef = useRef(null);
  const safeRows = Array.isArray(rows) ? rows : [];
  const scroll = safeRows.length > VISIBLE_ROWS;
  const rowKey = safeRows.map((r) => String(r.issue_key ?? "")).join("\0");
  const clipPx = useScrollClipHeightPx(scroll, listRef, rowKey, VISIBLE_ROWS);
  if (!safeRows.length) return null;
  const list = (
    <ul ref={listRef} className="linked-jira-tests-list">
      {safeRows.map((row) => {
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
  const n = safeRows.length;
  return (
    <div className="linked-jira-tests" role="region" aria-label={`Linked JIRA work items, ${n} items`}>
      <div className="linked-jira-tests-head-bar">
        <h3 className="linked-jira-tests-title">{heading}</h3>
        <span className="linked-jira-tests-count">Count: {n}</span>
      </div>
      <ScrollClip scroll={scroll} clipPx={clipPx} className="linked-jira-tests-scroll">
        {list}
      </ScrollClip>
    </div>
  );
}

export function RequirementAttachmentsInline({ attachments, onDownload, disabled }) {
  const rows = useMemo(
    () =>
      (Array.isArray(attachments) ? attachments : [])
        .map((a) => ({
          id: String(a.id ?? "").trim(),
          name: String(a.filename || "file").trim() || "file",
        }))
        .filter((r) => r.id),
    [attachments],
  );
  const listRef = useRef(null);
  const n = rows.length;
  const scroll = n > VISIBLE_ROWS;
  const rowKey = rows.map((r) => r.id).join("\0");
  const clipPx = useScrollClipHeightPx(scroll, listRef, rowKey, VISIBLE_ROWS);
  if (!n) return null;
  const list = (
    <ul ref={listRef} className="linked-jira-tests-list">
      {rows.map((r) => (
        <li key={r.id} className="linked-jira-tests-line">
          <div className="req-attach-row">
            <span className="req-attach-name" title={r.name}>
              {r.name}
            </span>
            <button
              type="button"
              className="req-attach-dl"
              disabled={disabled}
              onClick={() => onDownload(r.id, r.name)}
              aria-label={`Download ${r.name}`}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="linked-jira-tests" role="region" aria-label={`Attachments, ${n} items`}>
      <div className="linked-jira-tests-head-bar">
        <h3 className="linked-jira-tests-title">Attachments</h3>
        <span className="linked-jira-tests-count">Count: {n}</span>
      </div>
      <ScrollClip scroll={scroll} clipPx={clipPx} className="req-attachments-scroll">
        {list}
      </ScrollClip>
    </div>
  );
}
