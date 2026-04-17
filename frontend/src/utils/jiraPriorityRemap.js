const DEFAULT_LABELS = ["Highest", "High", "Medium", "Low", "Lowest"];

export function remapTestCasePriority(tc, meta) {
  if (!tc || typeof tc !== "object") return tc;
  if (!meta?.priorities?.length) return tc;
  const byName = Object.fromEntries(
    meta.priorities.map((p) => [String(p.name || "").toLowerCase(), p]),
  );
  const raw = String(tc.priority ?? "").trim();
  const aiMap = meta.ai_to_jira_name || {};

  const withIcon = (name) => {
    const pick = byName[String(name).toLowerCase()];
    const icon = pick?.iconUrl || pick?.iconURL || "";
    return { priority: pick?.name ?? name, priority_icon_url: icon };
  };

  if (!raw) {
    const mid = DEFAULT_LABELS[Math.floor(DEFAULT_LABELS.length / 2)];
    const jname = aiMap[mid] || mid;
    return { ...tc, ...withIcon(jname) };
  }

  if (byName[raw.toLowerCase()]) {
    const pick = byName[raw.toLowerCase()];
    return {
      ...tc,
      priority: pick.name,
      priority_icon_url: pick.iconUrl || pick.iconURL || "",
    };
  }

  for (const lab of Object.keys(aiMap)) {
    if (lab.toLowerCase() === raw.toLowerCase()) {
      const jname = aiMap[lab];
      return { ...tc, ...withIcon(jname) };
    }
  }

  for (const lab of Object.keys(aiMap)) {
    if (
      lab.toLowerCase().includes(raw.toLowerCase()) ||
      raw.toLowerCase().includes(lab.toLowerCase())
    ) {
      const jname = aiMap[lab];
      return { ...tc, ...withIcon(jname) };
    }
  }

  const mid = Math.floor(meta.priorities.length / 2);
  const pick = meta.priorities[mid];
  return {
    ...tc,
    priority: pick?.name ?? tc.priority,
    priority_icon_url: pick?.iconUrl || pick?.iconURL || "",
  };
}
