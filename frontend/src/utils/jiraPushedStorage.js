const STORAGE_KEY = "jira-ai-jira-pushed-v1";

export function loadJiraPushedMap() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const o = JSON.parse(raw);
    if (typeof o !== "object" || !o || Array.isArray(o)) return {};
    const out = {};
    for (const [k, v] of Object.entries(o)) {
      if (typeof k !== "string" || typeof v !== "string") continue;
      if (/^main:\d+$/.test(k)) continue;
      if (/^main:[^:]+:\d+$/.test(k)) continue;
      if (/^mem:[^:]+:\d+$/.test(k)) continue;
      out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

export function persistJiraPushedMap(map) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {}
}
