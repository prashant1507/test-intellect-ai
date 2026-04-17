const KNOWN = ["Highest", "High", "Medium", "Low", "Lowest"];

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

function PriorityGlyph({ level }) {
  switch (level) {
    case "highest":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
          <polyline points="6 18 12 12 18 18" {...stroke} />
          <polyline points="6 11 12 5 18 11" {...stroke} />
        </svg>
      );
    case "high":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
          <polyline points="6 16 12 10 18 16" {...stroke} />
        </svg>
      );
    case "medium":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
          <line x1="5" y1="9" x2="19" y2="9" {...stroke} />
          <line x1="5" y1="15" x2="19" y2="15" {...stroke} />
        </svg>
      );
    case "low":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
          <polyline points="6 8 12 14 18 8" {...stroke} />
        </svg>
      );
    case "lowest":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
          <polyline points="6 6 12 12 18 6" {...stroke} />
          <polyline points="6 13 12 19 18 13" {...stroke} />
        </svg>
      );
    default:
      return null;
  }
}

export function PriorityTag({ priority, iconUrl }) {
  const raw = String(priority ?? "").trim();
  if (!raw) return null;
  const label = KNOWN.find((k) => k.toLowerCase() === raw.toLowerCase()) || raw;
  const fromJira = Boolean(iconUrl);
  const slug = fromJira ? "jira" : KNOWN.includes(label) ? label.toLowerCase() : "unknown";
  return (
    <span className={`tc-priority tc-priority--${slug}`} title={`Priority: ${label}`}>
      {fromJira ? (
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
