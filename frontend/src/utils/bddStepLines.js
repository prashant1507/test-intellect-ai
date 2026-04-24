const BDD_STEP = /^(Given|When|Then|And)\b/i;
const BDD_SKIP = /^(Feature|Scenario|Background)\b/i;

export function parseBddStepLines(bdd) {
  const out = [];
  for (const line of String(bdd || "").split(/\r?\n/)) {
    const s = line.trim();
    if (!s || BDD_SKIP.test(s)) continue;
    if (BDD_STEP.test(s)) out.push(s);
  }
  return out;
}
