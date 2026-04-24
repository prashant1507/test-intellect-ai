export function normalizeTagName(s) {
  return String(s ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

export function parseTagCsv(raw) {
  if (raw == null) return [];
  if (!String(raw).trim()) return [];
  return String(raw)
    .split(",")
    .map((p) => normalizeTagName(p))
    .filter(Boolean);
}

export function normalizeTagCsv(s) {
  return parseTagCsv(s).join(", ");
}

export function parseJiraKeyCsv(raw) {
  if (raw == null || !String(raw).trim()) return [];
  return String(raw)
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
}

export function normalizeJiraKeyCsv(s) {
  return parseJiraKeyCsv(s).join(", ");
}
