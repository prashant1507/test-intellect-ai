import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { PriorityTag } from "./PriorityTag";

const VISIBLE_ROWS = 2;

const SCROLL_EXTRA_STORAGE = {
  attachments: "linkedListScrollExtra.attachments",
  tests: "linkedListScrollExtra.tests",
  work: "linkedListScrollExtra.work",
};

function viewportScrollCapPx() {
  if (typeof window === "undefined") return 512;
  return Math.min(window.innerHeight * 0.85, 32 * 16);
}

function readStoredExtraPx(key) {
  if (!key) return 0;
  try {
    const v = sessionStorage.getItem(key);
    if (v != null) return Math.max(0, Number(v));
  } catch {}
  return 0;
}

function ResizableScrollClip({ scroll, clipPx, className, children, storageKey }) {
  const [extraPx, setExtraPx] = useState(() => readStoredExtraPx(storageKey));
  const [viewportCap, setViewportCap] = useState(viewportScrollCapPx);

  useEffect(() => {
    const onResize = () => setViewportCap(viewportScrollCapPx());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!storageKey) return;
    try {
      sessionStorage.setItem(storageKey, String(extraPx));
    } catch {}
  }, [storageKey, extraPx]);

  const basePx = clipPx != null && clipPx > 0 ? clipPx : 120;

  useEffect(() => {
    setExtraPx((ex) => Math.min(ex, Math.max(0, viewportCap - basePx)));
  }, [basePx, viewportCap]);

  const onPointerDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const startY = e.clientY;
    const startExtra = extraPx;
    const cap = viewportCap;
    const onMove = (ev) => {
      const dy = ev.clientY - startY;
      let next = startExtra + dy;
      next = Math.max(0, Math.min(next, cap - basePx));
      setExtraPx(next);
    };
    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onUp);
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
    document.body.style.cursor = "ns-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onUp);
  };

  if (!scroll) return children;

  const effectiveMax = Math.min(basePx + extraPx, viewportCap);

  return (
    <div className="linked-jira-scroll-wrap">
      <div className={className} style={{ maxHeight: effectiveMax }}>
        {children}
      </div>
      <button
        type="button"
        className="linked-jira-resize-handle"
        aria-label="Drag to resize list height"
        onPointerDown={onPointerDown}
      >
        <svg width="18" height="10" viewBox="0 0 24 14" fill="currentColor" aria-hidden>
          <circle cx="8" cy="4" r="1.75" />
          <circle cx="16" cy="4" r="1.75" />
          <circle cx="8" cy="10" r="1.75" />
          <circle cx="16" cy="10" r="1.75" />
        </svg>
      </button>
    </div>
  );
}

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
      <ResizableScrollClip
        scroll={scroll}
        clipPx={clipPx}
        className="linked-jira-tests-scroll"
        storageKey={SCROLL_EXTRA_STORAGE.tests}
      >
        {list}
      </ResizableScrollClip>
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
      <ResizableScrollClip
        scroll={scroll}
        clipPx={clipPx}
        className="linked-jira-tests-scroll"
        storageKey={SCROLL_EXTRA_STORAGE.work}
      >
        {list}
      </ResizableScrollClip>
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
      <ResizableScrollClip
        scroll={scroll}
        clipPx={clipPx}
        className="req-attachments-scroll"
        storageKey={SCROLL_EXTRA_STORAGE.attachments}
      >
        {list}
      </ResizableScrollClip>
    </div>
  );
}
