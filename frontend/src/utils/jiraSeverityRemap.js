const DEFAULT_SEVERITIES = ["Blocker", "Critical", "Major", "Minor"];

export function remapTestCaseSeverity(tc, meta) {
  if (!tc || typeof tc !== "object") return tc;
  if (!meta?.severities?.length) return tc;
  const byName = Object.fromEntries(
    meta.severities.map((p) => [String(p.name || "").toLowerCase(), p]),
  );
  const raw = String(tc.severity ?? "").trim();
  const aiMap = meta.ai_to_jira_severity_name || {};

  const withName = (name) => {
    const pick = byName[String(name).toLowerCase()];
    return { severity: pick?.name ?? name };
  };

  if (!raw) {
    const mid = DEFAULT_SEVERITIES[Math.floor(DEFAULT_SEVERITIES.length / 2)];
    const jname = aiMap[mid] || mid;
    return { ...tc, ...withName(jname) };
  }

  if (byName[raw.toLowerCase()]) {
    const pick = byName[raw.toLowerCase()];
    return {
      ...tc,
      severity: pick.name,
    };
  }

  for (const lab of Object.keys(aiMap)) {
    if (lab.toLowerCase() === raw.toLowerCase()) {
      const jname = aiMap[lab];
      return { ...tc, ...withName(jname) };
    }
  }

  for (const lab of Object.keys(aiMap)) {
    if (
      lab.toLowerCase().includes(raw.toLowerCase()) ||
      raw.toLowerCase().includes(lab.toLowerCase())
    ) {
      const jname = aiMap[lab];
      return { ...tc, ...withName(jname) };
    }
  }

  const mid = Math.floor(meta.severities.length / 2);
  const pick = meta.severities[mid];
  return {
    ...tc,
    severity: pick?.name ?? tc.severity,
  };
}
