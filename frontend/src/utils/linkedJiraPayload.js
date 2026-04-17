export function normalizeLinkedJiraFromApi(d) {
  if (!d || typeof d !== "object") return { tests: [], work: [] };
  return {
    tests: Array.isArray(d.linked_jira_tests) ? d.linked_jira_tests : [],
    work: Array.isArray(d.linked_jira_work) ? d.linked_jira_work : [],
  };
}
