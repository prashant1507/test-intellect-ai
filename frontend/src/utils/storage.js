function getLocalStorageString(key, fallback = "") {
  try {
    const v = localStorage.getItem(key);
    return v ?? fallback;
  } catch {
    return fallback;
  }
}

export function readStoredJiraUrl() {
  return getLocalStorageString("jira-ai-jira-url", "");
}

export function readStoredJiraTestIssueType() {
  const s = getLocalStorageString("jira-ai-jira-test-issue-type", "").trim();
  return s || "Test";
}

export function readStoredJiraLinkType() {
  const t = getLocalStorageString("jira-ai-jira-link-type", "").trim();
  if (!t) return "Relates";
  if (t === "Relates to") return "Relates";
  return t;
}
