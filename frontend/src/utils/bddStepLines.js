const BDD_STEP = /^(Given|When|Then|And|But)\b/i;
const BDD_SKIP = /^(Feature|Rule|Background|Scenario)\b/i;

export function parseBddStepLines(bdd) {
  const out = [];
  let cur = null;
  let doc = null;
  for (const raw of String(bdd || "").split(/\r?\n/)) {
    const st = raw.trim();
    if (doc != null) {
      if (st === '"""' || st === "'''") {
        const inner = doc.join("\n").trim();
        cur = cur != null ? `${cur}\n${inner}` : inner;
        doc = null;
      } else {
        doc.push(raw);
      }
      continue;
    }
    if (!st) continue;
    if (st.startsWith("#")) continue;
    if (BDD_SKIP.test(st) && !BDD_STEP.test(st)) continue;
    if (BDD_STEP.test(st)) {
      if (cur != null) out.push(cur);
      cur = st;
    } else if (cur != null) {
      if (st === '"""' || st === "'''") {
        doc = [];
      } else if (st.startsWith('"""') && st.endsWith('"""') && st.length > 6) {
        cur = `${cur}\n${st.slice(3, -3).trim()}`;
      } else {
        cur = `${cur}\n${raw.replace(/\s+$/, "")}`;
      }
    }
  }
  if (cur != null) {
    if (doc != null) {
      out.push(`${cur}\n${doc.join("\n")}`);
    } else {
      out.push(cur);
    }
  }
  return out;
}
