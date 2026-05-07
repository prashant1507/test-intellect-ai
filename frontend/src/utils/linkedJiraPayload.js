import { attachmentSizeBytes } from "./format";

function normalizeRequirementAttachment(a) {
  if (!a || typeof a !== "object") return null;
  const id = String(a.id ?? "").trim();
  if (!id) return null;
  const sz = attachmentSizeBytes(a.size ?? a.file_size ?? a.fileSize);
  return { ...a, id, ...(sz != null ? { size: sz } : {}) };
}

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
    attachments: att === undefined ? undefined : att.map(normalizeRequirementAttachment).filter(Boolean),
  };
}
