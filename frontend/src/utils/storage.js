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
