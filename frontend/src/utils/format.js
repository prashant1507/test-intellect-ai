import { isUnifiedGherkin } from "./testCase";

export function jiraWikiToMarkdown(s) {
  if (!s || typeof s !== "string") return "";
  const lines = s.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let ol = 0;
  for (let line of lines) {
    const raw = line.replace(/\s+$/, "");
    const h = /^h([1-6])\.\s+(.+)$/.exec(raw);
    if (h) {
      ol = 0;
      out.push("#".repeat(+h[1]) + " " + h[2]);
      continue;
    }
    if (/^\*\*\s+/.test(raw)) {
      ol = 0;
      out.push("  - " + raw.slice(3).trimStart());
      continue;
    }
    if (/^\*\s+/.test(raw)) {
      ol = 0;
      out.push("- " + raw.slice(2).trimStart());
      continue;
    }
    if (/^#\s+/.test(raw)) {
      ol += 1;
      out.push(`${ol}. ` + raw.slice(2).trimStart());
      continue;
    }
    ol = 0;
    if (/^----\s*$/.test(raw)) {
      out.push("---");
      continue;
    }
    out.push(line);
  }
  return out.join("\n");
}

export function fmtReqMarkdown(r) {
  if (!r || typeof r !== "object") return "";
  const title = String(r.title ?? "").trim();
  const desc = jiraWikiToMarkdown(String(r.description ?? "").trim());
  const parts = [];
  if (title) parts.push(`# ${title.replace(/\r?\n/g, " ")}`);
  if (title && desc) parts.push("");
  if (desc) parts.push(desc);
  return parts.join("\n");
}

export function changeStatusLabel(raw) {
  const k = String(raw || "new").toLowerCase().replace(/-/g, "_");
  if (k === "unchanged") return "Unchanged";
  if (k === "updated") return "Updated";
  if (k === "new") return "New";
  return raw ? String(raw) : "New";
}

export function tcStatusSlug(raw) {
  const s = String(raw || "new").toLowerCase().replace(/_/g, "-");
  return ["new", "updated", "unchanged"].includes(s) ? s : "new";
}

function fmtScenarioLines(tc) {
  if (!tc) return "";
  if (isUnifiedGherkin(tc)) return (tc.steps || []).join("\n");
  const parts = [];
  if (tc.preconditions) parts.push(tc.preconditions);
  (tc.steps || []).forEach((s) => parts.push(s));
  if (tc.expected_result) parts.push(tc.expected_result);
  return parts.join("\n");
}

export function fmtTestsMarkdown(t) {
  if (!Array.isArray(t) || !t.length) return "";
  return t
    .map((c) => {
      if (!c || typeof c !== "object") return "";
      let status = changeStatusLabel(c.change_status);
      if (c.jira_existing) status = `${status} · EXISTING`;
      if (c.jira_status) status = `${status} · ${c.jira_status}`;
      if (c.jira_issue_key) status = `${status} (${String(c.jira_issue_key).trim()})`;
      const title = String(c.description || "Test case").trim().replace(/\r?\n/g, " ");
      const pri = String(c.priority || "").trim();
      const sc =
        typeof c.score === "number" && !Number.isNaN(c.score) ? Math.round(c.score * 10) / 10 : null;
      const meta = [`**Status:** ${status}`];
      if (pri) meta.push(`**Priority:** ${pri}`);
      if (sc != null) meta.push(`**Score:** ${sc}/10`);
      let body = "";
      if (isUnifiedGherkin(c)) {
        const g = fmtScenarioLines(c).trim();
        body = g ? `\`\`\`gherkin\n${g}\n\`\`\`` : "";
      } else {
        const bits = [];
        const pre = String(c.preconditions || "").trim();
        if (pre) bits.push(`**Preconditions:** ${pre}`);
        const steps = c.steps || [];
        if (steps.length) {
          bits.push("**Steps:**", "", steps.map((s, i) => `${i + 1}. ${s}`).join("\n"));
        }
        const exp = String(c.expected_result || "").trim();
        if (exp) bits.push(`**Expected:** ${exp}`);
        body = bits.join("\n\n");
      }
      return `### ${title}\n\n${meta.join("\n\n")}\n\n${body}`;
    })
    .filter(Boolean)
    .join("\n\n---\n\n");
}

export function formatSizeMb(n) {
  if (n == null || typeof n !== "number" || n < 0) return "";
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatTime(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch {
    return "";
  }
}

function _parseIso(iso) {
  if (iso == null || !String(iso).trim()) return null;
  const d = new Date(String(iso));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatSuiteAnalysisAt(iso) {
  const d = _parseIso(iso);
  if (!d) return "";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatHistoryDate(iso) {
  const d = _parseIso(iso);
  if (!d) return "—";
  return d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function formatHistoryTime(iso) {
  const d = _parseIso(iso);
  if (!d) return "—";
  return d.toLocaleTimeString(undefined, { timeStyle: "short" });
}

export function formatReportListAt(iso) {
  const d = _parseIso(iso);
  if (!d) return "—";
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

export function readTheme() {
  try {
    const t = localStorage.getItem("theme");
    if (t === "dark" || t === "light") return t;
    if (t === "soft") return "light";
  } catch (_) {}
  if (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
  return "light";
}

export function normTicketId(v) {
  return String(v ?? "").trim().toUpperCase();
}

const PASTE_AUTO_MEMORY_KEY = /^TEST-[0-9A-F]{10}$/i;

function isPasteAutoMemoryKey(k) {
  return PASTE_AUTO_MEMORY_KEY.test(normTicketId(k));
}

export function isLikelyJiraIssueKey(k) {
  const s = normTicketId(k);
  if (!s || isPasteAutoMemoryKey(s)) return false;
  return /^[A-Z][A-Z0-9_]*-\d+$/.test(s);
}
