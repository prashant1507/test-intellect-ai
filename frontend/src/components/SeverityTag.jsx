import { PriorityGlyph } from "./PriorityTag";

const KNOWN = ["Blocker", "Critical", "Major", "Minor", "Trivial"];

const SE_TO_VISUAL = {
  blocker: "highest",
  critical: "high",
  major: "medium",
  minor: "low",
  trivial: "lowest",
};

export function SeverityTag({ severity, iconUrl, fromJiraIssue = false }) {
  const raw = String(severity ?? "").trim();
  if (!raw) return null;
  const label = KNOWN.find((k) => k.toLowerCase() === raw.toLowerCase()) || raw;
  const showJiraImg = Boolean(fromJiraIssue && String(iconUrl ?? "").trim());
  const match = KNOWN.find((k) => k.toLowerCase() === raw.toLowerCase());
  const slug = showJiraImg
    ? "jira"
    : match && SE_TO_VISUAL[match.toLowerCase()]
      ? SE_TO_VISUAL[match.toLowerCase()]
      : "unknown";
  return (
    <span className={`tc-priority tc-priority--${slug}`}>
      {showJiraImg ? (
        <span className="tc-priority-icon" aria-hidden>
          <img src={iconUrl} alt="" className="tc-priority-icon-img" />
        </span>
      ) : slug !== "unknown" ? (
        <span className="tc-priority-icon" aria-hidden>
          <PriorityGlyph level={slug} />
        </span>
      ) : null}
      <span className="tc-priority-label">{label}</span>
    </span>
  );
}
