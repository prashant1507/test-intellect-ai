import { normTicketId } from "./format";

function normalizeWs(s) {
  return String(s ?? "").trim().replace(/\s+/g, " ");
}

function tcFingerprintCanonical(tc) {
  if (!tc || typeof tc !== "object") return "\u0000";
  const d = normalizeWs(tc.description).toLowerCase();
  const steps = Array.isArray(tc.steps) ? tc.steps : [];
  const stepParts = steps.map((x) => normalizeWs(x).toLowerCase());
  return `${d}\u0000${stepParts.join("\u0001")}`;
}

function fnv1a32(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function jiraPushFingerprint(tc) {
  const raw = tcFingerprintCanonical(tc);
  return `h${fnv1a32(raw).toString(36)}`;
}

export function normDescForJira(tc) {
  const d = normalizeWs(tc?.description).toLowerCase();
  return d || "__empty__";
}

function normScenarioTitleForJira(tc) {
  let s = String(tc?.description ?? "").trim();
  if (!s) return "__empty__";
  s = s.replace(/\s+/g, " ");
  s = s.replace(/[.!?:]+$/g, "").trim();
  return s.toLowerCase() || "__empty__";
}

export function jiraPushedTitleKey(ticketId, tc) {
  const tid = normTicketId(ticketId);
  if (!tid) return null;
  return `jt:${tid}:${normScenarioTitleForJira(tc)}`;
}

export function resolvePushedJiraKey(tc, ticketId, jiraPushed, scope) {
  const tid = normTicketId(ticketId);
  if (!tid || !tc || typeof jiraPushed !== "object") return undefined;
  const fromTc = normTicketId(tc.jira_issue_key);
  if (fromTc) return fromTc;
  const prefix = scope === "mem" ? "mem" : "main";
  const fp = jiraPushFingerprint(tc);
  const k1 = `${prefix}:${tid}:${fp}`;
  if (jiraPushed[k1]) return jiraPushed[k1];
  const jtKey = jiraPushedTitleKey(tid, tc);
  if (jtKey && jiraPushed[jtKey]) return jiraPushed[jtKey];
  const k2 = `${prefix}:${tid}:d:${normDescForJira(tc)}`;
  if (jiraPushed[k2]) return jiraPushed[k2];
  const k2t = `${prefix}:${tid}:d:${normScenarioTitleForJira(tc)}`;
  if (k2t !== k2 && jiraPushed[k2t]) return jiraPushed[k2t];
  return undefined;
}
