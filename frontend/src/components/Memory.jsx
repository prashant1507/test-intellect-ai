import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { changeStatusLabel, fmtReqMarkdown, fmtTestsMarkdown, jiraWikiToMarkdown } from "../utils/format";
import { resolvePushedJiraKey } from "../utils/jiraPushFingerprint";
import { Copy, Spinner } from "./common";
import { JiraTestPushButton } from "./JiraTestPushButton";
import { TestCaseBody } from "./TestCaseBody";
import { PriorityTag } from "./PriorityTag";

const mdLinkProps = (props) => <a {...props} target="_blank" rel="noopener noreferrer" />;

function MemoryRequirementsView({ requirements }) {
  const r = requirements;
  if (!r || typeof r !== "object") return <p className="empty-state">—</p>;
  const title = String(r.title ?? "").trim();
  const desc = String(r.description ?? "").trim();
  if (!title && !desc) return <p className="empty-state">—</p>;
  return (
    <div className="memory-detail-scroll memory-req-formatted">
      {title ? <h4 className="memory-req-title">{title}</h4> : null}
      {desc ? (
        <div className="paste-md-preview memory-md-embed">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: mdLinkProps }}>
            {jiraWikiToMarkdown(desc)}
          </ReactMarkdown>
        </div>
      ) : null}
    </div>
  );
}

function MemoryTestCasesView({ testCases, memoryTicketId, jiraUrl, jiraPushed }) {
  const list = Array.isArray(testCases) ? testCases : [];
  if (!list.length) return <p className="empty-state">—</p>;
  return (
    <div className="memory-detail-scroll memory-tc-formatted">
      {list.map((tc, idx) => {
        if (!tc || typeof tc !== "object") return null;
        const raw = String(tc.change_status || "new").toLowerCase().replace(/_/g, "-");
        const safeSt = ["new", "updated", "unchanged"].includes(raw) ? raw : "new";
        const pushedKey = memoryTicketId
          ? resolvePushedJiraKey(tc, memoryTicketId, jiraPushed, "mem")
          : undefined;
        return (
          <section key={idx} className={`tc memory-tc-block status-${safeSt}`}>
            <div className="memory-tc-summary-row">
              <div className="memory-tc-head">
                <span className={`badge badge--tc-${safeSt}`}>{changeStatusLabel(tc.change_status)}</span>
                <PriorityTag priority={tc.priority} iconUrl={tc.priority_icon_url} />
                <span className="tc-desc">{tc.description || "—"}</span>
              </div>
              <JiraTestPushButton displayMode="linkOnly" pushedKey={pushedKey} jiraBaseUrl={jiraUrl} />
            </div>
            <div className="tc-body">
              <TestCaseBody tc={tc} />
            </div>
          </section>
        );
      })}
    </div>
  );
}

export function MemoryDetailContent({ memoryPanel, onAnnounce, memoryTicketId, jiraUrl, jiraPushed }) {
  if (!memoryPanel) return null;
  return (
    <>
      {memoryPanel.phase === "loading" ? (
        <p className="memory-detail-loading">
          <Spinner /> Loading saved history…
        </p>
      ) : null}
      {memoryPanel.phase === "error" ? (
        <div className="err" role="alert">
          <strong>Error.</strong> {memoryPanel.message}
        </div>
      ) : null}
      {memoryPanel.phase === "ok" ? (
        <div className="memory-detail-split">
          <div className="memory-detail-pane">
            <div className="memory-detail-pane-head">
              <h3>Requirements</h3>
              <Copy text={fmtReqMarkdown(memoryPanel.requirements)} label="Copy requirements (Markdown)" onAnnounce={onAnnounce} />
            </div>
            <MemoryRequirementsView requirements={memoryPanel.requirements} />
          </div>
          <div className="memory-detail-pane">
            <div className="memory-detail-pane-head">
              <h3>Test Cases</h3>
              <Copy text={fmtTestsMarkdown(memoryPanel.test_cases)} label="Copy test cases (Markdown)" onAnnounce={onAnnounce} />
            </div>
            <MemoryTestCasesView
              testCases={memoryPanel.test_cases}
              memoryTicketId={memoryTicketId}
              jiraUrl={jiraUrl}
              jiraPushed={jiraPushed}
            />
          </div>
        </div>
      ) : null}
    </>
  );
}
