import { normalizeTagCsv } from "./tagCsv";
import { testCaseToSpikeBdd } from "./testCase";

function suiteTagWithTestType(testType, tagInput) {
  return normalizeTagCsv(
    [testType, tagInput].filter((s) => String(s || "").trim()).join(", "),
  );
}

export function stripLeadingTestTypeFromTag(tagCsv, spikeType) {
  const t = (spikeType || "ui").toLowerCase() === "api" ? "api" : "ui";
  const parts = String(tagCsv || "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length);
  if (parts.length && parts[0].toLowerCase() === t) {
    return parts.slice(1).join(", ");
  }
  return String(tagCsv || "").trim();
}

export function deriveTestTypeAndSpikeFromPrefill(raw) {
  const stRaw = String(raw?.spike_type ?? raw?.spikeType ?? "")
    .trim()
    .toLowerCase();
  if (stRaw === "api") return { testType: "API", spikeForTag: "api" };
  if (stRaw === "ui") return { testType: "UI", spikeForTag: "ui" };
  const tagCsv = String(raw?.tag ?? "");
  const first = tagCsv
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .find((s) => s.length);
  if (first === "api") return { testType: "API", spikeForTag: "api" };
  if (first === "ui") return { testType: "UI", spikeForTag: "ui" };
  return { testType: "UI", spikeForTag: "ui" };
}

export function suiteApiPayloadFromPrefillCase(pc) {
  if (!pc) return null;
  const { testType, spikeForTag } = deriveTestTypeAndSpikeFromPrefill(pc);
  const tagStripped = stripLeadingTestTypeFromTag(
    String(pc.tag ?? ""),
    spikeForTag,
  );
  return {
    title: String(pc.title ?? "").trim(),
    bdd: String(pc.bdd ?? ""),
    jira_id: String(pc.jiraId ?? "").trim(),
    requirement_ticket_id: String(pc.requirementTicketId ?? "").trim(),
    tag: suiteTagWithTestType(testType, tagStripped),
    spike_type: testType === "API" ? "api" : "ui",
  };
}

export function suiteApiPayloadFromForm(
  title,
  bdd,
  requirementTicketId,
  jiraId,
  testType,
  tag,
) {
  return {
    title: title.trim(),
    bdd,
    jira_id: jiraId.trim(),
    requirement_ticket_id: requirementTicketId.trim(),
    tag: suiteTagWithTestType(testType, tag),
    spike_type: testType === "API" ? "api" : "ui",
  };
}

export function suiteApiPayloadsEqual(a, b) {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

function canonicalSuiteTitleFromGeneratedCase(tc) {
  return String(tc?.description ?? "").trim() || "Untitled";
}

export function isGeneratedCaseAlreadyInSuite(tc, suiteCases) {
  const list = Array.isArray(suiteCases) ? suiteCases : [];
  const titleT = canonicalSuiteTitleFromGeneratedCase(tc);
  const jiraT = String(tc?.jira_issue_key ?? "").trim();
  if (jiraT) {
    const jl = jiraT.toLowerCase();
    return list.some((c) => String(c.jira_id || "").trim().toLowerCase() === jl);
  }
  return list.some((c) => {
    if (String(c.jira_id || "").trim()) return false;
    return String(c.title || "").trim() === titleT;
  });
}

export function suitePostBodyFromGeneratedCase(tc, requirementTicketId, testType) {
  const title = canonicalSuiteTitleFromGeneratedCase(tc);
  const bdd = testCaseToSpikeBdd(tc);
  const jiraId = String(tc?.jira_issue_key ?? "").trim();
  const reqId = String(requirementTicketId ?? "").trim();
  return {
    ...suiteApiPayloadFromForm(title, bdd, reqId, jiraId, testType, ""),
    url: "",
    html_dom: "",
  };
}
