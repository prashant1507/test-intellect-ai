const JIRA_GEN = new Set(["/generate-tests", "/generate-tests-agentic"]);
const PASTE_GEN = new Set(["/generate-from-paste", "/generate-from-paste-agentic"]);

export function isJiraGenBusy(busy) {
  return JIRA_GEN.has(busy);
}

export function isPasteGenBusy(busy) {
  return PASTE_GEN.has(busy);
}

export function isAnyGenBusy(busy) {
  return isJiraGenBusy(busy) || isPasteGenBusy(busy);
}
