export function normalizeLinkedJiraFromApi(d) {
  if (!d || typeof d !== "object") return { tests: [], work: [], attachments: undefined };
  const att = Object.prototype.hasOwnProperty.call(d, "requirement_attachments")
    ? Array.isArray(d.requirement_attachments)
      ? d.requirement_attachments
      : []
    : undefined;
  return {
    tests: Array.isArray(d.linked_jira_tests) ? d.linked_jira_tests : [],
    work: Array.isArray(d.linked_jira_work) ? d.linked_jira_work : [],
    attachments: att,
  };
}
