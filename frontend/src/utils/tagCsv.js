/**
 * Trims and collapses internal whitespace in one tag (CSV segment).
 * @param {string} s
 * @returns {string}
 */
export function normalizeTagName(s) {
  return String(s ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Splits a comma-separated tag list and normalizes each tag.
 * @param {string|null|undefined} raw
 * @returns {string[]}
 */
export function parseTagCsv(raw) {
  if (raw == null) return [];
  if (!String(raw).trim()) return [];
  return String(raw)
    .split(",")
    .map((p) => normalizeTagName(p))
    .filter(Boolean);
}

/**
 * @param {string|null|undefined} s
 * @returns {string}
 */
export function normalizeTagCsv(s) {
  return parseTagCsv(s).join(", ");
}

/**
 * Comma-separated JIRA keys; trim each segment (OR match when filtering).
 * @param {string|null|undefined} raw
 * @returns {string[]}
 */
export function parseJiraKeyCsv(raw) {
  if (raw == null || !String(raw).trim()) return [];
  return String(raw)
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
}

/**
 * @param {string|null|undefined} s
 * @returns {string}
 */
export function normalizeJiraKeyCsv(s) {
  return parseJiraKeyCsv(s).join(", ");
}
